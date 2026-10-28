# OCI 배포 런북 (Always Free A1)

> 이슈 #7의 명세이자 운영 절차다. OCI 콘솔 메뉴 이름은 바뀔 수 있으니 화면에서 같은 뜻의 항목을 찾는다.
> 확인된 사실의 출처: Oracle [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm) (2026-10-27 확인).

## 0. 전제와 숫자

| 항목 | 값 | 출처·비고 |
|---|---|---|
| A1 무료 한도 | 월 1,500 OCPU시간 + 9,000 GB시간 = **2 OCPU, 12 GB** 상당 | 공식 문서. VM 한 대(2 OCPU, 12 GB)로 한도를 다 쓴다 |
| 블록 스토리지 | 합계 200 GB(부트 볼륨 포함), 백업 5개 | 공식 문서. 부트 볼륨 최소 47~50 GB(문서 안에서 값이 엇갈림, 콘솔에서 확인) |
| 아웃바운드 전송 | 월 10 TB | 공식 문서 |
| 유휴 회수 | 7일 동안 **CPU 95퍼센타일 < 20%, 네트워크 < 20%, 메모리 < 20%(A1만)**이면 회수될 수 있음 | 공식 문서. 대응은 §10 |
| 유료(PAYG) 전환 | 무료 범위는 계속 무료. **회수 규칙이 달라진다는 말은 문서에 없다** | 공식 문서 |
| CPU 아키텍처 | **arm64(aarch64)**. 이미지는 VM에서 직접 빌드 | `python:3.11-slim`, onnxruntime·opencv·scipy 모두 aarch64 wheel 있음(2026-10-27 확인) |
| 계정 상태 | Always Free만인지 PAYG인지, 리전, 인스턴스 유무 | **미결 O-03** |

## 1. 서버 배치

```
OCI VM (Ubuntu, arm64, 2 OCPU, 12 GB)
├── /opt/autobim/src/autobim-be/        # git clone. deploy/ 아래 파일로 띄운다
├── /opt/autobim/src/autobim-fe/        # git clone. VM에서 빌드할 때만
├── /opt/autobim/models/
│   ├── seg-v0/ seg-v1/ ...             # 모델 번들 (연구실 서버에서 복사)
│   └── current -> seg-v1               # 상대 링크
├── /opt/autobim/fe/
│   ├── releases/20261108-1530/         # 프론트 빌드 결과 (dist 내용)
│   └── current -> releases/20261108-1530
└── docker
    ├── web  (caddy:2)   :80, :443  → /srv/fe/current, /api → api:8000
    └── api  (autobim-be) :8000      /models(ro), 볼륨 jobs
```

프론트와 모델은 **폴더를 통째로 마운트하고 `current` 링크만 바꾼다.** 디렉터리 자체를 `mv`로 바꾸면 bind mount가 옛 디렉터리를 계속 본다.

## 2. 인스턴스 만들기

1. Compute → Instances → Create instance
2. Image: **Canonical Ubuntu 22.04 또는 24.04 (aarch64)**
3. Shape: **VM.Standard.A1.Flex**, OCPU **2**, Memory **12 GB**
4. Networking: 공인 IPv4 할당. 새 VCN이면 공개 서브넷
5. SSH 키: 본인 공개 키 등록(개인 키는 레포·문서·에이전트에 넣지 않는다)
6. Boot volume: 100 GB 권장(도커 이미지 + 번들 여러 개 + 작업 파일). 무료 합계 200 GB 안에서
7. "Out of capacity" 오류가 나면 다른 가용성 도메인(AD)을 고르거나 시간을 두고 다시 시도한다

만든 뒤 기록할 것(팀 비공개 메모): 리전, 공인 IP, 인스턴스 OCID, 접속 사용자(`ubuntu`).

## 3. 네트워크 열기

1. VCN → Security List(또는 NSG) → Ingress 규칙 추가: TCP **80**, **443**, 소스 `0.0.0.0/0`. 22번은 이미 열려 있다.
2. VM 안에서 확인: `curl -I http://localhost`(스택을 띄운 뒤).
3. 밖에서 안 되면 OS 방화벽을 본다. OCI Ubuntu 이미지는 iptables에 REJECT 규칙이 있다.
   ```bash
   sudo iptables -L INPUT -n --line-numbers     # REJECT 줄 번호 확인 (예: 6)
   sudo iptables -I INPUT 6 -p tcp -m state --state NEW --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -p tcp -m state --state NEW --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```
   Docker가 공개한 포트는 보통 FORWARD 체인의 Docker 규칙으로 통과한다. 그래도 막히면 `sudo iptables -L FORWARD -n --line-numbers`도 본다.

## 4. 서버 기본 설정

