# PRD Ref: §8 · traps.md T13
"""P8 텔레그램 테스트. 외부 I/O 없이 돈다."""

from __future__ import annotations

import pytest

from src.config.constants import NOTIFY_GRADES
from src.notify.links import dart_report_url, naver_stock_url
from src.notify.telegram import (
    ALLOWED_METHODS,
    MAX_MESSAGE_CHARS,
    PREFIX,
    TelegramClient,
    TelegramMethodNotAllowed,
    truncate,
)
from src.notify.templates import daily_digest, flash_message, upgrade_message


# ═══════════════════════════════════════════════════════════════════
# ★★ T13 — 웹훅 차단이 이 Phase의 안전 장치다
#
# 봇을 분리한 뒤(2026-08-15)에도 **웹훅류는 영구 차단**이다.
# 이 프로젝트는 웹훅이 필요 없고(getUpdates 폴링), 잘못 부르면 남의 봇이
# 에러 없이 죽는다. 수신은 `getUpdates`로 열되 **전용 봇에서만** 허용한다.
# ═══════════════════════════════════════════════════════════════════
DEDICATED = "9999999999:dummy"


@pytest.mark.parametrize(
    "method",
    ["setWebhook", "deleteWebhook", "getWebhookInfo", "setMyCommands"],
)
def test_webhook_methods_are_blocked(method):
    """★ 봇 분리 후에도 풀지 않는다. 필요 없는 기능에 사고 경로를 열어둘 이유가 없다."""
    client = TelegramClient(token=DEDICATED, chat_id="1")
    with pytest.raises(TelegramMethodNotAllowed):
        client._ensure_allowed(method)


def test_allowlist_contains_no_webhook_method():
    assert ALLOWED_METHODS == {"sendMessage", "getMe", "getUpdates"}
    for method in ALLOWED_METHODS:
        assert "webhook" not in method.lower()


def test_send_message_is_allowed():
    TelegramClient(token=DEDICATED, chat_id="1")._ensure_allowed("sendMessage")


# ═══ 4,096자 상한 ═══
def test_short_message_untouched():
    text, truncated = truncate("짧은 메시지")
    assert text == "짧은 메시지" and truncated is False


def test_long_message_truncated_within_limit():
    text, truncated = truncate("가" * 5000)
    assert truncated is True
    assert len(text) <= MAX_MESSAGE_CHARS


def test_truncation_marks_itself():
    text, _ = truncate("가" * 5000)
    assert "생략" in text


def test_truncation_cuts_at_line_boundary():
    """줄 중간에서 자르면 표가 깨진다."""
    body = "\n".join(f"| 행{i} | 값 |" for i in range(500))
    text, truncated = truncate(body)
    assert truncated is True
    assert not text.replace("\n…(이하 생략)", "").endswith("| 행")


# ═══ 템플릿 ═══
def _flash_ctx(**over) -> dict:
    ctx = {
        "code": "058470", "name": "리노공업", "board": "KOSDAQ",
        "fiscal_year": 2026, "fiscal_quarter": 2, "grade": "★",
        "revenue": 135_100_000_000, "revenue_yoy": 20.1, "revenue_yoy_prev": 8.0,
        "yoy_delta_pp": 12.1, "op": 66_300_000_000, "op_yoy": 24.2,
        "opm": 49.1, "opm_yoy_delta": 1.6, "score": 82, "pri": 31,
        "score_a": 28, "score_b": 27, "raw_sum": 55, "denominator": 67,
        "has_consensus": True, "base_effect_warning": False,
        "url": "https://example/stock/058470",
    }
    ctx.update(over)
    return ctx


def test_flash_has_shield_prefix():
    """🛡️로 HermesCall의 ⚡/🔬와 구분한다."""
    assert flash_message(_flash_ctx()).startswith(PREFIX)


def test_flash_shows_grade_and_scores():
    text = flash_message(_flash_ctx())
    assert "★" in text and "82" in text and "31" in text



def test_flash_flags_base_effect_warning():
    assert "기저효과" in flash_message(_flash_ctx(base_effect_warning=True))


def test_flash_flags_unmeasurable_base_effect():
    """★ 판정 불가와 '경고 없음'을 구분한다 — 현재 rev_2y가 대부분 결측이다."""
    text = flash_message(_flash_ctx(base_effect_measurable=False))
    assert "판정불가" in text


