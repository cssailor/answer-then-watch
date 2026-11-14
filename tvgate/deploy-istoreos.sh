#!/bin/bash
# 从 Mac 一键部署到 iStoreOS (192.168.1.10)
#
# 用法：
#   ./deploy-istoreos.sh
#   NAS=root@192.168.1.10 REMOTE_DIR=/mnt/sda1/tvgate ./deploy-istoreos.sh
#
# 第一次运行会提示输入 iStoreOS 的 root 密码（SSH 复用，只问一次）。
set -euo pipefail

NAS="${NAS:-root@192.168.1.10}"
# iStoreOS 的 /mnt 是 4MB tmpfs，重启会丢；/overlay 才是持久化分区。
REMOTE_DIR="${REMOTE_DIR:-/overlay/tvgate}"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
SSH_OPTS=(-o ControlMaster=auto -o ControlPath="/tmp/tvgate-ssh-%r@%h:%p" -o ControlPersist=10m)

echo "==> 目标：$NAS:$REMOTE_DIR"
echo "==> 检查 NAS 环境（需要输入 root 密码）"
ssh "${SSH_OPTS[@]}" "$NAS" '
  echo "--- 架构 ---"; uname -m
  echo "--- 磁盘 ---"; df -h | head -15
  echo "--- Docker ---"; docker version --format "{{.Server.Version}}" 2>/dev/null || echo "docker 不可用"
  echo "--- Compose ---"; docker compose version 2>/dev/null || docker-compose version 2>/dev/null || echo "无 compose，将用 docker run"
'

echo "==> 传输文件到 $REMOTE_DIR"
tar czf - -C "$LOCAL_DIR" \
  --exclude='./data' --exclude='./adb' --exclude='./__pycache__' \
  --exclude='./tvgate.db' --exclude='./tvgate.db-wal' --exclude='./tvgate.db-shm' \
  . | ssh "${SSH_OPTS[@]}" "$NAS" "mkdir -p '$REMOTE_DIR' && tar xzf - -C '$REMOTE_DIR'"

echo "==> 构建并启动"
ssh "${SSH_OPTS[@]}" "$NAS" "cd '$REMOTE_DIR' && sh -s" <<'REMOTE'
set -e
[ -f .env ] || cp .env.example .env
. ./.env

if docker compose version >/dev/null 2>&1; then
  echo "==> 使用 docker compose"
  docker compose up -d --build
  docker compose logs --tail=40
elif command -v docker-compose >/dev/null 2>&1; then
  echo "==> 使用 docker-compose"
  docker-compose up -d --build
  docker-compose logs --tail=40
else
  echo "==> 使用 docker run"
  docker build -t tvgate .
  docker rm -f tvgate >/dev/null 2>&1 || true
  docker run -d --name tvgate --restart unless-stopped \
    -p 8765:8765 \
    -v "$PWD/data:/app/data" \
    -v "$PWD/adb:/root/.android" \
    -v "$PWD/questions.json:/app/questions.json:ro" \
    -e TZ=Asia/Shanghai \
    tvgate --firetv "$FIRE_TV_IP" \
      --server-url "http://192.168.1.10:8765" \
      --interval "$INTERVAL" --port 8765 --db /app/data/tvgate.db
  sleep 3
  docker logs --tail=40 tvgate
fi
REMOTE

echo
echo "==> 完成"
echo "    家长端：http://192.168.1.10:8765/  （默认 PIN 1234）"
echo "    第一次连接时电视会弹 ADB 授权框，用 Fire 遥控器点「允许」"
echo "    查看日志：ssh $NAS \"cd $REMOTE_DIR && docker compose logs -f\""
