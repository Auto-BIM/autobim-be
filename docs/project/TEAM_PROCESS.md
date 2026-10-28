# 일하는 방식

> PM이 없으니 **규칙이 PM 역할을 한다.** 이 문서의 규칙만 지키면 누가 무엇을 하는지, 무엇이 끝났는지 GitHub만 보고 알 수 있다.

## 1. 역할

[ROADMAP](ROADMAP.md) §7의 제안을 킥오프에서 확정한다([DECISIONS](DECISIONS.md) P-01). 일정 관리(이 문서들 갱신, 월요일 회의 진행)는 항민이 맡는다.

## 2. 주간 리듬

| 언제 | 무엇 | 시간 |
|---|---|---|
| **월요일** | 정기 회의: ① 지난주 끝난 것(이슈 닫힘 기준) ② 이번 주 할 일·담당 ③ 막힌 것 ④ [RISKS](RISKS.md) 신호 확인 ⑤ 결정은 [DECISIONS](DECISIONS.md)에 기록 | 30분 |
| **목요일** | 비동기 점검: 각자 메신저에 세 줄(한 것 / 할 것 / 막힌 것) | 5분 |
| **금요일** | OCI에 `develop` 배포(W10부터). 공개 URL에서 한 번 눌러 본다 | 15분 |
| 게이트 날짜 | 판정자가 기준표대로 판정하고 결과를 DECISIONS·ROADMAP에 적는다 | |

소통 채널·회의 시간은 미결 O-13.

## 3. GitHub 설정 (한 번만)

- **라벨**: `P0`, `P1`, `P2`, `area:be`, `area:fe`, `area:model`, `area:deploy`, `contract`, `blocked`
- **마일스톤**: `M1 끝까지 한 번`(11/8), `M2 실제 경로`(11/15), `M3 기능 완료`(11/29), `M4 코드 완성`(12/6), `v1.0 동결`(12/11)
- **이슈**: 이슈마다 담당자 1명, 라벨, 마일스톤. 본문의 범위·완료 조건은 [next-tasks.md](../next-tasks.md)(백엔드), `autobim-fe/docs/backlog.md`(프론트)가 원본
- **브랜치 보호**(가능하면): `main`·`develop`에 PR 필수, CI 통과 필수
- 모델 레포는 GitHub에 없으므로(미결 O-06) 작업 목록은 `autobim-model/docs/backlog.md`로 관리하고, 진행 상황은 월요일 회의에서 공유한다

## 4. 이슈 → 브랜치 → PR → 머지

1. 이슈를 하나 고른다(담당이 나인 것, 마일스톤이 가까운 것부터).
2. `develop`에서 브랜치: `feature/<이슈번호>-<짧은-이름>` (예: `feature/12-recognition-v1`). 급한 수정은 `fix/…`.
3. 작게 커밋한다. 헤더는 `<type>(<scope>): <요약>`.
4. PR(`develop` 대상): 제목에 이슈 번호, 본문에 이슈의 완료 조건을 체크리스트로 옮기고 체크한다. `Closes #<번호>`.
5. **CI green + 리뷰 1명 승인** 후 사람이 머지한다(squash 권장). 에이전트는 머지하지 않는다.
6. 계약을 건드려야 하면 그 부분만 먼저 계약 PR로(AGENTS.md 규칙 2). 지금 계약 변경은 #12 (BE-N3) 하나로 모았다.

**리뷰할 때 보는 것**: 완료 조건이 테스트로 증명되는가 / 건드리는 폴더 밖을 바꿨나 / 데이터·가중치·이미지·비밀값이 들어갔나 / 계약 파일이 바뀌었나.

## 5. "끝났다"의 정의 (Definition of Done)

- [ ] 이슈의 완료 조건이 모두 체크되고, 테스트로 증명된다
- [ ] 기존 테스트와 CI가 green이다
- [ ] 문서(명세, README, api.md)가 코드와 맞다
- [ ] `develop`에 머지됐다(머지 안 된 브랜치의 일은 끝난 것이 아니다)
- [ ] 화면·배포가 있는 작업은 OCI 또는 로컬에서 실제로 눌러 봤다

## 6. Claude Code / Codex + Orca 사용 규칙

1. **이슈 하나 = worktree 하나 = 에이전트 세션 하나.** 서로 다른 이슈를 한 세션에 섞지 않는다.
2. 프롬프트는 [PROMPTS.md](PROMPTS.md)에서 복사한다. 프롬프트는 명세 문서를 가리키기만 하므로 컨텍스트가 작다.
3. 에이전트는 `develop`·`main`에 push하지 않는다. PR까지만 만들고, 사람이 diff를 읽고 머지한다.
4. 정확성이 중요한 코드(데이터셋, 평가 하네스, 계약 테스트)는 **만든 세션과 다른 세션**이 검사한다(예: Claude Code가 만들고 Codex가 감사).
5. 비밀값(AI Hub 키, OCI 키, SSH 키, `.env`)을 프롬프트에 붙여 넣지 않는다. 키가 필요한 명령은 사람이 직접 친다.
6. 에이전트가 "완료"라고 해도 완료 조건을 직접 확인한다. 특히 "테스트를 고쳐서 통과시켰다"는 경우를 의심한다.
7. 길게 막히면(같은 실패 3번) 세션을 멈추고 이슈에 상황을 적은 뒤 회의에서 다룬다.

## 7. 처음 세팅 (각자 한 번)

| 누구 | 할 일 |
|---|---|
| 전원 | GitHub `Auto-BIM` 조직 접근, 각 레포 clone, Docker Desktop 설치, 이 `docs/project/` 읽기(README의 순서) |
| 백엔드 | Python 3.11, `pip install -r requirements-dev.lock && pip install --no-deps -e .`, `pytest -q` green 확인 |
| 프론트 | Node 22, 백엔드를 `docker compose up --build`로 띄우고 `/health` 확인, `autobim-fe/docs/FRONTEND_SPEC.md` §8 |
| 모델 | 연구실 서버 conda `autobim-model`, `autobim-model/AGENTS.md` |
| 배포 | OCI VM SSH 접근(미결 O-15) |

## 8. 문서 갱신 규칙

- 범위·완료 조건을 바꾸면 이슈와 원본 문서(next-tasks.md / backlog.md)를 **같은 PR**에서 고친다.
- 일정이 바뀌면 ROADMAP 해당 주차 표를 고치고 바꾼 이유를 DECISIONS에 남긴다.
- 문서 PR도 일반 PR과 같다(리뷰 1명).
