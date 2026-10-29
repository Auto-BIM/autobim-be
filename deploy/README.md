# deploy/

OCI Always Free A1 VM(arm64, 2 OCPU, 12 GB) 한 대에서 Caddy(프론트 정적 파일 + `/api`)와 API를 띄우는 파일. 같은 파일로 노트북(Docker Desktop)에서도 띄운다.
상세 절차·전제·문제 해결은 런북 [docs/deploy-oci.md](../docs/deploy-oci.md)가 원본이고, 여기는 요약이다.

| 파일 | 역할 |
|---|---|
| `docker-compose.prod.yml` | `api`(워커 1개, `mem_limit`, 번들 읽기 전용 마운트, 볼륨 `jobs`) + `web`(caddy:2) |
| `Caddyfile` | `/api/*`·`/health` → `api:8000`, 나머지는 `/srv/fe/current` |
| `.env.example` | 호스트 경로·포트·모델 선택. `deploy/.env`로 복사해서 쓴다(커밋하지 않는다) |
| `deploy.sh [ref]` | git 갱신 → 빌드 → 재시작 → health. 기본 `develop`, 태그도 된다 |
| `smoke.sh <base_url> [image]` | 업로드 → 폴링 → glb·dxf·json 다운로드 → 크기 검사. 이미지를 안 주면 빈 PNG를 만든다 |

## 배포 (런북 §6, §9)

```bash
cd /opt/autobim/src/autobim-be
cp deploy/.env.example deploy/.env           # 처음 한 번, 값 확인
deploy/deploy.sh develop                     # 시연 기간에는 태그: deploy/deploy.sh v1.0.0
deploy/smoke.sh http://localhost
```

처음이면 프론트 자리(`/opt/autobim/fe/current`)를 먼저 만든다(런북 §6). 밖에서 `http://<공인 IP>/health`가 200이면 끝.
**시연 기간에는 재시작하지 않는다.** 작업 목록이 메모리에 있어 재시작하면 기존 작업 링크가 404가 된다.

## 모델 교체·롤백 (런북 §7)

```bash
ln -sfn seg-v1 /opt/autobim/models/current            # 교체
docker compose -f deploy/docker-compose.prod.yml restart api
deploy/smoke.sh http://localhost <도면>.png

ln -sfn seg-v0 /opt/autobim/models/current            # 롤백: 링크만 되돌리고 재시작
docker compose -f deploy/docker-compose.prod.yml restart api
```

`current` 링크만 바꾼다. 디렉터리를 `mv`로 바꾸면 bind mount가 옛 디렉터리를 계속 본다. 실제 모델 경로로 처음 바꿀 때나 `autobim_seg`의 바이너리 의존성이 바뀌었을 때는 `deploy/.env`(`EXTRAS=seg` 등)를 고치고 `deploy.sh`로 이미지를 다시 빌드한다.

## 백엔드·프론트 롤백

- 백엔드: 이전 태그로 `deploy/deploy.sh <tag>`.
- 프론트(런북 §8): `ln -sfn releases/<이전 폴더> /opt/autobim/fe/current`. 재시작은 필요 없다.

## 백업 (런북 §9, §10)

OCI 콘솔 → Block Storage → Boot Volumes → 이 VM 부트 볼륨 → Create manual backup. 시점은 런북을 따른다(G4, 시연 전날).

## 노트북에서 띄우기 (런북 §11)

Docker Desktop은 기본적으로 `/opt`를 공유하지 않으므로 홈 아래 경로를 쓰고, 포트를 비켜 준다.

```bash
cp deploy/.env.example deploy/.env
# deploy/.env: HTTP_PORT=8080, HTTPS_PORT=8443,
#              MODELS_DIR=/Users/<me>/autobim/models, FE_DIR=/Users/<me>/autobim/fe
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build
deploy/smoke.sh http://localhost:8080
```

## CI

`.github/workflows/ci.yml`의 `deploy-stack` 잡이 arm64 러너에서 이 compose를 Fake 모델로 띄우고 `smoke.sh`, non-root, 재시작 뒤 작업 파일 유지를 확인한다.
