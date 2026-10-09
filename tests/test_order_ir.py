# PRD Ref: §9.1-3 · 공식 IR 실측 수주표 재생
import pytest

from src.collectors.order_ir import parse_quarter_order_page, parse_ls_backlog, parse_ls_new_orders
from src.collectors.order_ir import download_verified_pdf, merge_ir_scope
from src.collectors.order_ir import parse_separate_quarter_order_page


def test_separate_order_table_requires_quarter_scope_and_unit():
    # 산일전기 26Q2 실제 p2: 손계산 5567 / 4774 - 1 = 16.6108085%.
    text = "구분\n2Q25\n1Q26\n2Q26\nQoQ\nYoY\n매출액\n1,283\n1,503\n1,642\n수주\n924\n1,790\n2,435\n36.1%\n163.4%\n수주잔고\n4,195\n4,774\n5,567\n16.6%\n32.7%\n분기실적\n단위:억원, %\n주1: K-IFRS 별도기준\n신규수주YoY +163.4%\n수주"
    rows = parse_separate_quarter_order_page(text)
    assert [(r['year'], r['quarter'], r['new_orders'], r['backlog']) for r in rows] == [
        (2025, 2, 924, 4195), (2026, 1, 1790, 4774), (2026, 2, 2435, 5567)]
    assert all(r['new_orders_period'] == '당분기' and r['unit'] == '억원' for r in rows)
    for old, replacement in [('별도기준', '기준'), ('억원', '백만원'), ('2,435', '-'),
                             ('2Q26', '1Q26'), ('수주\n924', '수주\n수주\n924'), ('신규수주', '누적수주')]:
        assert parse_separate_quarter_order_page(text.replace(old, replacement)) == []


def test_ir_quarter_headers_and_row_units_override_financial_table_unit():
    # 실제 HD현대일렉트릭 2Q26 IR p4. 수주 행만 백만불, 재무 행은 억원.
    text = "구분\n2Q25\n1Q26\n2Q26\nQoQ\nYoY\n수주(백만불)\n996\n1,797\n1,440\n-19.9%\n44.6%\n수주잔고(백만불)\n6,550\n7,888\n8,490\n7.6%\n29.6%\n(연결기준, 단위: 억원)"
    rows = parse_quarter_order_page(text)
    assert [(r["year"], r["quarter"], r["backlog"], r["new_orders"]) for r in rows] == [
        (2025, 2, 6550, 996), (2026, 1, 7888, 1797), (2026, 2, 8490, 1440)]
    assert all(r["unit"] == "백만USD" and r["new_orders_period"] == "당분기" for r in rows)
    assert parse_quarter_order_page(text.replace("백만불", "")) == []
    assert parse_quarter_order_page(text.replace("(연결기준, 단위: 억원)", "")) == []
    assert parse_quarter_order_page(text.replace("1,440", "비공개")) == []


def test_ls_quarter_orders_preserve_chart_scale_and_backlog_table_scope():
    text = "Financial Results\n[단위:십억원]\nNew Orders\n852\n608\n684\n1,573\n1,086\n'25 1Q '25 2Q '25 3Q '25 4Q '26 1Q\nOperating Profit\nBacklog\n[단위:조원]"
    assert [r["new_orders"] for r in parse_ls_new_orders(text)] == [8520, 6080, 6840, 15730, 10860]
    assert parse_ls_new_orders(text.replace("십억원", "원")) == []
    table = "단위 : 억원\n수주잔고 현황\n주요 제품\n2Q ‘25\n1Q ‘26\n2Q ‘26\nYoY\n배전반\n20,009\nTotal\n38,557\n56,425\n69,998"
    assert [(r['year'], r['quarter'], r['backlog']) for r in parse_ls_backlog(table)] == [(2025, 2, 38557), (2026, 1, 56425), (2026, 2, 69998)]


def test_ir_scope_replay_keeps_other_business_and_legacy_evidence():
    # 미코의 HPS/미코파워/플랜텍은 같은 분기지만 서로 다른 수주 사업이다.
    old = {"series": ["범위 | HPS\n수주잔고 | 3844"], "evidence": {"scope": "HPS", "backlog": 3844}}
    power = {"scope": "미코파워", "backlog": 707}
    merged = merge_ir_scope(old, "범위 | 미코파워\n수주잔고 | 707", power)
    assert len(merged["series"]) == len(merged["evidence"]) == 2
    updated = {"scope": "HPS", "backlog": 3900}
    replay = merge_ir_scope(merged, "범위 | HPS\n수주잔고 | 3900", updated)
    assert replay["evidence"] == [power, updated]
    assert replay["series"] == ["범위 | 미코파워\n수주잔고 | 707", "범위 | HPS\n수주잔고 | 3900"]
    assert old["evidence"]["backlog"] == 3844


@pytest.mark.parametrize("fact", [
    {"code": "028050", "source_url": "https://evil.invalid/", "download_idx": 310},
    {"code": "006360", "source_url": "https://sea.samsungena.com/kr/ir/event-earnings", "download_idx": 310},
    {"code": "028050", "source_url": "https://sea.samsungena.com/kr/ir/event-earnings", "download_idx": -1},
    {"code": "028050", "source_url": "https://sea.samsungena.com/kr/ir/event-earnings", "download_idx": True},
])
def test_ir_form_rejects_other_company_host_and_invalid_file_id_before_io(fact):
    with pytest.raises(ValueError, match="대상 불일치"):
        download_verified_pdf(fact)
