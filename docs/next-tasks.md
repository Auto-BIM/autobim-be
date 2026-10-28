# 다음 작업 (백엔드 GitHub 이슈)

병렬 worktree 작업용 이슈 목록이다. 이 문서가 각 이슈의 **범위와 완료 조건의 원본**이고, 진행 상황과 논의는 GitHub 이슈에서 한다.
일정·담당·우선순위의 근거는 [project/ROADMAP.md](project/ROADMAP.md)다. 담당은 제안이며 킥오프에서 확정한다.

- `#2`~`#7`: 처음 만든 이슈. `#10`~`#15`: 이 문서로 새로 만든 이슈다. 괄호 안의 `BE-N1`~`BE-N6`은 이슈를 만들기 전에 쓰던 키다([project/PROMPTS.md](project/PROMPTS.md) P0-2).
- P0 = 없으면 시연 불가, P1 = 시연·보고서 품질, P2 = G3(11/29)에서 여유가 있을 때만.

| 키 | 제목 | 등급 | 담당(제안) | 목표 | 선행 |
|---|---|---|---|---|---|
| #10 (BE-N1) | 인식 v1: 마스크 → 벽·개구부 (프로토타입 이식) | P0 | 조예준 | W9~W11 | — |
| #2 | Plan → 3D/.dxf 접합부·개구부 | P0 | 조예준 | W9~W10 | — |
| #11 (BE-N2) | replay 어댑터 (평가 팩의 정답·예측 마스크 재생) | P0 | 조예준 | W10 | 평가 팩 형식(모델 ML-6) |
| #12 (BE-N3) | 계약 PR C1: 업로드 413, `/health` 모델 정보 | P0 | 조항민 | W10 | — |
| #5 | `seg` 어댑터 (`autobim_seg` 번들) | P0 | 조항민 | W10 | #12 (BE-N3), 번들 seg-v0 |
| #13 (BE-N4) | 서빙 안정화: 추론 동시 1개, EXIF 회전, 작업 TTL, 단계별 시간 로그 | P0 | 조예준 | W11 | — |
| #7 | OCI 배포 (Caddy + compose + 스크립트) | P0 | 조항민 | W9~W11 | — |
| #6 | Plan 단위 시스템 평가 | P1 | 임준형 | W12~W14 | #11 (BE-N2) |
| #14 (BE-N5) | SketchUp 호환 확인 | P1 | 조예준 | W12 | #2 |
| #15 (BE-N6) | 대체 데모 페이지 (조건부: M1에서 프론트 3D가 안 뜰 때만) | P1 | 조항민 | W11 | — |
| #3 | DXF 입력 경로 | P2 | 조예준 | G3 결정 | — |
| #4 | 작업 영속화 · 큐 분리 | P2 | — | G3 결정 | — |

**공통 규칙** ([AGENTS.md](../AGENTS.md) 참고)
- 각 이슈는 "건드리는 폴더" 안에서만 작업한다.
- 계약(`app/schemas/`, `app/models/base.py`, API 경로·형식, `docs/openapi.json`)을 바꿔야 하면 그 부분만 **별도 계약 PR**로 먼저 올린다. 지금 필요한 계약 변경은 #12 (BE-N3)에 모두 모았다.
- 모든 테스트는 Fake 모델로 돌아야 한다. 샘플 도면, 데이터셋, 가중치, 평가 팩은 커밋하지 않고 테스트 입력은 코드로 만든다.
- 완료 조건에는 기존 테스트 통과와 CI green이 항상 포함된다.

---

## #10 (BE-N1) 인식 v1: 마스크 → 벽·개구부 (P0)