def test_flash_marks_estimate():
    assert "잠정" in flash_message(_flash_ctx(is_estimate=True))


def test_flash_names_each_score_axis():
    """A/B/C/D를 문자로만 쓰지 않는다 — 무엇을 재는 축인지 이름을 붙인다."""
    text = flash_message(_flash_ctx())
    for label in ("성장가속", "수익성", "서프라이즈", "회계품질"):
        assert label in text











def test_flash_omits_valuation_block_when_no_data():
    """PER·PBR이 전부 없으면 빈 블록을 만들지 않는다."""
    text = flash_message(_flash_ctx())
    assert "💰 밸류에이션" not in text


def test_flash_handles_all_missing_values():
    """결측이어도 죽지 않고 —로 표시한다."""
    text = flash_message({"code": "A", "name": "N", "board": "KOSPI"})
    assert "—" in text


def test_daily_digest_truncates_to_top_n():
    """4,096자를 넘기지 않도록 상위 N개로 자르고 '외 M종목'을 붙인다."""
    rows = [{"grade": "○", "name": f"종목{i}", "score": 70, "pri": 40,
             "revenue_yoy": 10.0, "opm_yoy_delta": 1.0, "has_consensus": True}
            for i in range(40)]
    text = daily_digest({"date": "2026-08-13", "rows": rows, "counts": {"★": 2, "○": 3}})
    assert "외 25종목" in text
    assert len(text) <= MAX_MESSAGE_CHARS


def test_daily_digest_with_no_rows():
    text = daily_digest({"date": "2026-08-13", "rows": [], "counts": {}})
    assert "발송 대상" in text


def test_upgrade_message():
    text = upgrade_message({"rows": [
        {"from_grade": "△", "to_grade": "○", "name": "N", "code": "A",
         "score": 80, "pri": 38, "pri_before": 72}
    ]})
    assert "△" in text and "○" in text and PREFIX in text


def test_notify_grades_are_star_and_circle_only():
    """△와 ·는 대시보드에만. 발송 대상이 넓어지면 알림이 소음이 된다."""
    assert NOTIFY_GRADES == ("★", "○")


# ═══════════════════════════════════════════════════════════════════
# 모바일 가독성 — 이번 개편의 핵심이라 회귀를 테스트로 막는다
# ═══════════════════════════════════════════════════════════════════
import re

from src.notify.templates import (
    amount,
    bar,
    clip,
    display_width,
    pick_unit,
    signed,
)

#: 폰 세로 화면에서 접히지 않는 한계. 넘으면 표가 통째로 깨진다.
MOBILE_WIDTH = 38


def _visible_lines(text: str) -> list[str]:
    return [re.sub(r"<[^>]+>", "", line) for line in text.split("\n")]


def _rich_ctx(**over) -> dict:
    ctx = _flash_ctx(
        industry="통신 및 방송 장비 제조업",
        products="통신 및 방송 장비 제조(무선) 제품, 반도체 제조(메모리) 제품,"
                 " 전자부품 제조(디스플레이) 제품, 영상 및 음향기기 제조 제품 등",
        market_cap_label="1,552.2조",
        np=716_245_00000000, np_yoy=300.0,
        quarters=[
            {"fiscal_year": 2025, "fiscal_quarter": q, "revenue": 79e12,
             "revenue_yoy": 10.0, "opm": 8.0, "is_estimate": False}
            for q in (1, 2, 3, 4)
        ] + [
            {"fiscal_year": 2026, "fiscal_quarter": 1, "revenue": 133e12,
             "revenue_yoy": 69.0, "opm": 42.8, "is_estimate": False},
            {"fiscal_year": 2026, "fiscal_quarter": 2, "revenue": 171e12,
             "revenue_yoy": 130.0, "opm": 52.2, "is_estimate": True},
        ],
        n_estimates=24, revenue_est=173e12, op_est=85e12,
        revenue_surprise=-1.4, op_surprise=5.2,
        per=41.8, pbr=4.29, per_ttm=10.6, fwd_per=10.5,
        per_by_quarter=[
            {"fiscal_year": 2026, "fiscal_quarter": 1, "per": 19.1},
            {"fiscal_year": 2026, "fiscal_quarter": 2, "per": 10.6},
        ],
        pri_parts_detail={"p1": 24.0, "p2": 17.0, "p3": None, "p4": None},
        raw={"a1": 14.0, "a2": 10.0, "b1": 14.0, "c1": 3.0, "c2": 0.0},
        score_c=3,
    )
    ctx.update(over)
    return ctx


