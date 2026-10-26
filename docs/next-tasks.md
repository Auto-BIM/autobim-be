# 다음 작업 (GitHub 이슈 초안)

병렬 worktree 작업용 이슈 목록. 우선순위 순서다.

**공통 규칙** ([AGENTS.md](../AGENTS.md) 참고)
- 각 이슈는 "건드리는 폴더" 안에서만 작업한다.
- 계약(`app/schemas/`, `app/models/base.py`, API 경로·형식, `docs/openapi.json`)을 바꿔야 하면 그 부분만 **별도 계약 PR**로 먼저 올린다.
- 모든 테스트는 Fake 모델로 돌아야 한다. 샘플 도면, 데이터셋, 가중치는 커밋하지 않고 테스트 입력은 코드로 만든다.
- 완료 조건에는 기존 테스트 통과와 CI green이 항상 포함된다.

---

## #1 Plan → 3D/.dxf 기하 생성 완성 (접합부, 개구부)

**배경**: 지금은 벽이 중심선 끝점에서 그냥 끝난다. 그래서 L자 모서리 안쪽은 두 벽이 겹치고, 바깥 모서리는 두께 절반 크기 정사각형(외벽 200mm면 100×100mm)이 비어 있다. 설계([design.md](design.md) §5)는 한쪽 벽을 두께 절반만큼 늘리거나 줄여서 겹침도 빈 칸도 없게 하는 것이다.

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

## #2 DXF 입력 경로

**배경**: `.dxf` 업로드는 지금 `failed`(`not_implemented`)로 끝난다. 설계([design.md](design.md) §4)는 ezdxf로 읽고 레이어·블록 이름으로 분류하며, 이중선 벽을 병합하는 것이다.

**건드리는 폴더**: `app/dxf_input/`, `tests/test_dxf_input.py`. 필요하면 `app/jobs/runner.py`의 DXF 분기만 수정한다.

**할 일**
- 레이어·블록 이름 규칙으로 벽·문·창을 분류한다. 규칙 표는 설정 가능하게 하고 한국어·영문 레이어명을 모두 다룬다(예: `A-WALL`, `벽`, `WALL`).
- 이중선 벽(평행선 쌍)을 중심선 + 두께로 병합한다. 단선 벽은 기본 두께를 적용하고 확인 필요 요소(`default_value_applied`)로 남긴다.
- 문·창 블록 INSERT → 가장 가까운 벽에 배치(`position`, `width`).
- `$INSUNITS`로 mm 환산한다. 단위가 없으면 mm로 가정하고 확인 필요 요소를 남긴다. `scale.source = "source_units"`.

