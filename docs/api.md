# API 요약

전체 스펙: [openapi.json](openapi.json) — `scripts/export_openapi.py`로 생성하며,
`tests/test_contract.py`가 실제 앱과 일치하는지 검사한다. **경로·요청/응답 형식은 계약이며
계약 담당 PR에서만 바꾼다.** 서버 실행 중에는 `/docs`(Swagger UI)에서도 볼 수 있다.

## 엔드포인트

| 메서드 | 경로 | 성공 | 오류 | 설명 |
|---|---|---|---|---|
| POST | `/api/jobs` | 202 `Job` | 415, 422 | 평면도 업로드(`multipart/form-data`, 필드 `file`) → 작업 생성 |
| GET | `/api/jobs/{job_id}` | 200 `Job` | 404 | 상태, Plan, 파일 URL 조회 |
| POST | `/api/jobs/{job_id}/supplement` | 202 `Job` | 400, 404, 409, 422 | 보충 입력 → 재생성, `revision` +1 |
| GET | `/api/jobs/{job_id}/files/{kind}` | 200 파일 | 404, 409, 422 | `kind` = `dxf` \| `glb` \| `json` |
| GET | `/health` | 200 | | `{"status": "ok"}` |

입력 파일 종류는 확장자로 판별한다. `.dxf`이면 DXF 경로이고, png/jpg/jpeg/bmp/tif/tiff/webp(또는 `image/*`)이면 이미지 경로다.
DXF 경로는 아직 구현되지 않아 작업이 `failed`(`not_implemented`)로 끝난다(next-tasks #2).

## 작업 상태와 리비전

```
queued ──▶ running ──▶ succeeded
                  └──▶ failed
succeeded | failed(plan 있음) ──(supplement)──▶ queued (revision+1)
```

- `revision`: 요청된 최신 리비전. 생성 시 0이고, 보충 입력이 받아들여질 때마다 +1.
- `result_revision`: 지금 `plan`과 `files`가 속한 리비전, 즉 마지막 성공 리비전. 첫 성공 전에는 `null`.
  - 재생성 중(`queued`/`running`)이거나 재생성에 실패(`failed`)해도 **마지막 성공 결과를 유지**한다. 이때는 `result_revision < revision`.
  - `status == "succeeded"`이면 `result_revision == revision`.
- 파일은 `result_revision`이 있으면 상태와 무관하게 받을 수 있다. 없으면 409 `not_ready`.
- 보충 입력을 거절하는 경우:
  - `queued`/`running` → 409 `job_busy`
  - 한 번도 성공하지 못해 `plan`이 없음 → 409 `no_plan`
  - Plan에 없는 ID 참조 → 400 (작업은 바뀌지 않음, `revision` 그대로)

## 오류 형식

애플리케이션 오류(400/404/409/415):

```json
{ "detail": { "code": "job_not_found", "message": "job 'abc' not found" } }
```

| code | HTTP | 의미 |
|---|---|---|
| `job_not_found` | 404 | 작업 ID 없음 |
| `job_busy` | 409 | 처리 중인 작업에 보충 입력 |
| `no_plan` | 409 | 한 번도 성공하지 못한(Plan 없는) 작업에 보충 입력 |
| `not_ready` | 409 | 성공한 리비전이 없어 결과 파일 없음 |
| `unsupported_media_type` | 415 | 이미지나 .dxf가 아님 |
| `unknown_element` | 400 | 보충 입력이 Plan에 없는 벽·개구부 ID를 참조 |
| `invalid_supplement` | 400 | 보충 결과 Plan이 스키마 위반, 또는 적용할 수 없는 축척 |

요청 본문 형식 오류(422)는 FastAPI 기본 형식(`{"detail": [ ... ]}`)을 따른다.

`Job.error.code`(최신 리비전 실패 사유): `not_implemented`, `no_walls`, `scale_unresolvable`, `unknown_element`, `invalid_supplement`, `internal_error`.

## Job

```json
{
  "id": "3f2c…",
  "status": "running",
  "revision": 2,
  "result_revision": 1,
  "created_at": "2026-10-26T02:00:00Z",
  "updated_at": "2026-10-26T02:05:00Z",
  "input": { "filename": "plan.png", "type": "image", "content_type": "image/png" },
  "plan": { "...": "revision 1의 Plan" },
  "error": null,
  "files": {
    "json": "/api/jobs/3f2c…/files/json",
    "glb": "/api/jobs/3f2c…/files/glb",
    "dxf": "/api/jobs/3f2c…/files/dxf"
  }
}
```

## Plan (`schema_version` "1.0")

단위는 mm이고 축은 CAD 기준(y 위쪽)이다. 정의: `app/schemas/plan.py`. 좌표 규약은 [design.md](design.md) §2를 따른다.

```json
{
  "schema_version": "1.0",
  "units": "mm",
  "source": { "type": "image", "filename": "plan.png", "width_px": 1000, "height_px": 700 },
  "scale": { "source": "dimension", "estimated": false, "mm_per_px": 10.0 },
  "walls": [
    { "id": "w1", "start": {"x": 1000, "y": 6000}, "end": {"x": 9000, "y": 6000},
      "thickness": 200, "height": 2400, "kind": "exterior", "confidence": 0.99 }
  ],
  "openings": [
    { "id": "o4", "type": "window", "wall_id": "w1", "position": 2000,
      "width": 1200, "height": 1200, "sill_height": 900, "confidence": 0.92 }
  ],
  "review_items": [
    { "element_id": "o3", "element_kind": "opening", "reason": "low_confidence",
      "message": "door detected with low confidence", "confidence": 0.4 }
  ]
}
```

| 필드 | 값 |
|---|---|
| `scale.source` | `dimension` · `building_width` · `assumed_wall_thickness` · `user` · `source_units` |
| `scale.estimated` | 축척이 추정이면 `true`(현재 `assumed_wall_thickness`인 경우) |
| `wall.kind` | `exterior` · `interior` · `unknown` |
| `opening.position` | 벽 시작점 → 개구부 **중심**까지 중심선을 따라 잰 거리(mm) |
| `opening.sill_height` | 바닥 → 개구부 하단(mm). 문은 0 |
| `review_items[].element_kind` | `wall` · `opening` · `dimension` · `plan` |
| `review_items[].reason` | `low_confidence` · `scale_estimated` · `default_value_applied` · `unattached_opening` · `dimension_conflict` · `other` |

검증 규칙: ID는 벽·개구부를 통틀어 유일해야 한다. `opening.wall_id`는 존재하는 벽이어야 한다. `review_items[].element_id`는 존재하는 요소이거나 `"plan"`이어야 한다(`dimension`은 예외). 모르는 필드가 있으면 거부한다.

**ID 규칙**: 인식 결과에는 `w1…`, `o1…`이 순서대로 붙는다. 한 작업 안에서는 보충 입력 전후로 **기존 ID가 절대 바뀌지 않는다**. 새로 추가한 요소만 새 ID(기존 최대 번호 + 1)를 받는다.

## SupplementRequest

```json
{
  "scale": { "building_width_mm": 16000 },
  "walls": [ { "id": "w4", "thickness": 150 } ],
  "openings": [ { "id": "o1", "width": 1000 } ],
  "add_walls": [ { "start": {"x": 1000, "y": 3500}, "end": {"x": 5000, "y": 3500} } ],
  "add_openings": [ { "type": "door", "wall_id": "w4", "position": 4000 } ],
  "resolved": [ "o3" ]
}
```

- **모델을 다시 돌리지 않는다.** 저장된 기준 Plan(첫 인식 결과)에 보충 입력을 적용한 뒤 glb/dxf/json만 다시 만든다.
- 보충 입력은 **누적**된다. 다시 만들 때마다 기준 Plan에서 시작해 ① 가장 최근 `scale`로 축척을 바꾸고 ② 지금까지 받은 보충 입력을 순서대로 적용한다. 각 보충 입력 안의 적용 순서는 `walls` → `openings` → `add_walls` → `add_openings` → `resolved`.
- `scale`에는 다음 중 **정확히 하나**만 넣는다.
  - `mm_per_px`
  - `building_width_mm`: 가장 바깥 벽 중심선 사이의 x 길이
  - `reference: {wall_id, length_mm}`: 인식된 벽 하나의 실제 중심선 길이
- 축척을 바꾸면 픽셀에서 나온 길이(좌표, 개구부 위치·폭, 벽 두께)만 비율대로 다시 계산한다. 높이와, 패치로 직접 넣은 값은 바뀌지 않는다.
- `add_walls`와 `add_openings`에서 생략한 치수는 [ASSUMPTIONS.md](ASSUMPTIONS.md) 기본값을 쓴다. 벽 두께는 `kind`에 따른다(기본값은 `interior`). `add_openings[].wall_id`는 이미 있는 벽이어야 한다. 같은 요청에서 추가하는 벽은 아직 ID가 없어서 참조할 수 없다.
- `resolved`에 넣은 요소와 패치로 수정한 요소는 확인 필요 목록에서 빠진다. `resolved`에는 `"plan"`도 넣을 수 있다. 축척을 정하면 축척 관련 `plan` 항목은 자동으로 빠진다.
- 요소 삭제는 아직 지원하지 않는다.

## 출력 파일

| kind | 내용 |
|---|---|
| `json` | Plan |
| `glb` | 벽마다 노드 하나(이름 = 벽 ID). m 단위, Y-up. Plan (x, y) → glTF (x, −z) |
| `dxf` | mm(`$INSUNITS=4`). 벽마다 블록 `WALL_<id>`(polyface 메시)와 INSERT 하나, 레이어 `A-WALL`. 개구부는 블록 `DOOR_<id>` / `WINDOW_<id>`(평면 윤곽)이며 레이어는 `A-DOOR` / `A-WINDOW` |
