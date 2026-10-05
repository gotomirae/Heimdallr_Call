# JARVIS 설치 복구 — 2026-10-05

사용자 증상: HeimdallrKairosCollector만 Ready이고 HeimdallrKairosDeckRunner가 없었다.

## 수정

- install_jarvis.ps1을 UTF-8 BOM으로 저장해 Windows PowerShell 5.1의 한글 Drive 경로 오독을 해결했다.
- Python -c 중첩 따옴표 손실을 피하도록 claude_login.py를 만들고 설치기에서 파일로 실행한다. 로그인 검사 출력에는 계정 식별자·시크릿이 없다.
- pyproject.toml 패키지 검색에 telegram_bridge를 포함하고 실제 .venv editable 설치를 다시 실행했다.

## 실측

- 실제 Google Drive 분석 루트 접근 True, PowerPoint COM 등록 True.
- Claude loggedIn=True/authMethod=claude.ai, Pro 구독 확인. 생성 호출은 하지 않았다.
- 운영 DB 19개 테이블과 G 계약 컬럼 확인, 개인 테이블 anon 접근 차단 확인.
- 산업 aliases 28개, 미국 SEC 기업 7,679개, registry failures 0.
- Windows PowerShell 5.1로 수정된 설치기 종료 코드 0.
- HeimdallrKairosCollector/HeimdallrKairosDeckRunner 둘 다 Ready, 반복 PT1M.
- 수집기 LastTaskResult 0, queue collector.last_error 및 registry_error 빈 문자열.
- DeckRunner 실제 첫 실행 worker.json status=idle, checked_at=2026-10-05T13:39:31.877218+00:00.
- 프로젝트 .cache에서 src 및 telegram_bridge.deck_runner import 성공.
- DeckRunner LastTaskResult=0 (2026-10-05 22:40:55 KST), 두 작업 실제 성공 코드 0.
- 관련 회귀 91 passed (6.65초), git diff --check 통과.
- 테스트 Notion 페이지·운영 분석 요청·발표자료 생성 0건.

## 남은 검증

실제 JARVIS 기업/산업 버튼과 완료 후 발표자료 버튼의 종단 간 검증은 실제 사용자 요청으로 한다.
T252에 PowerShell 인코딩과 인수 전달 함정을 기록했다.
