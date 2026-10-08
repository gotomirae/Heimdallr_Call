# PRD Ref: §9.1-3
"""회사 공식 IR의 명시 분기·범위·행 단위 수주표. DART와 별도 출처로 보존한다."""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode, urljoin

import httpx
import pymupdf
from bs4 import BeautifulSoup

from src.config.constants import ORDER_IR_LIST_PAGES, ORDER_IR_QUARTERS
from src.db.supabase_client import get_client, select_all
from src.utils.http import decode_html, http_get
from src.utils.console import enable_utf8_stdout

HD_BASE = "https://www.hd-hyundaielectric.com"
OFFICIAL_ORDER_IR_COMPANIES = {
    "267260": "HD현대일렉트릭", "010120": "LS일렉트릭", "034020": "두산에너빌리티",
    "298040": "효성중공업", "059090": "미코", "475960": "토모큐브", "044490": "태웅",
    "100090": "SK오션플랜트", "388050": "지투파워", "213420": "덕산네오룩스", "010140": "삼성중공업",
    "140860": "파크시스템스", "079550": "LIG디펜스앤에어로스페이스", "356860": "티엘비", "006360": "GS건설",
    "028050": "삼성E&A", "000720": "현대건설", "299030": "하나기술",
}
OFFICIAL_IR_HOSTS = {
    "267260": HD_BASE, "010120": "https://www.ls-electric.com",
    "034020": "https://www.doosanenerbility.com", "298040": "https://www.hyosungheavyindustries.com",
    "010140": "https://www.samsungshi.com", "006360": "https://www.gsenc.com",
    "028050": "https://sea.samsungena.com", "000720": "https://m.hdec.kr",
    **{code: "https://kind.krx.co.kr/external/dst/irReference"
       for code in ("059090", "475960", "044490", "100090", "388050", "213420", "140860", "079550", "356860", "299030")},
}
OFFICIAL_IR_ADDITIONAL_HOSTS = {
    "079550": ("https://www.ligdefenseaerospace.com",),
    "000720": ("https://www.hdec.kr",),
}


def download_verified_pdf(fact: dict) -> bytes:
    """폼 전용 자료실은 공개 CSRF 절차로 내려받고 화면에는 자료실을 링크한다."""
    index = fact.get("download_idx")
    if index is None:
        return http_get(fact["source_url"], timeout=90).content
    library = "https://sea.samsungena.com/kr/ir/event-earnings"
    if fact["code"] != "028050" or fact["source_url"] != library or type(index) is not int or index <= 0:
        raise ValueError("공식 IR 폼 다운로드 대상 불일치")
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        response = client.get(library)
        response.raise_for_status()
        meta = BeautifulSoup(response.text, "html.parser").select_one('meta[name="_csrf"]')
        if meta is None or not meta.get("content"):
            raise ValueError("공식 IR 다운로드 폼 검증값 없음")
        token = meta["content"]
        response = client.post("https://sea.samsungena.com/kr/filedownload/ir",
                               data={"idx": str(index), "_csrf": token},
                               headers={"X-CSRF-TOKEN": token, "Referer": library})
        response.raise_for_status()
        return response.content


def parse_quarter_order_page(text: str) -> list[dict]:
    """실적 요약의 분기 열과 수주 두 행만 읽는다. 시장별 차트/연간 목표는 제외."""
    lines = [re.sub(r"\s+", "", line) for line in text.splitlines() if line.strip()]
    if not any("연결기준" in line for line in lines):
        return []
    try:
        header = lines.index("구분") + 1
    except ValueError:
        return []
    periods = []
    while header < len(lines) and (m := re.fullmatch(r"([1-4])Q(\d{2})", lines[header])):
        periods.append((2000 + int(m[2]), int(m[1])))
        header += 1
    if not periods or len(set(periods)) != len(periods) or lines[header:header + 2] != ["QoQ", "YoY"]:
        return []
    values = {}
    units = {}
    for label, key in (("수주", "new_orders"), ("수주잔고", "backlog")):
        matches = [(i, m) for i, line in enumerate(lines)
                   if (m := re.fullmatch(rf"{label}\((백만불|백만USD|백만원|억원)\)", line))]
        if len(matches) != 1:
            return []
        at, match = matches[0]
        numbers = lines[at + 1:at + 1 + len(periods)]
        if len(numbers) != len(periods) or not all(re.fullmatch(r"[\d,]+(?:\.\d+)?", n) for n in numbers):
            return []
        values[key] = [float(n.replace(",", "")) for n in numbers]
        units[key] = "백만USD" if match[1] in {"백만불", "백만USD"} else match[1]
    if units["new_orders"] != units["backlog"]:
        return []
    return [{"year": year, "quarter": quarter, "unit": units["backlog"], "scope": "공식 IR 연결 전체",
             "new_orders_period": "당분기", **{key: numbers[i] for key, numbers in values.items()}}
            for i, (year, quarter) in enumerate(periods)]


