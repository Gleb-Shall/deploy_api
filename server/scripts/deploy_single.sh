#!/bin/bash
#
# deploy_single.sh — деплой одного сайта из work tree.
# Вызывается deploy_worker или напрямую из rollback/forward скриптов.
#
# Использование: deploy_single.sh <slug> [deploy_id]
# Пример:        deploy_single.sh barbershop-lysinka-29a7160d
#
# Env vars:
#   TARGET_SHA  — если указан и образ deploy-<slug>:<sha> существует,
#                 docker build пропускается (instant rollback via layer cache)
#   WORKER_ID   — номер воркера для выбора очереди портов
#

set -eo pipefail

SITE_PATH="$1"
DEPLOY_ID="$2"
[[ -n "$SITE_PATH" ]] || { echo "Usage: $0 SLUG [DEPLOY_ID]" >&2; exit 1; }

TARGET_SHA="${TARGET_SHA:-}"

WORK_TREE="${SITES_BASE:-/opt/deploy}/${SITE_PATH}"
CONTAINER_NAME="deploy-${SITE_PATH}"
IMAGE_NAME="deploy-${SITE_PATH}"
REGISTRY_FILE="${SITES_BASE:-/opt/deploy}/registry.json"
PORTS_QUEUE_EVEN="${SITES_BASE:-/opt/deploy}/ports_queue_even.txt"
PORTS_QUEUE_ODD="${SITES_BASE:-/opt/deploy}/ports_queue_odd.txt"
NGINX_DEPLOY_DIR="/etc/nginx/sites-available/deploy"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
DOMAIN="${DOMAIN:-automatoria.ru}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGE_PORTS_SCRIPT="${SCRIPT_DIR}/manage_ports_queue.sh"

if [[ "$WORKER_ID" =~ -2$ ]] || [[ "$WORKER_ID" =~ worker-?2 ]]; then
  PORTS_QUEUE_FILE="$PORTS_QUEUE_ODD"
else
  PORTS_QUEUE_FILE="$PORTS_QUEUE_EVEN"
fi

if [[ -n "$DEPLOY_ID" ]]; then
  REDIS_RESULT_KEY="deploy:done:${SITE_PATH}:${DEPLOY_ID}"
else
  REDIS_RESULT_KEY="deploy:done:${SITE_PATH}"
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [deploy ${SITE_PATH}] $*"; }

notify_deploy_done() {
  local status="$1"
  redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" LPUSH "${REDIS_RESULT_KEY}" "$status" >/dev/null 2>&1 || true
}

trap 'notify_deploy_done "failed"' ERR

[[ -d "$WORK_TREE" ]] || { log "Work tree не найден: $WORK_TREE"; exit 1; }

# ── Docker build с layer cache ─────────────────────────────────────────────────
#
# Логика:
# 1. Если TARGET_SHA задан и образ IMAGE_NAME:TARGET_SHA уже существует локально —
#    пропускаем build, просто используем кешированный образ.
# 2. Иначе — собираем образ и тегируем его текущим HEAD SHA.
#
# Благодаря этому rollback к любой предыдущей версии — мгновенный,
# если образ этой версии уже собирался раньше.

SKIP_BUILD=false

if [[ -n "$TARGET_SHA" ]]; then
  if docker image inspect "${IMAGE_NAME}:${TARGET_SHA}" >/dev/null 2>&1; then
    log "Docker cache hit: ${IMAGE_NAME}:${TARGET_SHA} — пропускаем сборку"
    docker tag "${IMAGE_NAME}:${TARGET_SHA}" "${IMAGE_NAME}:latest"
    SKIP_BUILD=true
  else
    log "Docker cache miss для SHA ${TARGET_SHA} — собираем образ"
  fi
fi

if ! $SKIP_BUILD; then
  log "Сборка Docker образа..."
  tmpout="${WORK_TREE}/.build_out.$$"

  # BuildKit для эффективного кеширования слоёв
  DOCKER_BUILDKIT=1 docker build \
    --cache-from "${IMAGE_NAME}:latest" \
    -t "${IMAGE_NAME}:latest" \
    "$WORK_TREE" 2>&1 | tee "$tmpout"
  build_rc=${PIPESTATUS[0]}

  if [[ $build_rc -ne 0 ]]; then
    log "Ошибка сборки Docker"
    if [[ -s "$tmpout" ]]; then
      ( printf 'failed\n'; cat "$tmpout" ) | \
        redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -x LPUSH "$REDIS_RESULT_KEY" >/dev/null 2>&1 || true
      cat "$tmpout" >&2
    else
      notify_deploy_done "failed"
    fi
    rm -f "$tmpout"
    exit 1
  fi
  rm -f "$tmpout"

  # Тегируем текущий HEAD SHA для будущих rollback'ов
  CURRENT_SHA=$(git -C "${GIT_BASE:-/home/git/sites}/${SITE_PATH}.git" rev-parse refs/heads/main 2>/dev/null || echo "")
  if [[ -n "$CURRENT_SHA" ]]; then
    docker tag "${IMAGE_NAME}:latest" "${IMAGE_NAME}:${CURRENT_SHA}" 2>/dev/null || true
    log "Образ тегирован: ${IMAGE_NAME}:${CURRENT_SHA}"
  fi
