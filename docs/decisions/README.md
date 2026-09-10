# 설계 결정 기록 (ADR)

**되돌리면 안 되는 결정**만 여기에 `NNN-제목.md`로 남긴다.

기존 ADR 1~8은 `CLAUDE.md`의 "되돌리면 안 되는 설계 결정" 절에 요약되어 있고,
근거는 `docs/PRD.md` §2(v1 설계 검토 결과)에 있다.

| # | 결정 | 근거 |
|---|---|---|
| 1 | 게이트는 "실적 가속" — 컨센서스 서프라이즈가 아니다 | PRD §2 (코스닥 59.9%가 리포트 0건) |
| 2 | 컨센서스 없는 종목의 C축은 0점이 아니라 분모 제외 정규화 | PRD §4.2 · SC6 |
| 3 | 선별 단계에 LLM을 쓰지 않는다 | PRD §5.1 |
| 4 | LLM 입력에 공시 원문 전체를 넣지 않는다 | PRD §7.1 |
| 5 | PRI를 스코어에 합산하지 않는다 (2축 병기) | PRD §2 검토 ④ |
| 6 | 모든 테이블의 앵커는 `code` — watchlist 개념 없음 | PRD §6 |
| 7 | QoQ를 점수에 쓰지 않는다 (TTM 추세로 대체) | PRD §2 검토 ② |
| 8 | Supabase는 HermesCall과 분리된 신규 프로젝트 | PRD §6 · traps.md T16 |
| 9 | LLM Provider SDK를 분석 도메인에서 분리하고 자동 폴백하지 않는다 | [`009-provider-neutral-llm-layer.md`](009-provider-neutral-llm-layer.md) |
| 10 | LLM 사실 숫자 참조는 canary 전용으로 검증하며 운영 기본에는 승격하지 않는다 | [`010-llm-factual-number-references.md`](010-llm-factual-number-references.md) |
| 11 | LLM은 잠정·정기보고서·5거래일 최종갱신의 세 이벤트에만 연다 | [`011-event-driven-three-stage-analysis.md`](011-event-driven-three-stage-analysis.md) |
| 12 | 미근거 사실 숫자는 토큰만 제거하고 정성 해석은 보존한다 | [`012-redact-unsupported-factual-numbers.md`](012-redact-unsupported-factual-numbers.md) |
| 13 | 3단계는 최근 10일 리포트를 웹검색하고 지정 텔레그램 2곳을 우선한다 | [`013-broker-report-web-search.md`](013-broker-report-web-search.md) |
| 14 | PRI 3.0은 성장 정당화·상승 원인·성장단가·과열을 8축으로 측정한다 | [`014-pri-3-growth-price-decomposition.md`](014-pri-3-growth-price-decomposition.md) |
| 15 | 기업 투자 매력도 스코어를 7축으로 확장하고 현재 가격은 PRI로 분리한다 | [`015-current-investment-attractiveness-score.md`](015-current-investment-attractiveness-score.md) |

새 ADR을 쓸 때는 **무엇을 / 왜 / 되돌리면 무엇이 무너지는가**를 반드시 포함한다.
