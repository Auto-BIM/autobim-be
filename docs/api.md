# API 요약

전체 스펙: [openapi.json](openapi.json) — `scripts/export_openapi.py`로 생성하며,
`tests/test_contract.py`가 실제 앱과 일치하는지 검사한다. **경로·요청/응답 형식은 계약이며
계약 담당 PR에서만 바꾼다.** 서버 실행 중에는 `/docs`(Swagger UI)에서도 볼 수 있다.

## 엔드포인트

| 메서드 | 경로 | 성공 | 오류 | 설명 |
|---|---|---|---|---|
| POST | `/api/jobs` | 202 `Job` | 413, 415, 422 | 평면도 업로드(`multipart/form-data`, 필드 `file`) → 작업 생성 |
| GET | `/api/jobs/{job_id}` | 200 `Job` | 404 | 상태, Plan, 파일 URL 조회 |
| POST | `/api/jobs/{job_id}/supplement` | 202 `Job` | 400, 404, 409, 422 | 보충 입력 → 재생성, `revision` +1 |
| GET | `/api/jobs/{job_id}/files/{kind}` | 200 파일 | 404, 409, 422 | `kind` = `dxf` \| `glb` \| `json` |
| GET | `/health` | 200 `HealthResponse` | | 상태와 설정된 모델. [아래](#health) 참고 |

입력 파일 종류는 확장자로 판별한다. `.dxf`이면 DXF 경로이고, png/jpg/jpeg/bmp/tif/tiff/webp(또는 `image/*`)이면 이미지 경로다.
DXF 경로는 아직 구현되지 않아 작업이 `failed`(`not_implemented`)로 끝난다(이슈 #3).

### 업로드 제한

`POST /api/jobs`는 작업을 만들기 전에 업로드를 검사하고, 걸리면 작업을 만들지 않는다.

| 검사 | 응답 | 상한(설정) | 환경변수 |
|---|---|---|---|
| 파일 바이트 | 413 `file_too_large` | `limits.max_upload_mb` (기본 30) | `AUTOBIM_MAX_UPLOAD_MB` |
| 이미지 픽셀 수(폭 × 높이) | 413 `image_too_large` | `limits.max_pixels` (기본 40,000,000) | `AUTOBIM_MAX_PIXELS` |
| 디코딩할 수 없는 이미지 | 415 `unsupported_media_type` | | |

- 픽셀 수는 PIL로 이미지 헤더만 읽어 판단한다(전체를 디코딩하지 않는다).
- 설정은 `config/settings.yaml`의 `limits:`에 있다.

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

애플리케이션 오류(400/404/409/413/415):

```json
{ "detail": { "code": "job_not_found", "message": "job 'abc' not found" } }
```

| code | HTTP | 의미 |
|---|---|---|
| `job_not_found` | 404 | 작업 ID 없음 |
| `job_busy` | 409 | 처리 중인 작업에 보충 입력 |
| `no_plan` | 409 | 한 번도 성공하지 못한(Plan 없는) 작업에 보충 입력 |
| `not_ready` | 409 | 성공한 리비전이 없어 결과 파일 없음 |
| `file_too_large` | 413 | 업로드한 파일이 바이트 상한 초과 |
| `image_too_large` | 413 | 이미지가 픽셀 상한 초과 |
| `unsupported_media_type` | 415 | 이미지나 .dxf가 아님, 또는 디코딩할 수 없는 이미지 |
| `unknown_element` | 400 | 보충 입력이 Plan에 없는 벽·개구부 ID를 참조 |
| `invalid_supplement` | 400 | 보충 결과 Plan이 스키마 위반, 또는 적용할 수 없는 축척 |

요청 본문 형식 오류(422)는 FastAPI 기본 형식(`{"detail": [ ... ]}`)을 따른다.

`Job.error.code`(최신 리비전 실패 사유): `not_implemented`, `no_walls`, `scale_unresolvable`, `unknown_element`, `invalid_supplement`, `internal_error`.

## /health

```json
{ "status": "ok", "wall_segmenter": "fake", "opening_detector": "fake", "model": "fake" }
```

**HealthResponse** — 값은 모두 문자열이고 항상 들어 있다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `status` | string | `"ok"` |
| `wall_segmenter` | string | 설정된 벽 분할 구현 |
| `opening_detector` | string | 설정된 개구부 검출 구현 |
| `model` | string | 모델 이름. 번들을 쓰면 번들 이름(예: `seg-v1`), Fake면 `fake` |

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
  },
  "removed": [
    { "id": "w4", "element_kind": "wall", "revision": 2, "cascade_from": null },
    { "id": "o2", "element_kind": "opening", "revision": 2, "cascade_from": "w4" }
  ]
}
```

- `removed`: `revision`까지의 보충 입력으로 지워진 요소 전체(누적). 벽을 지울 때 함께 지워진 개구부는 `cascade_from`에 그 벽 ID가 들어간다. 보충 입력의 202 응답에 이미 반영돼 있어서, 재생성이 끝나기 전에도 함께 지워진 ID를 알 수 있다.

응답 필드에서 "항상"은 값이 늘 들어 있다는 뜻이고, "null 가능"은 값 대신 `null`이 올 수 있다는 뜻이다.

**Job**

| 필드 | 타입 | 값 | 설명 |
|---|---|---|---|
| `id` | string | 항상 | 작업 ID |
| `status` | string | 항상 | `queued` · `running` · `succeeded` · `failed` |
| `revision` | int | 항상 | 요청된 최신 리비전. 생성 시 0, 보충 입력마다 +1 |
| `result_revision` | int | null 가능 | `plan`·`files`가 속한 마지막 성공 리비전. 첫 성공 전에는 `null` |
| `created_at` | string (ISO 8601) | 항상 | 생성 시각(UTC) |
| `updated_at` | string (ISO 8601) | 항상 | 마지막 상태 변경 시각(UTC) |
| `input` | `JobInput` | 항상 | 업로드한 파일 정보 |
| `plan` | `Plan` | null 가능 | `result_revision`의 Plan. 아래 [Plan](#plan-schema_version-10) 참고 |
| `error` | `JobError` | null 가능 | 최신 리비전이 실패한 이유. 성공하거나 다시 대기하면 `null` |
| `files` | object | 항상(빈 객체 가능) | 키 `json` · `glb` · `dxf` → 다운로드 경로. `result_revision`이 없으면 `{}` |
| `removed` | `RemovedElement[]` | 항상(빈 배열 가능) | 지금까지 지워진 요소 |

**JobInput**

| 필드 | 타입 | 값 | 설명 |
|---|---|---|---|
| `filename` | string | 항상 | 업로드한 파일 이름 |
| `type` | string | 항상 | `image` · `dxf` |
| `content_type` | string | null 가능 | 업로드 시 `Content-Type` |

**JobError**

| 필드 | 타입 | 값 | 설명 |
|---|---|---|---|
| `code` | string | 항상 | 실패 코드. 목록은 [오류 형식](#오류-형식) 참고 |
| `message` | string | 항상 | 사람이 읽는 설명 |

**RemovedElement**

| 필드 | 타입 | 값 | 설명 |
|---|---|---|---|
| `id` | string | 항상 | 지워진 요소 ID |
| `element_kind` | string | 항상 | `wall` · `opening` |
| `revision` | int | 항상 | 이 요소를 지운 보충 입력이 만든 리비전 |
| `cascade_from` | string | null 가능 | 벽과 함께 지워진 개구부면 그 벽 ID. 직접 지웠으면 `null` |

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

길이는 모두 mm다.

**Plan**

| 필드 | 타입 | 값 | 설명 |
|---|---|---|---|
| `schema_version` | string | 항상 | `"1.0"` |
| `units` | string | 항상 | `"mm"` |
| `source` | `PlanSource` | 항상 | 입력 파일 정보 |
| `scale` | `Scale` | 항상 | 축척을 어떻게 얻었는지 |
| `walls` | `Wall[]` | 항상(빈 배열 가능) | 벽 |
| `openings` | `Opening[]` | 항상(빈 배열 가능) | 문·창 |
| `review_items` | `ReviewItem[]` | 항상(빈 배열 가능) | 확인 필요 요소 |

**PlanSource**

| 필드 | 타입 | 값 | 설명 |
|---|---|---|---|
| `type` | string | 항상 | `image` · `dxf` |
| `filename` | string | null 가능 | 입력 파일 이름 |
| `width_px` | int | null 가능 | 이미지 폭(px). DXF는 `null` |
| `height_px` | int | null 가능 | 이미지 높이(px). DXF는 `null` |

**Scale**

| 필드 | 타입 | 값 | 설명 |
|---|---|---|---|
| `source` | string | 항상 | `dimension`(치수 OCR) · `building_width`(사용자 건물 폭) · `assumed_wall_thickness`(외벽 200mm 가정) · `user`(사용자 `mm_per_px` 또는 기준 벽 길이) · `source_units`(DXF 단위) |
| `estimated` | bool | 항상 | 측정이 아니라 추정이면 `true`(현재 `assumed_wall_thickness`인 경우) |
| `mm_per_px` | number > 0 | null 가능 | 픽셀당 mm. DXF는 `null` |

**Wall**

| 필드 | 타입 | 값 | 설명 |
|---|---|---|---|
| `id` | string | 항상 | `w1`, `w2`, … |
| `start` | `{x, y}` | 항상 | 중심선 시작점 |
| `end` | `{x, y}` | 항상 | 중심선 끝점. 시작점과 같으면 안 된다(길이 0 금지) |
| `thickness` | number > 0 | 항상 | 두께 |
| `height` | number > 0 | 항상 | 높이 |
| `kind` | string | 항상 | `exterior` · `interior` · `unknown` |
| `confidence` | number 0~1 | null 가능 | 인식 신뢰도. 사용자가 추가한 벽은 `null` |

**Opening**

| 필드 | 타입 | 값 | 설명 |
|---|---|---|---|
| `id` | string | 항상 | `o1`, `o2`, … |
| `type` | string | 항상 | `door` · `window` |
| `wall_id` | string | 항상 | 이 개구부가 뚫린 벽 ID |
| `position` | number | 항상 | 벽 시작점 → 개구부 **중심**까지 중심선을 따라 잰 거리 |
| `width` | number > 0 | 항상 | 벽 방향 폭 |
| `height` | number > 0 | 항상 | 높이 |
| `sill_height` | number ≥ 0 | 항상 | 바닥 → 개구부 하단. 문은 0 |
| `confidence` | number 0~1 | null 가능 | 인식 신뢰도. 사용자가 추가한 개구부는 `null` |

**ReviewItem**

| 필드 | 타입 | 값 | 설명 |
|---|---|---|---|
| `element_id` | string | 항상 | 벽·개구부 ID. 도면 전체 문제면 `"plan"` |
| `element_kind` | string | 항상 | `wall` · `opening` · `dimension` · `plan` |
| `reason` | string | 항상 | `low_confidence` · `scale_estimated` · `default_value_applied` · `unattached_opening` · `dimension_conflict` · `other` |
| `message` | string | 항상(빈 문자열 가능) | 사람이 읽는 설명 |
| `confidence` | number 0~1 | 항상 | 관련 신뢰도 |

검증 규칙: ID는 벽·개구부를 통틀어 유일해야 한다. `opening.wall_id`는 존재하는 벽이어야 한다. `review_items[].element_id`는 존재하는 요소이거나 `"plan"`이어야 한다(`dimension`은 예외). 모르는 필드가 있으면 거부한다.

**ID 규칙**: 인식 결과에는 `w1…`, `o1…`이 순서대로 붙는다. 한 작업 안에서는 보충 입력 전후로 **기존 ID가 절대 바뀌지 않는다**. 새로 추가한 요소만 새 ID(지금까지 쓴 최대 번호 + 1)를 받는다. **삭제된 ID는 다시 쓰지 않는다.**

## SupplementRequest

```json
{
  "scale": { "building_width_mm": 16000 },
  "walls": [ { "id": "w4", "thickness": 150 } ],
  "openings": [ { "id": "o1", "width": 1000 } ],
  "remove": [ "w5", "o4" ],
  "add_walls": [ { "start": {"x": 1000, "y": 3500}, "end": {"x": 5000, "y": 3500} } ],
  "add_openings": [ { "type": "door", "wall_id": "w4", "position": 4000 } ],
  "resolved": [ "o3" ]
}
```

- **모델을 다시 돌리지 않는다.** 저장된 기준 Plan(첫 인식 결과)에 보충 입력을 적용한 뒤 glb/dxf/json만 다시 만든다.
- 보충 입력은 **누적**된다. 다시 만들 때마다 기준 Plan에서 시작해 ① 가장 최근 `scale`로 축척을 바꾸고 ② 지금까지 받은 보충 입력을 순서대로 적용한다. 각 보충 입력 안의 적용 순서는 `walls` → `openings` → `remove` → `add_walls` → `add_openings` → `resolved`.
- `scale`에는 다음 중 **정확히 하나**만 넣는다.
  - `mm_per_px`
  - `building_width_mm`: 가장 바깥 벽 중심선 사이의 x 길이
  - `reference: {wall_id, length_mm}`: 인식된 벽 하나의 실제 중심선 길이
- 축척을 바꾸면 픽셀에서 나온 길이(좌표, 개구부 위치·폭, 벽 두께)만 비율대로 다시 계산한다. 높이와, 패치로 직접 넣은 값은 바뀌지 않는다.
- `add_walls`와 `add_openings`에서 생략한 치수는 [ASSUMPTIONS.md](ASSUMPTIONS.md) 기본값을 쓴다. 벽 두께는 `kind`에 따른다(기본값은 `interior`). `add_openings[].wall_id`는 이미 있는 벽이어야 한다. 같은 요청에서 추가하는 벽은 아직 ID가 없어서 참조할 수 없다.
- `resolved`에 넣은 요소와 패치로 수정한 요소는 확인 필요 목록에서 빠진다. `resolved`에는 `"plan"`도 넣을 수 있다. 축척을 정하면 축척 관련 `plan` 항목은 자동으로 빠진다.
- `remove`: 지울 벽·개구부 ID 목록.
  - 벽을 지우면 그 벽에 붙은 개구부도 **함께 지워진다**. 함께 지워진 ID는 응답 `Job.removed`에 `cascade_from`과 함께 나온다. `remove`에 직접 넣은 개구부는 그 벽과 같이 지워져도 `cascade_from = null`이다.
  - 지운 요소의 확인 필요 항목도 같이 빠진다.
  - 없는 ID나 이미 지운 ID를 지우려 하면 400 `unknown_element`. 이후 보충 입력에서 지운 요소를 patch, 참조, `resolved`해도 마찬가지다.
  - 지운 ID는 다시 쓰지 않는다. `w5`를 지운 뒤 벽을 추가하면 `w6`이 된다.

요청 필드에서 "선택"은 생략하거나 `null`로 보낼 수 있다는 뜻이다. 모든 객체는 정의되지 않은 필드가 있으면 422로 거부한다.

**SupplementRequest** — 모든 필드가 선택이다. 빈 객체 `{}`도 받는다.

| 필드 | 타입 | 기본 | 설명 |
|---|---|---|---|
| `scale` | `ScaleHint` | `null` | 축척 지정 |
| `walls` | `WallPatch[]` | `[]` | 기존 벽 수정 |
| `openings` | `OpeningPatch[]` | `[]` | 기존 개구부 수정 |
| `remove` | string[] | `[]` | 지울 벽·개구부 ID |
| `add_walls` | `NewWall[]` | `[]` | 벽 추가 |
| `add_openings` | `NewOpening[]` | `[]` | 개구부 추가 |
| `resolved` | string[] | `[]` | 확인 완료한 요소 ID(`"plan"` 가능) |

**ScaleHint** — 셋 중 **정확히 하나**만 넣는다. 0개나 2개 이상이면 422.

| 필드 | 타입 | 설명 |
|---|---|---|
| `mm_per_px` | number > 0 | 픽셀당 mm. 이미지 입력에서만 쓸 수 있다(DXF면 400 `invalid_supplement`) |
| `building_width_mm` | number > 0 | 가장 바깥 벽 중심선 사이의 x 길이 |
| `reference` | `{wall_id: string, length_mm: number > 0}` | 인식된 벽 하나의 실제 중심선 길이. 없는 벽이면 400 `unknown_element` |

**WallPatch** — `id`만 필수. 넣은 필드만 바뀌고, 생략하거나 `null`이면 그대로 둔다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | string | 필수 | 수정할 벽 ID |
| `thickness` | number > 0 | 선택 | 두께 |
| `height` | number > 0 | 선택 | 높이 |
| `kind` | string | 선택 | `exterior` · `interior` · `unknown` |

벽 위치(`start`/`end`)는 패치로 바꿀 수 없다. `remove`로 지우고 `add_walls`로 다시 추가한다(새 ID를 받는다).

**OpeningPatch** — `id`만 필수. 넣은 필드만 바뀐다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | string | 필수 | 수정할 개구부 ID |
| `type` | string | 선택 | `door` · `window` |
| `wall_id` | string | 선택 | 다른 벽으로 옮김. 이미 있는 벽이어야 한다 |
| `position` | number | 선택 | 벽 시작점 → 중심 거리 |
| `width` | number > 0 | 선택 | 폭 |
| `height` | number > 0 | 선택 | 높이 |
| `sill_height` | number ≥ 0 | 선택 | 창대 높이 |

`type`만 바꿔도 크기와 창대 높이는 자동으로 바뀌지 않는다. 필요하면 함께 보낸다.

**NewWall**

| 필드 | 타입 | 필수 | 생략 시 |
|---|---|---|---|
| `start` | `{x, y}` | 필수 | |
| `end` | `{x, y}` | 필수 | 시작점과 같으면 400 `invalid_supplement` |
| `kind` | string | 선택 | `interior` |
| `thickness` | number > 0 | 선택 | `kind`가 `exterior`면 200, 아니면 120 |
| `height` | number > 0 | 선택 | 2400 |

**NewOpening**

| 필드 | 타입 | 필수 | 생략 시 |
|---|---|---|---|
| `type` | string | 필수 | `door` · `window` |
| `wall_id` | string | 필수 | 이미 있는 벽(같은 요청에서 추가한 벽은 안 됨) |
| `position` | number | 필수 | 벽 시작점 → 중심 거리 |
| `width` | number > 0 | 선택 | 문 900 · 창 1200 |
| `height` | number > 0 | 선택 | 문 2100 · 창 1200 |
| `sill_height` | number ≥ 0 | 선택 | 문 0 · 창 900 |

추가한 요소의 `confidence`는 `null`이다. 기본값의 출처는 [ASSUMPTIONS.md](ASSUMPTIONS.md)다.

## 출력 파일

| kind | 내용 |
|---|---|
| `json` | Plan |
| `glb` | 벽마다 노드 하나(이름 = 벽 ID). m 단위, Y-up. Plan (x, y) → glTF (x, −z) |
| `dxf` | mm(`$INSUNITS=4`). 벽마다 블록 `WALL_<id>`(polyface 메시)와 INSERT 하나, 레이어 `A-WALL`. 개구부는 블록 `DOOR_<id>` / `WINDOW_<id>`(평면 윤곽)이며 레이어는 `A-DOOR` / `A-WINDOW` |
