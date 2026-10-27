# Auto-BIM 백엔드 — 에이전트 작업 지침

> 에이전트 지침의 단일 원본이다. `CLAUDE.md`는 이 파일을 `@AGENTS.md`로 불러오기만 한다(Codex는 `@` 불러오기를 지원하지 않으므로 내용은 여기에 둔다). 지침은 여기에만 쓴다.

## 무엇을 하는 레포인가

2D 평면도(이미지 또는 DXF)를 읽어 중간 표현 **Plan**(mm)을 만들고, Plan에서 웹 뷰어용 `.glb`, 벽별 블록 `.dxf`, JSON을 만드는 FastAPI 백엔드.
설계: [docs/design.md](docs/design.md) · API: [docs/api.md](docs/api.md) · 기본값: [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) · 할 일: [docs/next-tasks.md](docs/next-tasks.md)

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
| `app/models/` | Fake / CubiCasa 어댑터(자리만) / 레지스트리 |
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
   - 계약 PR에서는 `SCHEMA_VERSION`을 올리고, `docs/openapi.json`을 다시 만들고, `docs/api.md`를 함께 고친다.
3. **`docs/ASSUMPTIONS.md`의 기본값은 바꾸지 않는다.** 코드 상수(`app/core/defaults.py`)와 일치하는지 `tests/test_assumptions.py`가 검사한다.
4. **데이터셋, 모델 가중치, 샘플 도면(이미지/.dxf/.dwg/.pdf)은 커밋하지 않는다.** 테스트 입력은 코드로 생성한다(PIL 이미지, `ezdxf.new()`). 출력은 `tmp_path`에 쓴다.
5. **모든 테스트는 Fake 모델로 돌아야 한다.** 실제 모델이 필요한 테스트는 기본 실행에서 빠지게 한다(예: 마커와 환경변수로 opt-in).
6. 기존 테스트는 계속 통과해야 한다. PR마다 CI가 lint, test, OpenAPI 스냅샷, `CLAUDE.md`의 `@AGENTS.md` 참조, docker build를 확인한다.
7. 담당 폴더 밖은 되도록 건드리지 않는다. 병렬 작업 영역은 [docs/next-tasks.md](docs/next-tasks.md)의 "건드리는 폴더"를 따른다.

## Git 작업 수칙

### 브랜치 (Git flow)

| 브랜치 | 어디서 만드나 | 어디로 머지하나 | 용도 |
|---|---|---|---|
| `main` | — | — | 릴리스된 코드. 머지할 때마다 버전 태그 `vX.Y.Z` |
| `develop` | — | — | 통합 브랜치, GitHub 기본 브랜치 |
| `feature/<이슈번호>-<요약>` | `develop` | `develop` | 기능·문서·리팩터링 등 일반 작업. 예: `feature/2-wall-junctions` |
| `feature/contract-<요약>` | `develop` | `develop` | 계약 PR(규칙 2) |
| `release/X.Y.Z` | `develop` | `main`, 그다음 `develop` | 릴리스 준비. 버전(`pyproject.toml`) 올리기와 버그 수정만 |
| `hotfix/X.Y.Z` | `main` | `main`, 그다음 `develop` | 릴리스된 코드의 긴급 수정 |

- `main`과 `develop`은 GitHub Ruleset으로 보호된다. PR로만 머지할 수 있고, 승인 1개(작성자 본인은 승인할 수 없음)와 CI(`test`, `docker`) 통과가 필요하다. PR 브랜치는 대상 브랜치의 최신 커밋을 포함해야 한다. force push와 브랜치 삭제는 막혀 있다.
- 머지 방식
  - `feature/*` → `develop`: **squash merge**. PR 제목이 커밋 헤더가 되므로 아래 형식을 따른다.
  - `release/*`·`hotfix/*` → `main`, 그리고 `main` → `develop` 역머지: **merge commit**(squash 금지). squash하면 두 브랜치의 이력이 갈라진다.
- 릴리스와 핫픽스는 `main`에 머지한 뒤 `vX.Y.Z` 태그를 달고, 같은 내용을 `develop`에도 PR로 머지한다.
- 버전은 SemVer다. 계약을 깨는 변경(`SCHEMA_VERSION` 메이저 증가)이 들어간 릴리스는 마이너 이상을 올린다(1.0 전까지).

### 커밋 메시지

헤더는 `<type>(<scope>): <요약>` 형식이다. scope는 선택이다.

```
feat: remove elements via supplement; cascade openings; never reuse IDs
docs(api): field-level tables for Job, Plan and SupplementRequest
chore: develop is the integration branch; CI also runs on pushes to develop
```

- type: `feat`(기능) · `fix`(버그 수정) · `docs`(문서) · `test`(테스트만) · `refactor`(동작 변화 없는 구조 변경) · `chore`(빌드·CI·의존성·설정)
- scope: 바뀐 영역 하나. 예: `api`, `schemas`, `geometry`, `export`, `jobs`, `models`, `recognition`, `dxf_input`, `ci`, `deps`
- 요약: 영어, 소문자로 시작, 끝에 마침표 없음, 한 줄 72자 이내. 여러 변경은 `;`로 잇는다.
- 본문은 필요할 때만, 빈 줄 하나 뒤에 "왜" 바꿨는지 쓴다.
- 계약 변경 커밋은 요약에 `(contract)`를 붙인다. 예: `feat(schemas): add wall layers (contract)`

### PR

- PR 하나에 이슈 하나. 본문에 `Closes #<이슈번호>`를 넣는다(기본 브랜치가 `develop`이라 `develop`에 머지되면 이슈가 닫힌다).
- PR 제목은 커밋 헤더 형식을 따른다.
- 본문에 무엇을 바꿨는지, 어떻게 확인했는지(테스트), 남은 한계를 적는다.

### `develop` 따라가기

- 작업 중에는 `git fetch && git rebase origin/develop`으로 맞춘다. 자기 `feature/*` 브랜치에서만 `git push --force-with-lease`를 쓴다. 남의 브랜치나 `main`·`develop`에는 force push하지 않는다.
- 계약 PR이 머지되면 그 계약에 의존하는 기능 브랜치는 `develop`으로 rebase한 뒤 계속한다.
- `--no-verify`로 훅을 건너뛰지 않는다. 머지된 브랜치는 지워도 된다.

### 워크트리 (병렬 작업)

- 이슈 하나에 워크트리 하나, 브랜치 하나.
  ```bash
  git fetch origin
  git worktree add ../autobim-be-wt/2-wall-junctions -b feature/2-wall-junctions origin/develop
  ```
- 워크트리는 레포 바깥 `../autobim-be-wt/<이슈번호>-<요약>`에 둔다. 레포 안에 만들지 않는다.
- 워크트리마다 `.venv`를 따로 만든다(위 [명령](#명령) 참고). 작업 데이터(`AUTOBIM_DATA_DIR`)도 워크트리 안의 기본값 `data/jobs`를 쓴다.
- 작업 범위는 이슈의 "건드리는 폴더"다(규칙 7). 여러 이슈가 함께 건드리는 공유 파일(`pyproject.toml`, lock 파일, `config/settings.yaml`, `.github/workflows/`)은 필요한 줄만 바꾸고, 충돌이 나면 rebase할 때 두 쪽 변경을 모두 살린다. lock 파일은 손으로 합치지 말고 다시 만든다.
- PR이 머지되면 `git worktree remove ../autobim-be-wt/<이름>`으로 정리한다.
