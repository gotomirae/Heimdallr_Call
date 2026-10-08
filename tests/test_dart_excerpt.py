# PRD Ref: §7.1 · ADR 4
"""정기보고서 발췌 — **순수 함수만** 테스트한다(네트워크 없음).

★ 실제 원문 구조를 줄여 만든 픽스처다. DART 반기보고서의 실제 모양
  (`<TITLE>`로 절이 갈리고, 표는 셀마다 줄바꿈이 들어 있다)을 그대로 재현한다.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from src.collectors.dart_excerpt import (
    DEFAULT_BUDGET_CHARS,
    ExcerptError,
    build_excerpt,
    explicit_order_metrics,
    fetch_report_xml,
    major_contract_backlog,
    structured_order_metrics,
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


def test_major_contract_backlog_uses_disclosed_scope_and_unit():
    # 두산 2026 반기 원문 표의 열 구성 축약. 손계산 10,561,864백만원 = 105,618.64억원.
    body = """(2) 주요프로젝트별 수주상황 | (단위 : 백만원, %)
품목 | 발주처 | 계약일 | 공사기한 | 수주총액 | 기납품액 | 수주잔고 | 진행률
원전 | 발전사 | 2023-03-29 | 2033-10-31 | 2,387,981 | 895,752 | 1,492,229 | 37.51
합 계 | 39,245,858 | 28,683,994 | 10,561,864 | -
"""
    assert major_contract_backlog(body) == (
        "범위 | 주요계약(전체 회사 아님)\n단위 | 백만원\n수주잔고 | 10,561,864"
    )
    assert major_contract_backlog(body.replace("(단위 : 백만원, %)", "(단위 불명)")) is None
    assert major_contract_backlog(body.replace("합 계", "소 계")) is None


def test_explicit_order_metrics_reads_company_total_new_orders_and_backlog():
    body = """수주상황 (단위 : 백만원)
구분 | 기초수주잔고 | 신규수주 | 매출계상액 | 기말수주잔고
국내 | 1,000 | 300 | 200 | 1,100
합 계 | 1,000 | 300 | 200 | 1,100
"""
    assert explicit_order_metrics(body) == (
        "범위 | 회사 공시 합계\n단위 | 백만원\n수주잔고 | 1,100\n신규수주 | 300"
    )


def test_explicit_order_metrics_rejects_ambiguous_multiple_totals():
    body = """A사업 (단위 : 억원)
구분 | 신규수주 | 수주잔고
합 계 | 30 | 100
B사업 (단위 : 억원)
구분 | 신규수주 | 수주잔고
합 계 | 20 | 80
"""
    assert explicit_order_metrics(body) is None


def test_structured_order_metrics_reads_real_two_level_dart_header():
    """실제 반기보고서 형식: 수주총액/기납품액/잔고 아래 수량·금액이 한 줄 더 있다."""
    xml = """<SECTION>
<P>(단위 : 백만원)</P>
<TABLE>
<TR><TH ROWSPAN="2">품목</TH><TH ROWSPAN="2">수주일자</TH><TH ROWSPAN="2">납기</TH>
<TH COLSPAN="2">수주총액</TH><TH COLSPAN="2">기납품액</TH><TH COLSPAN="2">수주잔고</TH></TR>
<TR><TH>수량</TH><TH>금액</TH><TH>수량</TH><TH>금액</TH><TH>수량</TH><TH>금액</TH></TR>
<TR><TD>콘덴서</TD><TD>2026.01.01~06.30</TD><TD>-</TD><TD>14,199</TD><TD>157,552</TD><TD>14,068</TD><TD>155,700</TD><TD>132</TD><TD>1,852</TD></TR>
<TR><TD>합 계</TD><TD COLSPAN="2"></TD><TD>14,199</TD><TD>157,552</TD><TD>14,068</TD><TD>155,700</TD><TD>132</TD><TD>1,852</TD></TR>
</TABLE></SECTION>"""
    assert structured_order_metrics(xml) == (
        "범위 | 회사 공시 합계\n단위 | 백만원\n수주잔고 | 1,852"
    )


def test_structured_order_metrics_reads_single_company_row_without_total():
    """기가비스(420770) 반기보고서처럼 단일 품목 수주표는 그 행 자체를 읽는다."""
    xml = """<SECTION><P>(단위 : 백만원)</P><TABLE>
