# PRD Ref: §9 · JARVIS INTEGRATION_TASKS B-10 · JARVIS PRD 부록 A.5
"""투자 섹터(이름 유지) → JARVIS 노션 L1 코드. `krx_universe.industry_l1`에 저장한다.

    python -m src.universe.industry_l1          # dry-run (섹터별 L1 분포)
    python -m src.universe.industry_l1 --save   # krx_universe.industry_l1 갱신

원칙
  1. **섹터 이름은 바꾸지 않는다.** 화면·점수·피어 분모가 이 이름을 쓴다.
  2. 매핑의 정본은 JARVIS `/api/public/taxonomy`다(사용자 확정 overrides 포함).
     API를 못 읽으면 부록 A.5 정적표로 떨어지고 `industry_l1_source='static'`으로 밝힌다.
  3. 어디에도 없는 섹터는 추측하지 않고 `ETC`(JARVIS unmatched_default)다.
"""

from __future__ import annotations

import re

#: JARVIS PRD 부록 A.5 (2026-09-27) + 그 뒤 생긴 섹터(AI·양자컴퓨터·화장품_미용기기·여행).
#: 코드는 JARVIS `config/taxonomy.yaml > l1[].code`다.
STATIC_SECTOR_L1: dict[str, tuple[str, ...]] = {
    "반도체 IDM": ("1b",), "반도체 장비": ("1b",), "반도체 소재": ("1b",),
    "반도체 부품": ("1b",), "반도체 DSP": ("1b",), "반도체 OSAT": ("1b",),
    "AI": ("1a",),
    "원전": ("1c",), "신재생에너지": ("1c",), "전력인프라": ("1c",),
    "우주방산": ("1g",),
    "배터리": ("1i",),
    "양자컴퓨터": ("3c",),
    "전자부품": ("2b",), "디스플레이": ("2b",), "인터넷·플랫폼": ("2b",),
    "소프트웨어·IT": ("2b",), "통신·네트워크": ("2b",),
    "조선·해운": ("1h",),
    "자동차": ("1l",),
    "화장품_미용기기": ("1e",),
    "바이오·제약": ("1d",),
    "의료기기": ("2c",),
    "엔터·미디어": ("1f",), "게임": ("1f",),
    "건설": ("2g",), "건자재": ("2g",), "부동산·리츠": ("2g",),
    "로봇기계": ("2a",),
    "음식료": ("2d",), "유통·소비재": ("2d",),
    "여행": ("2e",),
    "금융": ("2f",),
    "철강·금속": ("ETC",), "화학·소재": ("ETC",), "운송·물류": ("ETC",),
    "지주·기타서비스": ("ETC",), "기타": ("ETC",),
}
UNMATCHED_DEFAULT = "ETC"
TAXONOMY_PATH = "/api/public/taxonomy"
#: 정규화에서 지우는 문자 — JARVIS `matching.normalize_strip`과 같다.
_STRIP = re.compile(r"[\s_·\-./]+")


def _norm(value: str | None) -> str:
    return _STRIP.sub("", (value or "").strip()).lower()


def resolve_l1(sector: str | None, taxonomy: dict | None = None) -> tuple[tuple[str, ...], str]:
    """(L1 코드들, 근거). 근거는 'jarvis_override'|'static'|'jarvis_synonym'|'default'.

    순서: JARVIS 사용자 확정 매핑 → 부록 A.5 정적표 → JARVIS L1 이름·L2·동의어
    **완전 일치**(부분 일치는 JARVIS도 동의어에 금지한다 — 인바운드↔파운드리 오탐).
    """
    from src.universe.sector_map import canonical_sector_name

    name = canonical_sector_name(sector) or UNMATCHED_DEFAULT
    key = _norm(name)
    for override in (taxonomy or {}).get("overrides") or []:
        if override.get("project") not in ("*", "heimdallr"):
            continue
        if _norm(override.get("label")) == key and override.get("l1"):
            return tuple(str(code) for code in override["l1"]), "jarvis_override"
    if name in STATIC_SECTOR_L1:
        return STATIC_SECTOR_L1[name], "static"
    for row in (taxonomy or {}).get("l1") or []:
        names = [row.get("name"), *(row.get("l2") or []), *(row.get("synonyms") or [])]
        if any(_norm(candidate) == key for candidate in names if candidate):
            return (str(row["code"]),), "jarvis_synonym"
    default = (taxonomy or {}).get("unmatched_default") or UNMATCHED_DEFAULT
    return (str(default),), "default"


def unknown_codes(taxonomy: dict | None) -> list[str]:
    """정적표가 가리키는 코드 중 JARVIS taxonomy에 없는 것(노션 개편 감지용)."""
    if not taxonomy:
        return []
    known = {str(row.get("code")) for row in taxonomy.get("l1") or []}
    known |= {str(row.get("code")) for row in taxonomy.get("special_labels") or []}
    return sorted({code for codes in STATIC_SECTOR_L1.values() for code in codes} - known)


def fetch_taxonomy() -> dict | None:
    """JARVIS 공개 taxonomy. 주소·토큰이 없거나 실패하면 None(정적표로 진행)."""
    from src.utils.env import optional_env
    from src.utils.http import http_get

    base = (optional_env("JARVIS_BASE_URL") or "").rstrip("/")
    token = optional_env("JARVIS_PUBLIC_TOKEN")
    if not base or not token:
        return None
    try:
        response = http_get(
            f"{base}{TAXONOMY_PATH}", headers={"X-Jarvis-Token": token}, timeout=20.0, retries=2,
        )
        body = response.json()
    except Exception:
        return None
    return body if isinstance(body, dict) and body.get("ok") else None


def _main() -> int:
    import argparse
    import collections

    from src.db.supabase_client import get_client, select_all, upsert_tolerating_missing_columns
    from src.universe.sector_map import classify_sector
    from src.utils.console import enable_utf8_stdout

    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="투자 섹터 → JARVIS L1 → krx_universe.industry_l1")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    taxonomy = fetch_taxonomy()
    print(f"JARVIS taxonomy: {'API v' + str(taxonomy.get('version')) if taxonomy else '미사용(정적표 A.5)'}")
    missing = unknown_codes(taxonomy)
    if missing:
        print(f"  ⚠ 정적표 코드가 JARVIS에 없다: {', '.join(missing)} — 노션 L1 개편 확인 필요")

    rows = select_all("krx_universe", "code,symbol,name,board,industry,products,sector")
    payload = []
    dist: collections.Counter = collections.Counter()
    basis_count: collections.Counter = collections.Counter()
    for row in rows:
        sector = row.get("sector") or classify_sector(row.get("name"), row.get("industry"), row.get("products"))
        codes, basis = resolve_l1(sector, taxonomy)
        dist[(sector, ",".join(codes))] += 1
        basis_count[basis] += 1
        payload.append({
            "code": row["code"], "symbol": row["symbol"], "name": row["name"], "board": row["board"],
            "industry_l1": list(codes),
            "industry_l1_source": "jarvis_api" if taxonomy else "static",
        })
    for (sector, codes), count in sorted(dist.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {sector:<14} → {codes:<8} {count:>4}")
    print(f"근거 {dict(basis_count)}")
    if not args.save:
        print("\n(--save 미지정 — DB에 기록하지 않았다)")
        return 0
    saved, dropped = upsert_tolerating_missing_columns(get_client(), "krx_universe", payload, on_conflict="code")
    print(f"✓ krx_universe.industry_l1 {saved}행 갱신")
    if dropped:
        print(f"  ⚠ DB에 없는 컬럼: {', '.join(dropped)} — docs/migrations/entry_checks.sql 적용 필요")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
