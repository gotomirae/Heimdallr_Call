# PRD Ref: §3 (유니버스), §5.1(L0) · traps.md T5, T6
"""KIND 상장법인목록 수집.

응답은 확장자만 xls일 뿐 실제로는 **EUC-KR HTML 테이블**이다
(Content-Type: application/vnd.ms-excel).

★ 파서를 "lxml"로 바꾸지 마라 (T5).
  2026-08-13 이 프로젝트에서 재실측: KOSDAQ 원문 <tr> 1,841개 중
  lxml은 1,283개만 파싱하고 **예외도 경고도 내지 않는다**(558행 = 30% 소실).
  같은 바이트를 stdlib html.parser로 파싱하면 1,841행 전부 나온다.
  KOSPI(848행)는 두 파서가 동일해서 대형주만 보면 눈치채지 못한다.
  아래 행 수 대조가 회귀를 즉시 드러낸다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup

from src.utils.http import http_get

KIND_CORP_LIST_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do"

_BOARDS = {"KOSPI": "stockMkt", "KOSDAQ": "kosdaqMkt"}
_SUFFIX = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}

# 스팩 판정 — 회사명 기준. 실측(2026-08-13): KOSPI 0건 / KOSDAQ 71건,
# 그중 66건의 업종이 '금융 지원 서비스업', 5건이 '기타 금융업'이다.
_SPAC_TOKENS = ("스팩", "기업인수목적")


@dataclass(frozen=True)
class KindRow:
    """KIND 상장법인목록 1행."""

    code: str  # '005930'
    symbol: str  # '005930.KS' / '196170.KQ'
    name: str
    board: str  # 'KOSPI' | 'KOSDAQ'
    industry: str  # KRX 업종명
    products: str  # 주요제품 텍스트
    listed_at: date | None
    is_spac: bool


@dataclass
class KindFetchReport:
    """수집 결과의 실측 수치. 검증에서 이 값을 원문과 대조한다."""

    raw_tr_counts: dict[str, int]  # 원문 <tr> 개수
    parsed_row_counts: dict[str, int]  # 파싱된 <tr> 개수
    rows_by_board: dict[str, int]  # 유효 데이터 행 수
    duplicate_codes: list[str]  # 중복 제거된 종목코드 (T6)
    nonstandard_codes: list[str]  # '0126Z0' 같은 임시 코드 (T6)


def _parse_listed_at(text: str) -> date | None:
    """'2026-03-05' → date. 형식이 다르면 추측하지 않고 None."""
    try:
        return date.fromisoformat(text.strip())
    except (ValueError, AttributeError):
        return None


def fetch_kind_listing() -> tuple[list[KindRow], KindFetchReport]:
    rows_out: list[KindRow] = []
    report = KindFetchReport({}, {}, {}, [], [])
    seen: dict[str, str] = {}  # code → board (중복 감지용)

    for board, market_type in _BOARDS.items():
        resp = http_get(
            KIND_CORP_LIST_URL, params={"method": "download", "marketType": market_type}
        )
        text = resp.content.decode("euc-kr", errors="replace")

        # ★ html.parser 고정 (T5)
        soup = BeautifulSoup(text, "html.parser")
        table = soup.find("table")
        if table is None:
            raise RuntimeError(f"KIND 상장법인목록 파싱 실패({board}): table 요소 없음")

        trs = table.find_all("tr")
        raw_tr = text.count("<tr")
        report.raw_tr_counts[board] = raw_tr
        report.parsed_row_counts[board] = len(trs)

        # 파싱 유실 감지 — 유니버스가 조용히 줄어드는 것을 여기서 즉시 실패시킨다.
        if len(trs) < raw_tr * 0.99:
            raise RuntimeError(
                f"KIND {board} 파싱 유실: 원문 <tr> {raw_tr}개 중 {len(trs)}개만 파싱됨. "
                "파서가 'lxml'로 바뀌지 않았는지 확인하라 (traps.md T5)."
            )

        header = [th.get_text(strip=True) for th in trs[0].find_all(["th", "td"])]
        try:
            idx = {
                key: header.index(key)
                for key in ("회사명", "종목코드", "업종", "주요제품", "상장일")
            }
        except ValueError as exc:
            # 컬럼 구성이 바뀌면 조용히 빈 유니버스를 만들지 말고 즉시 실패
            raise RuntimeError(f"KIND 컬럼 구성 변경 감지({board}): {header}") from exc

        count = 0
        for tr in trs[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) <= max(idx.values()):
                continue

            raw_code = cells[idx["종목코드"]]
            code = raw_code.strip().upper().zfill(6)
            # ★ 영문이 섞인 6자리 코드('0126Z0')를 버리지 마라 (T6 갱신 2026-08-13).
            #   참고 프로젝트는 "시세 API에도 없는 임시 코드"로 보고 제외했으나,
            #   실측 결과 네이버 시총 API와 DART 모두 정상 지원한다
            #   (DART corpCode.xml에 56건 존재 · company.json 조회 성공).
            #   버리면 시총 하한 이상 실체 기업 12곳이 사라진다
            #   — 삼성에피스홀딩스 9.98조, 에임드바이오 1.75조 포함.
            #   KRX 종목코드 고갈로 신규 상장에 영숫자 코드가 배정되므로 앞으로 계속 늘어난다.
            if len(code) != 6 or not code.isalnum():
                report.nonstandard_codes.append(f"{cells[idx['회사명']]}({raw_code})")
                continue

            # 같은 종목코드가 두 번 실려 오는 행이 있다(T6). 먼저 나온 행을 남긴다.
            # 제거하지 않으면 PK 제약(23505)에 걸려 저장이 통째로 실패한다.
            if code in seen:
                report.duplicate_codes.append(code)
                continue
            seen[code] = board

            name = cells[idx["회사명"]]
            rows_out.append(
                KindRow(
                    code=code,
                    symbol=f"{code}{_SUFFIX[board]}",
                    name=name,
                    board=board,
                    industry=cells[idx["업종"]],
                    products=cells[idx["주요제품"]],
                    listed_at=_parse_listed_at(cells[idx["상장일"]]),
                    is_spac=any(t in name for t in _SPAC_TOKENS),
                )
            )
            count += 1

        report.rows_by_board[board] = count

    return rows_out, report