<TR><TH>품목</TH><TH>당기수주</TH><TH>납품액</TH><TH>수주잔고</TH></TR>
<TR><TD>반도체 기판 검사 및 수리장비</TD><TD>76,122</TD><TD>10,856</TD><TD>65,266</TD></TR>
</TABLE></SECTION>"""
    assert structured_order_metrics(xml) == (
        "범위 | 회사 공시 단일행\n단위 | 백만원\n수주잔고 | 65,266\n"
        "신규수주 | 76,122\n신규수주 기간 | 보고기간 누적"
    )


def test_structured_order_metrics_does_not_add_multiple_company_tables():
    """연결 자회사별 표를 임의 합산하면 중복 가능성이 있으므로 단일 분기값으로 만들지 않는다."""
    xml = """<SECTION><P>(단위 : 백만원)</P>
<TABLE><TR><TH>품목</TH><TH>당기수주</TH><TH>수주잔고</TH></TR><TR><TD>합계</TD><TD>30</TD><TD>100</TD></TR></TABLE>
<TABLE><TR><TH>품목</TH><TH>당기수주</TH><TH>수주잔고</TH></TR><TR><TD>합계</TD><TD>20</TD><TD>80</TD></TR></TABLE>
</SECTION>"""
    assert structured_order_metrics(xml) is None


def test_current_sfa_total_is_not_discarded_with_historical_or_major_contract_tables():
    # 실제 20260812000465: 합계-소계 987,499백만원, 신규 442,637백만원.
    xml = '''<P>(단위: 백만원)</P><TABLE><TR><TH>구분</TH><TH>구분</TH>
    <TH>당기 신규수주액(제29기 반기)</TH><TH>기말 수주잔고액(제29기 반기 말)</TH></TR>
    <TR><TD ROWSPAN="3">합계</TD><TD>내수</TD><TD>172,667</TD><TD>375,581</TD></TR>
    <TR><TD>수출</TD><TD>269,970</TD><TD>611,918</TD></TR>
    <TR><TD>소계</TD><TD>442,637</TD><TD>987,499</TD></TR></TABLE>
    <P>(단위: 백만원)</P><TABLE><TR><TH>연도</TH><TH>구분</TH><TH>수주잔고</TH></TR>
    <TR><TD>2025</TD><TD>합계</TD><TD>911,850</TD></TR>
    <TR><TD>2024</TD><TD>합계</TD><TD>991,679</TD></TR></TABLE>'''
    metric = structured_order_metrics(xml)
    assert metric and '수주잔고 | 987,499' in metric and '신규수주 | 442,637' in metric


def test_quantity_unit_before_currency_and_footnoted_headers():
    xml = '''<P>(단위: 천개, 백만원)</P><TABLE><TR><TH>품목</TH>
    <TH COLSPAN="2">수주잔고**</TH></TR><TR><TH>품목</TH><TH>수량</TH><TH>금액</TH></TR>
    <TR><TD>합계</TD><TD>41,090</TD><TD>21,944</TD></TR></TABLE>'''
    assert structured_order_metrics(xml) == '범위 | 회사 공시 합계\n단위 | 백만원\n수주잔고 | 21,944'


def test_named_company_tables_remain_separate_without_converting_foreign_currency():
    from src.collectors.dart_excerpt import structured_order_series
    xml = '''<TABLE><TR><TD>삼화전기주식회사</TD><TD>(단위: 천개,백만원)</TD></TR></TABLE>
    <TABLE><TR><TH>품목</TH><TH>수주잔고</TH></TR><TR><TD>합계</TD><TD>38,972</TD></TR></TABLE>
    <TABLE><TR><TD>천진삼화전기유한공사</TD><TD>(단위: 천개,천RMB)</TD></TR></TABLE>
    <TABLE><TR><TH>품목</TH><TH>수주잔고</TH></TR><TR><TD>합계</TD><TD>20,949</TD></TR></TABLE>
    <TABLE><TR><TD>삼화텍콤</TD><TD>(단위: 천개,백만원)</TD></TR></TABLE>
    <TABLE><TR><TH>품목</TH><TH>수주잔고</TH></TR><TR><TD>합계</TD><TD>1,410</TD></TR></TABLE>'''
    series = structured_order_series(xml)
    assert len(series) == 3
    assert '삼화전기주식회사' in series[0] and '38,972' in series[0]
    assert '천진삼화전기유한공사' in series[1] and '단위 | 천RMB' in series[1]
    assert '삼화텍콤' in series[2] and '1,410' in series[2]
    assert structured_order_metrics(xml) is None


def test_period_flow_definition_reads_current_mnc_row_not_contract_total():
    # 실제 엠앤씨솔루션: 2026.06.30 잔고 9,331억 / 당기수주 890억.
    xml = '''<P>(단위: 억원)</P><TABLE><TR><TH>품목</TH><TH>수주일자</TH>
    <TH>수주총액*</TH><TH>수주잔고**</TH></TR>
    <TR><TD>방산부품</TD><TD>2025.12.31</TD><TD>4,500</TD><TD>10,037</TD></TR>
    <TR><TD>방산부품</TD><TD>2026.06.30</TD><TD>890</TD><TD>9,331</TD></TR></TABLE>
    <P>* 수주총액 = 당기수주총액 ** 수주잔고 = 전년말 수주잔고 + 수주총액 - 기납품액</P>'''
    metric = structured_order_metrics(xml, period_end='2026-06-30')
    assert metric and '수주잔고 | 9,331' in metric and '신규수주 | 890' in metric
    assert structured_order_metrics(xml.replace('수주총액 = 당기수주총액', '총 계약금액'), period_end='2026-06-30') is None


def test_referenced_detailed_order_table_is_collected_outside_main_sales_section():
    xml = '''<TITLE>4. 매출 및 수주상황</TITLE><P>상세표-1 매출 및 수주상황(상세) 참조.</P>
    <P>회사와 종속회사의 매출 및 수주에 관한 상세한 내용은 보고서 후반 상세표에 기재하였습니다.</P>
    <TITLE>5. 위험관리</TITLE><P>위험관리</P><TITLE>1. 매출 및 수주상황(상세)</TITLE>
    <P>(단위: 백만원)</P><TABLE><TR><TH>품목</TH><TH>수주잔고</TH></TR>
    <TR><TD>합계</TD><TD>123,000</TD></TR></TABLE>'''
    assert '수주잔고 | 123,000' in build_excerpt('X', xml).sections['공시 수주지표']


def test_narrative_current_order_balance_has_explicit_unit():
    from src.collectors.dart_excerpt import narrative_order_metrics
    assert narrative_order_metrics('<P>본 보고서 작성기준일 현재 수주잔고는 2,691억원입니다.</P>') == (
        '범위 | 회사 공시 명시 잔고\n단위 | 억원\n수주잔고 | 2,691')
    assert narrative_order_metrics('<P>2027년 목표 수주잔고는 2,691억원입니다.</P>') is None


def test_inline_units_in_current_year_orders_do_not_use_previous_year():
    xml = '''<TABLE><TR><TH>구분</TH><TH>전년도 이월 수주액</TH><TH>당해 신규 수주액</TH></TR>
    <TR><TD>2025년</TD><TD>14,885 백만원</TD><TD>54,397 백만원</TD></TR>
    <TR><TD>2026년 반기</TD><TD>18,802백만원</TD><TD>71,782백만원</TD></TR></TABLE>'''
    metric = structured_order_metrics(xml, period_end='2026-06-30')
    assert metric and '신규수주 | 71,782' in metric and '수주잔고 |' not in metric


def test_minimum_contracts_not_added_to_contingent_forecast_orders():
    xml = '''<P>(단위: 백만USD)</P><TABLE><TR><TH>품목</TH><TH>구분</TH><TH>수주잔고</TH></TR>
    <TR><TD>CDMO</TD><TD>현 최소구매물량 기준</TD><TD>9,923</TD></TR>
    <TR><TD>CDMO</TD><TD>수요 증가 시 예상물량 기준</TD><TD>12,526</TD></TR></TABLE>'''
    metric = structured_order_metrics(xml)
    assert metric == '범위 | 최소구매물량(확정 계약)\n단위 | 백만USD\n수주잔고 | 9,923'


def test_table_sum_is_only_with_complete_independent_items():
    xml = '''<P>(단위: 백만원)</P><TABLE><TR><TH>품목</TH><TH>수주잔고</TH></TR>
    <TR><TD>A사업</TD><TD>100</TD></TR><TR><TD>B사업</TD><TD>50</TD></TR></TABLE>'''
    assert '수주잔고 | 150' in structured_order_metrics(xml)
    # 일부 미공개 항목은 더하지 않고 공개 항목 범위로만 남긴다.
    partial = structured_order_metrics(xml.replace('<TD>50</TD>', '<TD>-</TD>'))
    assert partial == '범위 | 공시 공개 항목: A사업\n단위 | 백만원\n수주잔고 | 100'
    assert structured_order_metrics(xml.replace('B사업', 'A사업')) is None


def test_report_zip_selects_receipt_main_document_not_first_audit_attachment(monkeypatch):
    """경동나비엔 2025 사업보고서 실제 ZIP 순서 재생: 감사첨부가 먼저 온다."""
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("20260312000931_00760.xml", "감사 첨부")
        archive.writestr("20260312000931.xml", SAMPLE)
    class Response:
        content = payload.getvalue()
    monkeypatch.setattr("src.collectors.dart_excerpt.http_get", lambda *a, **k: Response())
    monkeypatch.setattr("src.collectors.dart_excerpt.require_env", lambda *a: "fixture")
    assert fetch_report_xml("20260312000931") == SAMPLE


def test_empty_document_has_no_completed_marker():
    assert build_excerpt("X", "<DOCUMENT><P>첨부 감사보고서</P></DOCUMENT>").sections == {}


def test_api_missing_file_recovers_exact_receipt_viewer_section(monkeypatch):
    # 한화에어로스페이스 26Q1: API 014지만 공개 뷰어 수주 절은 UTF-8로 정상이다.
    import httpx
    receipt = "20260513000860"
    main = f'''viewDoc("{receipt}", "11376786", "1", "0", "100", "dart4.xsd");
var node2 = {{}};
node2['text'] = "4. 매출 및 수주상황";
node2['rcpNo'] = "{receipt}"; node2['dcmNo'] = "11376786";
node2['eleId'] = "13"; node2['offset'] = "96492";
node2['length'] = "30223"; node2['dtd'] = "dart4.xsd";'''
    body = '''<html><head><title>뷰어</title></head><body><p>4. 매출 및 수주상황</p>
<p>보고기간의 회사 수주상황과 사업내용입니다. 항공과 방산 및 종속회사의 계약을 원문 범위에 따라 표시하며 수주잔고와 신규계약을 구분하여 기재합니다. 단위를 추측하지 않습니다.</p><p>(단위 : 백만원)</p>
<table><tr><th>품목</th><th>수주잔고</th></tr>
<tr><td>합계</td><td>118,127,410</td></tr></table></body></html>'''
    def get(url, **kwargs):
        if url.endswith("document.xml"):
            return httpx.Response(200, text="<result><status>014</status></result>")
        if url.endswith("main.do"):
            return httpx.Response(200, text=main)
        assert kwargs["params"]["rcpNo"] == receipt
        assert kwargs["params"]["eleId"] == "13"
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})
    monkeypatch.setattr("src.collectors.dart_excerpt.http_get", get)
    monkeypatch.setattr("src.collectors.dart_excerpt.require_env", lambda *a: "fixture")
    excerpt = build_excerpt(receipt, fetch_report_xml(receipt))
    assert "수주잔고 | 118,127,410" in excerpt.sections["공시 수주지표"]
    assert "뷰어 절" in excerpt.sections["원문 수집 경로"]
    assert "eleId=13" in excerpt.sections["원문 수집 경로"]


def test_viewer_fallback_rejects_other_receipt(monkeypatch):
    import httpx
    monkeypatch.setattr("src.collectors.dart_excerpt.require_env", lambda *a: "fixture")
    monkeypatch.setattr("src.collectors.dart_excerpt.http_get", lambda url, **k:
        httpx.Response(200, text="<result><status>014</status></result>" if url.endswith("document.xml")
                       else 'viewDoc("999999", "123", "1", "0", "1", "dart4.xsd");'))
    with pytest.raises(ExcerptError):
        fetch_report_xml("20260513000860")


def test_non_missing_api_error_never_falls_back_to_viewer(monkeypatch):
    import httpx
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, text="<result><status>020</status></result>")
    monkeypatch.setattr("src.collectors.dart_excerpt.require_env", lambda *a: "fixture")
    monkeypatch.setattr("src.collectors.dart_excerpt.http_get", get)
    with pytest.raises(ExcerptError):
        fetch_report_xml("20260513000860")
    assert len(calls) == 1  # 호출 한도·인증 오류를 우회하는 대체 호출은 하지 않는다.


def test_missing_order_table_unit_does_not_inherit_sales_unit():
    xml = """<P>(단위: 백만원)</P>
