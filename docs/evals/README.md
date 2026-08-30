# LLM Provider offline replay eval

`src.analysis.eval_run`은 같은 `AnalysisInput`에서 이미 생성해 저장한 후보 payload를
결정론적으로 비교한다. 외부 API·DB·Provider SDK·LLM judge를 호출하지 않는다.

## 실행

```bash
python -m src.analysis.eval_run path/to/suite.json
python -m src.analysis.eval_run path/to/suite.json --output report.json
python -m src.analysis.eval_run path/to/suite.json \
  --canary-result path/to/completed-canary.json --candidate-id attempt-3 \
  --output report.json
```

suite의 각 case에는 다음이 필요하다.

- `input`: `AnalysisInput` 전체. 특히 `as_of`가 없으면 시간 평가를 거부한다.
- `evidence_anchors`: 그 사례에서 놓치면 안 되는 핵심 사실. 각 anchor는 표기 `aliases`뿐
  아니라 투자판단 `dimension`과 실제로 근거가 있어야 할 출력 `paths`를 갖는다.
- `candidates`: Provider·모델·payload·실측 비용과 호출 당시 `request_snapshot`,
  `request_sha256`, `input_sha256`. 비용을 모르면 `cost_usd`를 생략한다.
- `synthetic`: 합성 fixture면 반드시 `true`. 이 경우 승자를 선언하지 않는다.

평가 축과 임계값의 유일한 출처는 `src/config/constants.py`다. 총점 외에도 스키마 오류,
입력에 없는 사실 숫자, 과거/범위 밖 트리거는 하드 실패다. 비용 미측정은 `None`, 실제
비용 초과는 `False`로 구분한다.

근거 커버리지는 `improvement · sustainability · price_reflection · catalyst · risk` 다섯
영역으로 나눠 출력한다. 전체 75% 이상이어도 한 영역이 50% 미만이면 품질 실패다. suite의
`casebook_coverage.ready`는 실제 사례가 최소 4건, 3개 업종, `★/○ × 컨센서스 유/무` 네 셀,
턴어라운드와 비턴어라운드 가속화를 모두 포함할 때만 `true`다. Provider 비교 가능 여부와
사례집 대표성은 별도 판정이다.

HJ중공업 Attempt3을 이 계약으로 재평가한 고정 결과는
`results/hj-097230-2026q2-openai-terra-attempt-3-investment-eval.json`이다. 기존 90점 기록은
당시의 평면 anchor rubric 감사 결과로 보존하며, 새 92.14점을 모델 개선으로 비교하지 않는다.

실제 사례를 늘리는 외부 read 계획은 `casebook-read-plan.md`에 있다. 후보 metadata 2 GET과
선택된 3종목 replay 예상 27 GET을 별도 승인으로 나누며, Stage A 승인으로 Stage B나 Provider를
호출하지 않는다. 선택 로직은 `src.analysis.casebook_selection`의 순수 함수라 DB 행 순서와 무관하다.
Stage B는 실제 27 GET으로 엘앤씨바이오·롯데정밀화학·한화시스템 replay 3/3을 준비했다.
이 파일들은 입력 사례일 뿐 Provider 품질 결과가 아니며, 생성 호출은 여전히 별도 승인이다.
사람 대조가 끝난 4종목 anchor 계약은 `suites/investment-casebook-2026q2.json`에 있다.
대표성은 `ready=true`지만 Provider 후보는 의도적으로 비어 있다. 과거 exact candidate를 다른
JSON runtime으로 재직렬화하면 숫자 표기 변화로 hash가 깨질 수 있어 원본 canary 결과에서만
주입한다(T119). 계획 파일은 `plans/*openai-terra.json`과 `plans/*anthropic-sonnet5.json`이며,
각 plan hash는 실제 호출 직전에 다시 계산해 일치해야 한다.
2026-08-29 승인 실행 결과는 세 종목 모두 paid response를 받았지만 숫자 grounding gate에서
차단됐다. 실패 결과도 raw payload가 있으면 `--canary-result`로 평가할 수 있고, 옵션을 여러 번
지정하면 같은 사례집의 여러 canary를 한 보고서로 묶는다. `execution_status=failed`인 후보는
점수·비용을 보여도 canary 적격이나 Provider 비교 후보가 아니다.
Anthropic 4건도 같은 방식으로 실행했으며 실제 비용은 **$0.263351**, 품질 통과 **0/4**다.
두 Provider 통합 보고서는 `results/investment-casebook-2026q2-provider-comparison-eval.json`이다.
정상 동일 단위 표시 반올림 오탐을 제거한 평균은 OpenAI 84.64, Anthropic 46.07이지만
실행 실패와 HJ 계약 불일치 때문에
`comparison_ready=false`다. 여러 결과를 주입할 때 같은 case의 기존 Provider를 덮어쓰던
결함은 T122 회귀 검사로 막았다.
숫자 자체감사 프롬프트의 재검증 계획은
`plans/004000-2026q2-anthropic-sonnet5-numeric-audit.json`이다. 입력 replay는 이전과 같고
request hash만 바뀌었다. 승인 실행 결과는
`results/004000-2026q2-anthropic-sonnet5-numeric-audit.json`, 평가와 baseline 대조는 각각
`*-numeric-audit-eval.json`과 `*-numeric-audit-comparison.json`이다. 결과가 악화돼 이
프롬프트는 폐기했으며 현재 request/plan hash는 baseline으로 복구했다(T124).

