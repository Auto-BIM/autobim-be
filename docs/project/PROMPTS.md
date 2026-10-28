# 에이전트 프롬프트 모음 (Claude Code / Codex)

> 이슈 하나 = worktree 하나 = 세션 하나. 아래 블록을 그대로 붙여 넣고 `<…>`만 바꾼다.
> 프롬프트는 명세 문서를 **가리키기만** 한다. 세부 내용은 에이전트가 문서에서 읽는다(컨텍스트를 작게 유지).
> 공통 규칙은 각 레포의 `AGENTS.md`에 있으므로 반복하지 않는다. 비밀값은 절대 붙여 넣지 않는다.

## 목차

| 키 | 대상 | 레포 | 누가 |
|---|---|---|---|
| P0-1 | 이 문서 묶음 반영 | autobim-be | 항민 |
| P0-2 | GitHub 정리(라벨·마일스톤·이슈) | autobim-be, autobim-fe | 항민 |
| P0-3 | 모델 레포 문서·벤치 스크립트 반영 | autobim-model | 항민 |
| P0-4 | 프론트 레포 부트스트랩(FE-1) | autobim-fe | 강민재 |
| BE-N1, #2, BE-N2, BE-N3, #5, BE-N4, #7, #6, BE-N5, BE-N6 | 백엔드 이슈 | autobim-be | 담당 |
| ML-0a/0b, ML-2, ML-4, ML-5, ML-6 | 모델 작업 | autobim-model | 항민 |
| FE-2~8, FE-5, FE-P1 | 프론트 이슈 | autobim-fe | 담당 |

---

## P0-1 문서 묶음 반영 (autobim-be)

```text
[작업] Auto-BIM 프로젝트 문서 묶음을 autobim-be에 반영하고 develop 대상 PR을 만든다.
[번들 경로] <BUNDLE>/autobim-be   (예: ~/Downloads/autobim-docs/autobim-be)

1. git fetch origin && git switch develop && git pull --ff-only
2. PR #8(docs(next-tasks): align #5 and #6 …)이 아직 열려 있으면 멈추고 나에게 묻는다:
   "#8을 먼저 머지할까요, 이 PR이 대체하므로 닫을까요?" 답을 받은 뒤 진행한다.
3. git switch -c feature/project-docs
4. 번들의 파일을 같은 경로로 복사한다(덮어쓰기):
   - docs/project/*.md (새 폴더), docs/recognition.md, docs/deploy-oci.md, docs/next-tasks.md
   - docs/recognition-prototype/ 폴더 전체 (인식 v1 참고 구현, BE-N1 이식 후 삭제 예정)
   - AGENTS.md, README.md
   그 밖의 파일은 바꾸지 않는다. 앱 코드(app/), 테스트, 계약 파일은 건드리지 않는다.
5. 검사: pytest -q / ruff check . / python scripts/export_openapi.py --check /
   test "$(cat CLAUDE.md)" = "@AGENTS.md"
   ruff가 docs/recognition-prototype에서 실패하면 import 정렬만 `ruff check --fix`로 고친다(로직 변경 금지).
6. 문서 안의 상대 링크가 실제 파일을 가리키는지 확인한다(깨진 링크 목록을 PR 본문에).
7. 커밋: "docs: project roadmap, system spec, recognition v1 and OCI deploy specs"
   push 후 develop 대상 PR. 본문에 문서 목록과 "DECISIONS.md의 P(제안)·O(미결) 항목은 킥오프에서 확정"이라고 적는다.
   AGENTS.md 규칙 2 문구 변경(P-10)이 들어 있음을 본문에 따로 적는다. 머지는 하지 않는다.
```

## P0-2 GitHub 정리 (라벨 · 마일스톤 · 이슈)

