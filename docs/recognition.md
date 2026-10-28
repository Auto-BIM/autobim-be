# 인식 v1 — 벽 마스크 + 개구부 박스 → Plan

> 이슈 BE-N1의 명세다. 모델 출력(픽셀)을 Plan(mm)으로 바꾸는 후처리를 정한다.
> 검증된 프로토타입이 [recognition-prototype/](recognition-prototype/)에 있다(numpy + scipy, 합성 도면 테스트 18개 통과, Fake 도면 결과 재현).
> 이식이 끝나면 프로토타입 폴더는 지운다.

## 1. 범위

| 버전 | 다루는 것 | 다루지 않는 것 |
|---|---|---|
| **v1 (P0)** | 축에 평행한 벽, 개구부로 끊긴 벽 잇기, 문이 모서리에 붙어 벽 끝을 먹은 경우, 1~2 px 끊김, 작은 잡음 덩어리, 얇은 글자 획, 외벽/내벽 판정, 벽 두께 다양(외벽 200 · 내벽 120) | 사선 벽, 곡선 벽, 기둥 구분, 계단, 치수 OCR |
| v2 (W12~) | 실제 예측 마스크 실패 사례별 수정, 파라미터 조정 | |
| v3 (P2) | 사선 벽(Hough/LSD), 치수 OCR 축척 | |

사선 벽은 v1에서 **버리되 알린다**: 설명되지 않은 벽 픽셀 비율이 5%를 넘으면 확인 필요 항목을 만든다(§5).

## 2. 입력과 출력

```
입력:  WallMask.mask           (H, W) bool          # 벽 픽셀 (seg 어댑터: labels == 1)
       list[OpeningDetection]  type, BBox(px), conf # seg 어댑터: r.openings()
출력:  list[PixelWall]         축 정렬 벽(중심선, 두께, 끝점) — 픽셀
       list[PixelOpening]      붙은 벽 번호, 벽 방향 구간 [s0, s1] — 픽셀
       kinds                   벽마다 exterior | interior
       unexplained_wall_ratio  벽 픽셀 중 어떤 벽으로도 설명되지 않은 비율
→ 기존 pipeline.image_to_plan이 축척을 정하고 mm Plan으로 바꾼다
```

모델 출력의 성질(이 알고리즘이 가정하는 것):

- 라벨 우선순위가 벽 → 문 → 창이라 **문·창 자리의 벽 마스크는 끊겨 있다.** 끊긴 구간이 곧 개구부 위치·폭이다.
- 문 박스는 문짝이 아니라 **열림 호까지 감싼 사각형**이다. 벽 방향 길이 ≈ 문 폭, 벽에 수직인 방향은 방 안쪽으로 튀어나온다. 그래서 박스 중심으로 가장 가까운 벽을 고르면 틀린다(지금 코드의 방식). 박스가 걸친 벽을 고른다.
- 창 박스는 벽 두께 안에 있다.

## 3. 알고리즘

모든 임계값은 도면마다 잰 **대표 벽 두께 `t_med`(px)**에 비례한다. 해상도·배율이 달라도 같은 파라미터가 동작한다(테스트: 배율 0.5·1·2).