```bash
sudo apt update && sudo apt -y upgrade
sudo timedatectl set-timezone Asia/Seoul
sudo apt -y install git curl rsync unattended-upgrades

# 스왑 4 GB (메모리 12 GB의 안전판)
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Docker (공식 설치 스크립트) + compose 플러그인
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"     # 다시 로그인해야 적용

sudo mkdir -p /opt/autobim/{src,models,fe/releases} && sudo chown -R "$USER" /opt/autobim
git clone https://github.com/Auto-BIM/autobim-be /opt/autobim/src/autobim-be
```

## 5. 스택 파일 (`deploy/`, 이슈 #7에서 레포에 추가)

### `deploy/docker-compose.prod.yml`

```yaml
name: autobim                          # 컨테이너·볼륨 이름 접두어 (autobim-api-1, autobim_jobs)

services:
  api:
    build:
      context: ..
      args:
        EXTRAS: ${EXTRAS:-}            # 실제 경로: seg (onnxruntime 등, 이슈 #5)
    image: autobim-be:prod
    restart: unless-stopped
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
    environment:
      AUTOBIM_WALL_SEGMENTER: ${AUTOBIM_WALL_SEGMENTER:-fake}
      AUTOBIM_OPENING_DETECTOR: ${AUTOBIM_OPENING_DETECTOR:-fake}
      AUTOBIM_DIMENSION_READER: ${AUTOBIM_DIMENSION_READER:-none}
      AUTOBIM_SEG_BUNDLE: /models/current
      AUTOBIM_SEG_THREADS: "2"
      PYTHONPATH: /app:/models/current/pkg
    volumes:
      - jobs:/data/jobs
      - ${MODELS_DIR:-/opt/autobim/models}:/models:ro
    expose: ["8000"]
    mem_limit: 6g

  web:
    image: caddy:2
    restart: unless-stopped
    depends_on: [api]
    ports:
      - "${HTTP_PORT:-80}:80"
      - "${HTTPS_PORT:-443}:443"
    environment:
      SITE_ADDRESS: ${SITE_ADDRESS:-:80}
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ${FE_DIR:-/opt/autobim/fe}:/srv/fe:ro
      - caddy_data:/data
      - caddy_config:/config

volumes:
  jobs: {}
  caddy_data: {}
  caddy_config: {}
```

- **워커는 1개.** 작업 저장소가 메모리에 있어서 워커가 둘이면 조회가 404가 된다(SYSTEM_SPEC §9).
- 실제 경로에서는 `AUTOBIM_DIMENSION_READER=none`. Fake 치수 리더가 켜져 있으면 모든 도면이 "8,000 mm"로 축척된다.
- `PYTHONPATH`에 번들의 `pkg/`를 넣어 `import autobim_seg`가 번들과 짝인 코드를 쓰게 한다. onnxruntime 같은 바이너리 의존성은 이미지(`EXTRAS=seg`)에 들어 있다.

### `deploy/Caddyfile`

```caddyfile
{$SITE_ADDRESS} {
	encode zstd gzip

	handle /api/* {
		request_body {
			max_size 30MB
		}
		reverse_proxy api:8000
	}

	handle /health {
		reverse_proxy api:8000
	}

	# 디버깅할 때만 열기
	# handle /docs* {
	# 	reverse_proxy api:8000
	# }
	# handle /openapi.json {
	# 	reverse_proxy api:8000
	# }

	handle {
		root * /srv/fe/current
		try_files {path} /index.html
		file_server
	}

	log {
		output stdout
	}
}
```

`SITE_ADDRESS=:80`이면 IP로 HTTP만 연다. 도메인이 있으면 `SITE_ADDRESS=autobim.example.com`으로 바꾸고 DNS A 레코드를 VM 공인 IP로 맞추면 Caddy가 HTTPS 인증서를 자동으로 받는다(80·443이 열려 있어야 한다). 도메인 여부는 미결 O-04.

### `deploy/.env.example` (복사해서 `deploy/.env`로. `.env`는 커밋하지 않는다)

```dotenv
SITE_ADDRESS=:80
HTTP_PORT=80
HTTPS_PORT=443
MODELS_DIR=/opt/autobim/models
FE_DIR=/opt/autobim/fe
EXTRAS=
AUTOBIM_WALL_SEGMENTER=fake
AUTOBIM_OPENING_DETECTOR=fake
AUTOBIM_DIMENSION_READER=none
```

### `deploy/smoke.sh`