```text
[작업] Auto-BIM/autobim-be와 Auto-BIM/autobim-fe의 GitHub 이슈를 docs 기준으로 정리한다. gh CLI를 쓴다.
[원본] autobim-be: docs/next-tasks.md, docs/project/TEAM_PROCESS.md §3 / autobim-fe: docs/backlog.md
       (autobim-fe 문서가 아직 레포에 없으면 <BUNDLE>/autobim-fe/docs/backlog.md를 읽는다)

1. 두 레포에 라벨 생성(이미 있으면 건너뜀): P0, P1, P2, area:be, area:fe, area:model, area:deploy, contract, blocked
2. 두 레포에 마일스톤 생성(due_on은 그날 23:59:59 +09:00):
   "M1 끝까지 한 번" 2026-11-08 / "M2 실제 경로" 2026-11-15 / "M3 기능 완료" 2026-11-29 /
   "M4 코드 완성" 2026-12-06 / "v1.0 동결" 2026-12-11
3. autobim-be 새 이슈: BE-N1~BE-N6. 제목은 next-tasks.md 절 제목에서 "(P0)" 같은 표시를 뺀 것,
   본문은 그 절 전체 + 맨 아래 "원본: docs/next-tasks.md". 라벨·마일스톤:
   BE-N1 P0,area:be → M2 / BE-N2 P0,area:be → M1 / BE-N3 P0,area:be,contract → M1 /
   BE-N4 P0,area:be → M2 / BE-N5 P1,area:be → M3 / BE-N6 P1,area:be → M2
4. 기존 이슈: #5·#6·#7 본문을 next-tasks.md의 해당 절로 교체(gh issue edit --body-file).
   라벨·마일스톤: #2 P0 → M1 / #5 P0 → M1 / #7 P0,area:deploy → M1 / #6 P1 → M3 / #3 P2 / #4 P2(마일스톤 없음)
5. autobim-fe: backlog.md의 FE-1~FE-14로 이슈 생성. 제목 "FE-n …", 본문은 해당 절.
   P0(FE-1~8) → M1, P1 → M3, P2 → 없음. 라벨 area:fe + 등급.
6. 만든 이슈 번호 표(키 → 번호)를 출력한다.
7. autobim-be에서 feature/issue-numbers 브랜치: docs/의 "BE-N1"~"BE-N6" 키를 실제 번호와 함께 쓰도록
   바꾼다(예: "BE-N1" → "#12 (BE-N1)"). 커밋·PR. 머지는 하지 않는다.
담당자(assignee)는 지정하지 않는다(킥오프에서 사람이 정한다).
```

## P0-3 모델 레포 반영 (연구실 서버, autobim-model)

```text
[작업] autobim-model에 새 문서와 G1 벤치 스크립트를 반영한다. GitHub에는 올리지 않는다(로컬 커밋만).
[번들 경로] <BUNDLE>/autobim-model

1. git status가 깨끗한지 확인. 아니면 멈추고 알린다.
2. git switch -c feature/model-spec
3. 복사: AGENTS.md(새 파일), CLAUDE.md(내용을 정확히 "@AGENTS.md" 한 줄로 교체 — 기존 내용은 AGENTS.md로 옮겨져 있다),
   docs/MODEL_SPEC.md, docs/MODEL_CARD_TEMPLATE.md, docs/backlog.md, scripts/bench_cpu.py
4. .gitignore에 runs/, releases/, evalpacks/, bench_models/, data/processed_*/ 가 없으면 추가한다.
5. python scripts/bench_cpu.py --help 가 동작하는지만 확인한다(내보내기는 아직 하지 않는다).
6. 커밋: "docs: model spec, backlog and cpu benchmark for serving on OCI A1". 머지는 내가 한다.
```

## P0-4 프론트 레포 부트스트랩 (FE-1)

