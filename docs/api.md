# API 요약

전체 스펙: [openapi.json](openapi.json) — `backend/scripts/export_openapi.py`로 생성하며,
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

## 작업 상태

```
queued ──▶ running ──▶ succeeded
                  └──▶ failed
succeeded | failed ──(supplement)──▶ queued (revision+1)
```

- `queued` 또는 `running`인 작업에 보충 입력을 보내면 409 `job_busy`를 돌려준다.
- 보충 입력이 들어오면 `plan`과 `files`를 비우고, 다시 생성한 뒤 채운다. `plan`은 항상 현재 `revision`의 결과다.
- 파일은 `succeeded`일 때만 받을 수 있다. 그 외 상태에서는 409 `not_ready`를 돌려준다.

## 오류 형식

애플리케이션 오류(400/404/409/415):

```json
{ "detail": { "code": "job_not_found", "message": "job 'abc' not found" } }
```

| code | HTTP | 의미 |
|---|---|---|
| `job_not_found` | 404 | 작업 ID 없음 |
| `job_busy` | 409 | 처리 중인 작업에 보충 입력 |
| `not_ready` | 409 | 결과 파일 미생성(실행 중 또는 실패) |
| `unsupported_media_type` | 415 | 이미지나 .dxf가 아님 |
| `unknown_element` | 400 | 보충 입력이 Plan에 없는 벽·개구부 ID를 참조 |
| `invalid_supplement` | 400 | 보충 결과 Plan이 스키마 위반 |

요청 본문 검증 오류(422)는 FastAPI 기본 형식(`{"detail": [ ... ]}`)을 따른다.

`Job.error.code`(작업 실패 사유): `not_implemented`, `no_walls`, `scale_unresolvable`, `unknown_element`, `invalid_supplement`, `internal_error`.

## Job

```json
{
  "id": "3f2c…",
  "status": "succeeded",
  "revision": 0,
  "created_at": "2026-10-26T02:00:00Z",
  "updated_at": "2026-10-26T02:00:01Z",
  "input": { "filename": "plan.png", "type": "image", "content_type": "image/png" },
  "plan": { "...": "Plan, 아래 참고" },
  "error": null,
  "files": {
    "json": "/api/jobs/3f2c…/files/json",
    "glb": "/api/jobs/3f2c…/files/glb",
    "dxf": "/api/jobs/3f2c…/files/dxf"
  }
}
```

## Plan (`schema_version` "1.0")

단위는 mm이고 축은 CAD 기준(y 위쪽)이다. 정의: `backend/app/schemas/plan.py`. 좌표 규약은 [design.md](design.md) §2를 따른다.

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

## SupplementRequest

```json
{
  "scale": { "building_width_mm": 16000 },
  "walls": [ { "id": "w4", "thickness": 150 } ],
  "openings": [ { "id": "o1", "width": 1000 } ],
  "resolved": [ "o3" ]
}
```

- `scale`에는 `mm_per_px`, `building_width_mm`(가장 바깥 벽 중심선 사이 x 길이), `reference: {wall_id, length_mm}` 중 **정확히 하나**만 넣는다.
- 보충 입력은 **누적**된다. 원본 입력에서 다시 인식한 뒤, 가장 최근 `scale` 하나와 지금까지 받은 모든 patch를 순서대로 적용한다.
- `resolved`에 넣은 요소와 patch로 수정한 요소는 확인 필요 목록에서 빠진다.

## 출력 파일

| kind | 내용 |
|---|---|
| `json` | Plan |
| `glb` | 벽마다 노드 하나(이름 = 벽 ID). m 단위, Y-up. Plan (x, y) → glTF (x, −z) |
| `dxf` | mm(`$INSUNITS=4`). 벽마다 블록 `WALL_<id>`(polyface 메시)와 INSERT 하나, 레이어 `A-WALL`. 개구부는 블록 `DOOR_<id>` / `WINDOW_<id>`(평면 윤곽)이며 레이어는 `A-DOOR` / `A-WINDOW` |