| 단계 | 하는 일 | 프로토타입 함수 |
|---|---|---|
| R0 | 입력 정리: `mask`(bool), 박스 목록 | `recognize` |
| R1 | 3×3 닫힘(1 px 끊김 메움) → 연결 요소 중 면적 `< 4·t₀²`인 덩어리 제거(가구·글자 잡음) | `clean_mask` |
| R2 | 대표 두께 `t_med` = 가로·세로 **모든 연속 구간 길이 중 하위 90%의 중앙값**. 벽 단면이 가장 많은 구간이라 중앙값이 두께가 된다. R1 전후로 두 번 잰다 | `estimate_thickness` |
| R3 | 축 정렬 띠 찾기: 행마다 길이 `≥ L = max(2.5·t_med, 15)`인 구간만 남기고, 이웃 행끼리 겹치는 구간을 띠 하나로 묶는다(= 1×L 열림 연산과 같다). 세로도 같다. 띠의 두께 = 행 수, 양 끝 = 행별 끝점의 **중앙값**(글자가 붙은 몇 행에 끌려가지 않게). 두께 `< 0.4·t_med`(치수선 같은 가는 선)와 길이 ≤ 두께인 띠는 버린다 | `extract_axis_walls`, `_bands` |
| R4 | (예약) 사선 벽 — v3 | |
| R5 | **같은 선 위의 조각 잇기**: 중심이 `0.5·max(두께)` 안인 조각끼리 묶고, 정렬한 뒤 이웃 조각 사이 틈을 본다. ① 겹치면 합침 ② 틈의 50% 이상을 덮는 개구부 박스가 있으면 합치고 그 틈을 "개구부 구간"으로 기록 ③ 틈 `≤ t_med`이면 잡음 끊김으로 보고 합침 ④ 아니면 따로 둔다(진짜 끝). 합친 벽의 중심·두께는 길이 가중 평균 | `merge_collinear` |
| R6 | **접합부 맞추기**: 각 끝점이 수직 벽의 중심선에서 `t_other/2 + t_med` 안이면(그 벽이 이 벽의 중심선을 지나야 함) 그 중심선으로 옮긴다. 상대 벽이 이 벽의 선에 조금 못 미치면 상대도 늘린다(L자). L·T·+자를 모두 다룬다 | `snap_junctions`, `_snap_end` |
| R6b | **열린 끝 연장**: R6 뒤에도 아무 벽에 닿지 않은 끝이 개구부 박스로 이어지면 박스 끝까지 늘리고, 늘린 구간을 그 박스의 후보 구간으로 기록한다. 문이 모서리에 붙어 문 라벨이 이웃 벽 끝을 먹은 경우다. 그 뒤 R6을 한 번 더 | `extend_open_ends` |
| R6c | 길이 `< t_med`인 벽 제거, 정렬(가로 먼저 위→아래, 다음 세로 왼→오) | `finish_walls` |
| R7 | **외벽 판정**: 벽을 두께대로 다시 그린 마스크(R5에서 개구부를 이어 놓았으므로 외곽이 닫혀 있다)의 빈 공간 중 이미지 테두리와 이어진 영역 = 바깥. 벽의 양옆(`t/2 + max(2, 0.25·t_med)` 떨어진 곳)을 벽 길이 25·50·75% 지점에서 찍어 하나라도 바깥이면 외벽 | `classify`, `exterior_region` |
| R8 | **설명 안 된 벽 비율** = R1 마스크 중 R6c 벽들로 덮이지 않은 픽셀 / 전체 벽 픽셀 | `recognize` |
| R9 | **개구부 붙이기**: ① R5·R6b에서 이 박스가 설명한 틈이 있으면 그중 박스 폭과 가장 잘 맞는(`min/max` 비율이 큰) 것을 쓴다(`source = gap`) ② 없으면 박스가 벽 띠(±2 px)에 걸친 벽 중 벽 방향 겹침이 가장 긴 벽, 구간 = 박스를 벽 범위로 자른 것(`box`) ③ 그래도 없으면 박스 중심에서 가장 가까운 벽(`nearest`, 확인 필요 항목). 마지막으로 구간이 수직 벽의 두께 안으로 들어가면 그 면까지 잘라낸다 | `attach_openings` |
| R10 | Plan으로 변환(§4) | 기존 `image_to_plan` 수정 |

### 파라미터 (`Params`)

| 이름 | 기본값 | 단계 | 뜻 |
|---|---|---|---|
| `min_component_area_factor` | 4.0 | R1 | 면적 `< f·t²`인 덩어리 제거 |
| `run_len_factor` | 2.5 | R3 | 구간 최소 길이 `L = max(f·t_med, 15)` |
| `thin_factor` | 0.4 | R3 | 두께 `< f·t_med`인 띠 제거 |
| `collinear_tol_factor` | 0.5 | R5 | 같은 선으로 볼 중심 차 `≤ f·max(두께)` |
| `noise_gap_factor` | 1.0 | R5 | 개구부 없이도 이을 틈 `≤ f·t_med` |
| `gap_cover_ratio` | 0.5 | R5 | 박스가 틈의 이 비율 이상을 덮어야 개구부로 인정 |
| `snap_factor` | 1.0 | R6 | 끝점을 옮길 거리 `≤ t_other/2 + f·t_med` |
| `min_len_factor` | 1.0 | R6c | 길이 `< f·t_med`인 벽 제거 |