```text
[작업] 빈 레포 Auto-BIM/autobim-fe를 시작한다. FE-1의 범위와 완료 조건: <BUNDLE>/autobim-fe/docs/backlog.md
[번들 경로] <BUNDLE>/autobim-fe

1. 첫 커밋(예외적으로 main에 직접): README.md 한 줄 "Auto-BIM 프론트엔드" → push.
   develop 브랜치를 만들어 push하고, `gh repo edit --default-branch develop`.
2. develop에서 feature/1-scaffold 브랜치.
3. 번들의 AGENTS.md, CLAUDE.md(정확히 "@AGENTS.md"), docs/FRONTEND_SPEC.md, docs/backlog.md 복사.
4. docs/FRONTEND_SPEC.md §2·§6·§8대로 Vite + React + TypeScript 스캐폴드, 의존성 설치, 프록시, ESLint·Prettier·Vitest,
   스크립트(dev, build, lint, typecheck, test, gen:api), .gitignore(dist/, public/demo/).
5. .github/workflows/ci.yml: Node 22, npm ci, lint, typecheck, test, build.
6. 로컬 확인 후 커밋·push, develop 대상 PR. 머지는 사람이 한다.
```

---

## BE-N1 인식 v1 (조예준)

```text
[작업] BE-N1 인식 v1 — GitHub 이슈 #<번호>
[읽을 것] AGENTS.md, docs/recognition.md 전체, docs/next-tasks.md의 BE-N1 절, docs/recognition-prototype/*.py
[할 일] recognition.md §8 이식 가이드대로 프로토타입을 app/recognition/으로 옮긴다.
 - PixelWall의 기존 필드·메서드 유지, OpeningDetection(계약)은 그대로 사용
 - pipeline._classify → R7, pipeline._attach_openings → R9, 개구부 위치·폭·기본값 규칙은 §4, 확인 항목은 §5
 - Params → RecognitionSettings, config/settings.yaml recognition: 에 기본값
 - scipy 의존성 추가 후 lock 두 개 재생성(AGENTS.md 명령)
 - 합성 테스트를 tests/synthetic_plans.py + tests/test_recognition.py로 옮긴다(§6 표 전부)
 - scripts/debug_overlay.py (§7)
 - 이식이 끝나면 docs/recognition-prototype/ 삭제
[지킬 것] next-tasks.md의 "건드리는 폴더"만. 기존 tests/test_recognition.py는 수정 없이 통과해야 한다. 계약 변경 금지.
[끝나면] pytest -q, ruff check ., export_openapi --check 통과 → feature/<번호>-recognition-v1 → PR(완료 조건 체크리스트).
```

## #2 접합부 (조예준)

```text
[작업] 이슈 #2 Plan → 3D/.dxf 접합부·개구부
[읽을 것] AGENTS.md, docs/next-tasks.md의 #2 절, docs/design.md §5, app/geometry/walls.py, app/export/
[할 일] #2 절의 "할 일"과 "완료 조건"을 그대로 구현한다. 접합부 판정은 "끝점이 다른 벽의 중심선 위(허용 1 mm)"로 한다
       (인식 v1이 끝점을 중심선에 맞춘다). 규칙은 결정적이어야 한다(같은 Plan → 같은 메시).
[지킬 것] app/geometry/, app/export/, tests/test_geometry.py, tests/test_end_to_end.py만. Plan·API 변경 금지.
[끝나면] 검사 통과 → feature/2-junctions → PR.
```

## BE-N2 replay 어댑터 (조예준)

```text
[작업] BE-N2 replay 어댑터 — 이슈 #<번호>
[읽을 것] AGENTS.md, docs/next-tasks.md의 BE-N2 절(평가 팩 형식 포함), docs/project/SYSTEM_SPEC.md §3.3, app/models/
[할 일] 절의 "할 일"과 "완료 조건". 팩은 테스트에서 tmp_path에 코드로 만든다(PIL로 PNG, JSON).
       sha1은 app/preprocess/image.load_image 결과의 tobytes()로 계산한다.
[지킬 것] 건드리는 폴더만. app/models/base.py(계약) 변경 금지. 팩·이미지 커밋 금지.
[끝나면] 검사 통과 → feature/<번호>-replay-adapter → PR.
```

## BE-N3 계약 PR C1 (항민)

