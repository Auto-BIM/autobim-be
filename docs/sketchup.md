# SketchUp 호환 확인 (#14)

확인일 2026-11-01, SketchUp 2025(Windows, 종류 미확인), 확장 프로그램 설치됨. 스크린샷은 커밋하지 않는다.
입력은 Auto-BIM 개인 실험 레포의 데모 아파트 파일(IFC·DXF)이며 이 레포의 `.dxf`와 구조(벽마다 블록 + 메시)가 같다.

## 쓰임새

실무 흐름은 CAD(`.dwg`)에서 도면을 그린 뒤 SketchUp에서 3D로 만들어 `.skp`로 저장하는 것이다. 이 서비스의 출력은 CAD 이후 단계인 SketchUp에서 쓰인다. 그래서 확인 대상은 SketchUp이다.

## 결과

| 형식 | 가져오기 | 벽 단위 편집 | 비고 |
|---|---|---|---|
| `.dxf` | 열림, 형상 정상 | **안 됨**: 클릭하면 전체가 한 덩어리로 선택됨 | 블록은 묶음으로 남지 않는다. 레이어는 Tags에 그대로 들어온다 |
| `.ifc` | 열림, 형상·문창 위치·높이 2400 mm 정상 | 객체는 따로 들어옴(Outliner에 `WALL_<id>`, `DOOR_<id>`가 별도 그룹). 다만 `Project > Site > Building > Level` 계층 안에 중첩돼서 클릭하면 최상위 묶음이 선택되고, 그룹을 열면 벽 단위로 선택된다 | IFC 클래스가 Tags로 들어옴(IfcProject, IfcDoor 등) |

## 이 레포의 대응

- `app/export/ifc.py`의 `write_ifc(plan, meshes, path, junctions=None)`: 벽마다 `IfcWall`(`WALL_<id>`), 개구부마다 `IfcOpeningElement`(구멍) + `IfcDoor`/`IfcWindow`(`DOOR_<id>`/`WINDOW_<id>`). 벽 3D와 같은 접합부·개구부 범위를 쓰고 벽 부피가 `build_wall_meshes`와 일치함을 테스트한다. 개구부가 잘려 나가 형상이 없으면 문·창 객체를 만들지 않는다. 아직 API·결과 파일 종류에는 연결하지 않았다(계약 변경, 별도 PR).
- `.dxf`는 바꾸지 않았다(보조 형식). 벽마다 레이어(`A-WALL-<id>`)를 두는 방법은 레이어가 벽 수만큼 늘어 실무에서 거추장스럽고, SketchUp이 블록을 합치는 문제를 레이어로 우회할 뿐이라 채택하지 않았다. `3DFACE` 옵션도 폴리페이스가 잘 들어와서 넣지 않았다.
- SketchUp에서 벽 단위 객체가 필요하면 `.ifc`를 쓴다.
- `.dxf` 빈 개구부 블록 처리는 #23에서 다룬다. 이 문서의 확인 결과를 공유한다.

## 이 레포가 만든 IFC의 사전 확인 (FreeCAD 1.1)

SketchUp 확인 전에 독립 구현인 FreeCAD 1.1(BIM, 내장 `ifcopenshell` 0.8.4, `nativeifc` 가져오기)로 데모 도면의 `.ifc`를 열었다.

- 계층: Auto-BIM(프로젝트) > Site > Building > Level 0.
- 벽 5개(`WALL_w1~w5`), 문 3개, 창 2개가 각각 이름 있는 별도 객체로 형상과 함께 열렸다. `IfcOpeningElement`는 목록에 따로 안 나온다(구멍으로 처리됨).
- `WALL_w2`는 조각 3개로 들어오고 문 폭 구간(x 2050~2950, 높이 2100 아래)이 비어 있다. 조각 부피 합은 3D 부피와 같다.
- FreeCAD가 목록에 보여 주는 벽 부피는 3D 부피에 문·창 부피를 더한 값이다(문·창을 함께 묶어 계산하는 것으로 보이며 확인은 못 함).
- FreeCAD 1.1의 기존 `importIFC`는 내장 `ifcopenshell`과 맞지 않아(`USE_BREP_DATA`) 오류가 난다. 이 레포 파일의 문제가 아니다.

## 미확인

- 이 레포가 만든 `.dxf` 자체(A-WALL/A-DOOR/A-WINDOW 레이어, 개구부 윤곽선)를 SketchUp에서 연 결과
- 이 레포가 만든 `.ifc`를 SketchUp에서 연 결과, 그 상태로 수정해 `.skp`로 저장하고 다시 내보냈을 때 객체 정보 유지 여부
- SketchUp 종류(Pro 여부): IFC 가져오기가 되므로 Pro 이상으로 보이나 본인이 모르겠다고 답했다

## 검토했으나 하지 않은 것

- `.skp` 출력: 비공개 포맷이다. 공식 C SDK는 Linux 빌드와 서버 사용 라이선스가 불확실하고, Ruby API는 SketchUp 실행이 필요하며, 오픈소스 OpenSKP는 구버전(2013~2020) 포맷만 쓴다.
- AutoCAD 호환 확인, `.dwg` 입출력: 실무에서 CAD는 도면 작성 단계라 이 서비스의 출력이 쓰이는 단계가 아니다.
- 입력 형식 변경(PDF·DWG 추가): 이미지·`.dxf`를 유지한다.
