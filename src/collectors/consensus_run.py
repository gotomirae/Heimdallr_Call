# PRD Ref: §5.1(L3), §13 (P5 검증) · traps.md T17
"""P5 컨센서스 스냅샷 실행.

    python -m src.collectors.consensus_run --sample     # 시총 구간별 50종목 검증
    python -m src.collectors.consensus_run --save       # 대상 종목 수집 → DB
    python -m src.collectors.consensus_run --save --limit 200
"""

from __future__ import annotations

import argparse
import collections
import time

from src.collectors.consensus import (
    REQUEST_INTERVAL_SEC,
    fetch_annual_estimate,
    snapshot,
)
from src.db.supabase_client import get_client, select_all
from src.utils.console import enable_utf8_stdout

#: 시총 구간 경계 (원). PRD §13 검증은 대형 15 / 중형 20 / 소형 15를 요구한다.
LARGE_CAP_FLOOR = 3_000_000_000_000  # 3조
MID_CAP_FLOOR = 500_000_000_000  # 5,000억
SAMPLE_SIZES = {"대형": 15, "중형": 20, "소형": 15}


def _bucket(market_cap: int | None) -> str:
    if market_cap is None:
        return "소형"
    if market_cap >= LARGE_CAP_FLOOR:
        return "대형"
    if market_cap >= MID_CAP_FLOOR:
        return "중형"
    return "소형"


def load_targets() -> list[dict]:
    """시총 내림차순 · 업종 제외 종목은 뺀다."""
    rows = select_all(
        "krx_universe",
        "code,name,market_cap_krw,is_excluded",
        order="market_cap_krw",
        desc=True,
    )
    return [r for r in rows if not r["is_excluded"] and r["market_cap_krw"]]