GitHub: [#10](https://github.com/Auto-BIM/autobim-be/issues/10)

**배경**: 지금 후처리(`app/recognition/walls.py`)는 축에 평행하고 끊김 없는 Fake 마스크만 다룬다. 실제 모델 마스크는 문·창 자리에서 벽이 끊기고, 문 박스는 열림 호까지 감싸서 방 안쪽으로 튀어나오고, 잡음이 있다. 검증된 알고리즘과 프로토타입이 [recognition.md](recognition.md), [recognition-prototype/](recognition-prototype/)에 있다.

**건드리는 폴더**: `app/recognition/`, `app/core/config.py`(`RecognitionSettings`만), `config/settings.yaml`(`recognition:`만), `tests/test_recognition.py`, `tests/synthetic_plans.py`(신규), `scripts/debug_overlay.py`(신규), `pyproject.toml`·lock(`scipy` 추가), `docs/recognition-prototype/`(이식 후 삭제)

**할 일**
- [recognition.md](recognition.md) §3의 R1~R9를 §8 이식 가이드대로 옮긴다. `PixelWall`의 기존 필드·메서드는 유지한다.
- `pipeline._classify`를 R7(바깥 영역 판정)로, `pipeline._attach_openings`를 R9로 바꾼다. 개구부 위치·폭은 §4 표대로 계산한다.
- §5의 확인 필요 항목 규칙을 넣는다(기존 `ReviewReason`만 사용).
- 파라미터를 `recognition:` 설정으로 뺀다.
- `scripts/debug_overlay.py`(§7).

**완료 조건 (테스트)**
- [ ] 기존 `tests/test_recognition.py`가 그대로 통과한다(Fake 도면: 벽 5개, 개구부 5개, 확인 항목 `o3` 하나).
- [ ] 합성 도면 테스트(recognition.md §6의 L자·잡음·배율 3종·교란 10시드·모서리 문·사선 벽)가 통과한다.
- [ ] 합성 3500×5000 마스크에서 인식이 CI 기계 기준 10초 이내다(시간 측정 테스트는 느슨하게, `@pytest.mark.slow`로 빼도 된다).
- [ ] dev 평가 팩(#11 (BE-N2)) 30장으로 돌린 결과(성공 수, 실패 유형)를 PR 설명에 적는다. 팩이 없으면 W10에 후속 PR로.
- [ ] Plan 스키마와 API는 바뀌지 않는다(`test_contract.py`).

---

## #2 Plan → 3D/.dxf 기하 생성 완성 (접합부, 개구부) (P0)

GitHub: [#2](https://github.com/Auto-BIM/autobim-be/issues/2)

**배경**: 지금은 벽이 중심선 끝점에서 그냥 끝난다. 그래서 L자 모서리 안쪽은 두 벽이 겹치고, 바깥 모서리는 두께 절반 크기 정사각형(외벽 200mm면 100×100mm)이 비어 있다. 설계([design.md](design.md) §5)는 한쪽 벽을 두께 절반만큼 늘리거나 줄여서 겹침도 빈 칸도 없게 하는 것이다. 인식 v1(#10 (BE-N1))은 끝점을 상대 벽의 **중심선**에 맞춰 주므로, 접합부는 "중심선 끝점이 다른 벽의 중심선 위에 있다"로 판정할 수 있다.

**건드리는 폴더**: `app/geometry/`, `app/export/`, `tests/test_geometry.py`, `tests/test_end_to_end.py`

**할 일**
- 끝점이 만나는 지점에서 L·T·+자 접합부를 찾고, 정해진 규칙(결정적 순서)으로 늘리거나 줄인다.
- 두께가 다른 벽이 만나는 경우(외벽 200 + 내벽 120)를 처리한다.
- 개구부 경계 처리: 벽 끝을 넘는 개구부, 서로 겹치는 개구부, 접합부에 걸친 개구부.
- 축에 평행하지 않은 벽이 만나는 경우: 최소한 겹침 없이 처리하고, 정확한 마이터는 선택 사항이다.
- .dxf: 접합부를 처리한 뒤에도 벽마다 블록 하나를 유지한다. 개구부 표현을 개선한다(문 열림 호 등, 선택 사항).

**완료 조건 (테스트)**
- [ ] L자 접합부: 두 벽 메시의 부피 합 = 합집합 부피이고, 바깥 모서리 정사각형이 채워져 있다(점 포함 검사).
- [ ] T자 접합부: 가지 벽이 줄기 벽 면에서 끝나고 겹치는 부피가 0이다.
- [ ] 두께가 다른 L·T자 접합부도 같은 조건을 만족한다.
- [ ] 접합부 처리 후에도 벽 높이, 개구부 위치·크기 부피 검사가 유지된다(`test_geometry.py`의 기존 검사 포함).
- [ ] e2e: Fake 평면도의 glb bounds가 외곽선과 정확히 일치하고, 각 벽 메시가 watertight다.
- [ ] Plan 스키마와 API는 변경하지 않는다(`test_contract.py` 통과).

---

## #11 (BE-N2) replay 어댑터 (P0)

GitHub: [#11](https://github.com/Auto-BIM/autobim-be/issues/11)

**배경**: 모델 런타임 없이도 실제 도면으로 인식을 개발·평가해야 한다. 모델 레포가 만드는 **평가 팩**(ML-6)에는 이미지별 정답 마스크와 모델 예측 마스크, 그리고 `autobim_seg.openings_from_labels`로 만든 개구부 박스가 들어 있다. replay 어댑터는 업로드된 이미지에 해당하는 마스크를 팩에서 찾아 `WallSegmenter`·`OpeningDetector`로 돌려준다. 서빙과 같은 개구부 함수 결과를 쓰므로 평가가 서빙과 어긋나지 않는다.

**평가 팩 형식** (모델 레포 MODEL_SPEC §9와 같다)
```
<pack>/
  manifest.json                 # [{id, image, sha1, width, height, split}]
  images/<id>.png
  labels/gt/<sha1>.png          # uint8 0~3 (ignore 255는 0으로)
  openings/gt/<sha1>.json       # [{"type": "door", "bbox": [x0,y0,x1,y1], "conf": 1.0}]
  labels/pred/<번들 이름>/<sha1>.png
  openings/pred/<번들 이름>/<sha1>.json
  gt/<id>.json                  # 이 이미지의 COCO 폴리곤(px), #6이 쓴다
```
`sha1` = `hashlib.sha1(load_image(png_bytes).tobytes()).hexdigest()` — 백엔드 `app/preprocess/image.load_image`로 디코딩한 RGB 배열 기준.

**건드리는 폴더**: `app/models/replay.py`(신규), `app/models/registry.py`, `app/core/config.py`(`ModelSettings.replay`만), `config/settings.yaml`(`models.replay`만), `tests/test_models.py`

**할 일**
- `ReplayModel(pack_dir, variant)`: `segment` → `labels == 1`, `detect` → JSON 박스. `variant`는 `gt` 또는 `pred/<번들 이름>`.
- registry에 `"replay"` 추가. 두 역할이 같은 인스턴스를 공유한다.
- 팩에 없는 이미지면 "이미지가 평가 팩에 없음: sha1=…" 메시지로 예외(작업은 `internal_error`).
- 설정: `models.replay.pack_dir`·`variant`, 환경변수 `AUTOBIM_REPLAY_PACK`·`AUTOBIM_REPLAY_VARIANT`.

**완료 조건 (테스트)**
- [ ] `tmp_path`에 코드로 만든 작은 팩(이미지 2장)으로 `segment`·`detect` 결과가 팩 내용과 같다.
- [ ] API 통합: replay 설정으로 팩 이미지를 업로드하면 `succeeded`, 팩에 없는 이미지는 `failed`.
- [ ] 팩·이미지는 커밋하지 않는다.

---

## #12 (BE-N3) 계약 PR C1: 업로드 제한, `/health` 모델 정보 (P0, 계약)

GitHub: [#12](https://github.com/Auto-BIM/autobim-be/issues/12)

**배경**: 공개 서버라 큰 파일이 메모리를 터뜨릴 수 있고, 배포된 모델 버전을 확인할 방법이 없다. 필요한 계약 변경을 이 PR 하나로 모은다. 상세: [project/SYSTEM_SPEC.md](project/SYSTEM_SPEC.md) §8.

**건드리는 폴더**: `app/api/`, `app/main.py`(`/health`, `API_VERSION`), `app/schemas/jobs.py`(필요 시 응답 모델), `app/core/config.py`(`limits`만), `config/settings.yaml`(`limits:`만), `docs/api.md`, `docs/openapi.json`, `tests/test_jobs_api.py`

**할 일**
- `POST /api/jobs` 응답에 413 추가. 코드 `file_too_large`(바이트 상한 초과), `image_too_large`(픽셀 상한 초과, PIL로 헤더만 읽어 판단).
- 디코딩할 수 없는 이미지는 업로드 때 415 `unsupported_media_type`.
- `/health` → `{"status": "ok", "wall_segmenter": "...", "opening_detector": "...", "model": "seg-v1" | "fake"}`. 값은 모두 문자열.
- 상한값은 설정(`limits.max_upload_mb` 30, `limits.max_pixels` 40,000,000)과 환경변수(`AUTOBIM_MAX_UPLOAD_MB`, `AUTOBIM_MAX_PIXELS`)로 받는다.
- `API_VERSION` 0.2.0. `docs/openapi.json` 재생성, `docs/api.md`에 413·새 코드·`/health` 반영. Plan은 바뀌지 않으므로 `SCHEMA_VERSION`은 그대로.

**완료 조건 (테스트)**
- [ ] 상한보다 큰 바이트 → 413 `file_too_large`, 상한보다 많은 픽셀(작은 바이트의 큰 PNG를 코드로 생성) → 413 `image_too_large`, 깨진 PNG → 415.
- [ ] 기존 API 테스트가 그대로 통과한다.
- [ ] `python scripts/export_openapi.py --check` 통과.

---

## #5 `seg` 어댑터 (`autobim_seg` 번들) (P0)

GitHub: [#5](https://github.com/Auto-BIM/autobim-be/issues/5)

**배경**: 모델은 별도 레포 `autobim-model`에서 만든다. 4클래스 분할(0 배경, 1 벽, 2 문, 3 창)을 AI Hub 평면도로 학습하고 **모델 번들**(ONNX + `model.json` + `pkg/autobim_seg`)로 내보낸다. 구조는 UNet + 경량 인코더이고 G1 CPU 벤치(11/1)로 확정한다. 서빙은 OCI A1(CPU)에서 ONNX Runtime으로 한다. 번들 형식과 API: [project/SYSTEM_SPEC.md](project/SYSTEM_SPEC.md) §3.1~3.3. 후처리 견고화는 #10 (BE-N1), 사진 도면 전처리는 P2로 옮겼다. 계약(`app/models/base.py`)은 바꾸지 않는다.

```python
seg = autobim_seg.load(bundle_dir, runtime="onnx", threads=2)
r = seg.predict(img)   # img: (H, W, 3) uint8 RGB
r.labels               # (H, W) uint8, 0~3
r.openings()           # [(type, (x0, y0, x1, y1), conf)]
r.mean_confidence(1)   # 벽 평균 확률
```

**건드리는 폴더**: `app/models/`(`base.py` 제외), `app/core/config.py`(`ModelSettings.seg`만), `config/settings.yaml`(모델 항목), `pyproject.toml`·lock(`seg` extra, `requirements-seg.lock` 신규), `Dockerfile`(`EXTRAS` 빌드 인자), `README.md`(번들 받는 법), `tests/test_models.py`

**할 일**
- `app/models/seg.py`: `SegModel`이 `WallSegmenter`·`OpeningDetector`를 둘 다 구현한다. 마지막 이미지 객체를 기억하고 `is`로 비교해 `predict`는 이미지당 한 번만. `threading.Lock`으로 감싼다.
- registry에 `"seg"` 추가. 두 역할이 `seg`이면 **같은 인스턴스**를 쓴다. `autobim_seg`는 `seg`를 고를 때만 import한다.
- 번들이 없거나 `model.json`의 `autobim_seg_version`이 설치된 패키지와 다르면 앱 시작 시 명확한 오류로 실패한다.
- optional extra `seg = ["onnxruntime", "opencv-python-headless"]`(정확한 목록은 모델 레포 `autobim_seg` 의존성에 맞춘다). `Dockerfile`에 `ARG EXTRAS=""`를 두고 `seg`면 `requirements-seg.lock`을 추가 설치한다.
- `cubicasa` 자리표시는 제거한다(베이스라인은 모델 레포가 같은 `predict` 형식으로 감싸 평가한다).
- `/health`의 `model` 값에 번들 이름을 넣는다(#12 (BE-N3) 이후).

**완료 조건 (테스트)**
- [ ] 기본 `pytest`는 Fake만으로 통과하고 onnxruntime·torch를 import하지 않는다.
- [ ] 가짜 `autobim_seg` 모듈(`sys.modules`에 끼워 넣은 합성 `labels`·`openings`)로 단위 테스트한다. 같은 이미지에 `segment`·`detect`를 모두 불러도 `predict`는 1회.
- [ ] 실제 번들 테스트는 `@pytest.mark.model`, `AUTOBIM_SEG_BUNDLE`이 있을 때만 실행한다.
- [ ] 가중치·번들은 커밋하지 않는다.

---

## #13 (BE-N4) 서빙 안정화 (P0)

GitHub: [#13](https://github.com/Auto-BIM/autobim-be/issues/13)

**배경**: 공개 URL + CPU 2개라 동시 업로드에 약하다. 작업은 `BackgroundTasks` 스레드에서 돌아 추론이 겹치고, 휴대폰 JPEG는 EXIF 방향이 적용되지 않고, 오래된 작업 폴더가 쌓인다. 업로드 크기·픽셀 제한은 #12 (BE-N3)이 맡는다. 상세: [project/SYSTEM_SPEC.md](project/SYSTEM_SPEC.md) §9.

**건드리는 폴더**: `app/jobs/`, `app/preprocess/image.py`, `app/core/config.py`(`limits`·`jobs`만), `config/settings.yaml`, `tests/test_jobs_*.py`, `tests/test_preprocess.py`(신규)

**할 일**
- 인식 구간(디코딩 ~ Plan)을 세마포어(`jobs.max_concurrent`, 기본 1)로 감싼다. **기다리는 동안 상태는 `queued`**, 세마포어를 잡은 뒤 `running`으로 바꾼다.
- JPEG EXIF 방향을 적용한다(`ImageOps.exif_transpose`).
- 작업 폴더 TTL 정리(`jobs.ttl_hours`, 기본 72): 앱 시작 시와 새 작업 생성 시 오래된 폴더·레코드를 지운다. 진행 중 작업은 지우지 않는다.
- 작업 시작·끝·실패를 한 줄 로그로 남긴다(작업 ID, 단계별 소요 시간). 시간 측정(#6, EVALUATION_PLAN)에 쓴다.

**완료 조건 (테스트)**
- [ ] 느린 가짜 모델로 작업 두 개를 동시에 넣으면 한 번에 하나만 인식하고, 두 번째는 첫 번째가 끝날 때까지 `queued`다.
- [ ] EXIF 회전된 JPEG(코드로 생성) → 회전 적용된 크기로 디코딩.
- [ ] TTL보다 오래된 작업은 조회 시 404, 진행 중 작업은 남는다.
- [ ] 기존 Jobs API 테스트가 그대로 통과한다.

---

## #7 배포 (OCI A1) (P0)

GitHub: [#7](https://github.com/Auto-BIM/autobim-be/issues/7)

**배경**: 서빙은 OCI Always Free A1 VM 한 대(2 OCPU, 12 GB, arm64, GPU 없음)다. 이미지는 VM에서 직접 빌드한다(레지스트리 불필요). Caddy가 프론트 정적 파일과 `/api`를 같은 출처로 내보낸다. 런북: [deploy-oci.md](deploy-oci.md).

**건드리는 폴더**: `deploy/`(신규: `docker-compose.prod.yml`, `Caddyfile`, `.env.example`, `deploy.sh`, `smoke.sh`, `README.md`), `.github/workflows/`(기존 검사 유지, 선택: arm64 빌드 잡), `Dockerfile`, `docker-compose.yml`

**할 일**
- deploy-oci.md §5의 compose·Caddyfile을 파일로 만든다. 호스트 경로(`MODELS_DIR`, `FE_DIR`, `HTTP_PORT`)는 환경변수로 받아 노트북에서도 같은 파일로 띄운다.
- `api`: 워커 1개, `restart: unless-stopped`, `mem_limit`, 번들 읽기 전용 마운트, `AUTOBIM_DIMENSION_READER=none`(실제 경로).
- `deploy.sh`(git 갱신 → 빌드 → 재시작 → health), `smoke.sh <base_url> <image>`(업로드 → 폴링 → glb·dxf 다운로드 → 크기 검사).
- `deploy/README.md`: 배포·모델 교체·롤백·백업 절차 요약(상세는 deploy-oci.md).

**완료 조건 (테스트)**
- [ ] OCI VM에서 `deploy.sh`로 Fake 설정이 뜨고, 외부에서 `http://<공인 IP>/health` 200, `smoke.sh` 통과.
- [ ] 같은 compose로 노트북(Docker Desktop)에서도 뜬다.
- [ ] 컨테이너는 non-root로 돌고 작업 파일은 볼륨에 남는다.
- [ ] 기존 CI(lint, test, OpenAPI, docker build, smoke)는 그대로 통과한다.

---

## #6 Plan 단위 시스템 평가 (P1)

GitHub: [#6](https://github.com/Auto-BIM/autobim-be/issues/6)

**배경**: 모델 지표(픽셀 IoU, 문·창 객체 P/R)는 모델 레포가 잰다. 백엔드는 후처리까지 포함한 **Plan 단위** 평가를 한다. 같은 이미지를 정답 마스크와 예측 마스크로 각각 인식해 비교하면, 정답 마스크 결과는 후처리 한계, 둘의 차이는 모델 기여 오차가 된다. 지표 정의: [project/EVALUATION_PLAN.md](project/EVALUATION_PLAN.md) §3.

**건드리는 폴더**: `eval/`(신규), `tests/test_eval.py`(신규). 앱 코드는 읽기만 하고 수정하지 않는다.

**할 일**
- 입력: 평가 팩(#11 (BE-N2) 형식). replay 어댑터로 `gt`와 `pred/<번들>` 두 번 인식한다.
- 지표: ① Plan 렌더 벽 IoU(Plan 벽을 px로 다시 그려 정답 벽 마스크와 IoU) ② 벽 총길이 오차(정답 벽 마스크 골격 길이 대비) ③ 개구부 precision/recall/F1(같은 종류, 중심 거리 ≤ max(0.5·폭, 2·t_med)로 매칭) ④ 매칭된 개구부의 위치·폭 오차(px, 축척이 있으면 mm) ⑤ 작업 성공률과 확인 필요 항목 수.
- CLI: `python -m eval.run --pack <dir> --variant gt --variant pred/seg-v1 -o reports/` → `summary.json`, 이미지별 `per_image.csv`.
- 시간 측정: `python -m eval.measure_latency --url <base> --images <폴더> -n 20` → 작업별 시간 CSV, p50/p90(EVALUATION_PLAN §4).
- 범위 밖: 픽셀 IoU 같은 모델 지표(모델 레포 담당).

**완료 조건 (테스트)**
- [ ] 코드로 만든 작은 팩(정답 = 예측)에서 렌더 IoU ≈ 1, 개구부 F1 = 1.
- [ ] 개구부 하나를 빼고 하나를 옮긴 예측에서 P/R/위치 오차가 손으로 계산한 값과 같다.
- [ ] 팩이 없으면 친절한 오류 메시지와 종료 코드 ≠ 0.

---

## #14 (BE-N5) SketchUp 호환 확인 (P1)

GitHub: [#14](https://github.com/Auto-BIM/autobim-be/issues/14)

**배경**: `.dxf`는 벽마다 블록(polyface 메시) + INSERT, 레이어 `A-WALL`·`A-DOOR`·`A-WINDOW`, mm 단위다. 시연에서 SketchUp으로 열어 보여 주려면 실제 버전에서 확인해야 한다(SketchUp 버전은 미결 O-08).

**건드리는 폴더**: `app/export/dxf.py`(필요 시), `tests/test_export_dxf.py`(신규), `docs/sketchup.md`(신규)

**할 일**
- Fake 도면 + 실제 도면 2장의 `.dxf`를 SketchUp에서 가져오기(단위 mm). 확인: 벽마다 컴포넌트, 태그(레이어) 3개, 면이 생김, 개구부 구멍, 크기.
- polyface가 면으로 안 들어오면 `3DFACE`로 내보내는 옵션(`ezdxf` `MeshBuilder.render_3dfaces`)을 설정으로 추가한다.
- 결과와 스크린샷 위치를 `docs/sketchup.md`에 적는다(이미지 파일은 커밋하지 않음).

**완료 조건**
- [ ] 팀이 정한 SketchUp 버전에서 위 항목이 확인됐다.
- [ ] 내보내기 방식을 바꿨다면 블록 수 = 벽 수, `$INSUNITS = 4` 테스트.

---

## #15 (BE-N6) 대체 데모 페이지 (P1, 조건부)

GitHub: [#15](https://github.com/Auto-BIM/autobim-be/issues/15)

**배경**: M1(11/8)에서 프론트 3D가 뜨지 않을 때만 만든다. 시연이 프론트 일정에 묶이지 않게 하는 보험이다.

**건드리는 폴더**: `app/static/fallback/`(신규), `app/main.py`(StaticFiles 마운트만), `deploy/Caddyfile`(`handle /fallback/* { reverse_proxy api:8000 }` 추가). 마운트는 OpenAPI에 나타나지 않는다(`--check`로 확인). 프론트의 데모 모드(`/demo/:name`, FE-14)와 경로가 겹치지 않게 `/fallback/`을 쓴다.

**할 일**: 정적 HTML 한 장(`/fallback/`): 파일 선택 → `POST /api/jobs` → 1초 폴링 → three.js(고정 버전 CDN) `GLTFLoader`로 glb 표시 → 다운로드 링크.

**완료 조건**
- [ ] Fake 설정에서 `/fallback/`로 업로드 → 3D가 보인다. OpenAPI 스냅샷은 그대로다.

---

## #3 DXF 입력 경로 (P2)

GitHub: [#3](https://github.com/Auto-BIM/autobim-be/issues/3) — 범위·완료 조건은 이슈 본문 그대로다. G3(11/29)에서 P2로 고를 때만 착수한다.

## #4 작업 영속화 · 큐 분리 (P2)

GitHub: [#4](https://github.com/Auto-BIM/autobim-be/issues/4) — 업로드 크기 제한은 #12 (BE-N3), 동시 실행 제한은 #13 (BE-N4)로 옮겼다. 나머지(영속 저장소, 프로세스 밖 워커, 리비전 보존 정책, 이력 API)는 P2다. 작업 TTL 정리는 #13이 만들고, #4는 그 정리가 영속 저장소에서도 동작하게 한다. 영속화 전까지 uvicorn 워커는 1개여야 한다.
