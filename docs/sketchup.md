# SketchUp 객체 편집과 IFC 출력 (#14)

IFC는 SketchUp용 주 출력이고 DXF는 보조 출력이다. Plan과 팀 3D 메시를 유지하며
벽별 IfcWall, 문·창별 IfcDoor/IfcWindow와 개구부를 출력한다. API 연결은 #38이다.

## 사용 절차

1. IFC를 가져와 Site > Building > Level 0 안에서 객체를 선택한다.
2. 벽 솔리드 정리와 바로 선택하는 편집용 SKP가 필요하면 개인 검증 도구의
   build_sketchup_model.ps1에 -EditableLayout을 지정한다.
3. 편집 SKP에서 벽·문·창을 직접 선택하고 이동한다. 면을 수정할 때는 해당 벽을
   더블클릭해 Push/Pull한다. 같은 편집 상태에서 Undo·Redo를 확인한다.
4. SKP를 저장하고 다시 연다. IFC 재출력은 원시 파일과 원본 ID를 복원한
   usable IFC를 구분한다. 원본 공간 계층은 원본 IFC에 보관한다.

DXF는 mm로 가져온 뒤 바깥 컴포넌트를 한 번 분해해 객체에 접근한다.
태그는 A-WALL·A-DOOR·A-WINDOW다. 문·창은 2D 윤곽이고 개구부가 있는 벽은
면이 분할돼 닫힌 솔리드가 아닐 수 있다. 팀 DXF 형상은 그대로 사용한다.
빈 개구부 블록의 처리 정책은 #23에서 확정한다.

## 검증 범위

- SketchUp 2027에서 합성 모델과 GT 유래 실제 도면 두 장의 객체 편집·복구,
  저장·재열기·IFC 재가져오기를 검사했다.
- 편집용 배치 129개 객체의 최상위 솔리드·형상·속성·재열기·재가져오기를 확인했다.
- 별도 PC SketchUp 2025에서 합성 모델의 선택·이동·치수 수정·SKP 재열기·IFC
  재출력을 확인했고 반환 IFC의 이름·분류·GlobalId·형상을 독립 비교했다.
- 친구 회신의 일부 Undo 칸과 개선 SKP의 2025 직접 사용성은 미확인으로 남긴다.
- 실제 도면은 GT 기반 후처리 검증이며 seg 추론 정확도 근거로 사용하지 않는다.

## 교환 한계

SketchUp IFC 재출력은 공간 트리를 추가하거나 void 관계를 제거할 수 있다.
편집용 SKP의 공간 그룹 해제 후 원시 IFC GlobalId가 재생성될 수 있어,
최종 교환 파일은 원본 이름·분류를 일대일 대응해 ID를 복원하고 형상을 검사한다.
문 이동 시 벽 개구부는 자동으로 따라가지 않는다.
친구 반환 파일은 시험 이동·추가 도형·공간 계층 지적이 남은 검증 증거다.

개인 검증 근거는
https://github.com/Nonmaju/auto-bim_personal-repo/pull/21 와
https://github.com/Nonmaju/auto-bim_personal-repo/pull/23 를 참조한다.
원본·파생 도면·모델·캡처는 커밋하지 않고 집계·SHA만 공개한다.


## 검증 자료와 도구 위치

현재 담당: Codex (2026-11-11). 개인 인수 PR #24는 사용자 머지 완료다.
아래 링크는 구현·검증 시점을 고정한 개인 레포 자료다. 팀 서버에는 데스크톱
SketchUp 실행이나 SKP 변환을 연결하지 않는다.

- [최종 인수와 미확인 항목](https://github.com/Nonmaju/auto-bim_personal-repo/blob/066e985200fe3fbbee7e457b6a12a7b85eba9ce5/proposals/issue14/sketchup-acceptance.md)
- [실제 도면 두 건의 집계](https://github.com/Nonmaju/auto-bim_personal-repo/blob/066e985200fe3fbbee7e457b6a12a7b85eba9ce5/proposals/issue14/real-plan-validation-20261110.md)
- [친구 2025 반환 IFC 검사](https://github.com/Nonmaju/auto-bim_personal-repo/blob/066e985200fe3fbbee7e457b6a12a7b85eba9ce5/proposals/issue14/friend-return-validation-20261111.md)
- [편집 SKP 생성 명령과 교환 절차](https://github.com/Nonmaju/auto-bim_personal-repo/blob/066e985200fe3fbbee7e457b6a12a7b85eba9ce5/proposals/issue14/sketchup-import-procedure.md)
- [Windows 도구 소스](https://github.com/Nonmaju/auto-bim_personal-repo/blob/066e985200fe3fbbee7e457b6a12a7b85eba9ce5/scripts/build_sketchup_model.ps1)
- [Linux/Docker 검사와 팀 적용안](https://github.com/Nonmaju/auto-bim_personal-repo/tree/066e985200fe3fbbee7e457b6a12a7b85eba9ce5/proposals/issue14/team-apply)

실제 도면·파생 모델·캡처는 작성자의 로컬 개인 레포 data/results/ 아래에 보관한다.
최종 전달은 issue14_final_20261111, 배치 개선 검사는 issue22 관련 결과 폴더이며
파일 SHA와 검증 집계만 위 인수 자료에 기록한다. 모델이나 캡처를 PR에 첨부하지 않는다.

기능 PR은 exporter를 추가하지만 현재 write_outputs와 다운로드 API를 바꾸지 않는다.
#38 계약 PR은 #14 기능 PR 머지 후에만 통합한다. 현재 작업의 다음 단계는 팀 리뷰와
CI 확인이며, 개선 SKP의 2025 직접 사용성과 친구 회신의 일부 Undo·DXF 선택 순서는
미확인으로 남는다.
