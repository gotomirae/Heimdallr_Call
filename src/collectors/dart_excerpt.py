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
        name = archive.namelist()[0]
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
    remaining = budget_chars
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
    return ReportExcerpt(rcept_no=rcept_no, sections=picked, full_chars=len(xml))


def excerpt_for(rcept_no: str, **kwargs) -> ReportExcerpt | None:
    """한 번에. **실패하면 None** — 발췌가 없다고 분석을 막지 않는다."""
    try:
        return build_excerpt(rcept_no, fetch_report_xml(rcept_no), **kwargs)
    except ExcerptError:
        return None
