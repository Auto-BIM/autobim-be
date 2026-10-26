# Auto-BIM 백엔드 설계

2D 평면도(이미지 또는 DXF)를 읽어 중간 표현 **Plan**(mm)을 만들고, Plan에서 3D 모델과 CAD 파일을 만든다.

## 1. 전체 흐름

```
입력(이미지 | DXF)
   │
   ├─ 이미지 경로: 전처리 → 인식 모델(벽 마스크 · 문/창 박스 · 치수 OCR) → 후처리
   └─ DXF 경로:   ezdxf 파싱 → 레이어/블록 이름으로 분류 → 이중선 벽 병합
   │
   ▼
Plan (mm 단위 중간 표현, JSON)  ── 확인 필요 요소 → 사용자 보충 입력 → 재생성
   │
   ▼
3D 생성 (벽 직육면체, 개구부 절단, 접합부 처리)
   │
   ▼
출력: .glb (웹 3D 뷰어) · .dxf (벽별 블록) · .json (Plan)
```

## 2. Plan (중간 표현)

정의: `app/schemas/plan.py` (Pydantic, `schema_version` 포함). 구성 요소:

- **walls**: 벽 목록. 중심선 시작점·끝점, 두께, 높이, 종류(외벽/내벽/미상), 신뢰도
- **openings**: 개구부 목록. 종류(문/창), 붙은 벽 ID, 벽 위 위치, 폭, 높이, 창대 높이, 신뢰도
- **review_items**: 확인 필요 요소 목록. 요소 ID, 요소 종류, 이유(코드 + 메시지), 신뢰도
- **scale**: 크기 추정 여부. 축척을 어떻게 얻었는지(`source`)와 추정인지(`estimated`)

### 좌표·단위 규약 (계약)

| 대상 | 규약 |
|---|---|
| Plan | mm, CAD 축(x 오른쪽, **y 위쪽**), 원점은 자유(이미지 경로는 이미지 좌하단) |
| 이미지 픽셀 → Plan | 후처리에서 y축을 뒤집고 `mm_per_px`를 곱한다 |
| 개구부 위치 `position` | 벽 **시작점에서 개구부 중심까지** 중심선을 따라 잰 거리(mm) |
| 개구부 `sill_height` | 바닥에서 개구부 하단까지(mm). 문은 0 |
| .glb | glTF 규약: **m 단위, Y-up**. Plan (x, y) → glTF (x, ·, −y), 높이 → glTF Y |
| .dxf 출력 | mm, `$INSUNITS = 4`, Plan 좌표 그대로, 높이는 Z |

## 3. 이미지 경로

1. **전처리** (`app/preprocess/`): 디코딩, RGB 변환. 이후 기울기 보정·잡음 제거·해상도 정규화 추가 예정.
2. **인식 모델** (`app/models/`): 아래 세 인터페이스. 구현은 설정 파일(`config/settings.yaml`)로 고른다.
   - `WallSegmenter` → 벽 마스크
   - `OpeningDetector` → 문·창 박스 + 신뢰도
   - `DimensionReader` → 치수 텍스트 + 위치(치수선 양 끝 픽셀 좌표)
3. **후처리** (`app/recognition/`):
   - 마스크 → 벽 선분 (중심선 + 두께)
   - 문·창 박스 → 가장 가까운 벽에 배치 (벽 위 위치, 폭)
   - mm 환산: ① 치수 OCR ② 둘 다 없으면 외벽 두께 200mm로 가정. 건물 가로 길이 등 사용자 축척은 보충 입력으로 받는다(§7)
   - 확인 필요 요소 생성: 저신뢰도 검출, 추정 축척, 기본값 적용, 벽에 붙지 않은 개구부

## 4. DXF 경로 (`app/dxf_input/`)

- ezdxf로 읽고 레이어·블록 이름으로 벽·문·창 분류
- 이중선 벽(평행선 쌍)은 중심선 + 두께로 병합
- 단위는 `$INSUNITS`로 mm 환산. 축척 추정 없음(`scale.source = "source_units"`)

## 5. 3D 생성 (`app/geometry/`)

