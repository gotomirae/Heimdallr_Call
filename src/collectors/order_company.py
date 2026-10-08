# PRD Ref: §9.1-3
"""수주기업 분류와 세 항목 조사 장부. 금액 결측을 비수주기업으로 바꾸지 않는다."""
from __future__ import annotations

import re
from bs4 import BeautifulSoup


def classify_order_section(xml: str) -> dict:
    """단위를 읽기 전 원문 사업 형태를 판정한다. 업종명은 증거로 쓰지 않는다."""
    soup = BeautifulSoup(xml, "html.parser")
    text = soup.get_text(" ", strip=True)
    compact = re.sub(r"\s+", "", text)
    negative = re.search(r"(?:수주산업|수주사업|수주형사업).{0,24}(?:아니|아닌|아닙|아님|해당하지않|영위하지않)", compact)
    positive = None
    for table in soup.find_all("table"):
        cells = [re.sub(r"\s+", "", c.get_text(" ", strip=True)) for c in table.find_all(["td", "th"])]
        headers = [c for c in cells if re.fullmatch(r"(?:기말|당기말|당분기말|당반기말|기초)?(?:수주잔고|수주잔액|수주계약잔액|신규수주|신규수주계약금액)(?:액|금액)?", c)]
        if headers and any(re.fullmatch(r"[\d,]+(?:\.\d+)?", c) for c in cells):
            positive = "원문 수주표: " + ", ".join(dict.fromkeys(headers))
            break
    narrative = re.search(r"수주(?:잔고|잔액).{0,70}(?:[0-9][0-9,.]*)(?:억원|백만원|천원|원|USD|달러)", compact)
    private = re.search(r"(?:수주현황|수주상황|수주잔고).{0,100}(?:비공개|기밀|영업비밀|보안)", compact)
    if positive or narrative or private:
        if negative:
            return {"status": "review", "basis": "사업부별 수주표와 비수주 문구가 함께 있음; 범위 확인 필요", "evidence": negative.group(0)}
        match = narrative or private
        return {"status": "confirmed", "basis": positive or ("수주 금액 직접 기재" if narrative else "수주 내역 비공개 명시"),
                "evidence": positive or match.group(0)}
    if negative:
        return {"status": "not_applicable", "basis": "원문에서 수주사업 비해당 명시", "evidence": negative.group(0)}
    return {"status": "review", "basis": "원문에서 수주기업 여부를 확정하지 못함", "evidence": ""}


