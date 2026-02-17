#!/bin/bash
#
# Выполняет деплой одного сайта (вызывается воркером из очереди).
# Предполагает: work tree готов, Dockerfile и .dockerignore созданы post-receive.
#

set -e

PAGE_HASH="$1"
[[ -n "$PAGE_HASH" ]] || { echo "Usage: $0 PAGE_HASH" >&2; exit 1; }

WORK_TREE="/opt/deploy/${PAGE_HASH}"
CONTAINER_NAME="deploy-${PAGE_HASH}"
IMAGE_NAME="deploy-${PAGE_HASH}"
REGISTRY_FILE="/opt/deploy/registry.json"
NGINX_DEPLOY_DIR="/etc/nginx/sites-available/deploy"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [deploy $PAGE_HASH] $*"; }

[[ -d "$WORK_TREE" ]] || { log "Work tree не найден"; exit 1; }

# Docker build (default builder — один общий кэш pnpm/Astro для всех воркеров)
# deploy-node/deploy-nginx — локальные образы (docker_pull_images)
log "Сборка образа..."
if ! docker build -t "$IMAGE_NAME" "$WORK_TREE"; then
  log "Ошибка сборки Docker"
  exit 1
fi

# Останавливаем старый контейнер
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

# Порт
PORT=""
if [[ -f "$REGISTRY_FILE" ]] && command -v jq >/dev/null 2>&1; then
  REG_CONTENT=$(cat "$REGISTRY_FILE" 2>/dev/null)
  [[ -n "$REG_CONTENT" && "$REG_CONTENT" == *"{"* ]] && \
    PORT="$(echo "$REG_CONTENT" | jq -r --arg h "$PAGE_HASH" '.[$h].container_port // empty' 2>/dev/null)"
fi
if [[ -z "$PORT" || "$PORT" == "null" ]]; then
  PORT=$((9000 + $(echo -n "$PAGE_HASH" | cksum | cut -d' ' -f1) % 999))
fi

# Реестр
mkdir -p "$(dirname "$REGISTRY_FILE")"
if command -v jq >/dev/null 2>&1; then
  REG_CONTENT=$(cat "$REGISTRY_FILE" 2>/dev/null)
  [[ -z "$REG_CONTENT" || "$REG_CONTENT" != *"{"* ]] && REG_CONTENT="{}"
  echo "$REG_CONTENT" | jq --arg h "$PAGE_HASH" --argjson p "$PORT" --arg n "$CONTAINER_NAME" \
    '.[$h] = {container_port: $p, container_name: $n}' > "${REGISTRY_FILE}.tmp"
  mv "${REGISTRY_FILE}.tmp" "$REGISTRY_FILE"
fi

# Запуск контейнера
log "Запуск контейнера на порту $PORT..."
docker run -d \
  --name "$CONTAINER_NAME" \
  -p "127.0.0.1:${PORT}:8000" \
  --restart unless-stopped \
  "$IMAGE_NAME"

# Nginx config
CONFIG_FILE="${NGINX_DEPLOY_DIR}/${PAGE_HASH}.conf"
mkdir -p "$NGINX_DEPLOY_DIR"
cat > "$CONFIG_FILE" << NGINXEOF
# Location для /${PAGE_HASH}
# Все пути /PAGE_HASH/* идут в контейнер (в т.ч. /_astro/, assets)
# Astro требует base: '/PAGE_HASH/' в astro.config
location /${PAGE_HASH}/ {
    proxy_pass http://127.0.0.1:${PORT}/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
    rewrite ^/${PAGE_HASH}(/.*)\$ \$1 break;
}

location = /${PAGE_HASH} {
    return 301 /${PAGE_HASH}/;
}
NGINXEOF

# Явный reload — path unit может не сработать сразу
nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true

log "Готово."
