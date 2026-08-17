# PRD Ref: 부록 A (상수 테이블)
"""임계값 · 배점 · 외부 API 상수의 **단 하나의** 출처.

참고 프로젝트는 딥분석 문턱이 3곳(triage.py · workflow yml · costActions.ts)에
흩어져 있어 조용히 어긋난 적이 있다. 새 임계값을 코드에 하드코딩하지 말고
반드시 여기에 추가한 뒤 import해서 쓴다.

환경변수로 조정 가능한 항목(비용 실링 등)도 "해석은 여기 한 곳"에서만 한다.
"""

from __future__ import annotations

from src.utils.env import optional_env, optional_env_int

# ═══ 유니버스 ═══
MARKET_CAP_FLOOR_KRW = 100_000_000_000  # 1,000억원
MIN_QUARTERS_HISTORY = 5  # 신규 상장 판정 (5개 분기 미만이면 G3 탈락)

# ═══ 게이트 ═══
F4_OPM_DELTA_MIN_PP = 1.0

# ═══ 스코어 배점 (100점) ═══
SCORE_WEIGHTS = {"A": 35, "B": 32, "C": 15, "D": 18}
A_WEIGHTS = {"a1": 14, "a2": 10, "a3": 6, "a4": 5}
B_WEIGHTS = {"b1": 14, "b2": 7, "b3": 6, "b4": 5}
C_WEIGHTS = {"c1": 9, "c2": 6}
D_WEIGHTS = {"d1": 6, "d2": 4, "d3": 4, "d4": 4}

# ═══ 스코어 구간 경계 ═══
A1_DELTA_MAX_PP = 20.0  # 매출 YoY 델타 만점 기준
A2_DELTA_MAX_PP = 40.0
B1_OPM_TIERS_PP = (1.0, 3.0, 5.0)
B2_TTM_OPM_TIERS_PP = (0.5, 2.0)
C1_SURPRISE_TIERS_PCT = (3.0, 10.0, 20.0)
C2_SURPRISE_TIERS_PCT = (2.0, 5.0, 10.0)
D2_DILUTION_TIERS_PCT = (2.0, 5.0)
D4_LIQUIDITY_TIERS_KRW = (500_000_000, 1_000_000_000)

A3_TTM_GROWTH_BONUS_PCT = 5.0  # TTM 매출 증가율 ≥5%면 +3점
B4_SECTOR_TIERS_PCT = (50.0, 25.0)  # 업종 내 상위 50% → 3점, 상위 25% → 5점
D1_CFO_TO_OP_MIN = 0.5  # TTM CFO / TTM 영업이익 ≥ 0.5

# ═══ 컨센서스 ═══
MIN_ESTIMATES = 2  # 추정기관 1개는 컨센서스가 아니다

# ═══ PRI (주가반영도, 0~100 · 낮을수록 미반영) ═══
PRI_WEIGHTS = {"p1": 40, "p2": 25, "p3": 20, "p4": 15}
# PRI 분모 하한. P2(52주 위치, 25점) 하나만 측정돼도 산술적으로 PRI가 나오지만,
# "3개월간 시장 대비 얼마나 안 올랐나"(P1, 40점)를 빼고 반영도를 판정하면 위험하다 —
# 52주 저점 부근이기만 하면 이미 시장을 크게 이긴 종목도 '미반영'이 된다.
# P1 단독(40) 또는 P2+P4(40) 이상이 모여야 판정한다.
PRI_MIN_DENOMINATOR = 40
# P1 3개월 상대수익률(%p) → 점수 앵커. −10%p 이하 0점 · 0%p 20점 · +30%p 이상 만점
P1_REL_RETURN_ANCHORS_PP = (-10.0, 0.0, 30.0)
P1_MID_SCORE = 20.0
# P4 발표 D+1 초과수익(%) → 0% 이하 0점 · +10% 이상 만점
P4_REACTION_MAX_PCT = 10.0

# ═══ 매트릭스 임계 ═══
SCORE_HIGH = 75
SCORE_MID = 60
PRI_LOW = 40
PRI_HIGH = 65

# ═══ 알림 ═══
FLASH_DAILY_MAX = 15
NOTIFY_GRADES = ("★", "○")  # △와 ·는 대시보드에만

# ═══ 정규화 분모 (PRD §4.2 — 이 프로젝트에서 가장 중요한 계산 규칙) ═══
# 측정 불가능한 축은 0점 처리하지 않고 분모에서 제외한다.
#   score_norm = raw_sum / (100 - sum(미측정축_배점)) * 100
# 0점 처리하면 커버리지 없는 종목(코스닥 약 60%)이 구조적으로 15점 손해를 보고
# 상위에서 밀려나 시스템의 존재 이유가 사라진다. SC6으로 상시 감시한다.
SCORE_DENOM_FLASH_WITH_CONSENSUS = 82  # A+B+C
SCORE_DENOM_FLASH_NO_CONSENSUS = 67  # A+B
SCORE_DENOM_FINAL_WITH_CONSENSUS = 100  # A+B+C+D
SCORE_DENOM_FINAL_NO_CONSENSUS = 85  # A+B+D

# ═══ 대시보드 ═══
# ★ 텔레그램 메시지의 링크가 여기서 나온다. 틀리면 **에러 없이 링크만 죽는다** —
#   메시지는 멀쩡해 보이고 눌러보기 전까지 아무도 모른다.
#   운영 값은 저장소 변수 `DASHBOARD_BASE_URL`이 덮는다(워크플로에서 주입).
#   이 상수는 그게 없을 때의 fallback이므로 **실제 배포 도메인과 같아야** 의미가 있다.
DASHBOARD_URL_DEFAULT = "https://heimdallr-call.vercel.app"

