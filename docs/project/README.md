# Auto-BIM 프로젝트 문서

세 레포(`autobim-model`, `autobim-be`, `autobim-fe`)에 걸친 **프로젝트 전체** 문서다. 백엔드 레포에 두는 이유는 API 계약이 여기 있고, 팀 전원이 접근할 수 있는 공개 레포이기 때문이다.

## 읽는 순서

| 누구 | 순서 | 시간 |
|---|---|---|
| 전원 | [ROADMAP](ROADMAP.md) → [TEAM_PROCESS](TEAM_PROCESS.md) → [DECISIONS](DECISIONS.md)의 O(미결) 항목 | 20분 |
| 백엔드 | [SYSTEM_SPEC](SYSTEM_SPEC.md) → [../recognition.md](../recognition.md) → [../next-tasks.md](../next-tasks.md) → [../deploy-oci.md](../deploy-oci.md) | 40분 |
| 프론트 | [`autobim-fe/docs/FRONTEND_SPEC.md`](https://github.com/Auto-BIM/autobim-fe/blob/develop/docs/FRONTEND_SPEC.md) → SYSTEM_SPEC §3.4·§3.5 → [../api.md](../api.md) | 30분 |
| 모델 | `autobim-model/docs/MODEL_SPEC.md`(연구실 서버) → SYSTEM_SPEC §3.1~§3.3·§5 → [EVALUATION_PLAN](EVALUATION_PLAN.md) | 30분 |
| 발표·시연 준비 | [EVALUATION_PLAN](EVALUATION_PLAN.md) → [DEMO_PLAN](DEMO_PLAN.md) → [RISKS](RISKS.md) | 15분 |

에이전트(Claude Code / Codex)에게 일을 줄 때는 [PROMPTS](PROMPTS.md)의 블록을 쓴다.

## 문서 목록

| 문서 | 내용 | 바꾸는 사람 |
|---|---|---|
| [ROADMAP.md](ROADMAP.md) | 범위(P0/P1/P2), 게이트·마일스톤, 주차별 계획, 역할 제안 | 항민(회의 결정 반영) |
| [SYSTEM_SPEC.md](SYSTEM_SPEC.md) | 구성 요소, 요청 흐름, 레포 간 계약(모델 번들·`autobim_seg`·어댑터·좌표), 시간·메모리 예산, 설정, 오류 | 계약 변경 시 |
| [DECISIONS.md](DECISIONS.md) | 확정(D)·제안(P)·미결(O) | 누구나(회의 후) |
| [RISKS.md](RISKS.md) | 위험, 신호, 대응, 대체 수단 | 누구나 |
| [TEAM_PROCESS.md](TEAM_PROCESS.md) | 주간 리듬, GitHub 설정, PR 규칙, 완료 정의, 에이전트 사용 규칙 | 팀 합의 |
| [EVALUATION_PLAN.md](EVALUATION_PLAN.md) | 모델·시스템·실행·출력·정성 평가와 보고 표 | 항민·임준형 |
| [DEMO_PLAN.md](DEMO_PLAN.md) | 시연 시나리오, 대체 수단, 체크리스트 | 전원 |
| [PROMPTS.md](PROMPTS.md) | 작업별 에이전트 프롬프트 | 이슈를 만드는 사람 |
| [../recognition.md](../recognition.md) | 인식 v1 알고리즘(마스크 → 벽·개구부 → Plan) | 조예준 |
| [../deploy-oci.md](../deploy-oci.md) | OCI A1 배포 런북 | 항민 |
| [../next-tasks.md](../next-tasks.md) | 백엔드 이슈 범위·완료 조건(원본) | 이슈 담당 |

## 용어

| 용어 | 뜻 |
|---|---|
| **Plan** | 인식 결과의 중간 표현(JSON, mm, y 위). 벽(중심선·두께·높이·종류), 개구부(붙은 벽·위치·폭·높이), 확인 필요 항목, 축척. 정의 `app/schemas/plan.py` |
| **작업(Job)·리비전** | 업로드 한 건이 작업 하나. 보충 입력마다 `revision`이 1 늘고, `result_revision`은 마지막으로 성공한 리비전 |
| **보충 입력(supplement)** | 사용자가 축척·수정·삭제·추가·확인을 보내는 것. 모델을 다시 돌리지 않고 기준 Plan에 다시 적용한다 |
| **확인 필요 항목(review item)** | 신뢰도가 낮거나 추정한 값이라 사람이 봐야 하는 요소 |
| **모델 번들** | 모델 레포가 내보내는 폴더 `seg-vN/`: `model.onnx`, `model.json`, `pkg/autobim_seg/`, `SHA256SUMS`, `MODEL_CARD.md` |
| **`autobim_seg`** | 모델 레포의 추론 패키지. `predict(image)` → `labels`(0~3), `openings()` |
| **seg 어댑터** | 백엔드가 `autobim_seg` 결과를 `WallMask`·`OpeningDetection`으로 바꾸는 코드(#5) |
| **Fake 모델** | 입력과 상관없이 고정된 도면을 돌려주는 가짜 모델. 테스트·프론트 개발용 |
| **replay 어댑터·평가 팩** | 평가 팩(이미지 + 정답·예측 마스크)에서 마스크를 꺼내 모델 대신 쓰는 개발·평가용 어댑터(BE-N2) |
| **인식 v1** | 마스크 → 축 정렬 벽·개구부 → Plan 후처리(BE-N1) |
| **배율(scale)** | 추론 전에 이미지를 줄이는 비율(기본 0.5). 학습도 같은 배율 |
| **타일** | 큰 이미지를 1024×1024 조각으로 나눠 추론한다. 겹침 256 px |
| **`t_med`** | 도면에서 잰 대표 벽 두께(px). 인식 v1의 모든 임계값 기준 |
| **APT100 / unseen / tune** | 최종 평가 100장 / 그중 처음 보는 도면 / 모델 선택용 검증 세트 |
| **G0~G4, M1~M4** | 게이트(통과 못 하면 다음 단계 불가) / 마일스톤(눈에 보이는 결과) |
| **P0 / P1 / P2** | 없으면 시연 불가 / 품질 / 여유가 있을 때만 |