```bash
#!/usr/bin/env bash
# 사용: deploy/smoke.sh http://<host> path/to/plan.png
set -euo pipefail
BASE=${1:?base url}; IMG=${2:?image file}
json() { python3 -c "import sys, json; print(json.load(sys.stdin)$1)"; }

curl -fsS "$BASE/health"; echo
JOB=$(curl -fsS -F "file=@${IMG}" "$BASE/api/jobs" | json '["id"]')
echo "job $JOB"
STATUS=queued
for i in $(seq 1 180); do
  STATUS=$(curl -fsS "$BASE/api/jobs/$JOB" | json '["status"]')
  [ "$STATUS" = succeeded ] && break
  if [ "$STATUS" = failed ]; then curl -fsS "$BASE/api/jobs/$JOB"; echo; exit 1; fi
  sleep 1
done
[ "$STATUS" = succeeded ] || { echo "timeout after ${i}s"; exit 1; }
for k in glb dxf json; do
  curl -fsS -o "/tmp/smoke.$k" "$BASE/api/jobs/$JOB/files/$k"
  test -s "/tmp/smoke.$k" && echo "$k $(wc -c < "/tmp/smoke.$k") bytes"
done
echo "OK (${i}s)"
```

### `deploy/deploy.sh`

```bash
#!/usr/bin/env bash
# 사용: deploy/deploy.sh [브랜치 또는 태그, 기본 develop]
set -euo pipefail
cd "$(dirname "$0")/.."
REF=${1:-develop}
set -a
# shellcheck source=/dev/null
. deploy/.env            # HTTP_PORT 등
set +a
git fetch --all --tags --prune
if git show-ref --verify --quiet "refs/remotes/origin/$REF"; then
  git checkout "$REF" && git pull --ff-only
else
  git checkout "tags/$REF"
fi
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:${HTTP_PORT:-80}/health"; then echo; exit 0; fi
  sleep 2
done
docker compose -f deploy/docker-compose.prod.yml logs --tail 100 api
exit 1
```

## 6. 첫 배포 (Fake 모델) — M1

```bash
cd /opt/autobim/src/autobim-be
cp deploy/.env.example deploy/.env           # 값 확인
mkdir -p /opt/autobim/fe/releases/empty && echo '<h1>Auto-BIM</h1>' > /opt/autobim/fe/releases/empty/index.html
ln -sfn releases/empty /opt/autobim/fe/current
deploy/deploy.sh develop
deploy/smoke.sh http://localhost some-plan.png   # 아무 PNG (Fake는 내용을 무시)
```

밖에서 `http://<공인 IP>/health` → `{"status": "ok", ...}`이면 끝.

## 7. 모델 번들 올리기 · 교체 · 롤백

번들 형식은 [project/SYSTEM_SPEC.md](project/SYSTEM_SPEC.md) §3.1. 번들의 원본은 연구실 서버에 있다.

```bash
# 1) 복사 (연구실 서버 또는 노트북에서). 연구실 → OCI 직접 전송이 막혀 있으면 노트북을 거친다 (미결 O-12)
rsync -av seg-v1/ ubuntu@<공인 IP>:/opt/autobim/models/seg-v1/

# 2) VM에서 검사
cd /opt/autobim/models/seg-v1 && sha256sum -c SHA256SUMS

# 3) 처음 한 번: 실제 경로로 전환 (deploy/.env)
#    EXTRAS=seg, AUTOBIM_WALL_SEGMENTER=seg, AUTOBIM_OPENING_DETECTOR=seg, AUTOBIM_DIMENSION_READER=none
#    → deploy/deploy.sh (이미지 다시 빌드)

# 4) 교체
ln -sfn seg-v1 /opt/autobim/models/current
docker compose -f /opt/autobim/src/autobim-be/deploy/docker-compose.prod.yml restart api
curl -fsS http://localhost/health        # "model": "seg-v1" 확인 (#12 (BE-N3) 이후)
/opt/autobim/src/autobim-be/deploy/smoke.sh http://localhost <tune 도면>.png

# 5) 롤백: 링크만 되돌리고 재시작
ln -sfn seg-v0 /opt/autobim/models/current && docker compose ... restart api
```

