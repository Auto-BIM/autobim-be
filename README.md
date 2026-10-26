# autobim-be

Auto-BIM 백엔드. 2D 평면도(이미지 또는 DXF)를 중간 표현 **Plan**(mm)으로 바꾸고, 그로부터 웹 3D 뷰어용 `.glb`, 벽별 블록 `.dxf`, JSON을 만든다.

- 설계: [docs/design.md](docs/design.md)
- API: [docs/api.md](docs/api.md) · [docs/openapi.json](docs/openapi.json)
- 기본값: [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md)
- 다음 작업: [docs/next-tasks.md](docs/next-tasks.md)
- 에이전트/기여 규칙: [CLAUDE.md](CLAUDE.md) ([AGENTS.md](AGENTS.md)는 CLAUDE.md를 참조)

> 현재 상태: 인식 모델은 **Fake**(고정 결과)만 동작한다. CubiCasa 어댑터와 DXF 입력은 자리만 있다.
> 벽 접합부 처리가 아직 없어서 glb/dxf 모서리가 맞지 않는다(next-tasks #1).

## 로컬 실행

Python 3.11이 필요하다.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.lock
pip install --no-deps -e .

uvicorn app.main:app --reload
# http://127.0.0.1:8000/docs
```

## Docker

```bash
docker compose up --build
# http://localhost:8000/docs  (작업 파일은 named volume "jobs"에 저장)
```

## 사용 예

```bash
# 1) 업로드 → 작업 생성
curl -s -F "file=@plan.png" http://127.0.0.1:8000/api/jobs
# {"id": "<JOB>", "status": "queued", "revision": 0, ...}

# 2) 상태 · Plan · 확인 필요 요소
curl -s http://127.0.0.1:8000/api/jobs/<JOB>

# 3) 보충 입력 → 재생성 (모델은 다시 돌지 않고, 기존 요소 ID는 유지됨)
curl -s -H 'Content-Type: application/json' \
  -d '{"scale": {"building_width_mm": 12000}, "resolved": ["o3"]}' \
  http://127.0.0.1:8000/api/jobs/<JOB>/supplement

# 4) 결과 파일
curl -s -o model.glb http://127.0.0.1:8000/api/jobs/<JOB>/files/glb
curl -s -o model.dxf http://127.0.0.1:8000/api/jobs/<JOB>/files/dxf
curl -s -o plan.json http://127.0.0.1:8000/api/jobs/<JOB>/files/json
```

## 설정

`config/settings.yaml`에서 모델 구현을 고른다. 환경변수로 덮어쓸 수 있다.

| 환경변수 | 기본값 | 값 |
|---|---|---|
| `AUTOBIM_CONFIG` | `config/settings.yaml` | 설정 파일 경로 |
| `AUTOBIM_WALL_SEGMENTER` | `fake` | `fake` · `cubicasa` |
| `AUTOBIM_OPENING_DETECTOR` | `fake` | `fake` · `cubicasa` |
| `AUTOBIM_DIMENSION_READER` | `fake` | `fake` · `none` |
| `AUTOBIM_DATA_DIR` | `data/jobs` | 작업 파일 저장 위치 |

## 테스트

```bash
pytest -q                                  # Fake 모델로 실행
ruff check .
python scripts/export_openapi.py --check   # API 계약 스냅샷 확인
```

CI(GitHub Actions)는 PR마다 lint, test, OpenAPI 스냅샷, `AGENTS.md` → `CLAUDE.md` 참조, docker build와 smoke test를 돌린다.
