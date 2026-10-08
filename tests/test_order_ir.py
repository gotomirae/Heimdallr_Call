# PRD Ref: §9.1-3 · 공식 IR 실측 수주표 재생
from src.collectors.order_ir import parse_quarter_order_page, parse_ls_backlog, parse_ls_new_orders


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
