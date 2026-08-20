# PRD Ref: §9 /settings · CLAUDE.md 코딩 컨벤션
"""임계값을 대시보드가 읽을 JSON으로 내보낸다.

    python -m src.config.export_constants

★★ **임계값은 `constants.py` 한 곳에만 있어야 한다.**
   대시보드는 TypeScript라 파이썬 상수를 직접 못 읽는데, 그렇다고 TS에 다시 적으면
   두 곳이 조용히 어긋난다 — 참고 프로젝트에서 딥분석 문턱이 3곳에 흩어져
   실제로 겪은 사고다. 그래서 **생성물**로 만들고 손으로 고치지 않는다.

★ 생성물이 낡는 것도 같은 종류의 사고라 `tests/test_constants_export.py`가
  파일이 현재 상수와 일치하는지 검사한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.config import constants
from src.universe.sector_map import (
    INDUSTRY_ONLY_KEYWORDS,
    SECTOR_EXCLUDES,
    SECTOR_RULES,
    UNKNOWN_SECTOR,
)
from src.utils.console import enable_utf8_stdout

OUTPUT = Path(__file__).resolve().parents[2] / "dashboard" / "lib" / "constants.json"


def build() -> dict:
    """대시보드가 보여줄 임계값만 추린다. 전부 내보내면 무엇이 중요한지 흐려진다."""
    return {
        "_generated_by": "python -m src.config.export_constants",
        "_warning": "손으로 고치지 마라. src/config/constants.py가 유일한 출처다.",
        # ★ 섹터 분류 규칙을 함께 내보낸다.
        #   대시보드가 `industry`·`products`로 **읽는 시점에** 분류하므로
        #   DB에 `sector` 컬럼이 없어도 투자 섹터명이 보인다.
        #   규칙을 TS에 다시 적으면 두 곳이 조용히 어긋난다 — 생성물로 둔다.
        "sector_rules": [
            {"sector": name, "keywords": list(keywords)}
            for name, keywords in SECTOR_RULES
        ],
        # ★ 제외어·업종전용 키워드도 같이 내보낸다. 이 둘이 없으면 대시보드만
        #   옛 방식으로 분류해 **같은 종목이 화면과 DB에서 다른 섹터로 보인다.**
        "sector_excludes": {k: list(v) for k, v in SECTOR_EXCLUDES.items()},
        "sector_industry_only": sorted(INDUSTRY_ONLY_KEYWORDS),
        "sector_unknown": UNKNOWN_SECTOR,
        "gate": {
            "market_cap_floor_krw": getattr(constants, "MARKET_CAP_FLOOR_KRW", None),
            "min_quarters_history": constants.MIN_QUARTERS_HISTORY,
        },
        "score_axes": {
            "A_성장가속": sum(constants.A_WEIGHTS.values()),
            "B_수익성": sum(constants.B_WEIGHTS.values()),
            "C_서프라이즈": sum(constants.C_WEIGHTS.values()),
            "D_회계품질": sum(constants.D_WEIGHTS.values()),
        },
        "score_items": {
            **{f"a{i}": v for i, v in enumerate(constants.A_WEIGHTS.values(), 1)},
            **{f"b{i}": v for i, v in enumerate(constants.B_WEIGHTS.values(), 1)},
            **{f"c{i}": v for i, v in enumerate(constants.C_WEIGHTS.values(), 1)},
            **{f"d{i}": v for i, v in enumerate(constants.D_WEIGHTS.values(), 1)},
        },
        "denominators": {
            "flash_with_consensus": constants.SCORE_DENOM_FLASH_WITH_CONSENSUS,
            "flash_no_consensus": constants.SCORE_DENOM_FLASH_NO_CONSENSUS,
            "final_with_consensus": constants.SCORE_DENOM_FINAL_WITH_CONSENSUS,
            "final_no_consensus": constants.SCORE_DENOM_FINAL_NO_CONSENSUS,
        },
        "pri": {
            **constants.PRI_WEIGHTS,
            "min_denominator": constants.PRI_MIN_DENOMINATOR,
        },
        "matrix": {
            "score_high": constants.SCORE_HIGH,
            "score_mid": constants.SCORE_MID,
            "pri_low": constants.PRI_LOW,
            "pri_high": constants.PRI_HIGH,
        },
        "notify": {
            "grades": list(constants.NOTIFY_GRADES),
            "daily_max": constants.FLASH_DAILY_MAX,
        },
        "consensus": {"min_estimates": constants.MIN_ESTIMATES},
        "cost": {
            "monthly_ceiling_usd": constants.MONTHLY_COST_CEILING_USD,
            "input_token_budget": constants.LLM_INPUT_TOKEN_BUDGET,
            "model": constants.ANALYSIS_MODEL,
            "input_per_mtok": constants.SONNET_INPUT_PER_MTOK,
            "output_per_mtok": constants.SONNET_OUTPUT_PER_MTOK,
        },
        "data": {
            "start_year": constants.DATA_START_YEAR,
            "start_quarter": constants.DATA_START_QUARTER,
        },
    }


def main() -> int:
    enable_utf8_stdout()
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"✓ {OUTPUT.relative_to(OUTPUT.parents[2])} 생성")
    print(f"  축 배점: {payload['score_axes']}")
    print(f"  PRI 분모 하한: {payload['pri']['min_denominator']}")
    print(f"  월 비용 실링: ${payload['cost']['monthly_ceiling_usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
