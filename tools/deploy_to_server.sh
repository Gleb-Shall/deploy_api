#!/bin/bash
#
# Отправка скриптов на сервер и установка в нужные папки.
# Запуск: ./tools/deploy_to_server.sh
# Пароль (если не ключ) запрашивается один раз — соединение переиспользуется для scp и команд на сервере.
#
# Пути (см. server/docs/PATHS.md):
#   SCRIPTS_DIR  = /opt/deploy_api/scripts
#   systemd      = /etc/systemd/system
#

set -e

SERVER="${DEPLOY_SERVER:-root@45.90.35.151}"
SCRIPT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../server/scripts" && pwd)"
SYSTEMD_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../server/systemd" && pwd)"

# Один сокет на хост — переиспользуем соединение, пароль один раз
CONTROL_SOCKET="/tmp/deploy_ssh_${SERVER//[^a-zA-Z0-9]/_}_$$"
cleanup_control() { ssh -o ControlPath="$CONTROL_SOCKET" -O exit "$SERVER" 2>/dev/null || true; }
trap cleanup_control EXIT

echo "📤 Отправка на $SERVER (пароль — один раз)..."

# Мастер-соединение: один запрос пароля, дальше scp и ssh переиспользуют его
ssh -o ControlMaster=yes -o ControlPath="$CONTROL_SOCKET" -o ControlPersist=120 -f -N "$SERVER"
ssh -o ControlPath="$CONTROL_SOCKET" "$SERVER" "mkdir -p /tmp/deploy_api"

scp -o ControlPath="$CONTROL_SOCKET" \
  "$SCRIPT_SRC/deploy_single.sh" \
  "$SCRIPT_SRC/deploy_worker.sh" \
  "$SCRIPT_SRC/install_deploy_workers.sh" \
  "$SCRIPT_SRC/remove_site.sh" \
  "$SCRIPT_SRC/git_wrap.sh" \
  "$SCRIPT_SRC/post-receive.template" \
  "$SCRIPT_SRC/check_deploy_status.sh" \
  "$SCRIPT_SRC/manage_ports_queue.sh" \
  "$SCRIPT_SRC/docker_pull_images.sh" \
  "$SYSTEMD_SRC/docker_pull_images.service" \
  "$SYSTEMD_SRC/docker_pull_images.timer" \
  "$SCRIPT_SRC/seo_submit_google.py" \
  "$SCRIPT_SRC/seo_submit_yandex.py" \
  "$SERVER:/tmp/deploy_api/"

# Опционально, если есть
[[ -f "$SCRIPT_SRC/deploy_history.sh" ]] && scp -o ControlPath="$CONTROL_SOCKET" "$SCRIPT_SRC/deploy_history.sh" "$SERVER:/tmp/deploy_api/" || true
[[ -f "$SCRIPT_SRC/diagnose_docker.sh" ]] && scp -o ControlPath="$CONTROL_SOCKET" "$SCRIPT_SRC/diagnose_docker.sh" "$SERVER:/tmp/deploy_api/" || true
[[ -f "$SCRIPT_SRC/get_yandex_oauth_token.py" ]] && scp -o ControlPath="$CONTROL_SOCKET" "$SCRIPT_SRC/get_yandex_oauth_token.py" "$SERVER:/tmp/deploy_api/" || true
[[ -f "$SCRIPT_SRC/get_google_oauth_token.py" ]] && scp -o ControlPath="$CONTROL_SOCKET" "$SCRIPT_SRC/get_google_oauth_token.py" "$SERVER:/tmp/deploy_api/" || true

echo "📥 Установка на сервере..."

ssh -o ControlPath="$CONTROL_SOCKET" "$SERVER" 'bash -s' << 'REMOTE'
set -e
SCRIPTS="/opt/deploy_api/scripts"

mkdir -p /tmp/deploy_api
cd /tmp/deploy_api

# Скрипты → /opt/deploy_api/scripts/
cp -f deploy_single.sh deploy_worker.sh install_deploy_workers.sh remove_site.sh git_wrap.sh "$SCRIPTS/"
# post-receive: сначала в .tmp, потом mv — атомарная замена, симлинки в репо сразу видят новую версию
cp -f post-receive.template "$SCRIPTS/post-receive.tmp" && mv -f "$SCRIPTS/post-receive.tmp" "$SCRIPTS/post-receive"
cp -f check_deploy_status.sh manage_ports_queue.sh docker_pull_images.sh "$SCRIPTS/"
cp -f seo_submit_google.py seo_submit_yandex.py "$SCRIPTS/"
[[ -f deploy_history.sh ]] && cp -f deploy_history.sh "$SCRIPTS/" || true
[[ -f diagnose_docker.sh ]] && cp -f diagnose_docker.sh "$SCRIPTS/" && chmod +x "$SCRIPTS/diagnose_docker.sh" || true
[[ -f get_yandex_oauth_token.py ]] && cp -f get_yandex_oauth_token.py "$SCRIPTS/" || true
[[ -f get_google_oauth_token.py ]] && cp -f get_google_oauth_token.py "$SCRIPTS/" || true

chmod +x "$SCRIPTS"/*.sh "$SCRIPTS"/post-receive

# Systemd (docker pull)
cp -f docker_pull_images.service docker_pull_images.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable docker_pull_images.timer 2>/dev/null || true
systemctl start docker_pull_images.timer 2>/dev/null || true

# Лог-файл
touch /var/log/deploy/deploy.log 2>/dev/null || true
chmod 644 /var/log/deploy/deploy.log 2>/dev/null || true

# Перезапуск воркеров
systemctl restart deploy-worker-1 deploy-worker-2 2>/dev/null || true

echo "✅ Готово. Скрипты в $SCRIPTS"
REMOTE

echo ""
echo "✅ Деплой завершён."