**완료 조건 (테스트)**
- [ ] 테스트 DXF는 **코드로 생성**한다(`ezdxf.new()`). `.dxf` 파일은 커밋하지 않는다(`.gitignore`에 있음).
- [ ] 이중선 직사각형 방 + 내벽 1개 + 문 블록 2개 + 창 블록 1개 → 벽 수, 중심선 좌표, 두께, 개구부 `wall_id`와 `position`이 기대값과 같다(±1mm).
- [ ] `$INSUNITS`가 m 또는 cm인 도면도 mm로 맞게 환산한다.
- [ ] 분류할 수 없는 레이어는 무시하고, 단선 벽은 확인 필요 요소를 만든다.
- [ ] API 통합 테스트: `.dxf` 업로드 → `succeeded`, glb/dxf/json을 받을 수 있다. `tests/test_dxf_input.py`의 `not_implemented` 테스트를 이 동작으로 바꾼다(`tests/test_jobs_api.py`는 #3 담당이라 건드리지 않는다).

---

## #3 Jobs API 저장소 · 보충 입력 재생성 고도화

**배경**: 지금 작업 저장은 인메모리 + 로컬 파일이라 재시작하면 사라진다. 실행도 FastAPI `BackgroundTasks`(같은 프로세스)에서 한다. 보충 입력의 기본 의미(모델 재실행 없음, ID 불변, 마지막 성공 결과 유지, Plan 없는 작업은 409)는 확정됐고 테스트가 있다.

**건드리는 폴더**: `app/jobs/`, `app/main.py`(저장소/큐 주입부만), `tests/test_jobs_*.py`, `config/`

**할 일**
- `JobStore` 인터페이스를 분리하고 영속 구현을 추가한다(예: SQLite + 로컬 파일). 재시작 뒤에도 작업, 기준 Plan, 보충 입력 이력, 결과 파일을 복원한다.
- 작업 큐와 워커를 분리한다(프로세스 밖 실행). 동시 실행 수를 제한한다. 서버가 죽어 `running`에 멈춘 작업을 복구한다.
- 리비전별 결과 보존 정책(최근 N개)과 오래된 작업 정리(TTL).
- 업로드 크기 제한과 형식 검증 강화.
- (계약 변경 필요 → 별도 계약 PR) 요소 삭제 보충 입력, 리비전 이력 조회 API.

**완료 조건 (테스트)**
- [ ] 저장소를 다시 만든 뒤(재시작 시뮬레이션) 같은 작업 ID로 Job, Plan, 파일을 조회할 수 있고 `result_revision`도 유지된다.
- [ ] 재시작 뒤 보충 입력을 보내도 기존 요소 ID가 유지된다(`test_supplement.py`의 ID 불변 검사를 영속 저장소로도 실행).
- [ ] `running` 상태로 남은 작업은 시작 시 `failed`나 재시도로 정리되고, 마지막 성공 결과는 유지된다.
- [ ] 동시에 보충 입력을 두 번 보내면 하나만 받아들이고 다른 하나는 409 `job_busy`를 받는다.
- [ ] 보존 정책 밖의 리비전 파일이 지워져도 `result_revision`의 파일은 남아 있다.
- [ ] 기존 Jobs API 테스트가 변경 없이 통과한다.

---

## #4 모델 어댑터 (CubiCasa 베이스라인) + 전처리

**배경**: `app/models/cubicasa.py`는 자리만 있다(`NotImplementedError`). 후처리(`app/recognition/walls.py`)는 축에 평행하고 끊김 없는 Fake 마스크만 다룬다.

**건드리는 폴더**: `app/models/`(`base.py` 제외), `app/preprocess/`, `app/recognition/`, `tests/test_models.py`, `tests/test_recognition.py`, `tests/test_preprocess.py`(신규)

**할 일**
- CubiCasa5k 모델 로딩(가중치 경로는 설정이나 환경변수로 받는다), 추론, 출력 → `WallMask` / `OpeningDetection` 변환.
- torch 같은 무거운 의존성은 optional extra(`pip install .[cubicasa]`)로 둔다. 기본 설치와 CI는 영향받지 않아야 한다.
- 치수 OCR `DimensionReader` 구현을 하나 이상 추가한다(엔진은 자유).
- 전처리: 기울기 보정, 잡음 제거, 이진화, 해상도 정규화.
- 후처리 견고화: 개구부 때문에 끊긴 벽 이어 붙이기, 사선 벽, 잡음 마스크.

**완료 조건 (테스트)**
- [ ] 기본 `pytest`는 Fake만으로 통과하고 torch를 import하지 않는다.
- [ ] CubiCasa 출력 → 인터페이스 변환 함수는 합성 텐서(가짜 모델 출력)로 단위 테스트한다.
- [ ] 실제 가중치 테스트는 `@pytest.mark.model`로 표시하고, `AUTOBIM_CUBICASA_WEIGHTS`가 있을 때만 실행한다.
- [ ] 전처리: 코드로 만든 기울어진(예: 3°) 합성 평면도를 보정하면 벽 선분 각도 오차가 0.5° 이하다.
- [ ] 후처리: 개구부 간격이 있는 합성 마스크 → 벽 하나로 이어지고, 개구부가 그 벽에 붙는다.
- [ ] 가중치 파일은 커밋하지 않는다(받는 방법은 README에 적는다).

---

## #5 평가 하네스 (AI Hub COCO → 정답 마스크, IoU)

**배경**: 모델과 후처리 품질을 수치로 비교할 기준이 없다.

**건드리는 폴더**: `eval/`(신규), `tests/test_eval.py`(신규). 앱 코드는 읽기만 하고 수정하지 않는다.

**할 일**
- AI Hub 평면도 COCO 어노테이션 → 클래스별 정답 마스크(벽, 문, 창) 래스터화.
- 지표: 벽 마스크 IoU, 문·창 검출 precision/recall(IoU ≥ 0.5), 선택적으로 Plan 단위 지표(벽 수, 길이 오차).
- CLI: `python -m eval.run --dataset $AUTOBIM_DATASET_DIR --wall-segmenter fake|cubicasa ...` → JSON/CSV 리포트.
- 데이터셋 경로는 환경변수나 인자로 받는다. 데이터셋은 커밋하지 않는다.

**완료 조건 (테스트)**
- [ ] 코드로 만든 작은 COCO JSON(폴리곤 2~3개)으로 래스터화 결과 픽셀 수를 검증한다.
- [ ] IoU, precision, recall을 손으로 계산한 기대값과 비교한다(완전 일치, 부분 겹침, 겹침 없음).
- [ ] Fake 모델로 합성 데이터셋에서 CLI를 끝까지 실행하면 리포트 파일이 생성된다.
- [ ] 데이터셋이 없으면 친절한 오류 메시지를 내고 종료 코드 ≠ 0.

---

## #6 배포

**배경**: Dockerfile, docker-compose, CI의 docker build/smoke는 있다. 실제 배포 대상과 설정은 아직 없다.

**건드리는 폴더**: `deploy/`(신규), `.github/workflows/`(배포 워크플로 추가, 기존 `ci.yml`의 검사는 유지), `Dockerfile`, `docker-compose.yml`

**할 일**
- 이미지 레지스트리 push(예: GHCR), 태그 규칙(main = `latest`, 태그 = 버전).
- 배포 대상 설정(환경별 env, 시크릿, 작업 데이터 볼륨). 모델 가중치는 이미지 밖(볼륨이나 다운로드)에 둔다.
- 운영 설정: uvicorn 워커 수, 업로드 크기 제한, CORS(프론트 `autobim-fe` 출처), 로그 형식.
- 헬스체크와 롤백 절차 문서화.

**완료 조건 (테스트)**
- [ ] main 머지 시 이미지가 빌드·push되고, PR에서는 push 없이 build만 한다.
- [ ] 배포 이미지에서 `/health` 200, Fake 설정으로 `POST /api/jobs` → glb 다운로드까지 smoke test가 CI에서 통과한다.
- [ ] 컨테이너가 non-root로 실행되고 작업 데이터가 볼륨에 남는다(재시작 후 파일 유지, #3 영속 저장소와 연동).
- [ ] `deploy/README.md`에 배포·롤백 절차를 적는다.