파라미터는 `config/settings.yaml`의 `recognition:` 아래로 뺀다(계약 아님). 조정은 **dev 평가 팩(tune 셋)으로만** 한다. APT100으로 조정하면 시스템 지표가 무효가 된다.

## 4. Plan으로 바꾸기

`s = mm_per_px`, `H` = 마스크 높이.

| Plan 필드 | 값 |
|---|---|
| `Wall.start`, `Wall.end` | 가로 벽 `(a, center)`, `(b, center)` / 세로 벽 `(center, a)`, `(center, b)` → `(x·s, (H − y)·s)` |
| `Wall.thickness` | `thickness · s` |
| `Wall.kind` | R7 결과 |
| `Wall.height` | 기본값 2400 |
| `Wall.confidence` | `WallMask.confidence`(모든 벽 같은 값) |
| `Opening.wall_id` | R9의 벽 |
| `Opening.position` | `((s0 + s1)/2 − a) · s` (벽 시작점 `a`에서 중심까지) |
| `Opening.width` | `(s1 − s0) · s`. 300 mm 미만 또는 5000 mm 초과면 기본값(문 900, 창 1200)으로 바꾸고 `default_value_applied` |
| `Opening.height`, `sill_height` | 기본값(문 2100·0, 창 1200·900) |
| `Opening.confidence` | 박스 신뢰도 |
| ID | 벽 `w1…`(R6c 정렬 순서), 개구부 `o1…`(박스 순서) |

축척(`_resolve_scale`)은 지금 코드를 그대로 쓴다: 치수가 없으면 **외벽 두께 중앙값 = 200 mm**로 가정하고 `scale_estimated`를 단다. R7이 외벽을 하나도 못 찾으면 `scale_unresolvable`로 실패한다(v2에서 "가장 두꺼운 25% 벽"으로 대체 검토).

## 5. 확인 필요 항목 규칙

모두 기존 `ReviewReason` 값이다. 계약 변경 없음.

| 조건 | `element_id` | `reason` | `confidence` |
|---|---|---|---|
| 치수 없이 외벽 두께로 축척 추정 | `plan` | `scale_estimated` | 0.3 (지금 코드) |
| 개구부 신뢰도 `<` 설정값(0.5) | 개구부 ID | `low_confidence` | 박스 신뢰도 |
| R9가 `nearest`로 붙임 | 개구부 ID | `unattached_opening` | 박스 신뢰도 |
| 개구부 폭이 범위 밖이라 기본값 적용 | 개구부 ID | `default_value_applied` | 박스 신뢰도 |
| 설명 안 된 벽 비율 `> 0.05` | `plan` | `other`, 메시지 "인식되지 않은 벽 영역 N%(사선 벽 등)" | `1 − 비율` |

Fake 도면에서는 지금처럼 `o3`의 `low_confidence` **하나만** 나와야 한다(`tests/test_recognition.py`).

## 6. 테스트