사실 숫자 검사는 `src.analysis.numeric_grounding` 한 구현을 offline eval과 운영 저장 경계가
공유한다. 과거/현재 사실 필드에서 request에 같은 단위로 없는 숫자는 저장하지 않는다.
시나리오·리스크의 미래 관측 임계값은 투자 판단이므로 이 gate의 대상이 아니다.
2026-08-30 롯데 fact-ref v2는 숫자 오류 0건이었지만 `placeholder` 11곳과 빈 트리거로
실패했다. 운영 저장과 offline eval은 `src.analysis.schema_validation`의 재귀 schema+filler
검사도 공유하며, strict JSON의 형식 성공을 내용 품질 성공으로 간주하지 않는다(T125).
medium-effort 후속은 filler가 사라졌지만 `F106/F107/F124`의 원문값을 억원으로 바꿔
63.57점·unsupported 5건으로 실패했다. 세 fact-ref canary 모두 quality=false이므로 실험 계약은
운영 `analyze()`에서 비활성이고 canary plan에서만 명시적으로 켠다.

## 실제 Provider 비교가 성립하는 조건

1. 모든 Provider가 정확히 같은 replay case를 사용한다.
2. 시스템 프롬프트·사용자 메시지·JSON Schema·웹 검색 설정이 같다.
3. 모든 case에 비교 대상 Provider가 각각 정확히 한 번 존재한다.
4. synthetic가 `false`이고, 실측 payload를 수정하거나 사람이 보완하지 않는다.
5. 동점이거나 사례 집합이 다르면 승자를 만들지 않는다.
6. 각 후보의 snapshot/hash가 유효하고, 모델 ID만 제외한 request 계약 hash가 같다.

평가기는 저장 snapshot의 user message와 JSON Schema만 사용한다. snapshot이 없는 과거 후보는
최신 builder로 참고 점수만 계산하며 `request_replay_exact=false`라 canary 적격이나 Provider
비교에 쓰지 않는다. 과거 요청을 최신 코드로 소급 생성해 snapshot인 것처럼 붙이지 않는다(T111).

`--canary-result`는 완료된 단건 결과를 suite의 후보로 주입한다. suite와 결과의 replay 값이
다르면 거부하며, `28000`과 `28000.0`처럼 JSON 표현만 다른 같은 숫자는 허용한다. 실제 평가는
canary 결과에 저장된 정확한 입력 직렬화·request snapshot·hash를 사용한다.

## 승인 전 단건 canary 기준

- 범위: 대표 종목 1건, 웹 검색 OFF, OpenAI는 `store=false`, 분석 DB 저장 없음.
- 비용 하드캡: `$0.15`. 모델명과 공식 단가가 먼저 확정돼야 한다.
- 품질: 80점 이상, 핵심 근거 75% 이상, 하드 실패 0건.
- 실행 전 보고: 정확한 모델, token-count/생성 endpoint, 예상 호출 수와 비용, 외부 상태 변화.

이 문서는 실행 승인이 아니다. 유료 생성과 외부 쓰기는 사용자의 명시적 승인 뒤에만 한다.

OpenAI의 정확한 모델·단가·엔드포인트·비용 계산은
[`openai-canary-plan.md`](openai-canary-plan.md)를 따른다. 공통 CLI plan v2는 Provider를
승인 hash에 포함하며 OpenAI와 Anthropic 모두 SDK 자동 재시도를 0으로 고정한다.

승인된 canary의 입력 준비·exact 계획·호출은 서로 다른 명령이다. `prepare`는 저장된
Supabase 값만 필터 조회하고, `plan`은 외부 호출 없이 request/pricing/cap hash를 만든다.
`call`은 로컬 replay만 읽으며 승인된 동일 `plan_sha256`과 명시적 승인 플래그가 필요하다.

```bash
python -m src.analysis.canary_run prepare --code 097230 --quarter 2026.2 --output replay.json
python -m src.analysis.canary_run plan --input replay.json --output openai-plan.json
python -m src.analysis.canary_run call --input replay.json --output openai-result.json \
  --approved-plan-sha256 <승인한-plan-sha256> --execute-approved-canary

python -m src.analysis.canary_run plan --provider anthropic --input replay.json \
  --output anthropic-plan.json
python -m src.analysis.canary_run call --provider anthropic --input replay.json \
  --output anthropic-result.json --approved-plan-sha256 <승인한-plan-sha256> \
  --execute-approved-canary
```
