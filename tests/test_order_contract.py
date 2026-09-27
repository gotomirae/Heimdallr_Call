# PRD Ref: §9.1-3 — 단일판매·공급계약 구조화

from src.collectors.order_contract_run import parse_order_contract


def test_parse_order_contract_keeps_official_fields_without_unit_guessing():
    xml = """<TABLE>
    <TR><TD>계약내용</TD><TD>AI 서버용 HBM 검사장비 공급</TD></TR>
    <TR><TD>계약금액(원)</TD><TD>12,340,000,000</TD></TR>
    <TR><TD>최근매출액(원)</TD><TD>100,000,000,000</TD></TR>
    <TR><TD>매출액 대비(%)</TD><TD>12.34</TD></TR>
    <TR><TD>계약상대방</TD><TD>Global Customer</TD></TR>
    <TR><TD>계약(수주)일자</TD><TD>2026-09-24</TD></TR>
    <TR><TD>계약기간</TD><TD>시작일</TD><TD>2026-10-01</TD></TR>
    <TR><TD>계약기간</TD><TD>종료일</TD><TD>2027-03-31</TD></TR>
    </TABLE>"""
    result = parse_order_contract(xml)
    assert result is not None
    assert result.amount_krw == 12_340_000_000
    assert result.sales_ratio_pct == 12.34
    assert result.counterparty == "Global Customer"
    assert result.contract_date == "2026-09-24"
    assert result.start_date == "2026-10-01"
    assert result.end_date == "2027-03-31"


def test_contract_amount_without_won_label_is_not_scaled_or_guessed():
    xml = """<TABLE><TR><TD>계약내용</TD><TD>공급 계약</TD></TR>
    <TR><TD>계약금액</TD><TD>12,340</TD></TR></TABLE>"""
    result = parse_order_contract(xml)
    assert result is not None and result.amount_krw is None


def test_correction_summary_does_not_concatenate_before_and_after_amounts():
    xml = """<TABLE>
    <TR><TD>2. 계약내역</TD><TD>확정 계약금액 : 243,946,121,818 계약금액 총액(원) : 243,946,121,818</TD><TD>확정 계약금액 : 248,983,409,818 계약금액 총액(원) : 248,983,409,818</TD></TR>
    <TR><TD>계약금액 총액(원)</TD><TD>248,983,409,818</TD></TR>
    <TR><TD>최근 매출액(원)</TD><TD>367,399,208,640</TD></TR>
    <TR><TD>매출액 대비(%)</TD><TD>67.8</TD></TR>
    </TABLE>"""
    result = parse_order_contract(xml)
    assert result is not None
    assert result.amount_krw == 248_983_409_818
    assert result.sales_krw == 367_399_208_640


def test_contract_termination_is_kept_but_not_misclassified_as_new_order():
    xml = """<TABLE>
    <TR><TD>1. 판매ㆍ공급계약 해지내용</TD><TD>완제의약품 판매공급 계약</TD></TR>
    <TR><TD>해지금액(원)</TD><TD>11,942,752,371</TD></TR>
    <TR><TD>최근매출액(원)</TD><TD>139,079,924,912</TD></TR>
    <TR><TD>매출액대비(%)</TD><TD>8.59</TD></TR>
    <TR><TD>계약상대방</TD><TD>NOVOSCI사</TD></TR>
    </TABLE>"""
    result = parse_order_contract(xml)
    assert result is not None
    assert result.disclosure_status == "terminated"
    assert result.amount_krw == 11_942_752_371
    assert result.contract_name == "완제의약품 판매공급 계약"
