# PRD Ref: §7.1 (LLM 입력) · ADR 4 · traps.md T11
"""정기보고서 원문에서 **LLM에 넣을 발췌**를 뽑는다.

★★ **왜 필요한가** (사용자 지시 2026-08-23):
   그동안 LLM 입력은 8분기 숫자표뿐이었다(`AnalysisInput.excerpt`가 항상 `None`).
   숫자만 보고 "CAPA 증설·신제품·수주잔고·고객사 협업"을 쓰라고 하면 모델은
   **지어내거나 침묵한다**(T93 실측: 트리거 0건). 원문을 넣어야 답이 나온다.

★★ **`document.xml` API는 정기보고서에는 쓸 수 있다.**
   `provisional_parser`의 주석("document.xml은 쓸 수 없다")은 **공정공시에 한한 말**이다.
   실측(2026-08-23 · 삼화콘덴서 반기보고서):
       공정공시   → status 014 "파일이 존재하지 않습니다"  ✗
       정기보고서 → 200 · ZIP · UTF-8 XML 3.5MB          ✓
   그리고 **뷰어(`report/viewer.do`)로 받으면 인코딩이 깨진다** — 헤더는 MS949인데
   본문 선언은 utf-8이고 실제 바이트는 둘 중 어느 쪽으로도 깨끗이 안 풀린다.
   **정기보고서는 반드시 `document.xml`을 쓴다.**

★ 발췌는 **예산 안에서** 자른다(ADR 4). 원문 전체를 넣으면 캐시가 깨지고 비용이 폭발한다.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from src.config.constants import EXCERPT_BUDGET_CHARS
from src.utils.env import require_env
from src.utils.http import http_get

DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"

#: 뽑을 절. **`II. 사업의 내용` 아래가 전부다** — 재무는 이미 구조화돼 DB에 있다.
#:   키는 화면·프롬프트에 그대로 쓰는 이름이고, 값은 원문 목차의 제목 패턴이다.
#: ★ 순서가 곧 **우선순위**다. 예산이 모자라면 뒤쪽부터 잘린다.
SECTION_PATTERNS: list[tuple[str, str]] = [
    ("매출 및 수주상황", r"매출\s*및\s*수주"),
    ("원재료 및 생산설비", r"원재료\s*및\s*생산설비"),
    ("주요계약 및 연구개발활동", r"주요\s*계약\s*및\s*연구개발"),
    ("주요 제품 및 서비스", r"주요\s*제품\s*및\s*서비스"),
    ("사업의 개요", r"^\s*사업의\s*개요\s*$"),
    ("기타 참고사항", r"기타\s*참고사항"),
]

#: 발췌 총 상한(자). **값은 `constants.py`에 있다** — 여기서 정의하지 마라(T100).
#: 읽는 쪽(`analyze.EXCERPT_MAX_CHARS`)과 어긋나면 뽑아 놓고 버리게 된다.
#: ★ 늘리기 전에 `LLM_INPUT_TOKEN_BUDGET`(14,000토큰)을 먼저 보라 —
#:   한글은 대략 1자 ≈ 0.96토큰이라 2,400자면 이미 2,300토큰이다.
DEFAULT_BUDGET_CHARS = EXCERPT_BUDGET_CHARS
#: 한 절이 독차지하지 못하게 하는 상한. 수주상황 표 하나가 예산을 다 먹는 것을 막는다.
PER_SECTION_CHARS = 700
ORDER_METRIC_MARKER = "정기보고서 수주지표 파서 v4 완료"


class ExcerptError(RuntimeError):
    """원문을 가져오지 못했다. 분석은 발췌 없이 계속한다 — 파이프라인을 죽이지 않는다."""


@dataclass
class ReportExcerpt:
    rcept_no: str
    sections: dict[str, str] = field(default_factory=dict)
    #: 원문 전체 길이(자). 얼마나 잘랐는지 화면에 밝히기 위해 남긴다.
    full_chars: int = 0

    @property
    def text(self) -> str:
        """LLM에 넣을 형태. 절 제목을 남겨야 모델이 무엇을 읽는지 안다."""
        return "\n\n".join(f"### {name}\n{body}" for name, body in self.sections.items())


def fetch_report_xml(rcept_no: str, *, timeout: float = 120.0) -> str:
    """정기보고서 원문 XML. **UTF-8이 확정이다** — ZIP 안의 XML은 선언대로 풀린다."""
    resp = http_get(
        DOCUMENT_URL,
        params={"crtfc_key": require_env("OPENDART_API_KEY"), "rcept_no": rcept_no},
        timeout=timeout,
    )
    if resp.content[:2] != b"PK":
        # DART는 실패도 200 + XML(status/message)로 준다 — 바이트로 갈라야 한다.
        head = resp.content[:300].decode("utf-8", errors="replace")
        raise ExcerptError(f"ZIP이 아니다: {head[:160]}")
    try:
        archive = zipfile.ZipFile(io.BytesIO(resp.content))
        names = archive.namelist()
        # 사업보고서 ZIP에서는 감사보고서 _00760.xml이 본문보다 먼저 올 수 있다.
        name = next((n for n in names if n.rsplit("/", 1)[-1] == f"{rcept_no}.xml"), None)
        if name is None:
            xml_names = [n for n in names if n.lower().endswith(".xml")]
            if len(xml_names) != 1:
                raise ExcerptError("접수번호와 일치하는 본문 XML을 찾지 못했다")
            name = xml_names[0]
        return archive.read(name).decode("utf-8")
    except (zipfile.BadZipFile, IndexError, UnicodeDecodeError) as exc:
        raise ExcerptError(f"원문을 풀지 못했다: {type(exc).__name__}") from exc


# ── 태그 제거 ────────────────────────────────────────────────────────
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t ]+")
_BLANK_RE = re.compile(r"\n{3,}")
#: 표의 행 경계. 이걸 개행으로 바꾸지 않으면 수주 표가 한 줄로 뭉개져 읽히지 않는다.
_ROW_END_RE = re.compile(r"</TR>", re.I)
_CELL_END_RE = re.compile(r"</T[DH]>", re.I)


def to_text(xml: str) -> str:
    """XML → 사람이 읽는 텍스트. **표는 한 행을 한 줄로 압축한다.**

    ★★ 원문은 셀마다 이미 줄바꿈이 들어 있다. 그대로 두면 한 행이 열 줄로 흩어진다:

          품목 |
          수주일자 |
          납기 |

      실측(2026-08-23): 이 상태로 모델에 넣었더니 **출력 6,475토큰을 쓰고도 tool 호출
      구조가 깨져** 필드 대부분이 비었다(`earnings_change`가 객체가 아니라 문자열로 왔다).
      토큰도 낭비고 읽히지도 않는다. → 행 안의 줄바꿈을 먼저 없애고 한 행 = 한 줄로 만든다.
    """
    # ① 행 경계를 표시자로 (아직 개행이 아니다 — 셀 안 개행과 섞이면 안 된다).
    text = _ROW_END_RE.sub("\x00ROW\x00", xml)
    text = _CELL_END_RE.sub(" | ", text)
    text = _TAG_RE.sub("", text)
    text = text.replace("&cr;", " ").replace("&nbsp;", " ").replace("&amp;", "&")
    # ② 남은 개행·공백을 한 칸으로 — 셀 안 줄바꿈이 여기서 사라진다.
    text = re.sub(r"\s+", " ", text)
    # ③ 행 표시자를 진짜 개행으로.
    text = text.replace("\x00ROW\x00", "\n")
    # ④ 빈 셀만 남은 줄과 중복 구분자를 걷어낸다.
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"\s*\|\s*", " | ", line).strip(" |").strip()
        if line and re.search(r"[0-9A-Za-z가-힣]", line):
            lines.append(line)
    return "\n".join(lines).strip()


def split_sections(xml: str) -> dict[str, str]:
    """`<TITLE>`을 경계로 절을 가른다.

    ★ 제목 텍스트로만 자른다 — 목차 번호(`4.`)는 보고서마다 달라 믿을 수 없다.
    ★ 매칭되는 절이 없으면 **빈 dict**를 준다. 없는 것을 지어내지 않는다.
    """
    titles = [
        (m.start(), m.end(), _TAG_RE.sub("", m.group(1)).strip())
        for m in re.finditer(r"<TITLE[^>]*>(.*?)</TITLE>", xml, re.S)
    ]
    if not titles:
        return {}

    out: dict[str, str] = {}
    for name, pattern in SECTION_PATTERNS:
        rx = re.compile(pattern)
        for i, (_start, end, title) in enumerate(titles):
            # 목차 번호를 떼고 본문만 비교한다.
            bare = re.sub(r"^[\dIVX]+[.\-]?\s*", "", title).strip()
            if not (rx.search(bare) or rx.search(title)):
                continue
            stop = titles[i + 1][0] if i + 1 < len(titles) else len(xml)
            body = to_text(xml[end:stop])
            # ★ 목차 항목 자체도 <TITLE>이라 본문이 거의 비는 매치가 나온다 — 버린다.
            if len(body) < 80:
                continue
            out[name] = body
            break
    return out


def _section_xml(xml: str, wanted_name: str) -> str | None:
    """원문의 표 구조를 보존한 채 원하는 절만 돌려준다."""
    titles = [
        (m.start(), m.end(), _TAG_RE.sub("", m.group(1)).strip())
        for m in re.finditer(r"<TITLE[^>]*>(.*?)</TITLE>", xml, re.S)
    ]
    pattern = next((pattern for name, pattern in SECTION_PATTERNS if name == wanted_name), None)
    if pattern is None:
        return None
    rx = re.compile(pattern)
    for i, (_start, end, title) in enumerate(titles):
        bare = re.sub(r"^[\dIVX]+[.\-]?\s*", "", title).strip()
        if not (rx.search(bare) or rx.search(title)):
            continue
        stop = titles[i + 1][0] if i + 1 < len(titles) else len(xml)
        raw = xml[end:stop]
        if len(to_text(raw)) >= 80:
            return raw
    return None


def _table_grid(table) -> list[list[str]]:
    """DART의 ROWSPAN/COLSPAN을 실제 열 위치로 펼친다."""
    grid: list[list[str]] = []
    active: dict[int, tuple[int, str]] = {}
    for tr in table.find_all("tr"):
        row: dict[int, str] = {column: value for column, (_left, value) in active.items()}
        next_active = {
            column: (left - 1, value)
            for column, (left, value) in active.items()
            if left > 1
        }
        column = 0
        for cell in tr.find_all(["th", "td"], recursive=False):
            while column in row:
                column += 1
            value = " ".join(cell.get_text(" ", strip=True).split())
            try:
                colspan = max(1, int(cell.get("colspan", 1)))
                rowspan = max(1, int(cell.get("rowspan", 1)))
            except (TypeError, ValueError):
                colspan = rowspan = 1
            for offset in range(colspan):
                target = column + offset
                row[target] = value
                if rowspan > 1:
                    next_active[target] = (rowspan - 1, value)
            column += colspan
        if row:
            width = max(row) + 1
            grid.append([row.get(index, "") for index in range(width)])
        active = next_active
    width = max((len(row) for row in grid), default=0)
    return [row + [""] * (width - len(row)) for row in grid]


def _order_unit(table) -> str | None:
    """표와 가장 가까운 명시 단위만 읽는다. 단위가 없으면 값을 버린다."""
    contexts = [table.get_text(" ", strip=True)]
    for tag in table.find_all_previous(["p", "tu", "title", "table"], limit=8):
        if tag.name == "title":
            break
        # 다른 데이터 표의 단위를 물려받으면 금액이 조용히 1,000배 틀릴 수 있다.
        if tag.name == "table" and len(tag.find_all("tr")) > 1:
            break
        contexts.append(" ".join(tag.get_text(" ", strip=True).split()))
    for context in contexts:
        match = re.search(r"단위\s*[:：]?[^가-힣]{0,30}(백만원|억원|천원|원)(?:\s*[,，)]|\s*$)", context)
        if "단위" in context and not match:
            return None
        if match:
            return match.group(1)
    return None


def structured_order_metrics(section_xml: str) -> str | None:
    """다단 머리글을 포함한 DART 수주표에서 검증 가능한 합계만 구조화한다.

    `수주총액`은 오래된 프로젝트의 계약총액일 수 있으므로 신규수주로 바꾸지 않는다.
    신규수주는 원문 열이 `신규수주` 또는 `당기수주`라고 명시한 경우에만 읽는다.
    """
    soup = BeautifulSoup(section_xml, "html.parser")
    backlog_names = {"수주잔고", "기말수주잔고", "계약잔액", "수주잔액", "기말계약잔액"}
    new_names = {"신규수주", "당기수주", "신규수주액", "당기수주액"}
    numeric = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
    total_label = re.compile(r"^(?:합\s*계|총\s*계)$")
    candidates: list[tuple[str, str, str | None, str | None]] = []
    order_tables = [
        table for table in soup.find_all("table")
        if any(re.sub(r"\s+", "", cell.get_text(" ", strip=True)) in backlog_names | new_names
               for cell in table.find_all(["th", "td"]))
    ]
    # 단위를 읽지 못한 다른 자회사 표도 범위 모호성에 포함한다.
    if len(order_tables) != 1:
        return None

    for table in order_tables:
        unit = _order_unit(table)
        if unit is None:
            continue
        grid = _table_grid(table)
        header_at = next((
            index for index, row in enumerate(grid[:6])
            if any(re.sub(r"\s+", "", cell) in backlog_names | new_names for cell in row)
        ), None)
        if header_at is None:
            continue
        data_at = header_at + 1
        while data_at < len(grid):
            row = grid[data_at]
            if any(numeric.fullmatch(cell.replace(" ", "")) for cell in row):
                break
            data_at += 1
        if data_at >= len(grid):
            continue

        paths: list[list[str]] = []
        for column in range(len(grid[0])):
            path: list[str] = []
            for row in grid[header_at:data_at]:
                value = re.sub(r"\s+", "", row[column])
                if value and (not path or path[-1] != value):
                    path.append(value)
            paths.append(path)

        def metric_column(names: set[str]) -> int | None:
            matched = [index for index, path in enumerate(paths) if any(part in names for part in path)]
            if len(matched) == 1:
                return matched[0]
            amount_columns = [index for index in matched if paths[index] and paths[index][-1] in {"금액", "원화금액"}]
            return amount_columns[0] if len(amount_columns) == 1 else None

        backlog_column = metric_column(backlog_names)
        new_column = metric_column(new_names)
        if backlog_column is None and new_column is None:
            continue

        data_rows = grid[data_at:]
        total_rows = [row for row in data_rows if any(total_label.fullmatch(cell) for cell in row[:3])]
        if len(total_rows) == 1:
            chosen = total_rows[0]
            scope = "회사 공시 합계"
        else:
            usable_rows = [
                row for row in data_rows
                if any(numeric.fullmatch(cell.replace(" ", "")) for cell in row)
            ]
            if len(total_rows) == 0 and len(usable_rows) == 1:
                chosen = usable_rows[0]
                scope = "회사 공시 단일행"
            else:
                continue

        def value_at(column: int | None) -> str | None:
            if column is None or column >= len(chosen):
                return None
            value = chosen[column].replace(" ", "")
            return value if numeric.fullmatch(value) and float(value.replace(",", "")) >= 0 else None

        backlog = value_at(backlog_column)
        new_orders = value_at(new_column)
        if backlog is None and new_orders is None:
            continue
        nearby = " ".join(
            tag.get_text(" ", strip=True)
            for tag in table.find_all_previous(["p", "title"], limit=4)
        )
        if re.search(r"주요\s*(?:프로젝트|계약)", nearby):
            scope = "주요계약(전체 회사 아님)"
        # 연결 수주표가 하나라도 종속회사만 공시한 수치일 수 있다.
        # 가장 가까운 회사 범위 표제를 보존해 연결 전체 잔고로 오인하지 않는다.
        scope_heading = next((
            tag.get_text(" ", strip=True)
            for tag in table.find_all_previous(["p", "title"], limit=20)
            if re.search(r"(?:종속회사|지배회사)\s*[:：]?", tag.get_text(" ", strip=True))
            and len(tag.get_text(" ", strip=True)) < 160
        ), None)
        if scope_heading:
            scope = f"{scope_heading} / {scope}"
        candidates.append((unit, scope, backlog, new_orders))

    if len(candidates) != 1:
        return None
    unit, scope, backlog, new_orders = candidates[0]
    rows = [f"범위 | {scope}", f"단위 | {unit}"]
    if backlog is not None:
        rows.append(f"수주잔고 | {backlog}")
    if new_orders is not None:
        rows.extend((f"신규수주 | {new_orders}", "신규수주 기간 | 보고기간 누적"))
    return "\n".join(rows)


def major_contract_backlog(section: str) -> str | None:
    """공시의 주요계약 표 합계만 추출한다. 전체 회사 수주잔고로 해석하지 않는다."""
    lines = section.splitlines()
    found: list[str] = []
    for index, line in enumerate(lines):
        headers = [cell.strip() for cell in line.split("|")]
        if not ("수주총액" in headers and "수주잔고" in headers and
                headers.index("수주잔고") == headers.index("수주총액") + 2):
            continue
        context = " ".join(lines[max(0, index - 2):index])
        unit_match = re.search(r"단위\s*[:：]\s*(백만원|억원|천원|원)(?:\s*[,，)]|\s*$)", context)
        if not unit_match:
            continue
        for subsequent in lines[index + 1:]:
            cells = [cell.strip() for cell in subsequent.split("|")]
            if re.fullmatch(r"합\s*계", cells[0]) and len(cells) >= 4:
                # 표의 앞부분이 품목·발주처·날짜이고, 합계행은 금액부터 시작한다.
                # 수주총액·기납품액·수주잔고 세 열이 연속임을 머리글로 확인했다.
                amounts = cells[1:4]
                if all(re.fullmatch(r"[\d,]+(?:\.\d+)?", value) for value in amounts):
                    found.append(f"범위 | 주요계약(전체 회사 아님)\n단위 | {unit_match.group(1)}\n수주잔고 | {amounts[2]}")
                break
            if "수주잔고" in subsequent and "수주총액" in subsequent:
                break
    return found[0] if len(found) == 1 else None


def explicit_order_metrics(section: str) -> str | None:
    """회사 전체 표의 명시적 신규수주·수주잔고 합계만 구조화한다.

    열 이름과 단위, 합계행이 모두 있을 때만 읽는다. `수주총액`에서 신규수주를
    역산하거나 여러 사업부를 임의로 더하지 않는다.
    """
    lines = section.splitlines()
    candidates: list[tuple[str, str, str | None, str | None]] = []
    backlog_names = {"수주잔고", "기말수주잔고", "수주 잔고", "기말 수주잔고"}
    new_names = {"신규수주", "당기수주", "신규 수주", "당기 수주"}
    for index, line in enumerate(lines):
        headers = [cell.strip() for cell in line.split("|")]
        backlog_index = next((i for i, cell in enumerate(headers) if cell in backlog_names), None)
        new_index = next((i for i, cell in enumerate(headers) if cell in new_names), None)
        if backlog_index is None and new_index is None:
            continue
        context = " ".join(lines[max(0, index - 3):index + 1])
        unit_match = re.search(r"단위\s*[:：]\s*(백만원|억원|천원|원)(?:\s*[,，)]|\s*$)", context)
        if not unit_match:
            continue
        for subsequent in lines[index + 1:]:
            cells = [cell.strip() for cell in subsequent.split("|")]
            if not cells:
                continue
            if re.fullmatch(r"(?:합\s*계|총\s*계)", cells[0]):
                if len(cells) != len(headers):
                    break
                valid = lambda value: bool(re.fullmatch(r"[\d,]+(?:\.\d+)?", value))
                backlog = cells[backlog_index] if backlog_index is not None and valid(cells[backlog_index]) else None
                new_orders = cells[new_index] if new_index is not None and valid(cells[new_index]) else None
                if backlog is not None or new_orders is not None:
                    candidates.append((unit_match.group(1), "회사 공시 합계", backlog, new_orders))
                break
            if any(cell in backlog_names | new_names for cell in cells):
                break
    if len(candidates) != 1:
        return None
    unit, scope, backlog, new_orders = candidates[0]
    rows = [f"범위 | {scope}", f"단위 | {unit}"]
    if backlog is not None:
        rows.append(f"수주잔고 | {backlog}")
    if new_orders is not None:
        rows.append(f"신규수주 | {new_orders}")
    return "\n".join(rows)


def build_excerpt(
    rcept_no: str,
    xml: str,
    *,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
    per_section: int = PER_SECTION_CHARS,
) -> ReportExcerpt:
    """절을 우선순위대로 담되 **예산을 넘기지 않는다.**

    ★ 잘랐다는 사실을 남긴다(`full_chars`). 조용히 truncate하면
      모델이 "수주 정보가 없다"고 쓰는데 실제로는 우리가 잘라낸 것이 된다.
    """
    sections = split_sections(xml)
    picked: dict[str, str] = {}
    checked_marker = ORDER_METRIC_MARKER
    # 구 발췌를 한 번만 재수집하기 위한 완료 표식이다. DB 컬럼을 추가하지 않고도
    # 새 파서 적용 여부를 구분하며, 이 표식이 있으면 다음 예약 실행은 건너뛴다.
    remaining = max(0, budget_chars - len(checked_marker))
    for name, _ in SECTION_PATTERNS:
        body = sections.get(name)
        if not body or remaining <= 0:
            continue
        take = min(per_section, remaining)
        clipped = body[:take]
        if len(body) > take:
            clipped += f" …(이하 {len(body) - take:,}자 생략)"
        picked[name] = clipped
        remaining -= take
    order_section = sections.get("매출 및 수주상황")
    order_section_xml = _section_xml(xml, "매출 및 수주상황")
    order_metric = structured_order_metrics(order_section_xml) if order_section_xml else None
    raw_order_table = bool(order_section_xml and any(
        re.sub(r"\s+", "", cell.get_text(" ", strip=True)) in {
            "수주잔고", "기말수주잔고", "계약잔액", "수주잔액", "기말계약잔액",
            "신규수주", "당기수주", "신규수주액", "당기수주액",
        }
        for table in BeautifulSoup(order_section_xml, "html.parser").find_all("table")
        for cell in table.find_all(["td", "th"])
    ))
    # 단위·범위 검증에 실패한 원문 표를 평면 폴백으로 다시 승인하지 않는다.
    if order_metric is None and order_section and not raw_order_table:
        order_metric = explicit_order_metrics(order_section)
    if order_metric is None and order_section and not raw_order_table:
        order_metric = major_contract_backlog(order_section)
    if order_metric:
        picked["공시 수주지표"] = order_metric
    # 절이 없는 첨부·비정상 원문에 완료 표식을 쓰면 영원히 재수집되지 않는다.
    if sections:
        picked["공시 수주지표 확인"] = checked_marker
    return ReportExcerpt(rcept_no=rcept_no, sections=picked, full_chars=len(xml))


def excerpt_for(rcept_no: str, **kwargs) -> ReportExcerpt | None:
    """한 번에. **실패하면 None** — 발췌가 없다고 분석을 막지 않는다."""
    try:
        return build_excerpt(rcept_no, fetch_report_xml(rcept_no), **kwargs)
    except ExcerptError:
        return None