- 벽: 중심선 양옆으로 두께 절반씩 벌린 직육면체
- 문·창 구간은 잘라내고 다음만 남긴다: 문 위 상인방, 창 위 상인방 + 창 아래 창대
- L·T자 접합부: 한쪽 벽을 두께 절반만큼 늘리거나 줄여 겹침 방지 *(미구현 — next-tasks #1. 현재는 벽이 중심선 끝점에서 끝나서, 모서리 안쪽은 겹치고 바깥 모서리는 두께 절반 크기 정사각형만큼 비어 있음)*

## 6. 출력 (`app/export/`)

- **.glb**: 벽마다 노드(mesh) 하나. 웹 3D 뷰어용
- **.dxf**: 벽마다 블록 하나(polyface 메시) + INSERT. 레이어 분리: `A-WALL`, `A-DOOR`, `A-WINDOW`
- **.json**: Plan 그대로

## 7. API

비동기 작업 API (`app/api/`, `app/jobs/`). 상세: [api.md](api.md), [openapi.json](openapi.json)

- `POST /api/jobs` 업로드 → 작업 생성
- `GET /api/jobs/{id}` 상태 + Plan + 확인 필요 요소
- `POST /api/jobs/{id}/supplement` 보충 입력 → 재생성 (`revision` 증가)
- `GET /api/jobs/{id}/files/{dxf|glb|json}` 결과 파일

저장: 인메모리 + 로컬 파일(`AUTOBIM_DATA_DIR`, 기본 `data/jobs`).

### 보충 입력 → 재생성 규칙 (계약)

- 인식 모델은 **첫 리비전에서 한 번만** 돈다. 그 결과(기준 Plan)를 저장해 둔다.
- 보충 입력은 저장된 기준 Plan에 적용하고 3D/.dxf/JSON만 다시 만든다. 모델은 다시 돌지 않는다.
  - 축척 변경: 픽셀에서 나온 길이(좌표, 개구부 위치·폭, 벽 두께)에 비율을 곱해 다시 계산한다. 높이는 기본값이라 그대로 둔다.
  - 보충 입력은 누적된다. 축척은 최신 값 하나만 쓰고, 패치와 추가는 들어온 순서대로 모두 적용한다.
- **기존 요소 ID는 절대 바뀌지 않는다.** 새로 추가한 요소만 새 ID(`w<n+1>`, `o<n+1>`)를 받고, 삭제된 ID는 다시 쓰지 않는다.
- 요소 삭제(`remove`): 벽을 지우면 붙은 개구부도 함께 지워지고, 함께 지워진 ID는 `Job.removed`로 알려준다.
- 재생성 중이거나 재생성에 실패해도 마지막 성공 리비전의 `plan`과 `files`는 유지한다. 그 리비전 번호는 `Job.result_revision`이다.

## 8. 기본값

[ASSUMPTIONS.md](ASSUMPTIONS.md)가 기준. 외벽 200mm, 내벽 120mm, 벽 높이 2400mm, 문 900×2100, 창 1200×1200.

## 9. 폴더 ↔ 담당 영역

병렬 작업 시 충돌을 피하려고 영역별로 폴더를 나눈다.

| 폴더 | 내용 | 비고 |
|---|---|---|
| `app/schemas/` | Plan, API 요청/응답 모델 | **계약 — 계약 담당 PR에서만 수정** |
| `app/models/base.py` | 모델 인터페이스 | **계약** |
| `app/api/` | FastAPI 라우터 | 경로·형식은 계약 |
| `app/jobs/` | 작업 저장소·실행기 | |
| `app/models/` | Fake / CubiCasa 어댑터 / 레지스트리 | |
| `app/preprocess/` | 이미지 전처리 | |
| `app/recognition/` | 후처리(마스크→Plan) | |
| `app/dxf_input/` | DXF 입력 경로 | |
| `app/geometry/` | Plan → 3D 기하 | |
| `app/export/` | glb / dxf / json 출력 | |
| `eval/` | 평가 하네스 | 예정 |
| `deploy/` | 배포 설정 | 예정 |