def test_display_width_counts_hangul_as_two():
    """★ `len()`으로 재면 한글이 절반으로 계산돼 '32자 이내'가 실제 60칸이 된다."""
    assert display_width("abc") == 3
    assert display_width("삼성전자") == 8
    assert len("삼성전자") == 4  # len은 4라 폭 검사에 쓰면 안 된다



def test_html_has_no_stray_angle_bracket():
    """★ `<`가 본문에 남으면 텔레그램이 400을 준다 — 발송 자체가 실패한다.

    실측: F.PER 옆에 붙인 `<컨센 기준>`이 태그로 해석돼 죽었다.
    """
    text = flash_message(_rich_ctx())
    tags = set(re.findall(r"</?([a-zA-Z]+)[^>]*>", text))
    assert tags <= {"b", "i", "pre", "code", "a"}, f"허용 밖 태그: {tags}"
    assert not re.search(r"<(?![/a-zA-Z])", text)


def test_company_name_is_escaped():
    """종목명에 `&`가 실제로 들어온다 — 이스케이프 안 하면 발송이 깨진다."""
    text = flash_message(_rich_ctx(name="A&B <홀딩스>"))
    assert "&amp;" in text
    assert "<홀딩스>" not in text


def test_preliminary_is_labelled_and_confirmed_replaces_it():
    """★ 잠정을 우선 보여주고, 확정이 들어오면 확정으로 바뀐다."""
    assert "잠정" in flash_message(_rich_ctx(is_estimate=True))
    confirmed = flash_message(_rich_ctx(is_estimate=False))
    assert "확정" in confirmed


def test_confirmed_delta_is_surfaced():
    """확정치가 잠정보다 나빠졌으면 그 자체가 경고다(T4) — 숨기지 않는다."""
    text = flash_message(
        _rich_ctx(is_estimate=False, confirmed_delta={"영업익": -8.2})
    )
    assert "잠정 대비" in text and "-8.2" in text



def test_pick_unit_keeps_one_unit_per_table():
    """표 하나에 단위가 섞이면 자릿수가 흔들려 표가 표로 안 보인다."""
    divisor, unit = pick_unit([171e12, 89e12, 71e12])
    assert unit == "조"
    divisor, unit = pick_unit([1351e8, 663e8])
    assert unit == "억"


def test_amount_and_signed_pad_to_fixed_width():
    assert len(amount(171e12, 1e12, 8)) == 8
    assert len(signed(130.0, 9)) == 9
    assert amount(None, 1e12, 8).strip() == "—"


def test_bar_is_fixed_width():
    """막대는 폭이 고정이어야 열이 맞는다."""
    assert len(bar(0.0)) == len(bar(0.5)) == len(bar(1.0)) == 5


def test_clip_marks_truncation():
    assert clip("삼성전자", 20) == "삼성전자"
    assert clip("아주아주긴회사이름입니다", 8).endswith("…")
    assert display_width(clip("아주아주긴회사이름입니다", 8)) <= 8


# ═══════════════════════════════════════════════════════════════════
# 간소화된 알림 계약 (2026-08-16 개편)
#
# 상세(항목별 득점 · 분기 추이 · 컨센서스 표)는 **대시보드로 옮겼다.**
# 알림은 "무슨 회사가 / 얼마나 좋아졌고 / 주가는 얼마나 알고 있고 / 비싼가"만 답한다.
# ═══════════════════════════════════════════════════════════════════

def test_korean_particles_agree():
    """★ 받침을 안 보면 '제조업다' 같은 문장이 나온다 — 사람이 읽는 글이다."""
    from src.notify.templates import copula, subject_particle
    assert copula("제조업") == "이다"
    assert copula("반도체") == "다"
    assert subject_particle("저스템") == "은"
    assert subject_particle("삼성전자") == "는"
    assert copula("GST") == "다"  # 영문으로 끝나면 받침 규칙을 쓰지 않는다


