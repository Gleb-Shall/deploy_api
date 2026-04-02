#!/bin/bash
#
# Деплой media сервера (178.72.171.111) с нуля или обновление.
# Копирует screenshot_api, media_api, nginx конфиг, systemd units.
#
# Запуск: ./tools/deploy_media_server.sh
# Другой сервер: MEDIA_SERVER=root@1.2.3.4 ./tools/deploy_media_server.sh
#

set -e

MEDIA_SERVER="${MEDIA_SERVER:-root@178.72.171.111}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Деплой media сервера на $MEDIA_SERVER..."

# Копируем исходники screenshot_api и media_api
echo "==> Копирование исходников..."
ssh "$MEDIA_SERVER" "mkdir -p /tmp/deploy_media"
scp "$REPO_ROOT/screenshot_api/api.py" \
    "$REPO_ROOT/screenshot_api/config.py" \
    "$REPO_ROOT/screenshot_api/requirements.txt" \
    "$MEDIA_SERVER:/tmp/deploy_media/"

scp "$REPO_ROOT/media_api/api.py" \
    "$REPO_ROOT/media_api/storage.py" \
    "$REPO_ROOT/media_api/requirements.txt" \
    "$MEDIA_SERVER:/tmp/deploy_media/" 2>/dev/null || true

# Копируем nginx конфиг
echo "==> Копирование nginx конфига..."
scp "$REPO_ROOT/server/nginx/media_api.conf" \
    "$MEDIA_SERVER:/etc/nginx/sites-available/media_api"

# Копируем systemd units
echo "==> Копирование systemd units..."
scp "$REPO_ROOT/server/systemd/screenshot_api.service" \
    "$REPO_ROOT/server/systemd/media_api.service" \
    "$MEDIA_SERVER:/etc/systemd/system/"

# Устанавливаем на сервере
echo "==> Установка на сервере..."
ssh "$MEDIA_SERVER" 'bash -s' << 'REMOTE'
set -e

SCREENSHOT_DIR="/opt/deploy_api/screenshot_api"
MEDIA_DIR="/opt/deploy_api/media_api"

mkdir -p "$SCREENSHOT_DIR" "$MEDIA_DIR"

# screenshot_api
cp /tmp/deploy_media/api.py /tmp/deploy_media/config.py /tmp/deploy_media/requirements.txt "$SCREENSHOT_DIR/"

# media_api (если файлы пришли)
[ -f /tmp/deploy_media/storage.py ] && cp /tmp/deploy_media/api.py /tmp/deploy_media/storage.py /tmp/deploy_media/requirements.txt "$MEDIA_DIR/" 2>/dev/null || true

# venv + зависимости screenshot_api
if [ ! -d "$SCREENSHOT_DIR/venv" ]; then
    echo "   Создание venv для screenshot_api..."
    python3 -m venv "$SCREENSHOT_DIR/venv"
fi
"$SCREENSHOT_DIR/venv/bin/pip" install -q --upgrade pip
"$SCREENSHOT_DIR/venv/bin/pip" install -q -r "$SCREENSHOT_DIR/requirements.txt"

# venv + зависимости media_api
if [ -f "$MEDIA_DIR/requirements.txt" ]; then
    if [ ! -d "$MEDIA_DIR/venv" ]; then
        echo "   Создание venv для media_api..."
        python3 -m venv "$MEDIA_DIR/venv"
    fi
    "$MEDIA_DIR/venv/bin/pip" install -q --upgrade pip
    "$MEDIA_DIR/venv/bin/pip" install -q -r "$MEDIA_DIR/requirements.txt"
fi

# nginx
echo "   Проверка nginx конфига..."
nginx -t
systemctl reload nginx

# systemd
systemctl daemon-reload
systemctl enable screenshot_api media_api 2>/dev/null || true
systemctl restart screenshot_api media_api

# health checks
sleep 3
curl -sf http://127.0.0.1:5051/health && echo "   screenshot_api OK" || echo "   WARNING: screenshot_api health check failed"
curl -sf http://127.0.0.1:5052/health && echo "   media_api OK" || echo "   WARNING: media_api health check failed"

rm -rf /tmp/deploy_media
echo "==> Media сервер обновлён."
REMOTE

echo ""
echo "✅ Деплой media сервера завершён."
echo "   screenshot_api: https://media.automatoria.ru/screenshots/<id>"
echo "   media_api:      https://media.automatoria.ru/file/<id>"
