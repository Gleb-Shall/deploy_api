#!/bin/bash
#
# Удаление деплоенного сайта
# Использование: sudo bash remove_site.sh PAGE_HASH [--keep-repo]
#               sudo bash remove_site.sh -A [--keep-repo]
#
# PAGE_HASH   — хэш страницы (например 1d2637e8889b)
# -A          — удалить ВСЕ задеплоенные сайты
# --keep-repo — не удалять git репо (по умолчанию репо удаляется)
#

set -e

REGISTRY_FILE="/opt/deploy/registry.json"
NGINX_DEPLOY_DIR="/etc/nginx/sites-available/deploy"
GIT_BASE="/var/git/sites"
SCRIPTS_DIR="/opt/deploy_api/scripts"

if [[ "$1" == "-A" ]]; then
  # Удалить все сайты (объединяем все источники — при падении сборки registry/nginx могут быть пусты)
  KEEP_REPO=false
  [[ "$2" == "--keep-repo" ]] && KEEP_REPO=true
  declare -A HASH_SET
  shopt -s nullglob
  # Функция проверки валидности хэша
  is_valid_hash() {
    local hash="$1"
    [[ -n "$hash" && "$hash" != "null" && "$hash" =~ ^[a-zA-Z0-9_.-]+$ ]]
  }
  
  # 1. registry.json
  if [[ -f "$REGISTRY_FILE" ]] && command -v jq >/dev/null 2>&1; then
    for h in $(jq -r 'keys[]' "$REGISTRY_FILE" 2>/dev/null); do
      is_valid_hash "$h" && HASH_SET[$h]=1
    done
  fi
  # 2. nginx конфиги
  for f in "$NGINX_DEPLOY_DIR"/*.conf; do
    if [[ -f "$f" ]]; then
      h=$(basename "$f" .conf)
      is_valid_hash "$h" && HASH_SET["$h"]=1
    fi
  done
  # 3. work tree (/opt/deploy/*) — есть при падении сборки
  # Проверяем только директории (не файлы типа registry.json, ports_queue_*.txt)
  for d in /opt/deploy/*/; do
    if [[ -d "$d" ]]; then
      h=$(basename "$d")
      # Пропускаем служебные директории и файлы
      [[ "$h" == "" || "$h" == "." || "$h" == ".." ]] && continue
      is_valid_hash "$h" && HASH_SET["$h"]=1
    fi
  done
  # 4. git репо (/var/git/sites/*.git)
  for r in "${GIT_BASE}"/*.git; do
    if [[ -d "$r" ]]; then
      h=$(basename "$r" .git)
      is_valid_hash "$h" && HASH_SET["$h"]=1
    fi
  done
  shopt -u nullglob
  HASHES=("${!HASH_SET[@]}")
  if [[ ${#HASHES[@]} -eq 0 ]]; then
    echo "Нет задеплоенных сайтов"
    exit 0
  fi
  echo "Удаление ${#HASHES[@]} сайтов..."
  for h in "${HASHES[@]}"; do
    # Дополнительная проверка перед рекурсивным вызовом
    if ! is_valid_hash "$h"; then
      echo "Пропуск некорректного хэша: '$h'"
      continue
    fi
    # Рекурсивный вызов с обработкой ошибок (set -e отключен для этого блока)
    set +e
    if $KEEP_REPO; then
      "$SCRIPTS_DIR/remove_site.sh" "$h" --keep-repo || echo "Ошибка при удалении $h (продолжаем...)"
    else
      "$SCRIPTS_DIR/remove_site.sh" "$h" || echo "Ошибка при удалении $h (продолжаем...)"
    fi
    set -e
  done
  echo "Все сайты удалены."
  exit 0
fi

PAGE_HASH="$1"
if [[ -z "$PAGE_HASH" || "$PAGE_HASH" == "--keep-repo" ]]; then
  echo "Использование: $0 PAGE_HASH [--keep-repo]"
  echo "               $0 -A [--keep-repo]  — удалить все сайты"
  echo "  PAGE_HASH   — хэш сайта (например 1d2637e8889b)"
  echo "  -A          — удалить все задеплоенные сайты"
  echo "  --keep-repo — не удалять git репо"
  exit 1
fi

PURGE_REPO=true
[[ "$2" == "--keep-repo" ]] && PURGE_REPO=false

if ! [[ "$PAGE_HASH" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
  echo "ERROR: Invalid PAGE_HASH"
  exit 1
fi

CONTAINER_NAME="deploy-${PAGE_HASH}"
IMAGE_NAME="deploy-${PAGE_HASH}"
WORK_TREE="/opt/deploy/${PAGE_HASH}"
CONFIG_FILE="${NGINX_DEPLOY_DIR}/${PAGE_HASH}.conf"
NGINX_CUSTOM_DIR="${NGINX_DEPLOY_DIR}/custom"
REPO_PATH="${GIT_BASE}/${PAGE_HASH}.git"
PORTS_QUEUE_EVEN="/opt/deploy/ports_queue_even.txt"
PORTS_QUEUE_ODD="/opt/deploy/ports_queue_odd.txt"

# Из registry: кастомный домен (для удаления nginx custom) и порт (вернуть в очередь)
CUSTOM_DOMAIN=""
CONTAINER_PORT=""
if [[ -f "$REGISTRY_FILE" ]] && command -v jq >/dev/null 2>&1; then
  CUSTOM_DOMAIN=$(jq -r --arg h "$PAGE_HASH" '.[$h].custom_domain // empty' "$REGISTRY_FILE" 2>/dev/null)
  CONTAINER_PORT=$(jq -r --arg h "$PAGE_HASH" '.[$h].container_port // empty' "$REGISTRY_FILE" 2>/dev/null)
fi

# Вернуть порт в очередь (чётный → even, нечётный → odd)
return_port_to_queue() {
  local port="$1"
  [[ -z "$port" || "$port" == "null" || ! "$port" =~ ^[0-9]+$ ]] && return
  if (( port % 2 == 0 )); then
    echo "$port" >> "$PORTS_QUEUE_EVEN"
  else
    echo "$port" >> "$PORTS_QUEUE_ODD"
  fi
}

echo "Удаление сайта $PAGE_HASH..."

# 1. Остановить и удалить контейнер
if docker ps -a -q -f "name=^${CONTAINER_NAME}$" 2>/dev/null | grep -q .; then
  echo "  Остановка контейнера..."
  docker stop "$CONTAINER_NAME" 2>/dev/null || true
  docker rm "$CONTAINER_NAME" 2>/dev/null || true
  echo "  Контейнер удалён"
else
  echo "  Контейнер не найден"
fi

# 2. Удалить образ
if docker images -q "$IMAGE_NAME" 2>/dev/null | grep -q .; then
  echo "  Удаление образа..."
  docker rmi "$IMAGE_NAME" 2>/dev/null || true
  echo "  Образ удалён"
else
  echo "  Образ не найден"
fi

# 3. Удалить nginx конфиги (кастомный домен + превью по /hash/)
NGINX_CHANGED=false
if [[ -n "$CUSTOM_DOMAIN" ]] && [[ -f "${NGINX_CUSTOM_DIR}/${CUSTOM_DOMAIN}.conf" ]]; then
  rm "${NGINX_CUSTOM_DIR}/${CUSTOM_DOMAIN}.conf"
  echo "  Nginx конфиг кастомного домена (${CUSTOM_DOMAIN}) удалён"
  NGINX_CHANGED=true
fi
if [[ -f "$CONFIG_FILE" ]]; then
  rm "$CONFIG_FILE"
  echo "  Nginx конфиг (превью) удалён"
  NGINX_CHANGED=true
else
  echo "  Nginx конфиг превью не найден"
fi
if [[ "$NGINX_CHANGED" == true ]]; then
  nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true
fi

# 4. Удалить work tree
if [[ -d "$WORK_TREE" ]]; then
  rm -rf "$WORK_TREE"
  echo "  Work tree удалён"
else
  echo "  Work tree не найден"
fi

# 5. Удалить из registry и вернуть порт в очередь
if [[ -f "$REGISTRY_FILE" ]] && command -v jq >/dev/null 2>&1; then
  if jq -e ".\"$PAGE_HASH\"" "$REGISTRY_FILE" >/dev/null 2>&1; then
    return_port_to_queue "$CONTAINER_PORT"
    [[ -n "$CONTAINER_PORT" && "$CONTAINER_PORT" != "null" ]] && echo "  Порт $CONTAINER_PORT возвращён в очередь"
    jq "del(.\"$PAGE_HASH\")" "$REGISTRY_FILE" > "${REGISTRY_FILE}.tmp"
    mv "${REGISTRY_FILE}.tmp" "$REGISTRY_FILE"
    echo "  Запись из registry удалена"
  else
    echo "  Записи в registry нет"
  fi
else
  echo "  registry.json не найден или jq не установлен — пропуск"
fi

# 6. Удалить bare repo (по умолчанию; при push git_wrap создаст его заново)
if [[ "$PURGE_REPO" == true ]]; then
  if [[ -d "$REPO_PATH" ]]; then
    rm -rf "$REPO_PATH"
    echo "  Git репозиторий удалён (при следующем push будет создан заново)"
  else
    echo "  Git репозиторий не найден"
  fi
else
  echo "  Git репозиторий оставлен (--keep-repo)"
fi

# Лог удаления
DEPLOY_LOG="${DEPLOY_LOG:-/var/log/deploy/deploy.log}"
AT=$(date -Iseconds)
KEEP_REPO_VAL="false"
[[ "$PURGE_REPO" == false ]] && KEEP_REPO_VAL="true"
ENTRY="{\"action\":\"remove\",\"hash\":\"$PAGE_HASH\",\"at\":\"$AT\",\"keep_repo\":$KEEP_REPO_VAL}"
echo "$ENTRY" >> "$DEPLOY_LOG" 2>/dev/null || true

echo "Готово. Сайт $PAGE_HASH удалён."
