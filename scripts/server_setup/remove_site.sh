#!/bin/bash
#
# Удаление деплоенного сайта
# Использование: sudo bash remove_site.sh PAGE_HASH [--keep-repo]
#
# PAGE_HASH   — хэш страницы (например 1d2637e8889b)
# По умолчанию удаляет и bare git repo — при следующем push git_wrap создаст его заново.
# --keep-repo — оставить bare репо (сайт не будет доступен, но push сработает без пересоздания)
#

set -e

PAGE_HASH="$1"
REGISTRY_FILE="/opt/deploy/registry.json"
NGINX_DEPLOY_DIR="/etc/nginx/sites-available/deploy"
GIT_BASE="/var/git/sites"

if [[ -z "$PAGE_HASH" || "$PAGE_HASH" == "--keep-repo" ]]; then
  echo "Использование: $0 PAGE_HASH [--keep-repo]"
  echo "  PAGE_HASH   — хэш сайта (например 1d2637e8889b)"
  echo "  --keep-repo — не удалять git репо (по умолчанию репо удаляется, push создаст его заново)"
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
REPO_PATH="${GIT_BASE}/${PAGE_HASH}.git"

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

# 3. Удалить nginx конфиг
if [[ -f "$CONFIG_FILE" ]]; then
  rm "$CONFIG_FILE"
  echo "  Nginx конфиг удалён"
else
  echo "  Nginx конфиг не найден"
fi

# 4. Удалить work tree
if [[ -d "$WORK_TREE" ]]; then
  rm -rf "$WORK_TREE"
  echo "  Work tree удалён"
else
  echo "  Work tree не найден"
fi

# 5. Удалить из registry.json
if [[ -f "$REGISTRY_FILE" ]] && command -v jq >/dev/null 2>&1; then
  if jq -e ".\"$PAGE_HASH\"" "$REGISTRY_FILE" >/dev/null 2>&1; then
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

echo "Готово. Сайт $PAGE_HASH удалён."