```text
[작업] BE-N3 계약 PR — 이슈 #<번호>. 이 PR은 계약 담당 PR이다.
[읽을 것] AGENTS.md(규칙 2), docs/next-tasks.md의 BE-N3 절, docs/project/SYSTEM_SPEC.md §7·§8, docs/api.md
[할 일] 413(file_too_large, image_too_large), 디코딩 불가 이미지 415, /health 필드, limits 설정·환경변수,
       API_VERSION 0.2.0, docs/openapi.json 재생성(python scripts/export_openapi.py), docs/api.md 갱신.
       픽셀 수는 PIL Image.open으로 헤더만 읽어 판단한다(전체 디코딩 금지). SCHEMA_VERSION은 그대로.
[완료 조건] 절의 체크리스트 + 기존 테스트 무수정 통과.
[끝나면] feature/<번호>-contract-c1 → PR 제목에 [contract]. 머지 후 프론트에 gen:api 요청.
```

## #5 seg 어댑터 (항민)

```text
[작업] 이슈 #5 seg 어댑터 (autobim_seg 번들)
[읽을 것] AGENTS.md, docs/next-tasks.md의 #5 절, docs/project/SYSTEM_SPEC.md §3.1~3.3·§6, app/models/
[할 일] app/models/seg.py(SegModel: WallSegmenter + OpeningDetector, 이미지 is 비교 캐시, Lock),
       registry "seg"(두 역할이 같은 인스턴스), settings models.seg.bundle_dir·threads + 환경변수,
       번들·버전 불일치 시 시작 실패, optional extra seg + requirements-seg.lock, Dockerfile ARG EXTRAS,
       cubicasa 자리표시 제거(관련 테스트 정리), README에 번들 받는 법.
       테스트는 sys.modules에 가짜 autobim_seg를 끼워 넣어 predict 호출 횟수를 센다.
[지킬 것] 기본 pytest는 onnxruntime·torch를 import하지 않는다. app/models/base.py 변경 금지.
[끝나면] 검사 통과 → feature/5-seg-adapter → PR.
```

## BE-N4 서빙 안정화 (조예준)

```text
[작업] BE-N4 서빙 안정화 — 이슈 #<번호>
[읽을 것] AGENTS.md, docs/next-tasks.md의 BE-N4 절, docs/project/SYSTEM_SPEC.md §9, app/jobs/, app/preprocess/
[할 일] 절의 "할 일". 세마포어를 잡기 전에는 상태를 queued로 둔다(runner에서 running 전환 위치 조정).
       느린 가짜 모델(threading.Event로 제어)로 동시성 테스트를 결정적으로 만든다(sleep 금지).
[지킬 것] 건드리는 폴더만. API 형식 변경 금지(필요하면 멈추고 알린다).
[끝나면] 검사 통과 → feature/<번호>-serving-hardening → PR.
```

## #7 OCI 배포 (항민)

```text
[작업] 이슈 #7 OCI 배포
[읽을 것] AGENTS.md, docs/next-tasks.md의 #7 절, docs/deploy-oci.md 전체
[할 일] deploy-oci.md §5의 파일을 deploy/에 만든다(docker-compose.prod.yml, Caddyfile, .env.example, smoke.sh, deploy.sh, README.md).
       .gitignore에 deploy/.env. 셸 스크립트는 shellcheck로 검사(가능하면). compose는 `docker compose -f deploy/docker-compose.prod.yml config`로 검사.
       CI의 기존 잡은 그대로 두고, 선택으로 smoke.sh를 기존 docker 잡에서 실행한다.
[지킬 것] 비밀값·IP·도메인을 파일에 넣지 않는다(.env.example에는 자리표시만).
[끝나면] feature/7-deploy → PR. 실제 OCI 반영은 사람이 deploy-oci.md §6대로 한다.
```

## #6 Plan 단위 시스템 평가 (임준형)

```text
[작업] 이슈 #6 Plan 단위 시스템 평가
[읽을 것] AGENTS.md, docs/next-tasks.md의 #6·BE-N2 절, docs/project/EVALUATION_PLAN.md §3·§4, app/recognition/(읽기만)
[할 일] eval/ 패키지: replay로 gt·pred 두 번 인식 → 지표(렌더 벽 IoU, 길이 오차, 개구부 P/R/F1·위치·폭, 성공률, 확인 항목 수)
       → summary.json, per_image.csv. CLI python -m eval.run. 시간 측정 eval/measure_latency.py(URL, 이미지 폴더 → CSV, p50/p90).
       테스트용 팩은 tmp_path에 코드로 만든다.
[지킬 것] 앱 코드 수정 금지(필요하면 멈추고 알린다). 팩·결과 커밋 금지.
[끝나면] 검사 통과 → feature/6-plan-eval → PR.
```