def sample_check() -> int:
    targets = load_targets()
    buckets: dict[str, list[dict]] = collections.defaultdict(list)
    for row in targets:
        buckets[_bucket(row["market_cap_krw"])].append(row)

    line = "═" * 74
    print(line)
    print("P5 컨센서스 — 시총 구간별 샘플 검증")
    print(line)
    print(f"유니버스 구간 분포: "
          f"{ {k: len(v) for k, v in buckets.items()} }")
    print("\n★ 소형주 성공률이 낮게 나오는 것이 **정상**이다(PRD §2).")
    print("  코스닥 1,819사 중 1,089사(59.9%)가 최근 1년 증권사 리포트 0건이다.")
    print("  이 수치를 확인하는 것이 이 검증의 목적이다 — C축을 0점 처리하면 안 되는 근거다.\n")

    overall: dict[str, dict] = {}
    for bucket, size in SAMPLE_SIZES.items():
        pool = buckets.get(bucket, [])
        # 구간 안에서 고르게 뽑는다(상위 편중 방지)
        step = max(len(pool) // size, 1) if pool else 1
        chosen = pool[::step][:size]

        found = 0
        usable = 0
        n_values: list[int] = []
        no_estimate = 0
        print(f"■ {bucket} {len(chosen)}종목 (구간 전체 {len(pool)})")
        for row in chosen:
            snaps = snapshot(row["code"])
            if snaps:
                found += 1
                snap = snaps[0]
                if snap.n_estimates is not None:
                    n_values.append(snap.n_estimates)
                if snap.is_usable:
                    usable += 1
            else:
                no_estimate += 1
            time.sleep(REQUEST_INTERVAL_SEC)

        total = len(chosen) or 1
        overall[bucket] = {
            "chosen": len(chosen), "found": found, "usable": usable,
            "n_values": n_values,
        }
        print(f"    (E) 분기 추정치 확보 {found}/{len(chosen)} ({found / total * 100:.0f}%)")
        print(f"    컨센서스 인정(n≥2)  {usable}/{len(chosen)} ({usable / total * 100:.0f}%)")
        if n_values:
            n_values.sort()
            print(f"    추정기관수 분포: 최소 {n_values[0]} · 중앙값 "
                  f"{n_values[len(n_values) // 2]} · 최대 {n_values[-1]}")
            print(f"      n=1 {sum(1 for v in n_values if v == 1)}종목 "
                  f"(컨센서스로 인정하지 않는다) · n≥5 {sum(1 for v in n_values if v >= 5)}종목")
        else:
            print("    추정기관수: 확보 0건")
        print()

    print(line)
    print("[종합]")
    total_chosen = sum(v["chosen"] for v in overall.values())
    total_usable = sum(v["usable"] for v in overall.values())
    print(f"    샘플 {total_chosen}종목 중 컨센서스 인정 {total_usable}종목 "
          f"({total_usable / max(total_chosen, 1) * 100:.0f}%)")
    for bucket in ("대형", "중형", "소형"):
        v = overall.get(bucket)
        if v:
            print(f"      {bucket} {v['usable']}/{v['chosen']} "
                  f"({v['usable'] / max(v['chosen'], 1) * 100:.0f}%)")
    print(f"\n    → 나머지 종목의 C축(15점)은 **0점이 아니라 분모에서 제외**된다(ADR 2).")
    print(line)
    return 0


def save_all(limit: int | None) -> int:
    targets = load_targets()

    # 직전 분기 게이트 통과 종목은 시총과 무관하게 포함한다(발굴 대상이므로).
    passed = {
        r["code"]
        for r in select_all("screen_results", "code,gate_passed")
        if r["gate_passed"]
    }
    top = [r["code"] for r in targets[:500]]
    codes = list(dict.fromkeys(top + [c for c in passed if c]))
    if limit:
        codes = codes[:limit]

    print(f"대상 {len(codes)}종목 (시총 상위 500 ∪ 직전 분기 게이트 통과 {len(passed)})")
    print(f"예상 소요 {len(codes) * 2 * REQUEST_INTERVAL_SEC / 60:.0f}분 (요청 간 {REQUEST_INTERVAL_SEC}초)")

    db = get_client()
    payload: list[dict] = []
    found = usable = 0
    annual_found = 0
    for index, code in enumerate(codes, 1):
        snaps = snapshot(code)
        if snaps:
            found += 1
            usable += sum(1 for s in snaps if s.is_usable)
            payload.extend(s.to_db() for s in snaps)

        # ★ 연간 추정은 **Forward PER의 유일한 재료**다. 분기 컨센은 한 분기뿐이라
        #   "향후 4분기"를 만들 수 없다 — 연간 추정이 있어야 예상 PER이 나온다.
        #   `fiscal_quarter = 0`을 '연간'으로 쓴다(스키마 변경 없이 구분).
        annual = fetch_annual_estimate(code)
        # 순이익 추정이 비어도 네이버가 제공한 확정/선행 PER은 화면 근거로 유효하다.
        # fetch_annual_estimate()가 세 값이 전부 없을 때만 None을 돌려준다.
        if annual:
            annual_found += 1
            payload.append({
                "code": code,
                "fiscal_year": annual["fiscal_year"],
                "fiscal_quarter": 0,
                "revenue_est": annual.get("revenue_est"),
                "op_est": annual.get("op_est"),
                "np_est": annual.get("np_est"),
                "per": annual.get("per"),
                "fwd_per": annual.get("fwd_per"),
                "n_estimates": None,
                "source": "naver",
            })

        if index % 100 == 0:
            print(f"    {index}/{len(codes)} · 확보 {found} · 인정 {usable}")
        time.sleep(REQUEST_INTERVAL_SEC)

    for i in range(0, len(payload), 500):
        db.table("consensus_snapshots").insert(payload[i : i + 500]).execute()

    print(f"\n✓ consensus_snapshots insert {len(payload)}행")
    print(f"  추정치 확보 {found}/{len(codes)}종목 · 컨센서스 인정(n≥2) {usable}건")
    return 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="P5 컨센서스 스냅샷")
    parser.add_argument("--sample", action="store_true", help="시총 구간별 50종목 검증")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    if args.save:
        return save_all(args.limit)
    return sample_check()


if __name__ == "__main__":
    raise SystemExit(main())