def verified_ir_facts() -> list[dict]:
    facts = []
    downloads: dict[tuple[str, int | None], bytes] = {}
    # 벡터/이미지 표는 숫자 위치를 추측하지 않는다. 직접 렌더링 대조한 장부만
    # 원문 해시·페이지를 재검증한 뒤 받아들인다.
    manifest = Path(__file__).resolve().parents[1] / "config" / "order_ir_verified.json"
    for fact in json.loads(manifest.read_text(encoding="utf-8")):
        evidence = [(fact["source_url"], fact["sha256"], fact["source_page"])]
        if fact.get("new_orders_source_url"):
            evidence.append((fact["new_orders_source_url"], fact.get("new_orders_sha256", fact["sha256"]),
                             fact["new_orders_source_page"]))
        hosts = (OFFICIAL_IR_HOSTS.get(fact["code"], "invalid"), *OFFICIAL_IR_ADDITIONAL_HOSTS.get(fact["code"], ()))
        for url, digest, page in evidence:
            if not any(url.startswith(host + "/") for host in hosts):
                raise ValueError("검증 장부 회사/공식 출처 불일치")
            index = fact.get("download_idx") if url == fact["source_url"] else None
            key = (url, index)
            if key not in downloads:
                downloads[key] = download_verified_pdf(fact) if url == fact["source_url"] else http_get(url, timeout=90).content
            data = downloads[key]
            if not data.startswith(b"%PDF") or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("검증 IR 원문 해시 변경: 수동 재검증 필요")
            with pymupdf.open(stream=data, filetype="pdf") as document:
                if not 1 <= page <= len(document):
                    raise ValueError("IR 근거 페이지 없음")
        facts.append(fact)
    return facts


def collect_hd_electric(verified: list[dict]) -> list[dict]:
    facts = {(f["year"], f["quarter"], f["scope"]): f for f in verified if f["code"] == "267260"}
    for page in range(1, ORDER_IR_LIST_PAGES + 1):
        listing = HD_BASE + "/elect/ko/IR/IRdata1.jsp?" + urlencode({"paging.pageNo": page})
        soup = BeautifulSoup(decode_html(http_get(listing, timeout=60)), "html.parser")
        for tr in soup.find_all("tr"):
            title = tr.get_text(" ", strip=True)
            if "실적발표 자료" not in title or "_eng" in title:
                continue
            anchor = tr.find("a", onclick=True)
            args = re.findall(r"'([^']*)'", anchor["onclick"] if anchor else "")
            if len(args) != 4 or not re.fullmatch(r"[\w.]+\.pdf", args[1]):
                continue
            # 공식 HTML/JavaScript 다운로드 폼의 세 인수를 그대로 사용한다.
            url = HD_BASE + "/elec/common/fileDown.jsp?" + urlencode(dict(zip(
                ("fileName", "filePath", "fileOrgName"), args[1:])))
            response = http_get(url, timeout=90)
            if not response.content.startswith(b"%PDF"):
                raise ValueError("공식 IR 다운로드가 PDF가 아님")
            digest = hashlib.sha256(response.content).hexdigest()
            with pymupdf.open(stream=response.content, filetype="pdf") as document:
                for index, pdf_page in enumerate(document):
                    parsed = parse_quarter_order_page(pdf_page.get_text())
                    for fact in parsed:
                        key = (fact["year"], fact["quarter"], fact["scope"])
                        # 목록 최신 발표본이 과거 비교값을 정정한 경우 최신값을 우선한다.
                        facts.setdefault(key, {**fact, "code": "267260", "source_url": url,
                                               "source_page": index + 1, "source_title": title, "sha256": digest})
        if len(facts) >= ORDER_IR_QUARTERS:
            break
    return sorted(facts.values(), key=lambda f: (f["year"], f["quarter"]))[-ORDER_IR_QUARTERS:]