# ═══ 비용 ═══
# 날짜 기준 가격 전환 로직 금지(traps.md T19).
# Sonnet 5는 $2/$10이 정가로 확정됐고 2026-09-01 인상은 시행되지 않는다.
MONTHLY_COST_CEILING_USD = optional_env_int("MONTHLY_COST_CEILING_USD", 8)
DAILY_ANALYSIS_LIMIT = optional_env_int("DAILY_ANALYSIS_LIMIT", 20)

# 단가 ($/MTok). 2026-08-13 Anthropic 공식 pricing 페이지 실측 확인.
#   "The $2/$10 pricing for Claude Sonnet 5 ... is now the standard price.
#    The previously scheduled increase to $3/$15 on September 1, 2026 will not occur."
# → 참고 프로젝트의 날짜 기준 전환 로직이 틀렸다. 이식하지 않는다 (T19).
SONNET_INPUT_PER_MTOK = 2.0
SONNET_OUTPUT_PER_MTOK = 10.0
SONNET_CACHE_WRITE_PER_MTOK = 2.50  # 5분 캐시 쓰기 = 1.25× 입력
SONNET_CACHE_READ_PER_MTOK = 0.20  # 캐시 히트 = 0.1× 입력
HAIKU_INPUT_PER_MTOK = 1.0
HAIKU_OUTPUT_PER_MTOK = 5.0
HAIKU_CACHE_WRITE_PER_MTOK = 1.25
HAIKU_CACHE_READ_PER_MTOK = 0.10

# ═══ LLM 호출 ═══
ANALYSIS_MODEL = "claude-sonnet-5"  # PRD §5.1 L6 — 해석 전용
FALLBACK_MODEL = "claude-haiku-4-5"  # PRD §5.1 L2' — 잠정실적 규칙 파서 실패 시만
LLM_MAX_TOKENS = 8192  # stop_reason == "max_tokens"이면 명시적 실패 처리
# ★ Sonnet 5는 `thinking`을 생략하면 **적응형 사고가 켜진다**(실측 확인: 공식 마이그레이션
#   가이드). max_tokens는 사고 + 응답을 합친 상한이므로, 생략하면 8,192 안에서 사고가
#   출력 자리를 먹어 JSON이 잘린다. 해석 과제는 깊은 사고가 필요하지 않으므로 effort를
#   낮게 고정한다 — 이게 이 Phase 비용 설계의 일부다.
LLM_EFFORT = "low"
LLM_INPUT_TOKEN_BUDGET = 5000  # PRD §7.1 — 초과 시 호출하지 않는다

# ═══ DART ═══
DART_BASE_URL = "https://opendart.fss.or.kr/api"

# ═══ 데이터 시작 시점 (사용자 결정 2026-08-13) ═══
# 이보다 앞선 분기는 수집·저장하지 않는다.
# 2024.1Q 하한에서 계산 가능/불가 (t = 2026.2Q 기준):
#   ✓ G0·G1·G2 게이트 · TTM · A4(연속 가속) · rev_2y_stack
#   ✗ rev_2y(t) > rev_2y(t-1) — t-9(2024.1Q 이전)가 필요하다.
#     기저효과 경고 3조건 중 ①2년스택 가속이 빠지고 ②TTM 8분기 최고(11분기 필요)도
#     초기에는 불가. ③분기 최고 매출만 온전하다 (PRD §2 검토①).
#   하한을 낮추면 자동으로 복구된다.
DATA_START_YEAR = 2024
DATA_START_QUARTER = 1
DART_MULTI_ACNT_MAX_CORP_CODES = 100  # 규격상 상한: 쉼표로 최대 100개/콜
# ★ 실제 배치 크기는 100보다 작게 잡는다 (traps.md T24).
#   100개를 묶으면 응답이 커져 DART가 302 → error1.html로 리다이렉트하고,
#   follow_redirects 상태에서는 HTTP 200 + HTML이 돌아온다(에러가 아니다).
#   50이면 실측상 안전하며, 초과 시에는 수집기가 청크를 자동 분할한다.
DART_MULTI_ACNT_BATCH_SIZE = 50
REPRT_CODE = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}
#   11013 1분기보고서 : thstrm_amount = 3개월 단독
#   11012 반기보고서   : 6개월 누적    → Q2 = 반기 − Q1
#   11014 3분기보고서  : 3개월 단독 (+ 9개월 누적도 제공)
#   11011 사업보고서   : 12개월 누적   → Q4 = 연간 − 3Q누적

# ═══ KIS Open API ═══
KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
# ★ 문서·PRD는 "실전 초당 20건"이라고 하지만 **실측 1.8건/초에서도 EGW00201이 났다**
#   (1,112종목 순회 중 111종목 10%). 문서값을 믿지 말고 낮게 잡고, 재시도로 회복한다(T32).
KIS_RATE_LIMIT_PER_SEC = 8
KIS_TOKEN_CACHE_PATH = ".cache/kis_token.json"
KIS_TR_PRICE = "FHKST01010100"
KIS_TR_DAILY_CHART = "FHKST03010100"
KIS_ALLOWED_PATHS = (  # ★ 주문 API 호출 금지 — 클라이언트 내부에서 강제 차단
    "/oauth2/tokenP",
    "/uapi/domestic-stock/v1/quotations/inquire-price",
    "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
)

# ═══ 운영 ═══
SEASON_MODE = optional_env("SEASON_MODE", "off")  # 'on'이면 공시 폴링 15분 주기
KST = "Asia/Seoul"
POSTGREST_PAGE_SIZE = 1000  # max-rows 1,000 — 초과 테이블은 반드시 range() 페이징(T7)
