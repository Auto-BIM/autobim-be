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

정의: `backend/app/schemas/plan.py` (Pydantic, `schema_version` 포함). 구성 요소:

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
2. **인식 모델** (`app/models/`): 아래 세 인터페이스. 구현은 설정 파일(`backend/config/settings.yaml`)로 고른다.
   - `WallSegmenter` → 벽 마스크
   - `OpeningDetector` → 문·창 박스 + 신뢰도
   - `DimensionReader` → 치수 텍스트 + 위치(치수선 양 끝 픽셀 좌표)
3. **후처리** (`app/recognition/`):
   - 마스크 → 벽 선분 (중심선 + 두께)
   - 문·창 박스 → 가장 가까운 벽에 배치 (벽 위 위치, 폭)
   - mm 환산: ① 치수 OCR ② 건물 가로 길이(보충 입력) ③ 둘 다 없으면 외벽 두께 200mm로 가정
   - 확인 필요 요소 생성: 저신뢰도 검출, 추정 축척, 기본값 적용, 벽에 붙지 않은 개구부

## 4. DXF 경로 (`app/dxf_input/`)

- ezdxf로 읽고 레이어·블록 이름으로 벽·문·창 분류
- 이중선 벽(평행선 쌍)은 중심선 + 두께로 병합
- 단위는 `$INSUNITS`로 mm 환산. 축척 추정 없음(`scale.source = "source_units"`)

## 5. 3D 생성 (`app/geometry/`)

- 벽: 중심선 양옆으로 두께 절반씩 벌린 직육면체
- 문·창 구간은 잘라내고, 문 위 상인방과 창 아래 창대(창 위 상인방 포함)만 남긴다
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

저장: 인메모리 + 로컬 파일(`AUTOBIM_DATA_DIR`, 기본 `backend/data/jobs`).

## 8. 기본값

[ASSUMPTIONS.md](ASSUMPTIONS.md)가 기준. 외벽 200mm, 내벽 120mm, 벽 높이 2400mm, 문 900×2100, 창 1200×1200.

## 9. 폴더 ↔ 담당 영역

병렬 작업 시 충돌을 피하려고 영역별로 폴더를 나눈다.

| 폴더 | 내용 | 비고 |
|---|---|---|
| `backend/app/schemas/` | Plan, API 요청/응답 모델 | **계약 — 계약 담당 PR에서만 수정** |
| `backend/app/models/base.py` | 모델 인터페이스 | **계약** |
| `backend/app/api/` | FastAPI 라우터 | 경로·형식은 계약 |
| `backend/app/jobs/` | 작업 저장소·실행기 | |
| `backend/app/models/` | Fake / CubiCasa 어댑터 / 레지스트리 | |
| `backend/app/preprocess/` | 이미지 전처리 | |
| `backend/app/recognition/` | 후처리(마스크→Plan) | |
| `backend/app/dxf_input/` | DXF 입력 경로 | |
| `backend/app/geometry/` | Plan → 3D 기하 | |
| `backend/app/export/` | glb / dxf / json 출력 | |
| `backend/eval/` | 평가 하네스 | 예정 |
| `deploy/` | 배포 설정 | 예정 |
