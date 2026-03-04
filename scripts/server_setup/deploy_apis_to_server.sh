#!/bin/bash
#
# Скидывает на сервер только то, что нужно для API: domain_api, screenshot_api и скрипты systemd.
# Запуск с локальной машины из корня репо: SERVER=root@хост ./scripts/server_setup/deploy_apis_to_server.sh
#
# На сервере после первого раза: создать .env в domain_api, поставить pip зависимости, запустить install_api_services.sh.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVER="${SERVER:-root@45.90.35.151}"
REMOTE_DIR="${REMOTE_DIR:-/opt/deploy_api}"

echo "Копирую в $SERVER:$REMOTE_DIR ..."

ssh "$SERVER" "mkdir -p $REMOTE_DIR/domain_api $REMOTE_DIR/screenshot_api $REMOTE_DIR/scripts"

rsync -avz --exclude '__pycache__' --exclude '.env' --exclude '*.pyc' \
  "$REPO_ROOT/domain_api/" "$SERVER:$REMOTE_DIR/domain_api/"

rsync -avz --exclude '__pycache__' --exclude '.env' --exclude '*.pyc' \
  "$REPO_ROOT/screenshot_api/" "$SERVER:$REMOTE_DIR/screenshot_api/"

scp "$REPO_ROOT/scripts/server_setup/install_api_services.sh" \
    "$REPO_ROOT/scripts/server_setup/domain_api.service" \
    "$REPO_ROOT/scripts/server_setup/screenshot_api.service" \
    "$SERVER:$REMOTE_DIR/scripts/"

echo "✅ Готово. Дальше на сервере:"
echo "   cd $REMOTE_DIR/domain_api && cp .env.example .env && nano .env && pip3 install -r requirements.txt"
echo "   cd $REMOTE_DIR/screenshot_api && pip3 install -r requirements.txt"
echo "   sudo $REMOTE_DIR/scripts/install_api_services.sh"