<TABLE><TR><TH>매출</TH></TR><TR><TD>123</TD></TR></TABLE>
<P>수주상황</P><TABLE><TR><TH>품목</TH><TH>신규수주</TH><TH>수주잔고</TH></TR>
<TR><TD>합계</TD><TD>100</TD><TD>200</TD></TR></TABLE>"""
    assert structured_order_metrics(xml) is None


def test_mixed_currency_order_rows_keep_declared_scale_and_separate_totals():
    from src.collectors.dart_excerpt import structured_order_series
    # 네오셈/프레스티지 원문: K$는 천USD, 원화 행은 백만원. 26,598을 원화로 읽지 않는다.
    xml = '''<P>(단위: 천$, 백만원)</P><TABLE>
<TR><TH>품목</TH><TH>통화</TH><TH>수주잔고</TH></TR>
<TR><TD>바이오</TD><TD>USD</TD><TD>26,598</TD></TR>
<TR><TD>바이오</TD><TD>KRW</TD><TD>33,875</TD></TR></TABLE>'''
    series = structured_order_series(xml)
    assert len(series) == 2
    assert any("단위 | 천USD\n수주잔고 | 26,598" in s for s in series)
    assert any("단위 | 백만원\n수주잔고 | 33,875" in s for s in series)
    assert structured_order_metrics(xml) is None


def test_scope_uses_company_name_and_drops_report_date():
    from src.collectors.dart_excerpt import structured_order_series
    xml = '''<P>[LS ELECTRIC]</P><TABLE><TR><TD>(기준일: 2026.06.30) (단위: 억원)</TD></TR></TABLE>
<TABLE><TR><TH>품목</TH><TH>당기 수주금액</TH><TH>수주잔고</TH></TR>
<TR><TD>합계</TD><TD>34,677</TD><TD>69,998</TD></TR></TABLE>'''
    assert "[LS ELECTRIC] / 회사 공시 합계" in structured_order_series(xml)[0]
    assert structured_order_series(xml) == structured_order_series(xml.replace("2026.06.30", "2026.03.31"))


def test_generic_order_heading_is_not_a_new_company_scope():
    # SFA는 2026년에 제목에서 사업부문별만 지웠다. 회사 합계의 범위 변경이 아니다.
    xml = '''<P>(1) 사업부문별 수주/매출/수주잔고 현황</P><P>(단위: 백만원)</P>
<TABLE><TR><TH>품목</TH><TH>수주잔고</TH></TR><TR><TD>합계</TD><TD>987,499</TD></TR></TABLE>'''
    assert structured_order_metrics(xml) == structured_order_metrics(xml.replace("사업부문별 ", ""))
    assert "범위 | 회사 공시 합계" in structured_order_metrics(xml)
    assert "단위 | 천원" in structured_order_metrics(xml.replace("백만원", "백만개(KK), 천원"))


def test_explicit_whole_company_total_wins_over_product_subtotals():
    xml = '''<P>(단위: 천USD)</P><TABLE>
<TR><TH>품목</TH><TH>구분</TH><TH>수주잔고</TH></TR>
<TR><TD>전력선</TD><TD>계</TD><TD>648,960</TD></TR>
<TR><TD>변압기</TD><TD>계</TD><TD>1,290,131</TD></TR>
<TR><TD>합계</TD><TD>계</TD><TD>1,939,091</TD></TR></TABLE>'''
    assert "수주잔고 | 1,939,091" in structured_order_metrics(xml)


def test_total_with_domestic_export_subtotals_and_private_first_contract():
    # 일진전기의 전체/국내/해외 합계에서 전체 '계'만 선택한다.
    xml = '''<P>(단위: 천USD)</P><TABLE><TR><TH>품목</TH><TH>구분</TH><TH>수주일자</TH><TH>수주잔고</TH></TR>
<TR><TD>합계</TD><TD>국내</TD><TD>~2026년반기</TD><TD>468,895</TD></TR>
<TR><TD>합계</TD><TD>해외</TD><TD>~2026년반기</TD><TD>1,470,196</TD></TR>
<TR><TD>합계</TD><TD>계</TD><TD>계</TD><TD>1,939,091</TD></TR></TABLE>'''
    assert "수주잔고 | 1,939,091" in structured_order_metrics(xml)
    # 큐브 원문: 비공개 첫 계약은 머리글이 아니다. 명시 회사 합계를 읽는다.
    xml = '''<P>(단위: 천원)</P><TABLE><TR><TH>품목</TH><TH>수주잔고</TH><TH>수주잔고</TH></TR>
<TR><TH>품목</TH><TH>수량</TH><TH>금액</TH></TR>
<TR><TD>Tencent</TD><TD>-</TD><TD>-</TD></TR><TR><TD>카카오</TD><TD>-</TD><TD>85,374,311</TD></TR>
<TR><TD>합계</TD><TD>-</TD><TD>85,374,311</TD></TR></TABLE>'''
    assert "수주잔고 | 85,374,311" in structured_order_metrics(xml)


def test_currency_labelled_total_is_not_added_twice():
    from src.collectors.dart_excerpt import structured_order_series
    xml = '''<P>(단위: K$, 백만원)</P><TABLE><TR><TH>품목</TH><TH>통화</TH><TH>수주잔고</TH></TR>
<TR><TD>장비</TD><TD>USD</TD><TD>26,260</TD></TR><TR><TD>합계(USD)</TD><TD></TD><TD>26,260</TD></TR>
<TR><TD>보드</TD><TD>KRW</TD><TD>6,899</TD></TR><TR><TD>합계(KRW)</TD><TD></TD><TD>6,899</TD></TR></TABLE>'''
    series = structured_order_series(xml)
    assert len(series) == 2
    assert any("수주잔고 | 26,260" in s for s in series)
    assert any("수주잔고 | 6,899" in s for s in series)


def test_non_numeric_multirow_header_and_empty_total_are_not_private_contracts():
    # 한화에어로스페이스처럼 첫 머리글 표제가 두 행에서 달라도 금액 열을 유지한다.
    xml = '''<P>(단위: 백만원)</P><TABLE><TR><TH>사업부문</TH><TH>수주잔고</TH><TH>수주잔고</TH></TR>
<TR><TH>세부 사업</TH><TH>수량</TH><TH>금액</TH></TR>
<TR><TD>합계</TD><TD>-</TD><TD>114,918,238</TD></TR></TABLE>'''
    assert "수주잔고 | 114,918,238" in structured_order_metrics(xml)
    # 기간이 붙은 머리글의 연도는 실제 비공개 계약 날짜가 아니다.
    assert structured_order_metrics(xml) == structured_order_metrics(xml.replace("세부 사업", "세부 사업(2026년 1분기)"))
    # 세보 주요계약: 합계 칸에 금액을 쓰지 않았지만 독립 계약의 명시 잔고는 모두 공개했다.
    xml = '''<P>(단위: 천원)</P><TABLE><TR><TH>품목</TH><TH>수주일자</TH><TH>수주잔고</TH></TR>
<TR><TD>HVAC</TD><TD>20250917</TD><TD>3,182,280</TD></TR>
<TR><TD>HVAC</TD><TD>20250908</TD><TD>116,906,376</TD></TR>
<TR><TD>합계</TD><TD>합계</TD><TD>합계</TD></TR></TABLE>'''
    assert "수주잔고 | 120,088,656" in structured_order_metrics(xml)
    assert "공시 항목 합산(표 범위)" in structured_order_metrics(xml)


def test_amount_unit_cell_inside_minimum_purchase_body_is_not_a_header():
    xml = '''<TABLE><TR><TH>품목</TH><TH>구분</TH><TH>구분</TH><TH>수주잔고</TH></TR>
<TR><TD>항체의약품</TD><TD>현 최소구매물량 기준</TD><TD>금액(백만불)</TD><TD>9,923</TD></TR>
<TR><TD>항체의약품</TD><TD>예상물량 기준</TD><TD>금액(백만불)</TD><TD>12,526</TD></TR></TABLE>'''
    assert "수주잔고 | 9,923" in structured_order_metrics(xml)
    assert "수주잔고 | 12,526" not in structured_order_metrics(xml)


def test_unlabelled_total_requires_exact_item_sum():
    xml = '''<P>(단위: 백만원)</P><TABLE><TR><TH>품목</TH><TH>수주일자</TH><TH>납기</TH><TH>수주잔고</TH></TR>
<TR><TD>물품취급</TD><TD>-</TD><TD>-</TD><TD>100</TD></TR>
<TR><TD>건설</TD><TD>-</TD><TD>-</TD><TD>80</TD></TR>
<TR><TD></TD><TD></TD><TD></TD><TD>180</TD></TR></TABLE>'''
    assert "수주잔고 | 180" in structured_order_metrics(xml)
    assert structured_order_metrics(xml.replace(">180<", ">190<")) is None


def test_partly_private_table_preserves_public_items_without_a_total():
    from src.collectors.dart_excerpt import structured_order_series
    xml = '''<P>(단위: 백만원)</P><TABLE><TR><TH>사업부문</TH><TH>수주잔고</TH></TR>
<TR><TD>프레스</TD><TD>217,745</TD></TR><TR><TD>합금철</TD><TD>해당사항 없음</TD></TR>
<TR><TD>산업기계</TD><TD>24,010</TD></TR></TABLE>'''
    series = structured_order_series(xml)
    assert len(series) == 2
    assert all("공시 공개 항목:" in s for s in series)
    assert structured_order_metrics(xml) is None


def test_single_public_backlog_is_preserved_as_subset_not_company_total():
    from src.collectors.dart_excerpt import structured_order_series
    xml = '''<P>(단위: 백만원)</P><TABLE><TR><TH>품목</TH><TH>수주잔고</TH></TR>
<TR><TD>연료전지</TD><TD>-</TD></TR><TR><TD>수소충전소</TD><TD>61,071</TD></TR></TABLE>'''
    assert structured_order_series(xml) == ["범위 | 공시 공개 항목: 수소충전소\n단위 | 백만원\n수주잔고 | 61,071"]


def test_compound_won_cell_unit_does_not_require_guessing_scale():
    xml = '''<TABLE><TR><TH>품목</TH><TH>수주잔고</TH></TR>
<TR><TD>LNG</TD><TD>3조 2474억</TD></TR></TABLE>'''
    assert "단위 | 억원\n수주잔고 | 32474" in structured_order_metrics(xml)
    assert structured_order_metrics(xml.replace("3조 2474억", "32474")) is None


def test_submission_date_backlog_is_not_used_as_quarter_end_backlog():
    xml = '''<P>(기준일:2026년 06월 30일)</P><P>(단위: 천원)</P><TABLE>
<TR><TH>품목</TH><TH>수주잔고</TH></TR><TR><TD>합계</TD><TD>9,519,844</TD></TR></TABLE>
<P>(기준일:2026년 07월 31일)</P><P>(단위: 천원)</P><TABLE>
<TR><TH>품목</TH><TH>수주잔고</TH></TR><TR><TD>합계</TD><TD>9,343,851</TD></TR></TABLE>'''
    metric = structured_order_metrics(xml, period_end="2026-06-30")
    assert "수주잔고 | 9,519,844" in metric
    assert "2026년" not in metric and "9,343,851" not in metric


def test_order_metric_preserves_subsidiary_scope():
    xml = """<P>[종속회사 : 동성화인텍]</P><P>(단위 : 백만원)</P><TABLE>