## BE-N5 SketchUp 확인 (조예준)

```text
[작업] BE-N5 SketchUp 호환 — 이슈 #<번호>
[읽을 것] docs/next-tasks.md의 BE-N5 절, app/export/dxf.py
[할 일] (사람) SketchUp에서 확인한 결과를 docs/sketchup.md에 적는다. (에이전트) 실패 항목이 있으면
       3DFACE 내보내기 옵션(설정 export.dxf_mesh: polyface|3dface)과 테스트(블록 수, $INSUNITS)를 추가한다.
[끝나면] feature/<번호>-sketchup → PR.
```

## BE-N6 대체 데모 페이지 (조건부)

```text
[작업] BE-N6 대체 데모 페이지 — M1에서 프론트 3D가 안 떴을 때만
[읽을 것] docs/next-tasks.md의 BE-N6 절, docs/api.md
[할 일] app/static/fallback/index.html 한 장(업로드 → 1초 폴링 → three.js GLTFLoader, 버전 고정 CDN → 다운로드 링크),
       app/main.py에 StaticFiles 마운트(/fallback), deploy/Caddyfile에 /fallback/* 프록시.
[완료 조건] Fake로 /fallback/에서 3D 표시, export_openapi --check 통과(OpenAPI 불변).
```

---

## ML-0a 데이터셋 수정 (빌더 세션)

```text
[작업] ML-0 데이터셋 v2 — 빌더. 1차 감사 실패 원인을 고친다.
[읽을 것] AGENTS.md, docs/dataset.md, docs/backlog.md의 ML-0, reports/의 1차 감사 결과
[할 일] 1) docs/dataset.md 명세를 먼저 고친다(래스터화: 픽셀 모서리 좌표·4배 슈퍼샘플링·면적 50%, 평가 누수 제외 규칙)
       2) scripts/build_dataset.py, scripts/make_splits.py 수정 → 재빌드 → split 재생성
       3) manifest·split sha256을 reports/와 docs/dataset.md에 기록
[지킬 것] data/ai_hub 원본 읽기 전용. scripts/audit_dataset/는 열지도 고치지도 않는다. 스스로 감사 결과를 판정하지 않는다.
[끝나면] feature/dataset-v2 커밋. "감사 세션이 필요하다"고 보고하고 끝낸다.
```

## ML-0b 데이터셋 재감사 (감사 세션 — 다른 세션 또는 Codex)

```text
[작업] ML-0 데이터셋 v2 독립 감사.
[읽을 것] docs/dataset.md(명세), data/ai_hub(원본), data/processed(결과), splits/. 빌더 코드(scripts/build_dataset.py, src/data/)는 열지 않는다.
[할 일] scripts/audit_dataset/의 검사를 명세 기준으로 다시 실행·보완: 래스터화 위치(원본 폴리곤 재래스터화와 픽셀 일치),
       클래스 매핑, ignore 영역, 평가 누수(정렬 잉크 겹침 ≥ 0.9), split 그룹 분리.
[끝나면] reports/audit_v2.md에 항목별 통과/실패와 최종 판정("학습 가능"/"학습 진행 불가"). 판정만 하고 고치지 않는다.
```

## ML-2 학습 파이프라인

```text
[작업] ML-2 학습 파이프라인 (G0 통과 후)
[읽을 것] AGENTS.md, docs/MODEL_SPEC.md §3·§5, docs/backlog.md의 ML-2, src/data/
[할 일] backlog ML-2 체크리스트 전부. 구조·배율은 G1 결정값(DECISIONS 기록)을 configs/에.
       tune 평가는 autobim_seg.predict(runtime="torch")를 쓴다(ML-4 전이면 임시 함수 + TODO).
[끝나면] 배치 하나 과적합 결과를 reports/에, feature/train-pipeline 커밋.
```