def test_products_are_tidied():
    """원문의 '제조·도매·제품' 꼬리와 괄호 설명을 걷어낸다."""
    from src.notify.templates import tidy_products
    assert tidy_products("통신 및 방송 장비 제조(무선) 제품, 반도체 제조(메모리) 제품") == [
        "통신 및 방송 장비", "반도체"
    ]



def test_score_is_one_line_with_axes():
    """축별 요약만 한 줄. 항목별 상세는 대시보드로 갔다."""
    text = flash_message(_rich_ctx(score_c=3))
    assert "🎯" in text and "성장가속" in text and "서프라이즈" in text
    assert "매출YoY델타" not in text  # 항목 상세는 없다


def test_unmeasured_axis_shows_dash_not_zero():
    """★ 미측정 축은 0이 아니라 —다. 분모에서 빠졌다는 뜻이다(ADR 2)."""
    text = flash_message(_rich_ctx(score_c=None, score_d=None))
    assert "서프라이즈 —" in text and "회계품질 —" in text





def test_removed_sections_stay_removed():
    """★ 분기 추이·컨센서스 표는 대시보드 전용이다."""
    text = flash_message(_rich_ctx())
    assert "분기 추이" not in text
    assert "컨센서스</b> 추정" not in text


def test_message_is_short_enough_to_read_at_once():
    """스크롤하며 읽는 알림은 안 읽힌다. 개편 전 1,405자 → 목표 900자 이하."""
    text = flash_message(_rich_ctx())
    assert len(text) < 900, f"{len(text)}자 — 너무 길다"


# ═══════════════════════════════════════════════════════════════════
# 줄 단위 알림 계약 (2026-08-16 2차 개편)
#
# 숫자 표(`<pre>`)를 걷어내고 이모지 + 줄 단위로 바꿨다.
# 항목이 셋뿐이면 표를 쓸 이유가 없고, 폰에서는 표가 폭에 쫓긴다.
# ═══════════════════════════════════════════════════════════════════
def test_profile_says_what_the_company_makes():
    """★ 업종 분류가 아니라 **제품**으로 설명한다."""
    text = flash_message(_rich_ctx(name="삼성전자"))
    assert "삼성전자는" in text and "만든다" in text
    assert "반도체" in text


def test_profile_falls_back_to_industry():
    """제품이 없으면 업종으로. 문장 형태는 유지한다."""
    text = flash_message(_rich_ctx(products=None, industry="기타 식품 제조업"))
    assert "기타 식품 제조업" in text and "기업이다" in text


def test_strength_comes_only_from_full_marks():
    """★ '강점'은 지어내지 않는다 — 스코어가 만점을 준 항목만 쓴다."""
    from src.notify.templates import strength_line
    assert strength_line({"raw": {"b4": 5, "b3": 6}}) == "💪 업종 내 수익성 상위 · 영업레버리지 작동"
    assert strength_line({"raw": {"b4": 3}}) == ""  # 부분 점수는 강점이 아니다
    assert strength_line({}) == ""


def test_earnings_uses_lines_not_table():
    """★ `<pre>` 표를 쓰지 않는다. 이모지로 항목을 구분한다."""
    text = flash_message(_rich_ctx())
    assert "<pre>" not in text
    assert "💵 매출" in text and "💰 영업익" in text and "📐 OPM" in text


def test_acceleration_covers_all_three_metrics():
    """★★ 매출만 늘고 이익이 안 늘면 가속이 아니다 — 셋 다 보여준다."""
    text = flash_message(_rich_ctx(
        revenue_yoy_prev=33.2, revenue_yoy=35.0,
        op_yoy_prev=58.8, op_yoy=32.2,
        opm_prev=21.8, opm=24.8,
    ))
    accel = [l for l in text.split("\n") if l.startswith("   ")]
    assert any("매출" in l for l in accel)
    assert any("영업익" in l and "▼" in l for l in accel)  # 감속도 그대로 보인다
    assert any("OPM" in l for l in accel)


def test_acceleration_unit_is_percent_not_pp_for_levels():
    """★ 값 자체는 %, **변화량만** %p다.

    OPM 전분기를 '+21.8%p'로 쓰면 마진이 아니라 변화폭으로 읽힌다.
    """
    text = flash_message(_rich_ctx(opm_prev=21.8, opm=24.8))
    line = next(l for l in text.split("\n") if l.strip().startswith("OPM"))
    assert "+21.8% →" in line and "+24.8%" in line
    assert "▲3.0%p" in line


