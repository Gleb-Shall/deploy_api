#!/bin/bash
#
# Отправка domain_api на сервер и установка в нужные папки.
# Запуск: ./local_develope/deploy_domain_api.sh
#
# Пути:
#   DOMAIN_API_DIR = /opt/deploy_api/domain_api
#   systemd        = /etc/systemd/system/domain-api.service
#

set -e

SERVER="${DEPLOY_SERVER:-root@45.90.35.151}"
DOMAIN_API_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../domain_api" && pwd)"

echo "📤 Отправка domain_api на $SERVER..."

# Проверяем наличие необходимых файлов
if [ ! -f "$DOMAIN_API_SRC/api.py" ]; then
    echo "❌ Ошибка: api.py не найден в $DOMAIN_API_SRC"
    exit 1
fi

ssh "$SERVER" "mkdir -p /tmp/domain_api"

scp \
  "$DOMAIN_API_SRC/api.py" \
  "$DOMAIN_API_SRC/beget_client.py" \
  "$DOMAIN_API_SRC/config.py" \
  "$DOMAIN_API_SRC/media_storage.py" \
  "$DOMAIN_API_SRC/requirements.txt" \
  "$DOMAIN_API_SRC/.env.example" \
  "$SERVER:/tmp/domain_api/"

echo "📥 Установка на сервере..."

ssh "$SERVER" 'bash -s' << 'REMOTE'
set -e
DOMAIN_API_DIR="/opt/deploy_api/domain_api"

mkdir -p /tmp/domain_api
cd /tmp/domain_api

# Создаём директорию для domain_api
mkdir -p "$DOMAIN_API_DIR"

# Копируем файлы
cp -f api.py beget_client.py config.py media_storage.py requirements.txt "$DOMAIN_API_DIR/"
cp -f .env.example "$DOMAIN_API_DIR/"