`autobim_seg` 버전이 바뀌어 바이너리 의존성(onnxruntime 버전 등)이 달라졌다면 3)처럼 이미지를 다시 빌드한다. 번들의 `model.json`과 패키지 버전이 안 맞으면 앱이 시작하지 않는다(이슈 #5).

## 8. 프론트 배포

VM에서 빌드하는 방법(노드 설치 불필요):

```bash
cd /opt/autobim/src && git clone https://github.com/Auto-BIM/autobim-fe   # 처음 한 번 (비공개 레포면 배포 키 필요)
cd autobim-fe && git pull --ff-only
TS=$(date +%Y%m%d-%H%M)
docker run --rm -v "$PWD":/app -w /app node:22-alpine sh -c "npm ci && npm run build"
mkdir -p /opt/autobim/fe/releases/$TS && cp -r dist/. /opt/autobim/fe/releases/$TS/
ln -sfn releases/$TS /opt/autobim/fe/current     # 즉시 반영, 재시작 불필요
```

노트북에서 빌드했다면 `rsync -av dist/ ubuntu@<IP>:/opt/autobim/fe/releases/$TS/` 후 같은 `ln -sfn`. 롤백은 링크를 이전 폴더로.

## 9. 운영

| 할 일 | 명령 |
|---|---|
| 상태 | `docker compose -f deploy/docker-compose.prod.yml ps`, `docker stats --no-stream` |
| 로그 | `docker compose -f deploy/docker-compose.prod.yml logs -f --tail 200 api` |
| 백엔드 갱신 | `deploy/deploy.sh develop` (시연 기간에는 태그: `deploy/deploy.sh v1.0.0`) |
| 디스크 | `df -h /`, `docker system df`. 오래된 이미지 정리 `docker image prune -f` |
| 작업 파일 | TTL 정리(#13 (BE-N4)) 전에는 `docker volume inspect autobim_jobs`로 경로를 찾아 직접 확인 |
| 백업 | 콘솔 → Block Storage → Boot Volumes → 이 VM 부트 볼륨 → Create manual backup. **G4(12/11)와 시연 전날** |
| 재부팅 후 | `restart: unless-stopped`라 자동으로 뜬다. `curl localhost/health`로 확인 |

**시연 기간에는 재시작하지 않는다.** 작업 목록이 메모리에 있어서 재시작하면 미리 만든 작업 링크가 404가 된다(#4 전까지). 미리 만든 결과는 파일로도 보관한다([project/DEMO_PLAN.md](project/DEMO_PLAN.md)).

## 10. 유휴 회수 대응

규칙(공식 문서): 7일 동안 CPU 95퍼센타일, 네트워크, 메모리(A1) 사용률이 모두 20% 미만이면 회수될 수 있다. 우리 서버는 평소 대부분 쉬고 있으므로 **조건에 걸릴 수 있다고 보고** 다음을 지킨다.

1. 다시 만드는 데 1시간이 넘지 않게 한다: 설정은 전부 레포(`deploy/`), 번들은 연구실 서버, 프론트는 레포에 있다. 이 런북 §2~§8만 따라 하면 된다.
2. 부트 볼륨 백업을 G4·시연 전날 만든다(무료 5개).
3. 노트북 대체 실행(§11)을 W15에 한 번 실제로 해 본다.
4. 회수 규칙을 피하려고 의미 없는 부하를 만드는 방법은 쓰지 않는다. PAYG 전환이 회수를 막는다는 근거는 공식 문서에 없다(미결 O-03과 함께 판단).

## 11. 노트북 대체 실행 (Apple Silicon Mac도 arm64)

```bash
git clone https://github.com/Auto-BIM/autobim-be && cd autobim-be
mkdir -p ~/autobim/models ~/autobim/fe/releases
# 번들과 프론트 빌드 복사 후 링크: ~/autobim/models/current, ~/autobim/fe/current
cat > deploy/.env <<'EOF'
SITE_ADDRESS=:80
HTTP_PORT=8080
HTTPS_PORT=8443
MODELS_DIR=/Users/<me>/autobim/models
FE_DIR=/Users/<me>/autobim/fe
EXTRAS=seg
AUTOBIM_WALL_SEGMENTER=seg
AUTOBIM_OPENING_DETECTOR=seg
AUTOBIM_DIMENSION_READER=none
EOF
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build
open http://localhost:8080
```

인터넷이 없어도 동작한다(빌드는 미리 해 둔다).

## 12. 문제 해결

| 증상 | 원인 후보 | 확인 |
|---|---|---|
| 밖에서 접속 안 됨, VM 안 `curl localhost`는 됨 | 보안 목록·iptables | §3 |
| 업로드가 413 | 30 MB 초과(Caddy) 또는 픽셀 상한(#12 (BE-N3)) | 응답 `detail.code` |
| 작업이 계속 `queued` | 앞 작업이 추론 중(동시 1개) 또는 작업 스레드 죽음 | `logs api` |
| 모든 도면 크기가 같은 비율로 이상함 | `AUTOBIM_DIMENSION_READER=fake`가 켜져 있음 | `.env` |
| 앱이 시작 직후 종료 | 번들 경로·sha256·`autobim_seg` 버전 불일치 | `logs api` 첫 줄 |
| `job_not_found` | 컨테이너가 재시작됨(메모리 저장소) | `docker compose ps`의 시작 시각 |
| 메모리 부족·느림 | 큰 이미지, 동시 작업 | `docker stats`, 픽셀 상한 |
| HTTPS 인증서 실패 | DNS A 레코드, 80 포트 | `logs web` |
