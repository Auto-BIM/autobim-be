# SketchUp 호환 확인 (#14)

확인일 2026-11-01, SketchUp 2025(Windows, 종류 미확인), 확장 프로그램 설치됨. 스크린샷은 커밋하지 않는다.
입력은 Auto-BIM 개인 실험 레포의 데모 아파트 파일(IFC·DXF)이며 이 레포의 `.dxf`와 구조(벽마다 블록 + 메시)가 같다.

## 결과

| 형식 | 가져오기 | 벽 단위 편집 | 비고 |
|---|---|---|---|
| `.dxf` | 열림, 형상 정상 | **안 됨**: 클릭하면 전체가 한 덩어리로 선택됨 | 블록은 묶음으로 남지 않는다. 레이어는 Tags에 그대로 들어온다 |
| `.ifc` | 열림, 형상·문창 위치·높이 2400 mm 정상 | 객체는 따로 들어옴(Outliner에 `WALL_<id>`, `DOOR_<id>`가 별도 그룹). 다만 `Project > Site > Building > Level` 계층 안에 중첩돼서 클릭하면 최상위 묶음이 선택되고, 그룹을 열면 벽 단위로 선택된다 | IFC 클래스가 Tags로 들어옴(IfcProject, IfcDoor 등) |

## 이 레포의 대응

- `write_dxf(..., layer_per_wall=True)`: 벽마다 레이어 `A-WALL-<id>`. SketchUp에서 벽 단위로 잡을 수 있는 것은 Tag뿐이라서 쓴다. 기본값은 `False`(레이어 3개, 이슈 #14 기준).
- `write_dxf(..., faces_3d=True)`: polyface 대신 `3DFACE`. 폴리페이스는 SketchUp 2025에서 면으로 잘 들어왔으므로 기본값은 `False`.
- 두 옵션은 아직 API·설정에 연결하지 않았다(계약 변경이 필요해서 별도 PR 대상).

## 미확인

- 이 레포가 만든 `.dxf` 자체(A-WALL/A-DOOR/A-WINDOW 레이어, 개구부 윤곽선)를 SketchUp에서 연 결과
- `layer_per_wall=True` 파일을 SketchUp에서 열었을 때 Tag별 선택
- SketchUp 종류(Pro 여부): IFC 가져오기가 되므로 Pro 이상으로 보이나 본인이 모르겠다고 답했다