def parse_ls_backlog(text: str) -> list[dict]:
    """주요제품 수주잔고 표의 Total만 읽는다. 제품별 소계와 재무표는 제외."""
    part = text.split("수주잔고 현황")
    if len(part) != 2 or "단위 : 억원" not in text:
        return []
    periods = [(year or reverse_year, q or reverse_q) for year, q, reverse_q, reverse_year in
               re.findall(r"['’‘](\d{2})[.\s]*([1-4])Q|([1-4])Q\s*['’‘](\d{2})", part[1].split("YoY")[0])]
    total = re.search(r"Total\s*\n([\d,]+)\s*\n([\d,]+)\s*\n([\d,]+)", part[1])
    if len(periods) != 3 or not total:
        return []
    return [{"year": 2000 + int(year), "quarter": int(q), "backlog": float(total[i + 1].replace(",", ""))}
            for i, (year, q) in enumerate(periods)]


def parse_ls_new_orders(text: str) -> list[dict]:
    compact = re.sub(r"\s+", "", text)
    # 2026Q2부터 요약 표, 앞선 IR은 Financial Results 안의 New Orders 막대.
    if "1.Highlights" in compact and "단위:억원" in compact:
        period = re.search(r"([1-4])Q[‘’'](\d{2})", compact)
        value = re.search(r"New\s*orders\s*\n([\d,]+)", text)
        if period and value:
            return [{"year": 2000 + int(period[2]), "quarter": int(period[1]), "new_orders": float(value[1].replace(',', ''))}]
    if "FinancialResults" not in compact or "[단위:십억원]" not in compact:
        return []
    part = text.split("New Orders")
    if len(part) != 2:
        return []
    part = part[1].split("Operating Profit")[0]
    periods = re.findall(r"['’‘](\d{2})\s*([1-4])Q", part)
    values = [float(line.strip().replace(',', '')) for line in part.splitlines()
              if re.fullmatch(r"[\d,]+", line.strip())]
    if len(periods) != len(values) or len(set(periods)) != len(periods):
        return []
    return [{"year": 2000 + int(year), "quarter": int(q), "new_orders": values[i] * 10}
            for i, (year, q) in enumerate(periods)]


def collect_ls_electric() -> list[dict]:
    base = OFFICIAL_IR_HOSTS["010120"]
    soup = BeautifulSoup(decode_html(http_get(base + "/ko/company/invest/ir/")), "html.parser")
    links = sorted({a["href"] for a in soup.find_all("a", href=True)
                    if re.search(r"20\d{2}_[1-4]분기_실적자료\.pdf$", a["href"])}, reverse=True)[:ORDER_IR_QUARTERS]
    backlog, new = {}, {}
    for link in links:
        url = urljoin(base, link)
        if not url.startswith(base + "/ko/company/data/"):
            raise ValueError("LS IR 외부 출처 차단")
        data = http_get(url, timeout=90).content
        if not data.startswith(b"%PDF"):
            raise ValueError("LS IR PDF 아님")
        proof = {"source_url": url, "sha256": hashlib.sha256(data).hexdigest()}
        with pymupdf.open(stream=data, filetype="pdf") as document:
            for i, page in enumerate(document):
                text = page.get_text()
                for fact in parse_ls_backlog(text):
                    backlog.setdefault((fact["year"], fact["quarter"]), {**fact, **proof, "source_page": i + 1})
                for fact in parse_ls_new_orders(text):
                    new.setdefault((fact["year"], fact["quarter"]), {**fact, **proof, "source_page": i + 1})
    facts = []
    for key in sorted(set(backlog) | set(new))[-ORDER_IR_QUARTERS:]:
        order = new.get(key)
        fact = backlog.get(key) or {**order, "backlog": None}
        facts.append({**fact, "code": "010120", "scope": "공식 IR 주요제품 수주사업", "unit": "억원",
                      "new_orders_period": "당분기", "new_orders": order["new_orders"] if order else None,
                      "source_title": "LS ELECTRIC 공식 분기 IR",
                      **({"new_orders_source_url": order["source_url"], "new_orders_source_page": order["source_page"]} if order else {})})
    return facts