fi

# Extract CSS bundle → Redis
CSS_BUNDLE=$(docker run --rm --entrypoint cat "${IMAGE_NAME}:latest" /css_bundle.txt 2>/dev/null || echo "")
if [[ -n "$CSS_BUNDLE" ]]; then
  redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" SET "css_bundle:${SITE_PATH}" "$CSS_BUNDLE" EX 2592000 >/dev/null 2>&1 || true
  log "CSS bundle сохранён (${#CSS_BUNDLE} chars)"
fi

# ── Порт ──────────────────────────────────────────────────────────────────────

return_port_to_queue() {
  local port="$1"
  [[ -z "$port" || ! "$port" =~ ^[0-9]+$ ]] && return
  if (( port % 2 == 0 )); then
    echo "$port" >> "$PORTS_QUEUE_EVEN"
  else
    echo "$port" >> "$PORTS_QUEUE_ODD"
  fi
}

OLD_PORT=""
OLD_CUSTOM_DOMAIN=""
if [[ -f "$REGISTRY_FILE" ]] && command -v jq >/dev/null 2>&1; then
  OLD_PORT=$(jq -r --arg h "$SITE_PATH" '.[$h].container_port // empty' "$REGISTRY_FILE" 2>/dev/null)
  OLD_CUSTOM_DOMAIN=$(jq -r --arg h "$SITE_PATH" '.[$h].custom_domain // empty' "$REGISTRY_FILE" 2>/dev/null)
fi

docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

is_port_available() {
  local port="$1"
  docker ps -a --format '{{.Ports}}' 2>/dev/null | grep -qE ":(127\.0\.0\.1:)?${port}->" && return 1
  ss -tuln 2>/dev/null | grep -q ":${port} " && return 1
  return 0
}

allocate_port() {
  local reg_content=""
  if [[ ! -s "$PORTS_QUEUE_EVEN" ]] || [[ ! -s "$PORTS_QUEUE_ODD" ]]; then
    "$MANAGE_PORTS_SCRIPT" init
  fi
  local port
  port=$(head -n 1 "$PORTS_QUEUE_FILE" 2>/dev/null)
  [[ -z "$port" ]] && { "$MANAGE_PORTS_SCRIPT" rebuild; port=$(head -n 1 "$PORTS_QUEUE_FILE" 2>/dev/null); }
  [[ -z "$port" || ! "$port" =~ ^[0-9]+$ ]] && { log "Не удалось выделить порт"; return 1; }
  tail -n +2 "$PORTS_QUEUE_FILE" > "${PORTS_QUEUE_FILE}.tmp" && mv "${PORTS_QUEUE_FILE}.tmp" "$PORTS_QUEUE_FILE" || true
  mkdir -p "$(dirname "$REGISTRY_FILE")"
  reg_content=$(cat "$REGISTRY_FILE" 2>/dev/null)
  [[ -z "$reg_content" || "$reg_content" != *"{"* ]] && reg_content="{}"
  echo "$reg_content" | jq --arg h "$SITE_PATH" --argjson p "$port" --arg n "$CONTAINER_NAME" \
    '.[$h] = {container_port: $p, container_name: $n}' > "${REGISTRY_FILE}.tmp"
  mv "${REGISTRY_FILE}.tmp" "$REGISTRY_FILE"
  echo "$port"
}

if [[ -n "$OLD_PORT" && "$OLD_PORT" != "null" ]] && is_port_available "$OLD_PORT"; then
  PORT="$OLD_PORT"
  log "Повторное использование порта: $PORT"
else
  [[ -n "$OLD_PORT" && "$OLD_PORT" != "null" ]] && return_port_to_queue "$OLD_PORT"
  PORT=$(allocate_port)
  [[ -n "$PORT" ]] || { log "Ошибка выделения порта"; exit 1; }
  log "Выделен порт: $PORT"
