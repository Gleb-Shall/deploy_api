#!/bin/bash
#
# Выполняет деплой одного сайта (вызывается воркером из очереди).
# Предполагает: work tree готов, Dockerfile и .dockerignore созданы post-receive.
#

set -e

PAGE_HASH="$1"
DEPLOY_ID="$2"  # Опциональный уникальный ID деплоя
[[ -n "$PAGE_HASH" ]] || { echo "Usage: $0 PAGE_HASH [DEPLOY_ID]" >&2; exit 1; }

WORK_TREE="/opt/deploy/${PAGE_HASH}"
CONTAINER_NAME="deploy-${PAGE_HASH}"
IMAGE_NAME="deploy-${PAGE_HASH}"
REGISTRY_FILE="/opt/deploy/registry.json"
PORTS_QUEUE_EVEN="/opt/deploy/ports_queue_even.txt"  # Чётные порты (9000, 9002, ...)
PORTS_QUEUE_ODD="/opt/deploy/ports_queue_odd.txt"    # Нечётные порты (9001, 9003, ...)
NGINX_DEPLOY_DIR="/etc/nginx/sites-available/deploy"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"

# Путь к скрипту управления очередями портов
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGE_PORTS_SCRIPT="${SCRIPT_DIR}/manage_ports_queue.sh"

# Определяем, какой файл портов использовать (по WORKER_ID или по умолчанию)
# Воркер 1 → чётные порты (9000, 9002, ...), Воркер 2 → нечётные порты (9001, 9003, ...)
WORKER_ID="${WORKER_ID:-}"
if [[ "$WORKER_ID" =~ ^[12]$ ]] || [[ "$WORKER_ID" =~ -1$ ]] || [[ "$WORKER_ID" =~ worker-?1 ]]; then
  # Воркер 1 → чётные порты
  PORTS_QUEUE_FILE="$PORTS_QUEUE_EVEN"
  PORT_TYPE="even"
elif [[ "$WORKER_ID" =~ -2$ ]] || [[ "$WORKER_ID" =~ worker-?2 ]]; then
  # Воркер 2 → нечётные порты
  PORTS_QUEUE_FILE="$PORTS_QUEUE_ODD"
  PORT_TYPE="odd"
else
  # По умолчанию: если WORKER_ID не задан или не распознан, используем чётные
  PORTS_QUEUE_FILE="$PORTS_QUEUE_EVEN"
  PORT_TYPE="even"
fi

# Если есть DEPLOY_ID, используем уникальный ключ, иначе старый формат для обратной совместимости
if [[ -n "$DEPLOY_ID" ]]; then
  REDIS_RESULT_KEY="deploy:done:${PAGE_HASH}:${DEPLOY_ID}"
else
  REDIS_RESULT_KEY="deploy:done:${PAGE_HASH}"
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [deploy $PAGE_HASH] $*"; }

# Уведомление о завершении (успех или ошибка)
notify_deploy_done() {
    local status="$1"
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" LPUSH "${REDIS_RESULT_KEY}" "$status" >/dev/null 2>&1 || true
}

# При выходе с ошибкой отправляем "failed"
trap 'notify_deploy_done "failed"' ERR

[[ -d "$WORK_TREE" ]] || { log "Work tree не найден"; exit 1; }

# Docker build: при ошибке весь вывод (stdout+stderr) пишем в Redis — post-receive отдаёт в ответ на push
# docker build может писать ошибки в stdout или stderr в зависимости от версии/драйвера, поэтому захватываем оба
log "Сборка образа..."
tmpout="${WORK_TREE}/.build_out.$$"
docker build -t "$IMAGE_NAME" "$WORK_TREE" 2>&1 | tee "$tmpout"
build_rc=${PIPESTATUS[0]}
if [[ $build_rc -ne 0 ]]; then
  log "Ошибка сборки Docker"
  if [[ -s "$tmpout" ]]; then
    # Один пуш в ключ результата: "failed\n" + вывод сборки — post-receive по BLPOP получит и выведет тело
    ( printf 'failed\n'; cat "$tmpout" ) | redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -x LPUSH "$REDIS_RESULT_KEY" >/dev/null 2>&1 || true
    cat "$tmpout" >&2
  else
    notify_deploy_done "failed"
  fi
  rm -f "$tmpout"
  exit 1
