# PRD Ref: §9.1-3
"""금액 파싱 실패와 사업 형태를 혼동하지 않는지 원문 재생으로 확인한다."""
from src.collectors.order_company import classify_order_section


def test_unknown_unit_does_not_remove_order_company():
    xml = '<p>단위: 별도협의</p><table><tr><td>품목</td><td>수주잔고</td></tr><tr><td>장비</td><td>123</td></tr></table>'
    assert classify_order_section(xml)["status"] == "confirmed"


def test_missing_numbers_are_not_non_order_business():
    assert classify_order_section('<p>매출 및 수주상황 자료가 부족합니다.</p>')["status"] == "review"


def test_explicit_non_order_business_requires_original_statement():
    assert classify_order_section('<p>당사는 수주산업에 해당하지 않습니다.</p>')["status"] == "not_applicable"


def test_private_order_book_is_order_business():
    assert classify_order_section('<p>수주현황은 영업비밀에 해당하여 비공개합니다.</p>')["status"] == "confirmed"


def test_mass_production_reporting_omission_does_not_confirm_order_business():
    xml = '<p>수주상황: 당사는 대량생산계획체제로 수주총액의 의미가 미미하여 기재를 생략합니다.</p>'
    assert classify_order_section(xml)["status"] == "review"


def test_mixed_scope_needs_review():
    xml = '<p>본사는 수주사업이 아닙니다.</p><table><tr><td>수주잔고</td></tr><tr><td>100</td></tr></table>'
    assert classify_order_section(xml)["status"] == "review"


def test_empty_order_table_template_is_not_evidence():
    assert classify_order_section('<table><tr><td>수주잔고</td></tr><tr><td>-</td></tr></table>')["status"] == "review"