def merge_ir_scope(previous: dict, metric: str, fact: dict) -> dict:
    """같은 보고서에서 한 범위만 갱신하고 나머지 사업부·근거를 보존한다."""
    scope_line = f'범위 | {fact["scope"]}'
    series = [s for s in previous.get("series", []) if s.splitlines()[0] != scope_line]
    evidence = previous.get("evidence", [])
    if isinstance(evidence, dict):
        evidence = [evidence]
    evidence = [f for f in evidence if f.get("scope") != fact["scope"]]
    return {"series": [*series, metric], "evidence": [*evidence, fact]}


def plain_ir_amount(value: int | float) -> str:
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("IR 수주 금액은 유한 숫자여야 함")
    text = format(amount, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_ir_metric(fact: dict) -> str:
    """검증된 수치를 대시보드 계약의 숫자 행으로 직렬화한다."""
    metric = (f'범위 | {fact["scope"]}\n단위 | {fact["unit"]}'
              + (f'\n수주잔고 | {plain_ir_amount(fact["backlog"])}' if fact["backlog"] is not None else "")
              + (f'\n신규수주 | {plain_ir_amount(fact["new_orders"])}\n신규수주 기간 | {fact["new_orders_period"]}' if fact["new_orders"] is not None else "") +
              f'\n출처 | {fact["source_url"]}' +
              (f'\n출처 페이지 | {fact["source_page"]}' if fact.get("download_idx") is None else "") +
              f'\n자료명 | 공식 IR')
    if fact.get("new_orders_source_url"):
        metric += f'\n신규수주 출처 | {fact["new_orders_source_url"]}#page={fact["new_orders_source_page"]}'
    return metric


def save_facts(facts: list[dict]) -> int:
    db = get_client()
    stored = 0
    for code in sorted({fact["code"] for fact in facts}):
        rows = select_all("disclosure_excerpts", "rcept_no,code,fiscal_year,fiscal_quarter,sections", filters={"code": code})
        for fact in facts:
            if fact["code"] != code:
                continue
            month = fact["quarter"] * 3
            end = f'{fact["year"]}-{month:02d}-{calendar.monthrange(fact["year"], month)[1]:02d}'
            candidates = [r for r in rows if isinstance(r["sections"], dict)
                          and (r["sections"].get("공시 보고기간", {}).get("end") == end
                               or not r["sections"].get("공시 보고기간") and
                               r["fiscal_year"] == fact["year"] and r["fiscal_quarter"] == fact["quarter"])]
            if not candidates:
                continue
            row = max(candidates, key=lambda r: r["rcept_no"])
            # 한 보고서의 여러 사업부 IR를 덮어쓰지 않고 범위별 보존한다.
            checked_row = db.table("disclosure_excerpts").select("sections").eq("rcept_no", row["rcept_no"]).single().execute().data
            sections = dict(checked_row["sections"])
            metric = format_ir_metric(fact)
            sections["공식 IR 수주지표"] = merge_ir_scope(sections.get("공식 IR 수주지표", {}), metric, fact)
            db.table("disclosure_excerpts").update({"sections": sections}).eq("rcept_no", row["rcept_no"]).execute()
            checked = db.table("disclosure_excerpts").select("sections").eq("rcept_no", row["rcept_no"]).single().execute().data
            if checked["sections"].get("공식 IR 수주지표") != sections["공식 IR 수주지표"]:
                raise RuntimeError("공식 IR 저장 재조회 불일치")
            stored += 1
    return stored


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    verified = verified_ir_facts()
    facts = collect_hd_electric(verified) + collect_ls_electric() + [f for f in verified if f["code"] not in {"267260", "010120"}]
    if not facts:
        raise RuntimeError("공식 IR 명시 수주표를 확보하지 못함")
    print(json.dumps({"facts": facts, "stored": save_facts(facts) if args.save else 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