| 테스트 | 기대 | 위치 |
|---|---|---|
| 기존 Fake 회귀 | 벽 5개(외벽 4·내벽 1), 8000×5000 mm, 두께 200/120, 개구부 5개 폭 900·1200, 확인 항목 `o3` 하나 | `tests/test_recognition.py` (그대로 통과) |
| L자 평면, 깨끗함·잡음, 배율 0.5·1·2 | 벽 8개 위치 ±3 px, 외벽 6·내벽 2, 개구부 4개 구간 ±3 px, 두께 ±1.5 px, 설명 안 된 비율 < 5% | 프로토타입 `test_l_shaped` |
| 모델 같은 오류(가장자리 깎임·번짐, 작은 구멍, 벽에 붙은 덩어리) 10개 시드 | 위와 같음 | `test_perturbed` |
| 모서리 문(문 라벨이 이웃 벽 끝을 먹음) | 외곽 4벽이 닫히고 문은 아래 벽에, 구간이 벽 안쪽 면에서 잘림 | `test_door_at_corner` |
| 사선 벽 | 축 정렬 벽 4개만, 설명 안 된 비율 > 0.1 | `test_diagonal_wall_is_reported` |
| 실제 정답 마스크(dev 팩) | 30장 중 `succeeded` 비율, 실패 유형 목록. 수치 목표는 W10에 정한다 | `eval/`(#6) 또는 수동 |

프로토타입 실행: `cd docs/recognition-prototype && pytest -q` (scipy 필요).

## 7. 디버그 오버레이

`scripts/debug_overlay.py <image> <plan.json> -o out.png`(BE-N1에서 추가). 원본 위에 다음을 그린다.

- 벽 중심선(외벽 빨강, 내벽 파랑)과 두께 윤곽, 벽 ID
- 개구부 구간(문 초록, 창 하늘색)과 ID, `source`(gap/box/nearest)
- 확인 필요 항목이 달린 요소는 주황 테두리

픽셀 좌표는 §4의 역변환(`x_px = x_mm/s`, `y_px = H − y_mm/s`)으로 구한다. 결과 PNG는 커밋하지 않는다.

## 8. 이식 가이드 (프로토타입 → `app/recognition/`)

| 프로토타입 | 백엔드 |
|---|---|
| `PixelWall`(+ `gaps`) | `app/recognition/walls.py`의 `PixelWall`에 `gaps` 필드 추가(기존 필드·메서드 유지) |
| `Box` | `app/models/base.py`의 `OpeningDetection` 그대로 사용(계약이라 바꾸지 않음). `kind` → `type.value`, 좌표 → `bbox` |
| `estimate_thickness` · `clean_mask` · `extract_axis_walls` · `merge_collinear` · `snap_junctions` · `extend_open_ends` · `finish_walls` | `app/recognition/walls.py` |
| `classify` · `exterior_region` · `rasterize` | `app/recognition/topology.py`(새 파일) → `pipeline._classify` 대체 |
| `attach_openings` | `app/recognition/openings.py`(새 파일) → `pipeline._attach_openings` 대체 |
| `Params` | `app/core/config.py`의 `RecognitionSettings`에 필드 추가 |
| `synth.py`, `test_recog.py` | `tests/synthetic_plans.py`, `tests/test_recognition.py`에 합침 |

의존성: `scipy`를 `pyproject.toml`에 추가하고 lock 두 개를 다시 만든다(AGENTS.md 명령). aarch64 wheel 있음(2026-10-27 확인).
성능: 프로토타입은 3500×5000 마스크에서 약 1.9초(x86 2 vCPU). `_bands`의 행 단위 파이썬 반복이 대부분이다. A1에서 10초를 넘으면 run 추출을 numpy로 묶거나 배율 0.5 마스크에서 인식한 뒤 좌표에 2를 곱한다.

## 9. 알려진 한계 → v2 후보

| 한계 | 증상 | v2 방향 |
|---|---|---|
| 사선·곡선 벽 | 벽 누락, `other` 확인 항목 | 확률적 Hough / LSD로 선분 → 같은 R5~R9 |
| 두 벽이 붙어 있음(이중 벽) | 하나의 두꺼운 벽 | 띠 안의 행별 구간 수로 분리 |
| 기둥(정사각형 큰 덩어리) | 짧은 두꺼운 벽 또는 제거 | 정사각형 덩어리 분리 후 무시 |
| 외곽이 열린 도면(외벽 일부 누락) | 바깥이 안으로 새서 내벽이 외벽으로 | 바깥 영역이 전체의 90%를 넘으면 `other` 항목, 볼록 껍질로 보정 |
| 문 없이 뚫린 통로 | 벽이 두 개로 남음(맞는 동작) | — |
| 박스 없는 개구부(모델이 문을 놓침) | 벽이 끊긴 채 남음 | 사용자가 보충 입력으로 추가(P1 화면) |
