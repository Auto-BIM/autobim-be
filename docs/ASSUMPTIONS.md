# ASSUMPTIONS — 기본값

도면에서 값을 얻지 못했을 때 쓰는 기본값. 단위는 모두 mm.
이 표가 **기준(source of truth)** 이며, 코드 상수 `backend/app/core/defaults.py`와
일치하는지 `tests/test_assumptions.py`가 검사한다. 값을 바꾸려면 별도 합의가 필요하다.

| key | value | 설명 |
|---|---|---|
| exterior_wall_thickness | 200 | 외벽 두께. 이미지에 치수가 없을 때 축척 환산 기준으로도 사용 |
| interior_wall_thickness | 120 | 내벽 두께 |
| wall_height | 2400 | 벽 높이 |
| door_width | 900 | 문 폭 |
| door_height | 2100 | 문 높이 |
| window_width | 1200 | 창 폭 |
| window_height | 1200 | 창 높이 |
| window_sill_height | 900 | 창대 높이(바닥~창 하단). **추가 가정 — 확인 필요** (설계 기준 문서에 없던 값) |
