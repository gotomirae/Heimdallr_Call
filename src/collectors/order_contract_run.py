# PRD Ref: §5.3, §9.1-3 — 단일판매·공급계약 구조화
"""OpenDART 단일판매·공급계약 원문을 구조화해 기존 공시 발췌에 저장한다.

정기보고서 수주잔고와 수시공시 계약금액은 범위가 다르다. 따라서 계약금액은
``전체 신규수주``가 아니라 ``공시된 계약 합계(일부)``로만 표시한다.
"""

from __future__ import annotations

import argparse
import html
import re
import time
from dataclasses import asdict, dataclass

from src.collectors.dart_excerpt import ExcerptError, fetch_report_xml
from src.db.supabase_client import get_client, select_all
from src.utils.console import enable_utf8_stdout


@dataclass(frozen=True)
class OrderContract:
    contract_name: str | None
    amount_krw: int | None
    sales_krw: int | None
    sales_ratio_pct: float | None
    counterparty: str | None
    contract_date: str | None
    start_date: str | None
    end_date: str | None
    disclosure_status: str = "measured"


_TAG = re.compile(r"<[^>]+>")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", value))).strip(" |\u00a0")


def table_rows(xml: str) -> list[list[str]]:
    """DART XML 표를 셀 배열로 만든다. 셀 내부 개행은 의미가 없어 합친다."""
    out: list[list[str]] = []
    for row in re.findall(r"<TR\b[^>]*>(.*?)</TR>", xml, re.I | re.S):
        cells = [_clean(cell) for cell in re.findall(
            r"<T[DH]\b[^>]*>(.*?)</T[DH]>", row, re.I | re.S
        )]
        if any(cells):
            out.append(cells)
    return out


def _label_key(value: str) -> str:
    return re.sub(r"^[\d.\-]+", "", re.sub(r"\s+", "", value).replace("ㆍ", "·"))


def _value(rows: list[list[str]], labels: tuple[str, ...], *, exact: bool = False) -> str | None:
    normalized_labels = tuple(re.sub(r"\s+", "", label).replace("ㆍ", "·") for label in labels)
    for cells in rows:
        normalized = [_label_key(cell) for cell in cells]
        for index, cell in enumerate(normalized):
            if not any(cell == label if exact else label in cell for label in normalized_labels):
                continue
            values = [value for value in cells[index + 1:] if value and value not in {"-", "해당사항없음"}]
            if values:
                return values[-1]
    return None


def _integer(value: str | None) -> int | None:
    if not value:
        return None
    cleaned = re.sub(r"[^0-9-]", "", value)
    if not cleaned or cleaned == "-":
        return None
    parsed = int(cleaned)
    return parsed if parsed >= 0 else None


def _float(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"-?[\d,]+(?:\.\d+)?", value)
    return float(match.group().replace(",", "")) if match else None


def _date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})", value)
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}" if match else None


def parse_order_contract(xml: str) -> OrderContract | None:
    """명시된 값만 읽는다. 금액 단위가 원으로 명시되지 않으면 추측하지 않는다."""
    rows = table_rows(xml)
    has_won_amount = any(
        "계약금액" in re.sub(r"\s+", "", cell) and "(원)" in re.sub(r"\s+", "", cell)
        for cells in rows for cell in cells
    )
    amount = _integer(_value(rows, (
        "계약금액총액(원)", "확정계약금액", "계약금액(원)"
    ), exact=True)) if has_won_amount else None
    contract_name = _value(rows, (
        "체결계약명", "계약내용", "판매·공급계약내용", "판매ㆍ공급계약내용"
    ))
    if contract_name and "계약금액" in contract_name:
        contract_name = None
    limited = amount is None and contract_name is None and any(
        any(token in re.sub(r"\s+", "", cell) for token in ("계약내용", "계약내역", "체결계약명"))
        for cells in rows for cell in cells
    )
    contract = OrderContract(
        contract_name=contract_name,
        amount_krw=amount,
        sales_krw=_integer(_value(rows, ("최근매출액(원)",), exact=True)),
        sales_ratio_pct=_float(_value(rows, ("매출액대비(%)", "최근매출액대비(%)"), exact=True)),
        counterparty=_value(rows, ("계약상대방", "계약상대")),
        contract_date=_date(_value(rows, ("계약(수주)일자", "계약체결일", "계약일"))),
        start_date=_date(_value(rows, ("계약기간시작일", "시작일"))),
        end_date=_date(_value(rows, ("계약기간종료일", "종료일"))),
        disclosure_status="limited" if limited else "measured",
    )
    return contract if contract.contract_name or contract.amount_krw is not None or limited else None


def targets(limit: int, *, refresh: bool = False) -> list[dict]:
    rows = [row for row in select_all(
        "earnings_disclosures", "rcept_no,code,report_nm,doc_type,disclosed_at"
    ) if row.get("doc_type") == "order_contract"]
    have = {row["rcept_no"] for row in select_all("disclosure_excerpts", "rcept_no,sections")
            if isinstance(row.get("sections"), dict) and "단일판매·공급계약" in row["sections"]}
    return sorted((row for row in rows if refresh or row["rcept_no"] not in have),
                  key=lambda row: str(row.get("disclosed_at") or ""), reverse=True)[:limit]


def run(*, limit: int, save: bool, refresh: bool = False) -> int:
    rows = targets(limit, refresh=refresh)
    db = get_client() if save else None
    ok = failed = 0
    for index, row in enumerate(rows):
        try:
            xml = fetch_report_xml(row["rcept_no"])
            contract = parse_order_contract(xml)
        except ExcerptError as exc:
            print(f"  ✗ {row['code']} {row['rcept_no']} — {exc}")
            failed += 1
            continue
        if contract is None:
            print(f"  ⚠ {row['code']} {row['rcept_no']} — 계약 표 구조화 실패 · 저장 안 함")
            failed += 1
            continue
        payload = asdict(contract)
        payload.update({"report_name": row.get("report_nm"), "disclosed_at": str(row.get("disclosed_at") or "")[:10]})
        if db:
            db.table("disclosure_excerpts").upsert({
                "rcept_no": row["rcept_no"], "code": row["code"],
                "fiscal_year": None, "fiscal_quarter": None,
                "sections": {"단일판매·공급계약": payload},
                "excerpt_chars": len(str(payload)), "full_chars": len(xml),
            }, on_conflict="rcept_no").execute()
        ok += 1
        amount_label = f"{payload['amount_krw']}원" if payload["amount_krw"] is not None else "금액 비공개"
        print(f"  ✓ {row['code']} {payload['contract_name'] or '계약 내용 비공개'} · {amount_label}")
        if index + 1 < len(rows):
            time.sleep(0.4)
    print(f"단일판매·공급계약 구조화 {ok}건 · 실패 {failed}건" + ("" if save else " · DB 쓰기 0건"))
    return 0 if failed == 0 else 1


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="OpenDART 단일판매·공급계약 구조화")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="이미 구조화한 계약도 현재 파서로 다시 읽기")
    args = parser.parse_args()
    return run(limit=args.limit, save=args.save, refresh=args.refresh)


if __name__ == "__main__":
    raise SystemExit(main())
