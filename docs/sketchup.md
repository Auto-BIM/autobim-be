# SketchUp 호환 확인 (#14)

확인일 2026-11-01, SketchUp 2025(Windows, 종류 미확인), 확장 프로그램 설치됨. 스크린샷은 커밋하지 않는다.
입력은 Auto-BIM 개인 실험 레포의 데모 아파트 파일(IFC·DXF)이며 이 레포의 `.dxf`와 구조(벽마다 블록 + 메시)가 같다.

## 결과

| 형식 | 가져오기 | 벽 단위 편집 | 비고 |
|---|---|---|---|
| `.dxf` | 열림, 형상 정상 | **안 됨**: 클릭하면 전체가 한 덩어리로 선택됨 | 블록은 묶음으로 남지 않는다. 레이어는 Tags에 그대로 들어온다 |
| `.ifc` | 열림, 형상·문창 위치·높이 2400 mm 정상 | 객체는 따로 들어옴(Outliner에 `WALL_<id>`, `DOOR_<id>`가 별도 그룹). 다만 `Project > Site > Building > Level` 계층 안에 중첩돼서 클릭하면 최상위 묶음이 선택되고, 그룹을 열면 벽 단위로 선택된다 | IFC 클래스가 Tags로 들어옴(IfcProject, IfcDoor 등) |

## 이 레포의 대응

- `app/export/ifc.py`의 `write_ifc(plan, meshes, path)`: 벽마다 `IfcWall`(`WALL_<id>`), 개구부마다 `IfcOpeningElement`(구멍) + `IfcDoor`/`IfcWindow`(`DOOR_<id>`/`WINDOW_<id>`). 벽 3D와 같은 접합부·개구부 범위를 쓰고 벽 부피가 `build_wall_meshes`와 일치함을 테스트한다. 아직 API·결과 파일 종류에는 연결하지 않았다(계약 변경, 별도 PR).
- `.dxf`는 바꾸지 않았다. 벽마다 레이어(`A-WALL-<id>`)를 두는 방법은 레이어가 벽 수만큼 늘어 실무에서 거추장스럽고, SketchUp이 블록을 합치는 문제를 레이어로 우회할 뿐이라 채택하지 않았다. `3DFACE` 옵션도 폴리페이스가 잘 들어와서 넣지 않았다.
- SketchUp에서 벽 단위 객체가 필요하면 `.ifc`를 쓰고, AutoCAD에서는 `.dxf`의 레이어(`A-WALL` 등)와 벽별 블록을 쓴다.

## 미확인

- 이 레포가 만든 `.dxf` 자체(A-WALL/A-DOOR/A-WINDOW 레이어, 개구부 윤곽선)를 SketchUp에서 연 결과
- 이 레포가 만든 `.ifc`를 SketchUp·AutoCAD(`IFCIMPORT`)에서 연 결과
- SketchUp 종류(Pro 여부): IFC 가져오기가 되므로 Pro 이상으로 보이나 본인이 모르겠다고 답했다