def test_pri_shows_only_reflected_and_pending():
    """★ 미측정 항목은 적지 않는다 — 판단에 쓸 정보가 아니다."""
    text = flash_message(_rich_ctx(
        pri=62, pri_parts_detail={"p1": 24.0, "p2": 20.0, "p3": None, "p4": None}
    ))
    assert "✅ 반영:" in text and "⬜ 미반영:" in text
    assert "미측정" not in text


def test_pri_says_so_when_nothing_measured():
    """다만 아무것도 못 쟀으면 그 사실은 밝힌다 — 없는 것과 0점은 다르다."""
    text = flash_message(_rich_ctx(pri=None, pri_parts_detail={}))
    assert "판정하지 못했다" in text


def test_valuation_shows_ttm_and_forward_only():
    """최근 4분기 PER과 향후 4분기 Forward PER, 둘만."""
    text = flash_message(_rich_ctx(per=41.8, per_ttm=10.6, fwd_per=3.9))
    assert "최근 4분기" in text and "10.6배" in text
    assert "향후 4분기" in text and "3.9배" in text
    assert "41.8" not in text  # 후행 PER 값은 싣지 않는다


def test_valuation_states_when_forward_unavailable():
    """★ 컨센서스가 없으면 만들어내지 않고 없다고 밝힌다."""
    text = flash_message(_rich_ctx(per_ttm=22.0, fwd_per=None))
    assert "컨센서스가 없어 계산하지 않았다" in text


def test_message_stays_short():
    text = flash_message(_rich_ctx())
    assert len(text) < 900, f"{len(text)}자"


# ═══════════════════════════════════════════════════════════════════
# 바깥 링크 — 대시보드 · 네이버 증권 · DART 원문
# ═══════════════════════════════════════════════════════════════════
def test_dart_report_url_uses_receipt_number():
    """DART 원문은 **접수번호**로만 열린다."""
    url = dart_report_url("20260814003699")
    assert url == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814003699"


def test_dart_url_is_none_without_receipt_number():
    """★ 접수번호가 없으면 링크를 만들지 않는다.

    회사명으로 DART 검색 주소를 조립하면 **200이 뜨고 검색창에 이름까지
    채워지지만 검색이 실행되지 않아 빈 화면**이 나온다(T58).
    죽은 링크가 아니라 '살아 있는데 아무것도 없는' 링크라 더 나쁘다.
    """
    assert dart_report_url(None) is None
    assert dart_report_url("") is None


def test_naver_url_pc_and_mobile():
    assert naver_stock_url("005930") == (
        "https://finance.naver.com/item/main.naver?code=005930"
    )
    assert naver_stock_url("005930", mobile=True) == (
        "https://m.stock.naver.com/domestic/stock/005930/total"
    )


def test_alphanumeric_code_survives_url_building():
    """★ `0126Z0` 같은 영숫자 종목코드를 버리지 않는다(T6)."""
    assert "0126Z0" in naver_stock_url("0126Z0")


def test_flash_never_links_dart_search_page():
    """★ 회사명 검색 주소가 다시 기어들어오지 못하게 못 박는다."""
    text = flash_message(_rich_ctx(dart_url=dart_report_url("20260814003699")))
    assert "dsab007" not in text
    assert "textCrpNm" not in text
    assert "dsaf001/main.do?rcpNo=" in text


def test_flash_links_naver_and_dart():
    text = flash_message(
        _rich_ctx(
            naver_url=naver_stock_url("058470", mobile=True),
            dart_url=dart_report_url("20260814003699"),
        )
    )
    assert "대시보드" in text and "네이버증권" in text and "DART 원문" in text


def test_flash_omits_dart_link_when_no_disclosure():
    """공시를 못 받은 종목은 DART 링크를 아예 걸지 않는다."""
    text = flash_message(_rich_ctx(naver_url=naver_stock_url("058470"), dart_url=None))
    assert "네이버증권" in text
    assert "DART" not in text


def test_flash_states_acceleration_definition():
    """'가속'이 성장률이 아니라 **성장률의 변화**임을 제목이 말해야 한다."""
    text = flash_message(_rich_ctx())
    assert "전분기 성장률 →" in text
