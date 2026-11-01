# 2026-11-01 — ADR50 Pro 전용 운영 전환

## 구현과 보존

사용자 최종 요구: 국내 분기실적 자동 정량 발굴, 한국 평일 16시 변동 지표 갱신(한국 공휴일 제외), 시즌 공시 2시간, 기업 포함 고정 내용은 분석 버튼만. 과거 분기도 ChatGPT Pro 로그인 Codex 순차 처리. API/Batch/추가 크레딧 자동 구매 금지. Codex 작성→검수→게시, PPT는 요청만.

Python 휴일/일일 완료/공시 슬롯 게이트, private pro_analysis_jobs RPC 큐, 현재 우선/과거 후순위, 동일 근거 해시 재사용, 명시적 강제 재분석, 단계/세션/게시 체크포인트와 살아 있는 CLI 중복 방어를 구현했다. Provider 명시 인자로도 API SDK를 활성화하지 못한다. 자식 프로세스 API 키·기반 URL을 제거하고 ChatGPT 로그인 방식을 강제한다.

원자료와 고정 게시 내용을 분리했다. 고정 snapshots와 daily indicators 테이블은 service_role만 허용한다. 대시보드 서버는 기존 화면에 필요한 필드만 반환한다. 상세 페이지 시세 조회는 원천 직접 호출 대신 저장본만 읽는다. 신규 공시는 원자료·정량 결과와 갱신 필요 표시만 변경한다. 과거 보충은 현재 고정 스냅샷을 덮어쓰지 않는다. 매크로 숫자 확인 시각과 기존 해설 기준일을 구분한다.

Telegram 이름/코드 입력 후 분석 버튼 승인, 기존 요청 ID·전체 템플릿·출처·파일 해시·gap 검수·Notion 전체 재조회 규칙을 보존했다. 기존 sent 결과와 완성 PPT는 재처리하지 않았다. DB의 claude 등 기존 내부 상태명은 호환을 위해 유지하지만 실행 경로는 Codex이다.

## 실제 확인

- 정확한 Supabase 프로젝트 drpxciqkbjlruximqbox(Heimdallr-Call). 다른 Hermes 프로젝트 변경 0.
- private 큐 생성 후 대기 0건. 고정 baseline 1,446기업·11,101분기.
- SK하이닉스 2026-10-30 기준 일봉729개·수급729개, quote 정상·incomplete false.
- 실제 모든 원격/로컬 큐0을 확인한 뒤 새 통합 실행 idle/model_calls0.
- 실제 Codex ChatGPT 인증 smoke JSON 1건, 입력26,761/출력15토큰, 도구호출0. 구독 사용량이며 API 달러로 환산하지 않음.
- 전체 pytest UTF-8: 1,465 passed/3 skipped, 68.20초. 앞선 기본 인코딩 실패1건은 테스트 파일 쓰기에 UTF-8을 명시하여 수정.
- 대시보드 프로덕션 빌드12/12, 새 /api/pro-analysis 포함.
- 깨끗한 venv pip install -e . 후 프로젝트 루트 밖 import 성공: CodexSubscriptionProvider/gpt-6.1-sol.
- 실제 금융 분석 생성·Notion 시험 게시·PPT·Telegram 시험 발송0. 지표 초기 이관은 무료 원천의 마지막 실제 거래일을 저장하는 배포 기준선이며 정기 주말 갱신이 아님.

## 예약 교체 승인과 적용

기존 kairos-intake 일시중지는 자동 승인 검토가 명시적 승인을 요구하여 보류했다. 새 실행기를 비활성 등록하고 실제 빈 큐 검증을 마친 뒤 사용자에게 구체적 교체 범위를 제시했다. 사용자가 “승인: 기존 예약을 중지하고 새 Pro 실행기로 교체”로 명시 승인했다.

공식 automation_update로 kairos-intake PAUSED. Windows HeimdallrDashboardAnalysis/KairosDeckRunner 비활성·실행 중 인스턴스 중지. HeimdallrProAnalysisRunner 활성, 기존 TelegramListener/KairosCollector 활성 보존. 전환 직후 잠금 경합1회(CODEX_BUSY/model_calls0) 뒤 실제 idle/model_calls0/notifications sent0·watched0를 확인했다. 우회 파일 편집으로 자동화를 끄지 않았다.

새 snapshot anon SELECT는 자동 검토에서 과도한 공개 권한으로 거절되어 public 정책 없이 private service_role 전용으로 수정·적용했다. 큐 처리 smoke도 먼저 모든 대기0건을 증명하고 조건부 실행으로 해결했다.

## 비용과 사용 시간

기존 Pro 제외 월38,600원(100W PC 하루4시간) 또는56,600원(24시간)은 Supabase $25×환율1,400원·전력300원/kWh 가정이며 실청구가 아니다. API/Batch·자동 크레딧 구매0. Pro 실제 요금과 추가 compute/egress/호스팅 과금은 별도. 클라우드16시 지표, PC18시 이후 분석을 기본 권장한다. 과거 분기는 구독 잔량·갱신주기에 따라 길어지며 투자 수익 극대화는 검증된 결과가 아니다.

## 배포 검증 (후속 실측 추가)

원격 main의 추가78커밋이 자동 macro/season JSON 두 파일뿐임을 확인하고 ff-only 통합했다. 이전 미커밋 파일 인계/출처 계약은 삭제하지 않고 필수 런타임 의존성으로 보존했다. 배포·cron과 초기 전수 저장 최종 수치는 아래 추가 기록을 따른다.