# Устанавливаем права
chmod 644 "$DOMAIN_API_DIR"/*.py "$DOMAIN_API_DIR"/*.txt "$DOMAIN_API_DIR"/.env.example 2>/dev/null || true
chown -R root:root "$DOMAIN_API_DIR"

# Устанавливаем Python зависимости
echo "📦 Установка Python зависимостей..."

# Проверяем наличие python3
if ! command -v python3 >/dev/null 2>&1; then
    echo "   ❌ python3 не найден. Установите: apt install python3"
    exit 1
fi

# Устанавливаем python3-venv если модуль venv недоступен
if ! python3 -c "import venv" 2>/dev/null; then
    echo "   Установка python3-venv..."
    if command -v apt-get >/dev/null 2>&1; then
        PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
        apt-get update -qq >/dev/null 2>&1
        apt-get install -y -qq "python${PYTHON_VERSION}-venv" 2>/dev/null || \
        apt-get install -y -qq python3-venv 2>/dev/null || {
            echo "   ❌ Не удалось установить python3-venv. Установите вручную:"
            echo "      apt install python3-venv"
            exit 1
        }
    elif command -v yum >/dev/null 2>&1; then
        yum install -y -q python3-venv 2>/dev/null || exit 1
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y -q python3-venv 2>/dev/null || exit 1
    else
        echo "   ❌ Не найден пакетный менеджер (apt/yum/dnf). Установите python3-venv вручную"
        exit 1
    fi
fi

# Удаляем неполноценный venv если он есть
[ -d "$DOMAIN_API_DIR/venv" ] && [ ! -f "$DOMAIN_API_DIR/venv/bin/pip" ] && rm -rf "$DOMAIN_API_DIR/venv"

# Создаём venv если его нет
if [ ! -d "$DOMAIN_API_DIR/venv" ]; then
    echo "   Создание виртуального окружения..."
    python3 -m venv "$DOMAIN_API_DIR/venv" || {
        echo "   ❌ Ошибка создания venv. Проверьте установку python3-venv"
        exit 1
    }
fi

# Устанавливаем зависимости
"$DOMAIN_API_DIR/venv/bin/pip" install -q --upgrade pip
"$DOMAIN_API_DIR/venv/bin/pip" install -q -r "$DOMAIN_API_DIR/requirements.txt"
echo "   ✅ Зависимости установлены"

# Создаём systemd service
echo "🔧 Создание systemd service..."
cat > /etc/systemd/system/domain-api.service << 'SERVICEEOF'
[Unit]
Description=Domain API (Beget domain check/purchase)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/deploy_api/domain_api
Environment="PATH=/opt/deploy_api/domain_api/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/opt/deploy_api/domain_api/venv/bin/python /opt/deploy_api/domain_api/api.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/deploy/domain-api.log
StandardError=append:/var/log/deploy/domain-api.log

[Install]
WantedBy=multi-user.target
SERVICEEOF

# Создаём лог-файл
mkdir -p /var/log/deploy
touch /var/log/deploy/domain-api.log 2>/dev/null || true
chmod 644 /var/log/deploy/domain-api.log 2>/dev/null || true

# Перезагружаем systemd и запускаем/перезапускаем сервис
systemctl daemon-reload
systemctl enable domain-api.service 2>/dev/null || true
systemctl restart domain-api.service

echo ""
echo "✅ Domain API установлен в $DOMAIN_API_DIR"
echo ""
echo "📝 Следующие шаги:"
echo "   1. Создайте .env файл на сервере:"
echo "      sudo cp $DOMAIN_API_DIR/.env.example $DOMAIN_API_DIR/.env"
echo "      sudo nano $DOMAIN_API_DIR/.env"
echo "      # Заполните BEGET_LOGIN и BEGET_PASSWORD"
echo "      sudo chmod 600 $DOMAIN_API_DIR/.env"
echo ""
echo "   2. Запустите сервис:"
echo "      sudo systemctl start domain-api"
echo ""
echo "   3. Проверьте статус:"
echo "      sudo systemctl status domain-api"
echo "      sudo journalctl -u domain-api -f"
echo ""
REMOTE

# Nginx для поддомена media (картинки /picture/<id> через domain_api:5000)
MEDIA_DOMAIN="${MEDIA_DOMAIN:-media.automatoria.ru}"
echo "🌐 Nginx для $MEDIA_DOMAIN → 127.0.0.1:5000..."
ssh "$SERVER" "MEDIA_DOMAIN=$MEDIA_DOMAIN" 'bash -s' << 'NGINXREMOTE'
set -e
NGINX_CUSTOM_DIR="/etc/nginx/sites-available/deploy/custom"
mkdir -p "$NGINX_CUSTOM_DIR"
cat > "$NGINX_CUSTOM_DIR/${MEDIA_DOMAIN}.conf" << NGINXEOF
server {
    listen 80;
    listen [::]:80;
    server_name ${MEDIA_DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${MEDIA_DOMAIN};

    location /picture/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 30s;
    }

    location /screenshots/ {
        proxy_pass http://127.0.0.1:5051/screenshot/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 30s;
    }

    location /health {
        proxy_pass http://127.0.0.1:5000/health;
        access_log off;
    }
}
NGINXEOF
[[ -d /etc/nginx/sites-enabled ]] && ln -sf "$NGINX_CUSTOM_DIR/${MEDIA_DOMAIN}.conf" /etc/nginx/sites-enabled/ 2>/dev/null || true
nginx -t && systemctl reload nginx
CERTBOT_EMAIL="${CERTBOT_EMAIL:-deploy@automatoria.ru}"
[[ -f /opt/deploy/domain.txt ]] && CERTBOT_EMAIL="deploy@$(cat /opt/deploy/domain.txt 2>/dev/null | head -1)"
certbot --nginx -d "$MEDIA_DOMAIN" --redirect --non-interactive --agree-tos -m "$CERTBOT_EMAIL" 2>/dev/null || true
nginx -t && systemctl reload nginx 2>/dev/null || true
echo "   ✅ https://${MEDIA_DOMAIN}/picture/{id}"
echo "   ✅ https://${MEDIA_DOMAIN}/screenshots/{id}"
NGINXREMOTE

echo "🔄 Перезапуск domain-api..."
ssh "$SERVER" "systemctl restart domain-api.service 2>/dev/null || true"

echo ""
echo "✅ Деплой domain_api завершён (в т.ч. nginx для $MEDIA_DOMAIN)."