## ML-4 autobim_seg v0.1

```text
[작업] ML-4 추론 패키지 autobim_seg v0.1
[읽을 것] AGENTS.md(추론 계약·서빙 환경), docs/MODEL_SPEC.md §2·§6·§9, scripts/bench_cpu.py(predict_tiled 참조 구현)
[할 일] backlog ML-4 체크리스트 전부. runtime="onnx" 경로는 torch import 금지(테스트로 확인).
       openings_from_labels는 MODEL_SPEC §6 순서 그대로. 의존성 목록(numpy, onnxruntime, opencv-python-headless)을 README에.
[끝나면] pytest -q 통과, feature/autobim-seg 커밋. 의존성 목록을 백엔드 #5 담당에게 전달할 문장으로 요약.
```

## ML-5 번들 · 일치 검사

```text
[작업] ML-5 make_bundle.py, check_parity.py → releases/seg-v0
[읽을 것] docs/MODEL_SPEC.md §2.2·§7·§10
[할 일] 스크립트 두 개, SHA256SUMS 생성, 번들로 tests/test_contract.py 실행, 일치율 ≥ 99.5% 미달 시 실패 종료.
[끝나면] releases/seg-v0 경로와 검사 결과 요약. 번들은 커밋하지 않는다.
```

## ML-6 평가 팩

```text
[작업] ML-6 make_eval_pack.py → evalpacks/dev (tune 30장)
[읽을 것] docs/MODEL_SPEC.md §9, 백엔드 docs/next-tasks.md의 BE-N2 절(같은 형식)
[할 일] 형식 그대로 생성. sha1은 PIL로 PNG를 다시 열어 convert("RGB")한 배열로 계산(백엔드와 같은 디코딩).
       목록을 splits/evalpack_dev.txt로 고정. gt/<id>.json은 COCO 폴리곤·박스(px, 픽셀 모서리 기준).
[끝나면] 팩 경로, 이미지 수, 한 장 예시 manifest 항목. 팩은 커밋하지 않는다.
```

---

## FE-2~FE-8 기본 흐름 (강민재)

```text
[작업] FE-<n> — 이슈 #<번호>
[읽을 것] AGENTS.md, docs/backlog.md의 FE-<n> 절, docs/FRONTEND_SPEC.md(절에서 가리키는 부분)
[할 일] 절의 범위를 구현하고 완료 조건을 테스트로 증명한다. 로컬 백엔드(Fake, docker compose up)로 실제로 눌러 본다.
[지킬 것] src/api/schema.d.ts 손으로 수정 금지. 좌표 변환은 src/lib/coords.ts만.
[끝나면] lint·typecheck·test·build 통과 → feature/<번호>-<이름> → PR.
```

## FE-5 3D 뷰어 (임준형)

```text
[작업] FE-5 3D 뷰어 — 이슈 #<번호>
[읽을 것] AGENTS.md, docs/FRONTEND_SPEC.md §4.4·§5.1·§5.2, docs/backlog.md의 FE-5
[할 일] Viewer3D(useGLTF + Bounds + OrbitControls + Grid + 조명), 외벽·내벽 색, 시점 버튼, coords.ts + 테스트.
       Fake 백엔드의 model.glb로 확인(벽 노드 이름 w1~w5).
[끝나면] 검사 통과 → PR.
```

## FE P1 묶음 (FE-9, FE-10, FE-11, FE-12, FE-14)

```text
[작업] FE-<n> — 이슈 #<번호>
[읽을 것] AGENTS.md, docs/backlog.md의 FE-<n>, docs/FRONTEND_SPEC.md §3·§5의 해당 절, 백엔드 docs/api.md의 SupplementRequest
[할 일] 절의 범위와 완료 조건. 보충 입력 뒤에는 useJob.refresh()로 폴링을 다시 시작한다.
[끝나면] 검사 통과 → PR.
```
