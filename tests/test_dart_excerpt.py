# PRD Ref: §7.1 · ADR 4
"""정기보고서 발췌 — **순수 함수만** 테스트한다(네트워크 없음).

★ 실제 원문 구조를 줄여 만든 픽스처다. DART 반기보고서의 실제 모양
  (`<TITLE>`로 절이 갈리고, 표는 셀마다 줄바꿈이 들어 있다)을 그대로 재현한다.
"""

from __future__ import annotations

from src.collectors.dart_excerpt import (
    DEFAULT_BUDGET_CHARS,
    build_excerpt,
    split_sections,
    to_text,
)

# ★ 셀마다 개행이 들어간 실제 모양. 이게 압축되지 않으면 모델 출력이 깨진다.
SAMPLE = """<DOCUMENT>
<TITLE>II. 사업의 내용</TITLE>
<TITLE>4. 매출 및 수주상황</TITLE>
<P>4) 수주상황</P>
<TABLE>
<TR>
<TD>품목
</TD>
<TD>수주총액
</TD>
<TD>수주잔고
</TD>
</TR>
<TR>
<TD>콘덴서
</TD>
<TD>157,552
</TD>
<TD>1,852
</TD>
</TR>
</TABLE>
<P>이하 생략을 채우기 위한 본문이다. """ + ("가" * 120) + """</P>
<TITLE>5. 위험관리 및 파생거래</TITLE>
<P>여기는 뽑지 않는 절이다.</P>
</DOCUMENT>"""


# ═══ 표 압축 ═══
def test_table_row_becomes_one_line():
    """★★ 한 행이 한 줄이어야 한다.

    실측(2026-08-23): 셀마다 줄바꿈이 남은 채로 모델에 넣었더니 출력 6,475토큰을
    쓰고도 tool 호출 구조가 깨져 `earnings_change`가 객체가 아니라 문자열로 왔다.
    """
    text = to_text(SAMPLE)
    assert "품목 | 수주총액 | 수주잔고" in text
    assert "콘덴서 | 157,552 | 1,852" in text


def test_no_empty_separator_lines():
    """`| | |`처럼 내용 없는 줄은 남기지 않는다 — 토큰만 먹는다."""
    for line in to_text(SAMPLE).splitlines():
        assert line.strip(" |").strip(), f"빈 줄이 남았다: {line!r}"


# ═══ 절 분리 ═══
def test_extracts_only_wanted_sections():
    sections = split_sections(SAMPLE)
    assert "매출 및 수주상황" in sections
    # 목록에 없는 절은 뽑지 않는다.
    assert not any("위험관리" in name for name in sections)


def test_section_body_keeps_the_numbers():
    body = split_sections(SAMPLE)["매출 및 수주상황"]
    assert "1,852" in body, "수주잔고 숫자가 사라졌다"


def test_returns_empty_when_no_titles():
    """★ 절을 못 찾으면 **빈 dict**다. 없는 것을 지어내지 않는다."""
    assert split_sections("<DOCUMENT><P>제목이 없다</P></DOCUMENT>") == {}


# ═══ 예산 ═══
def test_excerpt_respects_budget():
    huge = SAMPLE.replace("가" * 120, "나" * 40_000)
    ex = build_excerpt("X", huge, budget_chars=300, per_section=300)
    total = sum(len(v) for v in ex.sections.values())
    # 생략 표시가 붙으므로 정확히 300은 아니지만 크게 넘지 않아야 한다.
    assert total <= 300 + 40, total


def test_excerpt_marks_what_was_cut():
    """★ 조용히 자르면 모델이 '정보가 없다'고 쓴다 — 실제로는 우리가 자른 것이다."""
    huge = SAMPLE.replace("가" * 120, "나" * 5_000)
    ex = build_excerpt("X", huge, budget_chars=200, per_section=200)
    assert any("생략" in body for body in ex.sections.values())


def test_full_chars_is_recorded():
    ex = build_excerpt("X", SAMPLE)
    assert ex.full_chars == len(SAMPLE)


def test_default_budget_is_within_token_budget():
    """★ 발췌 상한이 입력 토큰 상한과 어긋나지 않는지 — 한글 1자 ≈ 0.96토큰."""
    from src.config.constants import LLM_INPUT_TOKEN_BUDGET

    assert DEFAULT_BUDGET_CHARS < LLM_INPUT_TOKEN_BUDGET, (
        "발췌만으로 입력 상한을 넘긴다"
    )