fi
rm -f "$tmpout"

# Extract CSS bundle from Docker image → store in Redis for fingerprint API
CSS_BUNDLE=$(docker run --rm --entrypoint cat "${IMAGE_NAME}" /css_bundle.txt 2>/dev/null || echo "")
if [[ -n "$CSS_BUNDLE" && "$CSS_BUNDLE" != "" ]]; then
  redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" SET "css_bundle:${PAGE_HASH}" "$CSS_BUNDLE" EX 2592000 >/dev/null 2>&1 \
    || log "Warning: CSS bundle not stored in Redis"
  log "CSS bundle stored (${#CSS_BUNDLE} chars)"
else
  log "No CSS bundle found — CSS obfuscation inactive for this deploy"
fi

# Функция возврата порта в очередь при освобождении
# Определяет правильный файл (чётный/нечётный) автоматически
# Просто добавляет порт в конец файла - никаких проверок не нужно
return_port_to_queue() {
  local port="$1"
  [[ -z "$port" || ! "$port" =~ ^[0-9]+$ ]] && return
  
  # Определяем, в какой файл возвращать порт (чётный или нечётный)
  local target_file
  if (( port % 2 == 0 )); then
    target_file="$PORTS_QUEUE_EVEN"
  else
    target_file="$PORTS_QUEUE_ODD"
  fi
  
  # Просто добавляем порт в конец файла
  echo "$port" >> "$target_file"
}

# Останавливаем старый контейнер и возвращаем порт в очередь
# Сначала получаем порт и кастомный домен из registry (до перезаписи в allocate_port)
OLD_PORT=""
OLD_CUSTOM_DOMAIN=""
if [[ -f "$REGISTRY_FILE" ]] && command -v jq >/dev/null 2>&1; then
  OLD_PORT=$(cat "$REGISTRY_FILE" 2>/dev/null | jq -r --arg h "$PAGE_HASH" '.[$h].container_port // empty' 2>/dev/null)
  OLD_CUSTOM_DOMAIN=$(cat "$REGISTRY_FILE" 2>/dev/null | jq -r --arg h "$PAGE_HASH" '.[$h].custom_domain // empty' 2>/dev/null)
fi

docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

# Функция проверки доступности порта
is_port_available() {
  local port="$1"
  
  # 1. Проверяем через docker ps (все контейнеры, включая остановленные)
  # Формат вывода: "127.0.0.1:9995->8000/tcp" или "0.0.0.0:9995->8000/tcp"
  if docker ps -a --format '{{.Ports}}' 2>/dev/null | grep -qE ":(127\.0\.0\.1:)?${port}->|:0\.0\.0\.0:${port}->"; then
    return 1
  fi
  
  # 2. Проверяем через ss (если доступен)
  if command -v ss >/dev/null 2>&1; then
    if ss -tuln 2>/dev/null | grep -q ":${port} "; then
      return 1
    fi
  # 3. Или через netstat (альтернатива)
  elif command -v netstat >/dev/null 2>&1; then
    if netstat -tuln 2>/dev/null | grep -q ":${port} "; then
      return 1
    fi
  fi
  
  return 0
}