<TR><TH>품목</TH><TH>수주잔고</TH></TR><TR><TD>합계</TD><TD>2,041,085</TD></TR></TABLE>"""
    metric = structured_order_metrics(xml)
    assert metric is not None
    assert "종속회사 : 동성화인텍" in metric


def test_current_end_backlog_does_not_use_previous_end_or_sales_footnote():
    """HB테크 원문: 당기말 88,651,626천원, 당기수주 68,189,250천원. 전기말은 별도다."""
    xml = """<P>(*) 금융업부문은 회사의 종속회사인 투자조합에서 발생한 매출액입니다.</P>
<P>나. 수주상황(연결기준) [장비사업부]보고기간 종료일 현재 수주상황입니다.</P>
<P>(단위 : 천원)</P><TABLE><TR><TH>품목</TH><TH>전기말 수주잔고</TH>
<TH>당기수주</TH><TH>기납품액</TH><TH>당기말 수주잔고</TH></TR>
<TR><TD>합계</TD><TD>92,506,069</TD><TD>68,189,250</TD><TD>72,043,693</TD>
<TD>88,651,626</TD></TR></TABLE>"""
    metric = structured_order_metrics(xml)
    assert metric == ("범위 | [장비사업부] / 회사 공시 합계\n단위 | 천원\n"
                      "수주잔고 | 88,651,626\n신규수주 | 68,189,250\n신규수주 기간 | 보고기간 누적")
    for current_label in ("당분기말 수주잔고", "당반기말 수주잔고"):
        assert structured_order_metrics(xml.replace("당기말 수주잔고", current_label)) == metric
    # 비교 대상만 기재한 표를 이번 기말 잔고로 바꾸지 않는다.
    assert structured_order_metrics(xml.replace("당기말 수주잔고", "전기말 수주잔고")) == (
        "범위 | [장비사업부] / 회사 공시 합계\n단위 | 천원\n"
        "신규수주 | 68,189,250\n신규수주 기간 | 보고기간 누적")


def test_structured_rejection_is_not_bypassed_by_flat_fallback():
    xml = """<DOCUMENT><TITLE>4. 매출 및 수주상황</TITLE><P>아래 두 자회사 수주표를 각각 공개합니다.</P>
<P>(단위 : 백만원)</P><TABLE><TR><TH>품목</TH><TH>수주잔고</TH></TR><TR><TD>합계</TD><TD>100</TD></TR></TABLE>
<P>(단위 : 백만원)</P><TABLE><TR><TH>품목</TH><TH>수주잔고</TH></TR><TR><TD>합계</TD><TD>80</TD></TR></TABLE>
<TITLE>5. 원재료 및 생산설비</TITLE><P>원재료 조달에 관한 설명을 기재합니다.</P></DOCUMENT>"""
    assert "공시 수주지표" not in build_excerpt("X", xml).sections
