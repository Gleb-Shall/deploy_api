#!/bin/bash
#
# Деплой Screenshot API на сервер (скриншоты Playwright, модуль генерации).
# Запуск: ./local_develope/deploy_screenshot_api.sh
#
# Пути:
#   SCREENSHOT_API_DIR = /opt/deploy_api/screenshot_api
#   systemd            = /etc/systemd/system/screenshot-api.service
#

set -e

SERVER="${DEPLOY_SERVER:-root@45.90.35.151}"
SCREENSHOT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../screenshot_api" && pwd)"

echo "📤 Отправка screenshot_api на $SERVER..."

if [[ ! -f "$SCREENSHOT_SRC/api.py" ]]; then
    echo "❌ Ошибка: api.py не найден в $SCREENSHOT_SRC"
    exit 1
fi

ssh "$SERVER" "mkdir -p /tmp/screenshot_api"

scp \
  "$SCREENSHOT_SRC/api.py" \
  "$SCREENSHOT_SRC/config.py" \
  "$SCREENSHOT_SRC/requirements.txt" \
  "$SERVER:/tmp/screenshot_api/"

echo "📥 Установка на сервере..."

ssh "$SERVER" 'bash -s' << 'REMOTE'
set -e
SCREENSHOT_API_DIR="/opt/deploy_api/screenshot_api"

mkdir -p /tmp/screenshot_api
cd /tmp/screenshot_api

mkdir -p "$SCREENSHOT_API_DIR"
cp -f api.py config.py requirements.txt "$SCREENSHOT_API_DIR/"
chmod 644 "$SCREENSHOT_API_DIR"/*.py "$SCREENSHOT_API_DIR"/*.txt 2>/dev/null || true
chown -R root:root "$SCREENSHOT_API_DIR"

echo "📦 Установка Python зависимостей..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "   ❌ python3 не найден. Установите: apt install python3"
    exit 1
fi
if ! python3 -c "import venv" 2>/dev/null; then
    echo "   Установка python3-venv..."
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq >/dev/null 2>&1
        apt-get install -y -qq python3-venv 2>/dev/null || {
            echo "   ❌ Не удалось установить python3-venv"
            exit 1
        }
    else
        echo "   ❌ Установите python3-venv вручную"
        exit 1
    fi
fi

[[ -d "$SCREENSHOT_API_DIR/venv" ]] && [[ ! -f "$SCREENSHOT_API_DIR/venv/bin/pip" ]] && rm -rf "$SCREENSHOT_API_DIR/venv"
if [[ ! -d "$SCREENSHOT_API_DIR/venv" ]]; then
    echo "   Создание venv..."
    python3 -m venv "$SCREENSHOT_API_DIR/venv" || exit 1
fi

"$SCREENSHOT_API_DIR/venv/bin/pip" install -q --upgrade pip
"$SCREENSHOT_API_DIR/venv/bin/pip" install -q -r "$SCREENSHOT_API_DIR/requirements.txt"
echo "   ✅ Зависимости установлены"

echo "🔧 Создание systemd service..."
cat > /etc/systemd/system/screenshot-api.service << 'SERVICEEOF'
[Unit]
Description=Screenshot API (Playwright screenshots, module generator)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/deploy_api/screenshot_api
Environment="PATH=/opt/deploy_api/screenshot_api/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/opt/deploy_api/screenshot_api/venv/bin/python /opt/deploy_api/screenshot_api/api.py
Restart=always
RestartSec=5
StandardOutput=append:/var/log/deploy/screenshot-api.log
StandardError=append:/var/log/deploy/screenshot-api.log

[Install]
WantedBy=multi-user.target
SERVICEEOF

mkdir -p /var/log/deploy
touch /var/log/deploy/screenshot-api.log 2>/dev/null || true
chmod 644 /var/log/deploy/screenshot-api.log 2>/dev/null || true

systemctl daemon-reload
systemctl enable screenshot-api.service 2>/dev/null || true
systemctl restart screenshot-api.service

echo ""
echo "✅ Screenshot API установлен в $SCREENSHOT_API_DIR (порт 5051)"
echo "   Upload: POST http://127.0.0.1:5051/api/screenshots"
echo "   Просмотр: GET http://127.0.0.1:5051/screenshot/<id>"
echo "   Опционально: создайте .env с SCREENSHOT_API_KEY, SCREENSHOT_STORAGE_DIR"
REMOTE

echo ""
echo "✅ Деплой screenshot_api завершён."