# Функция выделения свободного порта из очереди (O(1) операция)
# Простая логика: берём первую строку из файла, удаляем её
# Блокировка не нужна: воркер обрабатывает задачи последовательно, файлы разделены по воркерам
allocate_port() {
  local reg_content=""
  
  # Инициализируем обе очереди, если хотя бы одна не существует
  if [[ ! -f "$PORTS_QUEUE_EVEN" ]] || [[ ! -f "$PORTS_QUEUE_ODD" ]] || \
     [[ ! -s "$PORTS_QUEUE_EVEN" ]] || [[ ! -s "$PORTS_QUEUE_ODD" ]]; then
    "$MANAGE_PORTS_SCRIPT" init
  fi
  
  # Берём первый порт из своей очереди (O(1) операция)
  # Воркер 1 использует чётные порты, воркер 2 - нечётные
  local port=$(head -n 1 "$PORTS_QUEUE_FILE" 2>/dev/null)
  
  # Если очередь пуста, переинициализируем
  if [[ -z "$port" ]]; then
    "$MANAGE_PORTS_SCRIPT" rebuild
    port=$(head -n 1 "$PORTS_QUEUE_FILE" 2>/dev/null)
  fi
  
  if [[ -z "$port" || ! "$port" =~ ^[0-9]+$ ]]; then
    log "Не удалось выделить порт из очереди"
    return 1
  fi
  
  # Удаляем порт из очереди (удаляем первую строку)
  tail -n +2 "$PORTS_QUEUE_FILE" > "${PORTS_QUEUE_FILE}.tmp" 2>/dev/null && mv "${PORTS_QUEUE_FILE}.tmp" "$PORTS_QUEUE_FILE" 2>/dev/null || true
  
  # Записываем порт в registry
  mkdir -p "$(dirname "$REGISTRY_FILE")"
  if [[ -f "$REGISTRY_FILE" ]] && command -v jq >/dev/null 2>&1; then
    reg_content=$(cat "$REGISTRY_FILE" 2>/dev/null)
  fi
  [[ -z "$reg_content" || "$reg_content" != *"{"* ]] && reg_content="{}"
  echo "$reg_content" | jq --arg h "$PAGE_HASH" --argjson p "$port" --arg n "$CONTAINER_NAME" \
    '.[$h] = {container_port: $p, container_name: $n}' > "${REGISTRY_FILE}.tmp"
  mv "${REGISTRY_FILE}.tmp" "$REGISTRY_FILE"
  
  echo "$port"
}

# Порт: при повторном деплое того же сайта используем тот же порт из registry
if [[ -n "$OLD_PORT" && "$OLD_PORT" != "null" ]] && is_port_available "$OLD_PORT"; then
  PORT="$OLD_PORT"
  log "Повторное использование порта: $PORT"
else
  if [[ -n "$OLD_PORT" && "$OLD_PORT" != "null" ]]; then
    return_port_to_queue "$OLD_PORT"
  fi
  PORT=$(allocate_port)
  [[ -n "$PORT" ]] || { log "Ошибка выделения порта"; exit 1; }
  log "Выделен порт: $PORT"
fi

# Запуск контейнера
log "Запуск контейнера на порту $PORT..."
docker run -d \
  --name "$CONTAINER_NAME" \
  -p "127.0.0.1:${PORT}:8000" \
  --restart unless-stopped \
  "$IMAGE_NAME"

