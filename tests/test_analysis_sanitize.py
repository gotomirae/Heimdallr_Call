# PRD Ref: §7 · traps.md T61
"""LLM 응답에 새어 든 XML 태그 제거. 외부 I/O 없이 돈다.

★ 이 함정의 고약한 점: **아무것도 실패하지 않는다.**
  - 도구 호출(tool_use) 스키마 검증 통과 (타입은 여전히 문자열)
  - `validate_payload` 통과 (필드가 비어 있지 않다)
  - 텔레그램 발송 성공 (`esc()`가 태그를 escape한다)
  화면에 `&lt;/one_line_thesis&gt;`가 그대로 보이는 것만이 유일한 증상이다.
"""

from __future__ import annotations

from src.analysis.analyze import sanitize_payload, strip_tag_leakage


#: 실측 그대로 (042700 한미반도체 2026.2Q · 2026-08-17)
LEAKED = (
    "1Q 급락 후 2Q 매출 2,512억(+39.5% YoY, 분기 사상 최대)으로 급반등, "
    "HBM용 TC본더 중심 실적 정상화 신호이나 주가는 52주 고점 대비 46% 하락해 있어 "
    "밸류에이션 부담과 회복 기대가 충돌하는 구간이다.</one_line_thesis>\n"
    '<parameter name="why_now">2026.1Q 매출이 전년 대비 -65.5%까지 급락했다가 '
    "2Q에 곧바로 +39.5% 증가하며 분기 매출 사상 최대치를 경신했다."
)


def test_strips_real_measured_leak():
    out = strip_tag_leakage(LEAKED)
    assert out.endswith("충돌하는 구간이다.")
    assert "</one_line_thesis>" not in out
    assert "why_now" not in out
    # 실측 334자 → 127자. 뒤 207자가 통째로 다른 필드의 내용이었다.
    assert len(out) == 127, f"{len(out)}자 — 334자에서 127자로 잘려야 한다"


def test_leaves_clean_text_untouched():
    clean = "매출이 2분기 연속 가속했고 이익률도 함께 올랐다."
    assert strip_tag_leakage(clean) == clean


def test_strips_various_markers():
    for marker in ("</thesis>", "<parameter name=", "<function_calls>", "<invoke "):
        assert strip_tag_leakage(f"정상 문장이다.{marker}뒤쪽 쓰레기") == "정상 문장이다."


def test_returns_original_when_cut_would_empty_it():
    """★ 잘라서 빈 문자열을 만들지 않는다 — 없는 값으로 바꿔치기하는 셈이다."""
    assert strip_tag_leakage("</only_a_tag>") == "</only_a_tag>"


def test_sanitize_walks_nested_structures():
    """어느 필드에서 샐지 미리 알 수 없다 — dict·list를 전부 훑는다."""
    payload = {
        "one_line_thesis": LEAKED,
        "risks": [{"risk": "고객 집중도</risk> 누출", "impact": "큼"}],
        "acceleration_quality": {"is_genuine": True, "sustainability_quarters": 2},
        "scenarios": {"bull": {"probability": 0.3, "description": "정상"}},
    }
    out = sanitize_payload(payload)
    assert out["one_line_thesis"].endswith("충돌하는 구간이다.")
    assert out["risks"][0]["risk"] == "고객 집중도"
    # 문자열이 아닌 값은 건드리지 않는다
    assert out["acceleration_quality"]["is_genuine"] is True
    assert out["acceleration_quality"]["sustainability_quarters"] == 2
    assert out["scenarios"]["bull"]["probability"] == 0.3


def test_sanitize_handles_non_string_scalars():
    assert sanitize_payload(None) is None
    assert sanitize_payload(3) == 3
    assert sanitize_payload([1, "a</b>c"]) == [1, "a"]