def main() -> int:
    import argparse
    import csv
    import json
    import subprocess
    from collections import Counter
    from datetime import datetime, timezone
    from pathlib import Path

    from src.config.constants import MARKET_CAP_FLOOR_KRW
    from src.db.supabase_client import get_client, select_all
    from src.utils.console import enable_utf8_stdout

    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--output", default=".cache/orders/company-audit.json")
    parser.add_argument("--source-cache", default=".cache/orders/sources")
    parser.add_argument("--ir-audit-dir", default=".cache/orders/kind-ir")
    args = parser.parse_args()
    universe = select_all("krx_universe", "code,name,sector,market_cap_krw,is_excluded", order="code")
    universe = [u for u in universe if not u.get("is_excluded") and (u.get("market_cap_krw") or 0) >= MARKET_CAP_FLOOR_KRW]
    codes = {u["code"] for u in universe}
    rows = select_all("disclosure_excerpts", "rcept_no,code,fiscal_year,fiscal_quarter,sections,excerpt_chars,full_chars", page_size=250, order="rcept_no")
    rows = [r for r in rows if r["code"] in codes]
    print(f"loaded_universe={len(universe)}; reports={len(rows)}", flush=True)
    source_count = 0
    enriched = set()
    for index, row in enumerate(rows):
        source = Path(args.source_cache) / f'{row["rcept_no"]}.xml'
        if source.is_file():
            # 저장된 본문을 바꾸지 않고 전체 원문으로 분류를 보완한다.
            row["sections"] = dict(row.get("sections") or {})
            row["sections"]["order_business_evidence"] = classify_order_section(source.read_text(encoding="utf-8"))
            enriched.add(row["rcept_no"])
            source_count += 1
        if index and index % 2000 == 0:
            print(f"source_review={index}/{len(rows)}; full_sources={source_count}", flush=True)
    stamp = datetime.now(timezone.utc).isoformat()
    # KIND 조사 결과는 후보 장부이며 숫자 승인으로 취급하지 않는다.
    ir_root = Path(args.ir_audit_dir)
    ir_targets = json.loads((ir_root / "targets.json").read_text(encoding="utf-8")) if (ir_root / "targets.json").is_file() else []
    ir_summary = json.loads((ir_root / "summary.json").read_text(encoding="utf-8")) if (ir_root / "summary.json").is_file() else {}
    ir_scan = json.loads((ir_root / "scan.json").read_text(encoding="utf-8")) if (ir_root / "scan.json").is_file() else {}
    manifest = Path(__file__).resolve().parents[1] / "config/order_ir_verified.json"
    approved = json.loads(manifest.read_text(encoding="utf-8"))
    previous = {}
    for row in rows:
        saved = (row.get("sections") or {}).get("order_company_audit")
        if isinstance(saved, dict) and saved.get("irResearch"):
            if row["code"] not in previous or previous[row["code"]].get("generatedAt", "") < saved.get("generatedAt", ""):
                previous[row["code"]] = saved
    for company in universe:
        code = company["code"]
        if code in ir_targets and ir_summary and ir_summary.get("target_companies") == len(ir_targets) and ir_summary.get("read_documents") == len(ir_scan.get("results", [])) and ir_summary.get("failures") == len(ir_scan.get("failures", [])):
            docs = [r for r in ir_scan.get("results", []) if r["code"] == code]
            company["irResearch"] = {"documents": len(docs), "candidates": sum(bool(r.get("pages")) for r in docs),
                                     "failures": sum(r["code"] == code for r in ir_scan.get("failures", [])), "throughDate": ir_summary["to_date"],
                                     "verifiedFacts": sum(f["code"] == code for f in approved)}
        elif code in previous:
            company["irResearch"] = {**previous[code]["irResearch"], "verifiedFacts": sum(f["code"] == code for f in approved)}
    script = Path(__file__).resolve().parents[2] / "dashboard/scripts/order_company_audit.mjs"
    result = subprocess.run(["node", str(script)], input=json.dumps({"universe": universe, "rows": rows, "generatedAt": stamp}, ensure_ascii=False),
                            capture_output=True, text=True, encoding="utf-8", check=True)
    audits = json.loads(result.stdout)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audits, ensure_ascii=False, indent=2), encoding="utf-8")
    with output.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "기업명", "분류", "분류 근거", "최신 보고기간", "금액 범위", "단위", "수주잔고", "분기 신규수주", "잔고 QoQ", "최신 세 항목", "추가 조사", "근거"])
        for audit in audits:
            s = audit["series"][0] if audit["series"] else {}
            writer.writerow([audit["code"], audit["name"], audit["status"], audit["basis"], audit["latestPeriod"],
                             s.get("scope"), s.get("unit"), s.get("backlog"), s.get("newOrders"), s.get("qoq"),
                             s.get("complete", False), " / ".join(s.get("missing", [])) or ("원문·기업 IR 추가 조사" if not s else ""), audit["sourceUrl"]])
    with output.with_suffix(".confirmed.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "기업명"])
        writer.writerows((a["code"], a["name"]) for a in audits if a["status"] == "confirmed")
    print(json.dumps({"universe": len(universe), "full_source_reports": source_count, "classification": dict(Counter(a["status"] for a in audits)),
                      "latest_all_three": sum(any(s["complete"] for s in a["series"]) for a in audits)}, ensure_ascii=False), flush=True)
    if args.save:
        db = get_client()
        by_receipt = {r["rcept_no"]: r for r in rows}
        updates = {receipt: by_receipt[receipt] for receipt in enriched}
        saved_audits = 0
        for audit in audits:
            if not audit["anchorReceipt"]:
                continue
            old = by_receipt[audit["anchorReceipt"]]
            # 전체 JSON을 읽어 기존 IR·DART 수치를 보존하고 독립 조사 키를 추가한다.
            sections = dict(old.get("sections") or {})
            sections["order_company_audit"] = audit
            updates[old["rcept_no"]] = {**old, "sections": sections}
            saved_audits += 1
        payloads = list(updates.values())
        for start in range(0, len(payloads), 50):
            db.table("disclosure_excerpts").upsert(payloads[start:start + 50], on_conflict="rcept_no").execute()
        print(f"saved_company_audits={saved_audits}; saved_source_classifications={source_count}; no_report_anchor={len(audits)-saved_audits}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