fi

# ── Запуск контейнера ─────────────────────────────────────────────────────────

log "Запуск контейнера ${CONTAINER_NAME} на порту ${PORT}..."
docker run -d \
  --name "$CONTAINER_NAME" \
  -p "127.0.0.1:${PORT}:8000" \
  --restart unless-stopped \
  "${IMAGE_NAME}:latest"

# ── Nginx конфиг ──────────────────────────────────────────────────────────────

NGINX_CUSTOM_DIR="${NGINX_DEPLOY_DIR}/custom"
mkdir -p "$NGINX_DEPLOY_DIR" "$NGINX_CUSTOM_DIR"
CONFIG_FILE="${NGINX_DEPLOY_DIR}/${SITE_PATH}.conf"

# Читаем кастомный домен и флаг no_protection из domain файла
CUSTOM_DOMAIN=""
NO_PROTECTION=false
if [[ -f "${WORK_TREE}/domain" ]]; then
  CUSTOM_DOMAIN=$(head -n1 "${WORK_TREE}/domain" 2>/dev/null | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
  [[ "$CUSTOM_DOMAIN" != *"."* ]] && CUSTOM_DOMAIN=""
  if grep -qx "no_protection" "${WORK_TREE}/domain" 2>/dev/null; then
    NO_PROTECTION=true
    log "Nginx конфиг без защиты от парсинга (флаг no_protection)"
  fi
fi

if [[ -n "$CUSTOM_DOMAIN" ]]; then
  # ── Кастомный домен: отдельный server-блок + certbot ──────────────────────
  rm -f "$CONFIG_FILE"
  if [[ -n "$OLD_CUSTOM_DOMAIN" && "$OLD_CUSTOM_DOMAIN" != "$CUSTOM_DOMAIN" ]]; then
    rm -f "${NGINX_CUSTOM_DIR}/${OLD_CUSTOM_DOMAIN}.conf"
  fi
  CUSTOM_CONF="${NGINX_CUSTOM_DIR}/${CUSTOM_DOMAIN}.conf"

  # IndexNow ключ
  INDEXNOW_DIR="/opt/deploy/indexnow-keys"
  INDEXNOW_KEY_FILE="${INDEXNOW_DIR}/${CUSTOM_DOMAIN}"
  mkdir -p "$INDEXNOW_DIR"
  if [[ ! -s "$INDEXNOW_KEY_FILE" ]]; then
    INDEXNOW_KEY=$(openssl rand -hex 16 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null)
    [[ -n "$INDEXNOW_KEY" ]] && echo -n "$INDEXNOW_KEY" > "$INDEXNOW_KEY_FILE" && chmod 644 "$INDEXNOW_KEY_FILE"
  fi

  if [[ -f "$CUSTOM_CONF" ]]; then
    # Конфиг уже есть (certbot добавил 443) — только обновляем порт
    sed -i.bak "s|proxy_pass http://127.0.0.1:[0-9]*/|proxy_pass http://127.0.0.1:${PORT}/|g" "$CUSTOM_CONF" 2>/dev/null || \
      sed -i '' "s|proxy_pass http://127.0.0.1:[0-9]*/|proxy_pass http://127.0.0.1:${PORT}/|g" "$CUSTOM_CONF" 2>/dev/null || true
    rm -f "${CUSTOM_CONF}.bak" 2>/dev/null || true
    log "Обновлён порт в конфиге кастомного домена: ${PORT}"
    # Добавляем IndexNow location если ещё нет
    if ! grep -q "location = /indexnow-key.txt" "$CUSTOM_CONF" 2>/dev/null && [[ -s "$INDEXNOW_KEY_FILE" ]]; then
      awk -v keyfile="$INDEXNOW_KEY_FILE" '
        /^[[:space:]]*location \/ \{/ && !done {
          print "    location = /indexnow-key.txt {"
          print "        alias " keyfile ";"
          print "        default_type text/plain;"
          print "    }"
          print ""
          done=1
        }
        { print }
      ' "$CUSTOM_CONF" > "${CUSTOM_CONF}.tmp" && mv "${CUSTOM_CONF}.tmp" "$CUSTOM_CONF"
      log "Добавлен ключ IndexNow (Yandex) и location в конфиг"
    fi
  else
    # Первый деплой: пишем HTTP server-блок, certbot добавит 443
    if [[ "$NO_PROTECTION" == true ]]; then
cat > "$CUSTOM_CONF" << NGINXEOF
# Кастомный домен для ${SITE_PATH} (защита от парсинга отключена)
server {
    listen 80;
    listen [::]:80;
    server_name ${CUSTOM_DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location = /indexnow-key.txt {
        alias ${INDEXNOW_KEY_FILE};
        default_type text/plain;
    }

    location / {
        proxy_set_header Accept-Encoding "";
        sub_filter_types text/html;
        sub_filter_once on;
        sub_filter '</head>' '<script src="https://automatoria.ru/api/analytics.js?site_id=${SITE_PATH}&v=2" defer></script></head>';
        proxy_pass http://127.0.0.1:${PORT}/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
NGINXEOF
    else
cat > "$CUSTOM_CONF" << NGINXEOF
# Кастомный домен для ${SITE_PATH}
server {
    listen 80;
    listen [::]:80;
    server_name ${CUSTOM_DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location = /indexnow-key.txt {
        alias ${INDEXNOW_KEY_FILE};
        default_type text/plain;
    }

    location / {
        if (\$bad_bot) { return 403; }
        limit_req zone=deploy_site burst=50 nodelay;
        proxy_set_header Accept-Encoding "";
        sub_filter_types text/html;
        sub_filter_once on;
        sub_filter '</head>' '<script src="https://automatoria.ru/api/analytics.js?site_id=${SITE_PATH}&v=2" defer></script><script src="https://automatoria.ru/api/preview-js?h=${SITE_PATH}"></script></head>';
        proxy_pass http://127.0.0.1:${PORT}/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
NGINXEOF
    fi
    nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true
    # Выпускаем SSL
    CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
    [[ -z "$CERTBOT_EMAIL" ]] && CERTBOT_EMAIL="deploy@automatoria.ru"
    log "Настройка SSL для ${CUSTOM_DOMAIN}..."
    if ! certbot --nginx -d "$CUSTOM_DOMAIN" --redirect --non-interactive --agree-tos -m "$CERTBOT_EMAIL"; then
      log "Предупреждение: certbot не выполнен для ${CUSTOM_DOMAIN} (проверь A-запись и порт 80)"
    fi
  fi

  nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true

  # Обновляем registry: добавляем custom_domain
  if [[ -f "$REGISTRY_FILE" ]] && command -v jq >/dev/null 2>&1; then
    reg_content=$(cat "$REGISTRY_FILE" 2>/dev/null)
    [[ -z "$reg_content" || "$reg_content" != *"{"* ]] && reg_content="{}"
    echo "$reg_content" | jq --arg h "$SITE_PATH" --arg cd "$CUSTOM_DOMAIN" '.[$h].custom_domain = $cd' > "${REGISTRY_FILE}.tmp"
    mv "${REGISTRY_FILE}.tmp" "$REGISTRY_FILE"
  fi

  log "Сайт доступен по https://${CUSTOM_DOMAIN}/"

  # SEO: уведомление поисковиков
  if command -v curl >/dev/null 2>&1; then
    for sitemap_path in sitemap.xml sitemap-index.xml; do
      SITEMAP_URL="https://${CUSTOM_DOMAIN}/${sitemap_path}"
      ENCODED=$(SITEMAP_URL="$SITEMAP_URL" python3 -c "import os, urllib.parse; print(urllib.parse.quote(os.environ['SITEMAP_URL'], safe=''))" 2>/dev/null)
      [[ -z "$ENCODED" ]] && continue
      curl -sS -o /dev/null -m 10 "https://www.google.com/ping?sitemap=$ENCODED" 2>/dev/null && log "Google: уведомление о sitemap отправлено ($sitemap_path)" || true
      curl -sS -o /dev/null -m 10 "https://www.bing.com/ping?sitemap=$ENCODED" 2>/dev/null && log "Bing: уведомление о sitemap отправлено ($sitemap_path)" || true
    done
    if [[ -s "$INDEXNOW_KEY_FILE" ]]; then
      INDEXNOW_KEY=$(cat "$INDEXNOW_KEY_FILE" 2>/dev/null)
      HOMEPAGE_URL="https://${CUSTOM_DOMAIN}/"
      KEYLOCATION_URL="https://${CUSTOM_DOMAIN}/indexnow-key.txt"
      URL_ENC=$(HOMEPAGE_URL="$HOMEPAGE_URL" python3 -c "import os, urllib.parse; print(urllib.parse.quote(os.environ['HOMEPAGE_URL'], safe=''))" 2>/dev/null)
      KEYLOC_ENC=$(KEYLOCATION_URL="$KEYLOCATION_URL" python3 -c "import os, urllib.parse; print(urllib.parse.quote(os.environ['KEYLOCATION_URL'], safe=''))" 2>/dev/null)
      if [[ -n "$INDEXNOW_KEY" && -n "$URL_ENC" ]]; then
        INDEXNOW_Q="url=${URL_ENC}&key=${INDEXNOW_KEY}"
        [[ -n "$KEYLOC_ENC" ]] && INDEXNOW_Q="${INDEXNOW_Q}&keyLocation=${KEYLOC_ENC}"
        CODE=$(curl -sS -o /dev/null -w "%{http_code}" -m 10 "https://yandex.com/indexnow?${INDEXNOW_Q}" 2>/dev/null)
        if [[ "$CODE" == "200" || "$CODE" == "202" ]]; then
          log "Yandex IndexNow: уведомление отправлено (HTTP $CODE)"
        else
          log "Yandex IndexNow: ответ HTTP $CODE"
        fi
      fi
    fi
    if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" || -n "${GOOGLE_OAUTH_CREDENTIALS:-}" || -n "${GOOGLE_REFRESH_TOKEN:-}" ]] && [[ -f "$SCRIPT_DIR/seo_submit_google.py" ]]; then
      GOOGLE_EXIT=0
      python3 "$SCRIPT_DIR/seo_submit_google.py" "$CUSTOM_DOMAIN" || GOOGLE_EXIT=$?
      [[ "$GOOGLE_EXIT" -eq 0 ]] && log "Google Search Console: sitemap отправлен" || log "Google Search Console API: ошибка (код $GOOGLE_EXIT)"
    fi
    if [[ -n "${YANDEX_REFRESH_TOKEN:-}" || -n "${YANDEX_WEBMASTER_CREDENTIALS:-}" ]] && [[ -f "$SCRIPT_DIR/seo_submit_yandex.py" ]]; then
      YANDEX_EXIT=0
      python3 "$SCRIPT_DIR/seo_submit_yandex.py" "$CUSTOM_DOMAIN" || YANDEX_EXIT=$?
      [[ "$YANDEX_EXIT" -eq 0 ]] && log "Яндекс.Вебмастер API: сайт/sitemap отправлен" || log "Яндекс.Вебмастер API: ошибка (код $YANDEX_EXIT)"
    fi
  fi

else
  # ── Обычный деплой: превью по /{hash}/ на основном домене ─────────────────
  if [[ -n "$OLD_CUSTOM_DOMAIN" ]]; then
    rm -f "${NGINX_CUSTOM_DIR}/${OLD_CUSTOM_DOMAIN}.conf"
  fi

  if [[ "$NO_PROTECTION" == true ]]; then
cat > "$CONFIG_FILE" << NGINXEOF
# Location для /${SITE_PATH}/ (автосгенерировано deploy_single.sh, защита отключена)
location /${SITE_PATH}/ {
    proxy_set_header Accept-Encoding "";
    sub_filter_types text/html;
    sub_filter_once on;
    sub_filter '</head>' '<script src="https://automatoria.ru/api/analytics.js?site_id=${SITE_PATH}&v=2" defer></script></head>';
    proxy_pass http://127.0.0.1:${PORT}/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
    rewrite ^/${SITE_PATH}(/.*)\$ \$1 break;
}

location = /${SITE_PATH} {
    return 301 /${SITE_PATH}/;
}
NGINXEOF
  else
cat > "$CONFIG_FILE" << NGINXEOF
# Location для /${SITE_PATH}/ (автосгенерировано deploy_single.sh)
location /${SITE_PATH}/ {
    if (\$bad_bot) { return 403; }
    limit_req zone=deploy_site burst=50 nodelay;
    proxy_set_header Accept-Encoding "";
    sub_filter_types text/html;
    sub_filter_once on;
    sub_filter '</head>' '<script src="https://automatoria.ru/api/analytics.js?site_id=${SITE_PATH}&v=2" defer></script><script src="https://automatoria.ru/api/preview-js?h=${SITE_PATH}"></script></head>';
    proxy_pass http://127.0.0.1:${PORT}/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
    rewrite ^/${SITE_PATH}(/.*)\$ \$1 break;
}

location = /${SITE_PATH} {
    return 301 /${SITE_PATH}/;
}
NGINXEOF
  fi

  nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true
fi

notify_deploy_done "ok"
log "Готово. Сайт: https://${DOMAIN}/${SITE_PATH}/"