# Кастомный домен: из файла domain в корне проекта (одна строка)
CUSTOM_DOMAIN=""
if [[ -f "$WORK_TREE/domain" ]]; then
  CUSTOM_DOMAIN=$(head -n1 "$WORK_TREE/domain" 2>/dev/null | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
fi
[[ -z "$CUSTOM_DOMAIN" ]] && CUSTOM_DOMAIN=""

CONFIG_FILE="${NGINX_DEPLOY_DIR}/${PAGE_HASH}.conf"
NGINX_CUSTOM_DIR="${NGINX_DEPLOY_DIR}/custom"
mkdir -p "$NGINX_DEPLOY_DIR" "$NGINX_CUSTOM_DIR"

if [[ -n "$CUSTOM_DOMAIN" ]]; then
  # Сайт только на кастомном домене: убираем превью по /{hash}/ на основном домене
  rm -f "$CONFIG_FILE"
  if [[ -n "$OLD_CUSTOM_DOMAIN" && "$OLD_CUSTOM_DOMAIN" != "$CUSTOM_DOMAIN" ]]; then
    rm -f "${NGINX_CUSTOM_DIR}/${OLD_CUSTOM_DOMAIN}.conf"
  fi
  CUSTOM_CONF="${NGINX_CUSTOM_DIR}/${CUSTOM_DOMAIN}.conf"
  # Если конфиг уже есть (certbot уже добавил listen 443) — только обновляем порт в proxy_pass
  if [[ -f "$CUSTOM_CONF" ]]; then
    sed -i.bak "s|proxy_pass http://127.0.0.1:[0-9]*/|proxy_pass http://127.0.0.1:${PORT}/|g" "$CUSTOM_CONF" 2>/dev/null || \
      sed -i '' "s|proxy_pass http://127.0.0.1:[0-9]*/|proxy_pass http://127.0.0.1:${PORT}/|g" "$CUSTOM_CONF" 2>/dev/null || true
    rm -f "${CUSTOM_CONF}.bak" 2>/dev/null || true
    log "Обновлён порт в конфиге кастомного домена: ${PORT}"
    # IndexNow: если ключа ещё нет (конфиг создан до появления этой фичи) — создаём ключ и добавляем location
    INDEXNOW_DIR="/opt/deploy/indexnow-keys"
    INDEXNOW_KEY_FILE="${INDEXNOW_DIR}/${CUSTOM_DOMAIN}"
    if [[ ! -s "$INDEXNOW_KEY_FILE" ]]; then
      mkdir -p "$INDEXNOW_DIR"
      INDEXNOW_KEY=$(openssl rand -hex 16 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null)
      if [[ -n "$INDEXNOW_KEY" ]]; then
        echo -n "$INDEXNOW_KEY" > "$INDEXNOW_KEY_FILE" && chmod 644 "$INDEXNOW_KEY_FILE"
        if ! grep -q "location = /indexnow-key.txt" "$CUSTOM_CONF" 2>/dev/null; then
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
          nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true
          log "Добавлен ключ IndexNow (Yandex) и location в конфиг"
        fi
      fi
    fi
  else
    # Ключ для Yandex IndexNow: один раз создаём, отдаём по /indexnow-key.txt
    INDEXNOW_DIR="/opt/deploy/indexnow-keys"
    INDEXNOW_KEY_FILE="${INDEXNOW_DIR}/${CUSTOM_DOMAIN}"
    mkdir -p "$INDEXNOW_DIR"
    if [[ ! -s "$INDEXNOW_KEY_FILE" ]]; then
      INDEXNOW_KEY=$(openssl rand -hex 16 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null)
      [[ -n "$INDEXNOW_KEY" ]] && echo -n "$INDEXNOW_KEY" > "$INDEXNOW_KEY_FILE" && chmod 644 "$INDEXNOW_KEY_FILE"
    fi
    # Первый деплой: пишем server-блок (listen 80), потом certbot добавит 443
    cat > "$CUSTOM_CONF" << NGINXEOF
# Кастомный домен для ${PAGE_HASH} (превью на основном домене отключена)
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
        # Anti-scraping: block bad bots, rate limit (search engines unaffected)
        if (\$bad_bot) { return 403; }
        limit_req zone=deploy_site burst=50 nodelay;
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
    nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true
    # Всегда вызываем certbot: при новом сертификате — получит, при уже существующем — добавит listen 443 в конфиг (нужно после remove+redeploy, когда конфиг писали заново)
    CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
    if [[ -z "$CERTBOT_EMAIL" && -f /opt/deploy/domain.txt ]]; then
      CERTBOT_EMAIL="deploy@$(cat /opt/deploy/domain.txt 2>/dev/null | head -1)"
    fi
    [[ -z "$CERTBOT_EMAIL" ]] && CERTBOT_EMAIL="deploy@${CUSTOM_DOMAIN}"
    log "Настройка SSL для ${CUSTOM_DOMAIN}..."
    if ! certbot --nginx -d "$CUSTOM_DOMAIN" --redirect --non-interactive --agree-tos -m "$CERTBOT_EMAIL"; then
      log "Предупреждение: certbot не выполнен для ${CUSTOM_DOMAIN} (проверь A-запись и порт 80)"
    fi
  fi
  nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true
  # Обновить registry: добавить custom_domain
  if [[ -f "$REGISTRY_FILE" ]] && command -v jq >/dev/null 2>&1; then
    reg_content=$(cat "$REGISTRY_FILE" 2>/dev/null)
    [[ -z "$reg_content" || "$reg_content" != *"{"* ]] && reg_content="{}"
    echo "$reg_content" | jq --arg h "$PAGE_HASH" --arg cd "$CUSTOM_DOMAIN" '.[$h].custom_domain = $cd' > "${REGISTRY_FILE}.tmp"
    mv "${REGISTRY_FILE}.tmp" "$REGISTRY_FILE"
  fi
  log "Сайт доступен по https://${CUSTOM_DOMAIN}/ (превью по /${PAGE_HASH}/ отключено)"
  # SEO: уведомление поисковиков об обновлении sitemap (Google, Bing) и IndexNow (Yandex)
  if command -v curl >/dev/null 2>&1; then
    for sitemap_path in sitemap.xml sitemap-index.xml; do
      SITEMAP_URL="https://${CUSTOM_DOMAIN}/${sitemap_path}"
      ENCODED=$(SITEMAP_URL="$SITEMAP_URL" python3 -c "import os, urllib.parse; print(urllib.parse.quote(os.environ['SITEMAP_URL'], safe=''))" 2>/dev/null)
      [[ -z "$ENCODED" ]] && continue
      curl -sS -o /dev/null -m 10 "https://www.google.com/ping?sitemap=$ENCODED" 2>/dev/null && log "Google: уведомление о sitemap отправлено ($sitemap_path)" || true
      curl -sS -o /dev/null -m 10 "https://www.bing.com/ping?sitemap=$ENCODED" 2>/dev/null && log "Bing: уведомление о sitemap отправлено ($sitemap_path)" || true
    done
    # Yandex IndexNow: уведомление об URL (ключ лежит в /indexnow-key.txt на сайте)
    INDEXNOW_KEY_FILE="/opt/deploy/indexnow-keys/${CUSTOM_DOMAIN}"
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
          log "Yandex IndexNow: ответ HTTP $CODE (проверь доступность https://${CUSTOM_DOMAIN}/indexnow-key.txt)"
        fi
      fi
    else
      log "Yandex IndexNow: пропущено (ключ не найден; при первом деплое с новым конфигом создаётся автоматически)"
    fi
    # Опционально: Google Search Console — OAuth пользователя (добавить сайт в аккаунт + верификация + sitemap) или сервисный аккаунт (только sitemap)
    if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" || -n "${GOOGLE_OAUTH_CREDENTIALS:-}" || -n "${GOOGLE_REFRESH_TOKEN:-}" ]] && [[ -f "$SCRIPT_DIR/seo_submit_google.py" ]]; then
      GOOGLE_EXIT=0
      python3 "$SCRIPT_DIR/seo_submit_google.py" "$CUSTOM_DOMAIN" || GOOGLE_EXIT=$?
      if [[ "$GOOGLE_EXIT" -eq 0 ]]; then
        log "Google Search Console: сайт добавлен в аккаунт, верификация и sitemap выполнены (или только sitemap при сервисном аккаунте)"
      elif [[ "$GOOGLE_EXIT" -ne 0 ]]; then
        log "Google Search Console API: ошибка (код $GOOGLE_EXIT)"
      fi
    fi
    # Опционально: добавление сайта и sitemap в Яндекс.Вебмастер (OAuth)
    if [[ -n "${YANDEX_REFRESH_TOKEN:-}" || -n "${YANDEX_WEBMASTER_CREDENTIALS:-}" ]] && [[ -f "$SCRIPT_DIR/seo_submit_yandex.py" ]]; then
      YANDEX_EXIT=0
      python3 "$SCRIPT_DIR/seo_submit_yandex.py" "$CUSTOM_DOMAIN" || YANDEX_EXIT=$?
      if [[ "$YANDEX_EXIT" -eq 0 ]]; then
        log "Яндекс.Вебмастер API: сайт/sitemap отправлен"
      elif [[ "$YANDEX_EXIT" -eq 8 ]]; then
        log "Яндекс.Вебмастер: API вернул «сайт не верифицирован» (см. stderr выше); если в интерфейсе уже верифицирован — проверь совпадение хоста (www/без www) или подожди синхронизацию API"
      elif [[ "$YANDEX_EXIT" -ne 0 ]]; then
        log "Яндекс.Вебмастер API: ошибка (код $YANDEX_EXIT)"
      fi
    fi
  fi
else
  # Обычный деплой: превью на основном домене по /{hash}/
  if [[ -n "$OLD_CUSTOM_DOMAIN" ]]; then
    rm -f "${NGINX_CUSTOM_DIR}/${OLD_CUSTOM_DOMAIN}.conf"
  fi

  # Generate canary tokens for this preview page
  CANARY_HTML=""
  CANARY_TTL=31536000  # 1 year
  for i in 1 2 3 4 5; do
    CANARY_TOKEN=$(openssl rand -hex 16 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || echo "")
    if [[ -n "$CANARY_TOKEN" ]]; then
      CANARY_META="{\"page_hash\":\"${PAGE_HASH}\",\"created_at\":$(date +%s)}"
      redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" SETEX "canary:token:${CANARY_TOKEN}" "$CANARY_TTL" "$CANARY_META" >/dev/null 2>&1 || true
      CANARY_HTML="${CANARY_HTML}<a href=https://automatoria.ru/r/${CANARY_TOKEN}></a>"
    fi
  done
  log "Canary tokens generated"

  cat > "$CONFIG_FILE" << NGINXEOF
# Location для /${PAGE_HASH}
# Все пути /PAGE_HASH/* идут в контейнер (в т.ч. /_astro/, assets)
# Astro требует base: '/PAGE_HASH/' в astro.config
location /${PAGE_HASH}/ {
    # Anti-scraping: block bad bots, rate limit
    if (\$bad_bot) { return 403; }
    limit_req zone=deploy_site burst=50 nodelay;
    # sub_filter requires uncompressed response from backend
    proxy_set_header Accept-Encoding "";
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
    # Anti-scraping injections via sub_filter
    sub_filter_types text/html;
    sub_filter_once on;
    # Domain lock: redirect to automatoria.ru if HTML is hosted elsewhere
    sub_filter '</head>' '<script src=https://automatoria.ru/api/preview-js?h=${PAGE_HASH}></script></head>';
    # Canary links: hidden, detect when stolen HTML is opened on another domain
    sub_filter '</body>' '<span style=display:none aria-hidden=true>${CANARY_HTML}</span></body>';
}

location = /${PAGE_HASH} {
    return 301 /${PAGE_HASH}/;
}
NGINXEOF
  # Убрать custom_domain из registry
  if [[ -f "$REGISTRY_FILE" ]] && command -v jq >/dev/null 2>&1; then
    reg_content=$(cat "$REGISTRY_FILE" 2>/dev/null)
    [[ -z "$reg_content" || "$reg_content" != *"{"* ]] && reg_content="{}"
    echo "$reg_content" | jq --arg h "$PAGE_HASH" 'del(.[$h].custom_domain)' > "${REGISTRY_FILE}.tmp"
    mv "${REGISTRY_FILE}.tmp" "$REGISTRY_FILE"
  fi
fi

# Явный reload — path unit может не сработать сразу
nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true

# Уведомляем post-receive о завершении (для синхронного деплоя)
notify_deploy_done "ok"

log "Готово."
