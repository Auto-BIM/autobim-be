# Auto-BIM 백엔드 — 에이전트 작업 지침

> 에이전트 지침의 단일 원본이다. `CLAUDE.md`는 이 파일을 `@AGENTS.md`로 불러오기만 한다(Codex는 `@` 불러오기를 지원하지 않으므로 내용은 여기에 둔다). 지침은 여기에만 쓴다.

## 무엇을 하는 레포인가

2D 평면도(이미지 또는 DXF)를 읽어 중간 표현 **Plan**(mm)을 만들고, Plan에서 웹 뷰어용 `.glb`, 벽별 블록 `.dxf`, JSON을 만드는 FastAPI 백엔드.
설계: [docs/design.md](docs/design.md) · API: [docs/api.md](docs/api.md) · 기본값: [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) · 할 일: [docs/next-tasks.md](docs/next-tasks.md)
프로젝트 전체(로드맵·시스템 명세·결정·평가·시연): [docs/project/](docs/project/README.md) · 인식 알고리즘: [docs/recognition.md](docs/recognition.md) · 배포: [docs/deploy-oci.md](docs/deploy-oci.md)

## 아키텍처

```
POST /api/jobs ─▶ app/jobs/runner.py
                   ├─ 이미지: app/preprocess → app/models (WallSegmenter·OpeningDetector·DimensionReader)
                   │          → app/recognition (마스크→벽, 개구부 배치, mm 환산, 확인 필요 요소)
                   └─ DXF:    app/dxf_input (미구현)
                   ▼
                 Plan (app/schemas/plan.py) ── 보충 입력: app/jobs/supplement.py (모델 재실행 없음)
                   ▼
                 app/geometry (벽 직육면체, 개구부 절단) → app/export (glb · dxf · json)
```

| 폴더 | 역할 |
|---|---|
| `app/schemas/` | **계약**: Plan, API 요청/응답 모델 |
| `app/models/base.py` | **계약**: 모델 인터페이스 |
| `app/api/` | 라우터(경로·형식은 계약) |
| `app/jobs/` | 작업 저장소(인메모리 + 로컬 파일), 실행기, 보충 입력 적용 |
| `app/models/` | Fake / CubiCasa 어댑터(자리만) / 레지스트리. 계획: `seg`(#5), `replay`(#11 (BE-N2)) |
| `app/preprocess/`, `app/recognition/` | 이미지 경로 |
| `app/dxf_input/` | DXF 경로 |
| `app/geometry/`, `app/export/` | 3D 기하, 파일 출력 |
| `config/settings.yaml` | 모델 구현 선택(`fake`/`cubicasa`/`none`), 저장 경로 |
| `scripts/export_openapi.py` | `docs/openapi.json` 생성/검사 |

핵심 규약: Plan은 mm, y축 위쪽. `opening.position`은 벽 시작점에서 개구부 중심까지의 거리. glb는 m, Y-up. 기존 요소 ID는 보충 입력 전후로 절대 바뀌지 않는다.

## 명령

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.lock && pip install --no-deps -e .

pytest -q                                  # 테스트 (Fake 모델)
ruff check .                               # 린트
python scripts/export_openapi.py           # docs/openapi.json 재생성 (계약 PR에서만)
python scripts/export_openapi.py --check   # 스냅샷 최신인지 확인
uvicorn app.main:app --reload              # 개발 서버 http://127.0.0.1:8000/docs
docker compose up --build                  # 컨테이너 실행
```

의존성을 바꾸면 lock을 다시 만든다:
`pip-compile --strip-extras --no-emit-index-url -o requirements.lock pyproject.toml`
`pip-compile --strip-extras --no-emit-index-url --extra dev -o requirements-dev.lock pyproject.toml`

## 규칙

1. **main·develop에 직접 커밋하지 않는다.** Git flow를 따른다(아래 [Git 작업 수칙](#git-작업-수칙)). 머지는 사람이 한다.
2. **Plan 스키마와 API는 계약 담당 PR에서만 수정한다.** 대상은 `app/schemas/`, `app/models/base.py`, `app/api/`의 경로·요청/응답 형식, `docs/openapi.json`이다.
   - 기능 PR에서 `tests/test_contract.py`가 실패하면 계약을 건드린 것이다. 되돌리거나 계약 PR로 분리한다.
   - 계약 PR에서는 Plan이 바뀌면 `SCHEMA_VERSION`을, API가 바뀌면 `API_VERSION`(`app/main.py`)을 올리고, `docs/openapi.json`을 다시 만들고, `docs/api.md`를 함께 고친다.
3. **`docs/ASSUMPTIONS.md`의 기본값은 바꾸지 않는다.** 코드 상수(`app/core/defaults.py`)와 일치하는지 `tests/test_assumptions.py`가 검사한다.
4. **데이터셋, 모델 가중치, 샘플 도면(이미지/.dxf/.dwg/.pdf)은 커밋하지 않는다.** 테스트 입력은 코드로 생성한다(PIL 이미지, `ezdxf.new()`). 출력은 `tmp_path`에 쓴다.
5. **모든 테스트는 Fake 모델로 돌아야 한다.** 실제 모델이 필요한 테스트는 기본 실행에서 빠지게 한다(예: 마커와 환경변수로 opt-in).
6. 기존 테스트는 계속 통과해야 한다. PR마다 CI가 lint, test, OpenAPI 스냅샷, `CLAUDE.md`의 `@AGENTS.md` 참조, docker build를 확인한다.
7. 담당 폴더 밖은 되도록 건드리지 않는다. 병렬 작업 영역은 [docs/next-tasks.md](docs/next-tasks.md)의 "건드리는 폴더"를 따른다.

## Git 작업 수칙

### 브랜치 (Git flow)

| 브랜치 | 어디서 만드나 | 어디로 머지하나 |
|---|---|---|
| `main` | — | — |
| `develop` | — | — |
| `feature/*` | `develop` | `develop` |
| `release/*` | `develop` | `main`, `develop` |
| `hotfix/*` | `main` | `main`, `develop` |

### 커밋 메시지

헤더는 `<type>(<scope>): <요약>` 형식이다. scope는 선택이다.

```
feat: remove elements via supplement; cascade openings; never reuse IDs
docs(api): field-level tables for Job, Plan and SupplementRequest
chore: develop is the integration branch; CI also runs on pushes to develop
```
