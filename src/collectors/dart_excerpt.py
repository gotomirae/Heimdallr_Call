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
   정기보고서는 `document.xml`을 우선한다. 상태 014에 한해서만 동일 접수번호·문서의
   공식 뷰어 절을 엄격히 검증해 복구하며, 절 수집임과 직접 링크를 장부에 남긴다.

★ 발췌는 **예산 안에서** 자른다(ADR 4). 원문 전체를 넣으면 캐시가 깨지고 비용이 폭발한다.
"""

from __future__ import annotations

import io
import html
import re
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from src.config.constants import EXCERPT_BUDGET_CHARS
from src.utils.env import require_env
from src.utils.http import decode_html, http_get

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
ORDER_METRIC_MARKER = "정기보고서 수주지표 파서 v9 완료"


class ExcerptError(RuntimeError):
    """원문을 가져오지 못했다. 분석은 발췌 없이 계속한다 — 파이프라인을 죽이지 않는다."""


@dataclass
class ReportExcerpt:
    rcept_no: str
    sections: dict[str, str | dict] = field(default_factory=dict)
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
        if re.search(r"<status>\s*014\s*</status>", head):
            return _fetch_viewer_sections(rcept_no, timeout=timeout)
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


def _fetch_viewer_sections(rcept_no: str, *, timeout: float) -> str:
    """API 014 예외만 복구. 접수번호·문서·절 위치·인코딩을 검증하고 표는 보존한다."""
    main = http_get("https://dart.fss.or.kr/dsaf001/main.do",
                    params={"rcpNo": rcept_no}, timeout=timeout)
    text = decode_html(main)
    default = re.search(r'viewDoc\(\s*"(\d+)"\s*,\s*"(\d+)"', text)
    if not default or default.group(1) != rcept_no or "\ufffd" in text:
        raise ExcerptError("API 014 · 뷰어의 동일 접수번호 본문을 검증하지 못했다")
    blocks = re.findall(r"var (node\d+) = \{\};(.*?)(?=var node\d+ = \{\};|$)", text, re.S)
    nodes = []
    for variable, block in blocks:
        fields = dict(re.findall(
            re.escape(variable) + r"\['(text|rcpNo|dcmNo|eleId|offset|length|dtd)'\]\s*=\s*\"([^\"]*)\"",
            block,
        ))
        if fields.get("rcpNo") == rcept_no and fields.get("dcmNo") == default.group(2):
            nodes.append(fields)
    fragments, links, fetched_chars = [], [], 0
    for name, pattern in SECTION_PATTERNS:
        candidates = [node for node in nodes if re.search(pattern, node.get("text", ""))]
        if len(candidates) != 1:
            continue  # 모호한 목차는 임의 선택하지 않는다.
        node = candidates[0]
        if (not all(node.get(key, "").isdigit() for key in ("eleId", "offset", "length"))
                or int(node["length"]) <= 0 or not re.fullmatch(r"dart\d+\.xsd", node.get("dtd", ""))):
            continue
        params = {key: node[key] for key in ("rcpNo", "dcmNo", "eleId", "offset", "length", "dtd")}
        response = http_get("https://dart.fss.or.kr/report/viewer.do", params=params, timeout=timeout)
        raw = decode_html(response)
        soup = BeautifulSoup(raw, "html.parser")
        if "\ufffd" in raw or not soup.body or not re.search(pattern, soup.body.get_text(" ", strip=True)):
            raise ExcerptError(f"API 014 · 뷰어 절 인코딩/제목 검증 실패: {name}")
        for script in soup.find_all(["script", "style"]):
            script.decompose()
        body = soup.body.decode_contents()
        fragments.append(f"<TITLE>{html.escape(name)}</TITLE>{body}")
        links.append(f"{name}: https://dart.fss.or.kr/report/viewer.do?{urlencode(params)}")
        fetched_chars += len(raw)
    if not fragments:
        raise ExcerptError("API 014 · 검증 가능한 정기보고서 뷰어 절이 없다")
    provenance = "공식 DART 뷰어 절 원문 복구(API 014). 전체 보고서가 아닌 수집한 절의 문자수.\n" + "\n".join(links)
    return (f'<DOCUMENT><SOURCE chars="{fetched_chars}">{html.escape(provenance)}</SOURCE>'
            + "".join(fragments) + "</DOCUMENT>")


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
    matched = []
    for i, (_start, end, title) in enumerate(titles):
        bare = re.sub(r"^[\dIVX]+[.\-]?\s*", "", title).strip()
        if not (rx.search(bare) or rx.search(title)):
            continue
        stop = titles[i + 1][0] if i + 1 < len(titles) else len(xml)
        raw = xml[end:stop]
        if len(to_text(raw)) >= 80 or re.search(r"<TABLE\b", raw, re.I):
            matched.append((title, raw))
    if not matched:
        return None
    first = matched[0][1]
    if wanted_name == "매출 및 수주상황" and "상세표" in first:
        details = [raw for title, raw in matched[1:] if "상세" in title]
        if details:
            return first + "\n" + "\n".join(details)
    return first


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
    inline_usd = any(re.fullmatch(r"(?:USD|US\$)\s*[\d,]+(?:\.\d+)?", cell.get_text(" ", strip=True))
                     for cell in table.find_all(["td", "th"]))
    for tag in table.find_all_previous(["p", "tu", "title", "table"], limit=8):
        if tag.name == "title":
            break
        # 다른 데이터 표의 단위를 물려받으면 금액이 조용히 1,000배 틀릴 수 있다.
        if tag.name == "table" and len(tag.find_all("tr")) > 1:
            break
        contexts.append(" ".join(tag.get_text(" ", strip=True).split()))
    for context in contexts:
        # DART에서 자주 쓰는 달러 별칭의 배율은 명시 표기대로만 정규화한다.
        context = re.sub(r"US\$\s*1,?000|U\$\s*천|K\$|천\s*\$|천\s*불", "천USD", context, flags=re.I)
        context = re.sub(r"백만\s*불", "백만USD", context)
        context = re.sub(r"US\$", "USD", context)
        context = re.sub(r"금액\s*\(\s*(백만USD|천USD|백만원|억원|천원|원)\s*\)", r"단위: \1)", context)
        # 수량(천개,대,척)과 금액의 병기 단위도 금액 열에서만 읽는다.
        declaration = re.search(r"단위\s*(?:[:：]\s*|\s+(?=백만원|억원|천원|원|USD|달러))((?:[^()]|\([^)]*\)){1,100})", context)
        currencies = re.findall(r"백만원|억원|천원|(?<![가-힣])원(?![가-힣])|USD|달러|EUR|유로", declaration[1] if declaration else "")
        if len(set(currencies)) > 1:
            return None
        match = re.search(r"(백만원|억원|천원|(?<![가-힣])원(?![가-힣])|백만\s*(?:USD|달러)|천\s*(?:USD|달러)|USD|달러|천RMB|백만IDR)", declaration[1] if declaration else "")
        if declaration and not match:
            return "USD" if inline_usd else None
        if match:
            return re.sub(r"\s+", "", match.group(1))
    # 저스템처럼 숫자 셀마다 단위를 붙인 표는 다른 매출 표 단위를 상속하지 않는다.
    cell_units = {m[1] for cell in table.find_all(["td", "th"])
                  if (m := re.fullmatch(r"[\d,]+(?:\.\d+)?\s*(백만원|억원|천원|원)", cell.get_text(" ", strip=True)))}
    if len(cell_units) == 1:
        return cell_units.pop()
    if any(re.fullmatch(r"[\d,]+조\s*[\d,]+억(?:원)?", cell.get_text(" ", strip=True))
           for cell in table.find_all(["td", "th"])):
        return "억원"
    return "USD" if inline_usd else None


def _order_currency_parts(table) -> list[str] | None:
    """통화 열과 통화별 명시 배율이 함께 있는 표만 분리한다."""
    grid = _table_grid(table)
    header_at = next((i for i, row in enumerate(grid[:4]) if "통화" in row), None)
    if header_at is None:
        return None
    column = grid[header_at].index("통화")
    currencies = {row[column] for row in grid[header_at + 1:] if row[column] in {"USD", "KRW", "CHF", "EUR"}}
    if not currencies:
        return None
    contexts = [table.get_text(" ", strip=True)]
    for tag in table.find_all_previous(["p", "table"], limit=4):
        if tag.name == "table" and len(tag.find_all("tr")) > 1:
            break
        contexts.append(tag.get_text(" ", strip=True))
    declaration = " ".join(re.findall(r"단위\s*[:：]\s*([^)]{1,100})", " ".join(contexts)))
    units = {}
    krw = re.search(r"백만원|억원|천원|(?<![가-힣])원(?![가-힣])", declaration)
    usd = re.search(r"백만\s*(?:USD|달러|불)|천\s*(?:USD|달러|불|\$)|K\$|US\$1,?000|USD|US\$", declaration, re.I)
    if krw: units["KRW"] = krw[0]
    if usd:
        units["USD"] = "백만USD" if "백만" in usd[0] else "천USD" if re.search(r"천|K|1,?000", usd[0], re.I) else "USD"
    # 배율 선언이 없는 통화에는 추측 단위를 붙이지 않는다.
    if not units:
        return []
    parts = []
    heading = _order_scope_heading(table)
    for currency in sorted(currencies):
        if currency not in units:
            continue
        selected = [row for row in grid[header_at + 1:]
                    if row[column] == currency or any(re.fullmatch(rf"합\s*계\s*\({currency}\)", cell) for cell in row)]
        if not selected:
            continue
        # 분리한 표의 통화 열을 제거해야 하위 파서가 다시 혼합 통화 표로 해석하지 않는다.
        cells = "".join("<TR>" + "".join(f"<TD>{html.escape(cell)}</TD>" for i, cell in enumerate(row) if i != column) + "</TR>"
                        for row in [grid[header_at], *selected])
        parts.append(f"<P>[{html.escape(heading or '공시 통화별 표')} / {currency}]</P>"
                     f"<P>(단위: {units[currency]})</P><TABLE>{cells}</TABLE>")
    return parts


def _order_header(value: str) -> str:
    """단위/기간 각주만 제거하고 전기말·수주총액의 의미는 보존한다."""
    value = re.sub(r"\([^)]*\)|\[[^]]*\]|[*※]+\d*$|주\d+$", "", value)
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"(?<=수주잔고)A\+B-C$|(?<=수주총액)[AB]$", "", value)
    if value.endswith("금액") and value[:-2] in {"수주잔고", "기말수주잔고", "신규수주", "당기수주"}:
        value = value[:-2]
    return value


def _order_scope_heading(table) -> str | None:
    for tag in table.find_all_previous(["p", "title", "table"], limit=20):
        if tag.name == "table" and len(tag.find_all("tr")) > 1:
            break
        heading = tag.get_text(" ", strip=True)
        if not heading or len(heading) >= 160:
            continue
        match = re.search(r"\[[^\]]{1,70}\]", heading)
        if match and (re.search(r"부문|사업부|종속회사|지배회사", match[0]) or not re.search(r"수주|매출|주\d|기준일|현재|\d{4}", match[0])):
            label = heading if re.search(r"종속회사|지배회사", match[0]) else match[0]
            return re.sub(r"\s+", "", label) if re.search(r"[가-힣]", label) and not re.search(r"종속회사|지배회사", label) else label
        if re.match(r"^(?:종속회사|지배회사)\s*[:：]", heading):
            return heading
        numbered = re.search(r"\(\d+\)\s*([^()]{2,45})$", heading)
        if numbered and not re.search(r"판매|수주|매출", numbered[1]):
            return numbered[1].strip()
        business = re.search(r"([^。.]{2,50}사업[^。.]{0,20})의\s*수주상황", heading)
        if business:
            return business[1].strip()
        # 한 행짜리 단위 표에 회사명을 함께 적는 원문(삼화전기 등).
        if tag.name == "table" and '단위' in heading:
            label = re.sub(r"\(?\s*단위\s*[:：].*$", "", heading).strip()
            if label and len(label) < 70 and not re.search(r"기준일|현재|\d{4}[.년-]", label):
                return label
    return None


def _contract_rollforward_series(table) -> list[str] | None:
    """명시 신규 계약 행의 당기 통화 열과 원문 변동식을 대조한다."""
    grid = _table_grid(table)
    labels = ["기초수주계약잔액", "신규수주계약금액", "변경수주계약금액", "수익인식액", "수주계약잔액"]
    if not any(row and _order_header(row[0]) == labels[1] for row in grid):
        return None
    if (len(grid) < 7 or any(len(row) != 5 for row in grid)
            or _order_header(grid[0][0]) != "구분"
            or grid[0][1] != grid[0][2] or _order_header(grid[0][1]) not in {"당기", "당분기", "당반기"}
            or not all(_order_header(grid[0][i]) == "전기" for i in (3, 4))):
        return []
    headers = [re.sub(r"\s+", "", cell) for cell in grid[1]]
    if not re.fullmatch(r"국내계약(?:\(원\))?", headers[1]) or headers[2] != "수출계약(USD)":
        return []
    if headers[3:] != headers[1:3]:
        return []
    explicit_won = headers[1] == "국내계약(원)"
    for tag in table.find_all_previous(["p", "table"], limit=3):
        if tag.name == "table" and len(tag.find_all("tr")) > 1:
            break
        context = re.sub(r"\s+", "", tag.get_text())
        if "단위" in context:
            if not re.search(r"단위[:：]원,USD(?:\)|$)", context):
                return []
            explicit_won = True
            break
    rows = {label: [r for r in grid[2:] if _order_header(r[0]) == label] for label in labels}
    if any(len(items) != 1 for items in rows.values()):
        return []
    results = []
    for column, unit, scope in ((1, "원" if explicit_won else None, "국내계약"), (2, "USD", "수출계약")):
        if unit is None:
            continue
        raw = [re.sub(r"\s+", "", rows[label][0][column]) for label in labels]
        if not all(re.fullmatch(r"-?[\d,]+(?:\.\d+)?|\([\d,]+(?:\.\d+)?\)", value)
                   or i == 2 and value == "-" for i, value in enumerate(raw)):
            continue
        # 신규·잔고는 반드시 명시 숫자다. 변경 행 '-'의 0은 변동식 검증에만 쓴다.
        amounts = [Decimal("0" if value == "-" else value.replace(",", "").replace("(", "-").replace(")", "")) for value in raw]
        if (amounts[0] + amounts[1] + amounts[2] + amounts[3] != amounts[4]
                or amounts[1] < 0 or amounts[4] < 0):
            continue
        results.append(f"범위 | 공시 진행기준 수주계약 / {scope}\n단위 | {unit}"
                       f"\n수주잔고 | {raw[4]}\n신규수주 | {raw[1]}\n신규수주 기간 | 보고기간 누적")
    return results


def structured_order_series(section_xml: str, *, period_end: str | None = None) -> list[str]:
    """다단 머리글을 포함한 DART 수주표에서 검증 가능한 합계만 구조화한다.

    `수주총액`은 오래된 프로젝트의 계약총액일 수 있으므로 신규수주로 바꾸지 않는다.
    신규수주는 원문 열이 `신규수주` 또는 `당기수주`라고 명시한 경우에만 읽는다.
    """
    soup = BeautifulSoup(section_xml, "html.parser")
    for table in list(soup.find_all("table")):
        parts = _order_currency_parts(table)
        if parts is not None:
            table.replace_with(BeautifulSoup("".join(parts), "html.parser"))
    backlog_names = {"수주잔고", "수주잔고액", "기말수주잔고액", "기말수주잔고", "당기말수주잔고", "당기말수주잔액",
                     "당분기말수주잔고", "당반기말수주잔고",
                     "당분기수주잔고", "당반기수주잔고", "당기수주잔고",
                     "계약잔액", "수주잔액", "기말계약잔액"}
    new_names = {"신규수주", "당기수주", "신규수주액", "당기수주액", "당기수주금액", "당기신규수주액", "당기신규수주",
                 "당반기수주총액", "당기수주총액", "당분기수주총액", "당해신규수주액",
                 "당반기수주", "당분기수주", "신규수주계약금액"}
    # 명시 정의가 있을 때만 수주총액을 당기 신규수주로 읽는다(엠앤씨솔루션).
    period_flow = bool(re.search(r"수주총액\s*=\s*당기\s*수주총액", soup.get_text(" ", strip=True)))
    if period_flow:
        new_names.add("수주총액")
    numeric = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
    total_label = re.compile(r"^(?:(?:총|전체|전사|수주)\s*)?(?:합\s*계|총\s*계|계)$")
    candidates: list[tuple[str, str, str | None, str | None]] = []
    vertical_series: list[str] = []
    candidate_items: list[str | None] = []
    period_labels: dict[str, str] = {}
    order_tables = [
        table for table in soup.find_all("table")
        if any(_order_header(cell.get_text(" ", strip=True)) in backlog_names | new_names
               for cell in table.find_all(["th", "td"]))
    ]
    for table in order_tables:
        rollforward = _contract_rollforward_series(table)
        if rollforward is not None:
            vertical_series.extend(rollforward)
            continue
        if period_end:
            # 코미팜은 분기말 표 뒤에 보고서 제출 직전 잔고도 싣는다. 후자를
            # 같은 분기 잔고로 쓰거나 두 표를 합산하지 않는다.
            basis = None
            for tag in table.find_all_previous(["p", "tu", "table", "title"], limit=8):
                if tag.name == "title" or tag.name == "table" and len(tag.find_all("tr")) > 1:
                    break
                basis = re.search(r"기준일\s*[:：]\s*(\d{4})\s*[년./-]\s*(\d{1,2})\s*[월./-]\s*(\d{1,2})", tag.get_text(" ", strip=True))
                if basis:
                    end = f"{int(basis[1]):04d}-{int(basis[2]):02d}-{int(basis[3]):02d}"
                    break
            else:
                basis = None
            if basis and end != period_end:
                continue
        scope_heading = _order_scope_heading(table)
        unit = _order_unit(table)
        if unit is None:
            scope = f"{scope_heading} / 회사 공시 합계" if scope_heading else "회사 공시 합계"
            if any(re.fullmatch(r"(?:USD|EUR|CHF)\s*[\d,]+(?:\.\d+)?", cell.get_text(" ", strip=True))
                   for cell in table.find_all(["td", "th"])):
                scope += " / 원문 외화 계약(단위 혼합)"
            candidates.append(("", scope, None, None))
            candidate_items.append(None)
            continue
        grid = _table_grid(table)
        if unit == "억원":
            grid = [[str(int(m[1].replace(',', '')) * 10000 + int(m[2].replace(',', '')))
                     if (m := re.fullmatch(r"([\d,]+)조\s*([\d,]+)억(?:원)?", cell)) else cell
                     for cell in row] for row in grid]
        grid = [[re.sub(rf"(?<=[\d,])\s*{re.escape(unit)}$", "", cell) for cell in row] for row in grid]
        if unit == "USD":
            grid = [[re.sub(r"^(?:USD\s*|US\$|\$)(?=[\d,])", "", cell) for cell in row] for row in grid]
        header_at = next((
            index for index, row in enumerate(grid[:6])
            if any(_order_header(cell) in backlog_names | new_names for cell in row)
        ), None)
        if header_at is None:
            continue
        data_at = header_at + 1
        header_labels = {"", "-", "품목", "구분", "사업부문", "부문", "수량", "금액", "단위", "수주일자", "납기", "납기일자"} | backlog_names | new_names
        while data_at < len(grid):
            row = grid[data_at]
            is_header_row = any(_order_header(cell) in {"수량", "금액"} for cell in row)
            if (any(numeric.fullmatch(cell.replace(" ", "")) for cell in row)
                    or (not is_header_row and _order_header(row[0]) not in header_labels
                        and any(cell == "-" or re.search(r"\d{4}[./-]\d{1,2}|\d{4}년", cell) for cell in row))):
                break
            data_at += 1
        if data_at >= len(grid):
            continue

        paths: list[list[str]] = []
        for column in range(len(grid[0])):
            path: list[str] = []
            for row in grid[header_at:data_at]:
                value = _order_header(row[column])
                if value and (not path or path[-1] != value):
                    path.append(value)
            paths.append(path)

        def metric_column(names: set[str]) -> int | None:
            matched = [index for index, path in enumerate(paths) if any(part in names for part in path)]
            if len(matched) == 1:
                return matched[0]
            current_flow = [index for index in matched if any(part.startswith("당기") or part.startswith("당반기") for part in paths[index])]
            if len(current_flow) == 1:
                return current_flow[0]
            amount_columns = [index for index in matched if paths[index] and paths[index][-1] in {"금액", "원화금액"}]
            return amount_columns[0] if len(amount_columns) == 1 else None

        backlog_column = metric_column(backlog_names)
        new_column = metric_column(new_names)
        contract_column = metric_column({"수주총액"})
        delivered_column = metric_column({"기납품액", "기납품금액", "기납품총액"})
        if backlog_column is None and new_column is None:
            continue

        data_rows = grid[data_at:]
        if period_end:
            y, month = int(period_end[:4]), int(period_end[5:7])
            label = {3: rf"{y}년(?:1분기|당분기|1Q)", 6: rf"{y}년(?:반기|상반기|당반기)",
                     9: rf"{y}년(?:3분기|3Q)", 12: rf"{y}년"}.get(month)
            labeled_rows = [row for row in data_rows if label and re.fullmatch(label, re.sub(r"\s+", "", row[0]))]
            if len(labeled_rows) == 1:
                data_rows = labeled_rows
        if period_flow and period_end:
            period_rows = [row for row in data_rows if any(
                re.sub(r"[. /]", "-", cell).rstrip('-') == period_end for cell in row[:3])]
            if len(period_rows) == 1:
                data_rows = period_rows
        # 연도별 과거 비교표를 이번 보고기간의 잔고로 읽지 않는다.
        if len(data_rows) > 1 and any(re.fullmatch(r"(?:19|20)\d{2}(?:년)?", row[0].strip()) for row in data_rows):
            continue
        monetary_labels = backlog_names | new_names | {"수주총액", "기납품액", "이월수주잔액", "전기말수주잔고"}
        label_columns = max(1, min(i for i, path in enumerate(paths) if any(part in monetary_labels for part in path)))
        # 사업부문과 품목이 분리된 표는 두 표제가 함께 독립 항목을 식별한다.
        item_key_columns = 2 if label_columns >= 2 and _order_header(grid[header_at][1]) in {"품목", "프로젝트명"} else 1
        def item_key(row: list[str]) -> str:
            return " / ".join(row[:item_key_columns])
        total_rows = [row for row in data_rows if any(total_label.fullmatch(_order_header(cell)) for cell in row[:label_columns])]
        complete_totals = [row for row in total_rows if all(not _order_header(cell) or cell == "-"
                          or total_label.fullmatch(_order_header(cell)) for cell in row[:label_columns])]
        if len(complete_totals) == 1:
            total_rows = complete_totals
        strong_totals = [row for row in total_rows if any(re.search(r"合計|합\s*계|총\s*계", cell) for cell in row[:label_columns])]
        if strong_totals:
            total_rows = strong_totals
        company_totals = [row for row in total_rows if any(re.fullmatch(r"전사\s*합\s*계|총\s*합\s*계", cell) for cell in row[:label_columns])]
        if len(company_totals) == 1:
            total_rows = company_totals
        elif len(total_rows) > 1:
            # 품목별 '계'와 전체 '합계'를 구분하고, 합계의 기간별 소계를 중복 선택하지 않는다.
            repeated_totals = [row for row in total_rows if sum(bool(re.fullmatch(r"합\s*계", cell)) for cell in row[:label_columns]) >= 2]
            if len(repeated_totals) == 1:
                total_rows = repeated_totals
        minimum_rows = [row for row in data_rows if any("최소구매물량" in cell.replace(" ", "") for cell in row)
                        and not any("예상" in cell for cell in row)]
        # rowspan 합계 아래 내수·수출·소계가 반복될 때 명시 소계 한 행만 선택한다.
        subtotals = [row for row in total_rows if any(re.fullmatch(r"소\s*계", cell) for cell in row[:3])]
        if len(total_rows) > 1 and len(subtotals) == 1:
            total_rows = subtotals
        # 일부 보고서는 마지막 총계행의 표제를 비운다. 명시 항목 합과 정확히 일치할 때만 승인한다.
        if not total_rows and len(data_rows) > 1 and all(cell in {"", "-"} for cell in data_rows[-1][:3]):
            details = data_rows[:-1]
            if all(row[0].strip() for row in details) and len({row[0] for row in details}) == len(details):
                columns = [c for c in (backlog_column, new_column) if c is not None]
                if all(all(numeric.fullmatch(row[c].replace(" ", "")) for row in data_rows)
                       and sum(Decimal(row[c].replace(" ", "").replace(",", "")) for row in details)
                       == Decimal(data_rows[-1][c].replace(" ", "").replace(",", "")) for c in columns):
                    total_rows = [data_rows[-1]]
        if len(minimum_rows) == 1:
            chosen = minimum_rows[0]
            scope = "최소구매물량(확정 계약)"
        elif len(total_rows) == 1:
            chosen = total_rows[0]
            scope = "회사 공시 합계"
        else:
            usable_rows = [
                row for row in data_rows
                if any(c is not None and c < len(row) and numeric.fullmatch(row[c].replace(" ", ""))
                       for c in (backlog_column, new_column))
            ]
            item_rows = [row for row in data_rows if row[0].strip() and not re.match(r"주\d|[※*]", row[0].strip())]
            if len(total_rows) == 0 and len(usable_rows) == 1 and len(item_rows) == 1:
                chosen = usable_rows[0]
                scope = "회사 공시 단일행"
            elif (not total_rows and len(usable_rows) > 1
                  and len(usable_rows) == len(item_rows)
                  and all(row[0].strip() for row in usable_rows)
                  and len({item_key(row) for row in usable_rows}) == len(usable_rows)
                  and not any(re.search(r"소\s*계|합\s*계|총\s*계", cell)
                              for row in usable_rows for cell in row[:3])):
                # 한 표의 모든 공개 항목만 합산한다. 결측·비공개·통화 혼합은 합산하지 않는다.
                chosen = [""] * len(grid[0])
                for column in (backlog_column, new_column):
                    if column is not None and all(numeric.fullmatch(row[column].replace(" ", "")) for row in usable_rows):
                        amounts = [Decimal(row[column].replace(" ", "").replace(",", "")) for row in usable_rows]
                        if all(v >= 0 for v in amounts):
                            chosen[column] = format(sum(amounts), ",f")
                scope = "공시 항목 합산(표 범위)"
            else:
                # 같은 표에 해당 없음/비공개 행이 섞여 있어도 공개 항목 각각은 보존한다.
                # 합계를 만들지 않으며 식별 가능한 공개 항목만 범위별로 승인한다.
                published = [row for row in usable_rows if row[0].strip()
                             and not re.search(r"합\s*계|소\s*계|총\s*계", row[0])
                             and len(row[0]) <= 100
                             and any(c is not None and c < len(row) and numeric.fullmatch(row[c].replace(" ", ""))
                                     for c in (backlog_column, new_column))]
                if not total_rows and len(published) >= 1 and len({item_key(row) for row in published}) == len(published):
                    for row in published:
                        scoped = f"공시 공개 항목: {item_key(row)}"
                        if scope_heading:
                            scoped = f"{scope_heading} / {scoped}"
                        values = [row[c].replace(" ", "") if c is not None and c < len(row)
                                  and numeric.fullmatch(row[c].replace(" ", ""))
                                  and Decimal(row[c].replace(" ", "").replace(",", "")) >= 0 else None
                                  for c in (backlog_column, new_column)]
                        if any(v is not None for v in values):
                            candidates.append((unit, scoped, *values))
                            candidate_items.append(None)
                            period_labels[scoped] = "보고기간 누적"
                continue

        def value_at(column: int | None) -> str | None:
            if column is None or column >= len(chosen):
                return None
            value = chosen[column].replace(" ", "")
            # 삼성중공업의 합계 323.129(25Q1)/315.350(24Q4)는 쉼표 오기다.
            # 배율을 추측하지 않는다. 모든 독립 세부행이 정수 금액이고 그 합이
            # 점을 제거한 합계와 정확히 같을 때만 원문 세부행 합산액을 채택한다.
            if len(total_rows) == 1 and chosen is total_rows[0] and re.fullmatch(r"\d{1,3}\.\d{3}", value):
                details = [row for row in data_rows if row not in total_rows]
                keys = [tuple(row[:label_columns]) for row in details]
                if (len(details) >= 2 and len(set(keys)) == len(keys)
                        and all(row[0].strip() and not any(total_label.fullmatch(_order_header(cell))
                                for cell in row[:label_columns]) for row in details)
                        and all(column < len(row) and re.fullmatch(r"\d+(?:,\d{3})*", row[column].replace(" ", ""))
                                for row in details)):
                    detail_sum = sum(Decimal(row[column].replace(" ", "").replace(",", "")) for row in details)
                    if detail_sum == Decimal(value.replace(".", "")):
                        value = format(detail_sum, ",f")
            # 한 계약만 있어도 원문 수주총액-기납품액의 명시 금액으로 입증할 수 있다.
            # 당기 신규수주-매출로 잔고를 추정하는 것이 아니라 같은 계약 행의 오기 대조다.
            if (column == backlog_column and re.fullmatch(r"\d{1,3}\.\d{3}", value)
                    and contract_column is not None and delivered_column is not None
                    and all(c < len(chosen) and re.fullmatch(r"\d+(?:,\d{3})*", chosen[c].replace(" ", ""))
                            for c in (contract_column, delivered_column))):
                remaining = (Decimal(chosen[contract_column].replace(" ", "").replace(",", ""))
                             - Decimal(chosen[delivered_column].replace(" ", "").replace(",", "")))
                if remaining == Decimal(value.replace(".", "")):
                    value = format(remaining, ",f")
            return value if numeric.fullmatch(value) and float(value.replace(",", "")) >= 0 else None

        backlog = value_at(backlog_column)
        new_orders = value_at(new_column)
        if backlog is None and new_orders is None and len(total_rows) == 1:
            details = [row for row in data_rows if row not in total_rows]
            keys = [tuple(row[:label_columns]) for row in details]
            if details and len(set(keys)) == len(keys) and all(row[0].strip() for row in details):
                chosen = [""] * len(grid[0])
                for column in (backlog_column, new_column):
                    if column is not None and all(numeric.fullmatch(row[column].replace(" ", "")) for row in details):
                        values = [Decimal(row[column].replace(" ", "").replace(",", "")) for row in details]
                        if all(v >= 0 for v in values):
                            chosen[column] = format(sum(values), ",f")
                backlog, new_orders = value_at(backlog_column), value_at(new_column)
                scope = "공시 항목 합산(표 범위)"
        if backlog is None and new_orders is None:
            continue
        nearby = " ".join(
            tag.get_text(" ", strip=True)
            for tag in table.find_all_previous(["p", "title"], limit=4)
        )
        if re.search(r"주요\s*(?:프로젝트|(?:수주\s*)?계약)|진행률적용", nearby):
            scope = "주요계약(전체 회사 아님)"
        # 연결 수주표가 하나라도 종속회사만 공시한 수치일 수 있다.
        # 가장 가까운 회사 범위 표제를 보존해 연결 전체 잔고로 오인하지 않는다.
        if scope_heading:
            scope = f"{scope_heading} / {scope}"
        candidates.append((unit, scope, backlog, new_orders))
        items = sorted({row[0] for row in data_rows if row[0].strip()
                        and not total_label.fullmatch(row[0]) and not re.search(r"합\s*계|소\s*계", row[0])})
        candidate_items.append(" · ".join(items) if items and len(" · ".join(items)) <= 140 else None)
        period_labels[scope] = "당분기" if any("당분기수주총액" in path for path in paths) else "보고기간 누적"

    # 복수 표를 합산하지 않는다. 범위가 구분되지 않는 중복은 승인하지 않는다.
    original_counts = {(unit, scope): sum(c[0] == unit and c[1] == scope for c in candidates)
                       for unit, scope, _, _ in candidates}
    for i, (unit, scope, backlog, new_orders) in enumerate(candidates):
        if candidate_items[i] and original_counts[(unit, scope)] > 1:
            # 회사 표제가 없더라도 표의 품목 범위는 원문대로 보존한다.
            named_scope = f"{scope} / 표 품목: {candidate_items[i]}"
            candidates[i] = (unit, named_scope, backlog, new_orders)
            period_labels[named_scope] = period_labels[scope]
    counts = {(scope, unit): sum(c[1] == scope and c[0] == unit for c in candidates)
              for unit, scope, _, _ in candidates}
    result = []
    for unit, scope, backlog, new_orders in candidates:
        if counts[(scope, unit)] != 1 or not unit or any(not c[0] and c[1] == scope for c in candidates):
            continue
        rows = [f"범위 | {scope}", f"단위 | {unit}"]
        if backlog is not None:
            rows.append(f"수주잔고 | {backlog}")
        if new_orders is not None:
            rows.extend((f"신규수주 | {new_orders}", f"신규수주 기간 | {period_labels[scope]}"))
        result.append("\n".join(rows))
    # 회사 구분이 없는 서로 다른 변동표를 같은 범위로 덮어쓰지 않는다.
    vertical_by_scope: dict[tuple[str, str], set[str]] = {}
    for metric in vertical_series:
        lines = metric.splitlines()
        vertical_by_scope.setdefault((lines[0], lines[1]), set()).add(metric)
    result.extend(next(iter(values)) for values in vertical_by_scope.values() if len(values) == 1)
    narrative = narrative_order_metrics(section_xml) if not result else None
    return result or ([narrative] if narrative else [])


def structured_order_metrics(section_xml: str, *, period_end: str | None = None) -> str | None:
    series = structured_order_series(section_xml, period_end=period_end)
    return representative_order_metric(series)


def representative_order_metric(series: list[str]) -> str | None:
    if len(series) == 1:
        return series[0]
    # 회사 합계와 주요 계약 부분집합이 함께 있으면 합계가 대표 지표다.
    primary = [s for s in series if '주요계약(전체 회사 아님)' not in s]
    return primary[0] if len(primary) == 1 else None


def narrative_order_metrics(section_xml: str) -> str | None:
    """표 대신 명시한 현재 잔고 한 문장도 읽는다. 과거/목표/추정 값은 제외한다."""
    text = BeautifulSoup(section_xml, "html.parser").get_text(" ", strip=True)
    matches = re.findall(r"(?:작성기준일|보고기간\s*종료일|당(?:반기|분기|기)말)"
                         r"[^。.!?]{0,60}?수주\s*잔고\s*(?:는|[:：])\s*"
                         r"([\d,]+(?:\.\d+)?)\s*(억원|백만원|천원|원)", text)
    if len(matches) != 1:
        return None
    value, unit = matches[0]
    return f"범위 | 회사 공시 명시 잔고\n단위 | {unit}\n수주잔고 | {value}"


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
    report_period_end: str | None = None,
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
    order_series = structured_order_series(order_section_xml, period_end=report_period_end) if order_section_xml else []
    order_metric = representative_order_metric(order_series)
    if not order_series and order_section_xml:
        narrative = narrative_order_metrics(order_section_xml)
        if narrative:
            order_series = [narrative]
            order_metric = narrative
    raw_order_table = bool(order_section_xml and any(
        _order_header(cell.get_text(" ", strip=True)) in {
            "수주잔고", "기말수주잔고", "당기말수주잔고", "당기말수주잔액",
            "당분기말수주잔고", "당반기말수주잔고",
            "계약잔액", "수주잔액", "기말계약잔액", "수주잔고액", "기말수주잔고액",
            "신규수주", "당기수주", "신규수주액", "당기수주액", "당기신규수주액", "당기신규수주",
            "당반기수주", "당분기수주", "신규수주계약금액",
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
    if order_series:
        picked["공시 수주지표 목록"] = {"series": order_series}
    # 절이 없는 첨부·비정상 원문에 완료 표식을 쓰면 영원히 재수집되지 않는다.
    if sections:
        picked["공시 수주지표 확인"] = checked_marker
    source = re.search(r'<SOURCE chars="(\d+)">(.*?)</SOURCE>', xml, re.S)
    if source and sections:
        picked["원문 수집 경로"] = html.unescape(source.group(2))
    return ReportExcerpt(rcept_no=rcept_no, sections=picked,
                         full_chars=int(source.group(1)) if source else len(xml))


def excerpt_for(rcept_no: str, **kwargs) -> ReportExcerpt | None:
    """한 번에. **실패하면 None** — 발췌가 없다고 분석을 막지 않는다."""
    try:
        return build_excerpt(rcept_no, fetch_report_xml(rcept_no), **kwargs)
    except ExcerptError:
        return None
