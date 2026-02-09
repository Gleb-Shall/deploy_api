#!/bin/bash
#
# Настройка нового сервера для Git push → deploy (post-receive)
# Запуск: sudo bash scripts/server_setup/setup_fresh_server.sh
#
# Перед запуском задай DOMAIN (опционально):
#   export DOMAIN=example.com
#

set -e

DOMAIN="${DOMAIN:-your-domain.com}"
GIT_BASE="/var/git/sites"
WORK_TREE_BASE="/opt/deploy"
CONTAINERS_BASE="/root/deploy_api/containers"
REGISTRY_FILE="/opt/deploy/registry.json"
NGINX_DEPLOY_DIR="/etc/nginx/sites-available/deploy"

echo "🚀 Настройка сервера для Git push deploy"
echo "   DOMAIN=$DOMAIN"
echo ""

# 1. Установка пакетов (Ubuntu/Debian)
echo "1️⃣  Установка пакетов..."
apt-get update -qq
apt-get install -y git docker.io nginx jq

# 2. Пользователь git (если ещё нет)
echo ""
echo "2️⃣  Настройка пользователя git..."
if ! id -u git >/dev/null 2>&1; then
  useradd -m -s /usr/bin/git-shell git
  mkdir -p /home/git/.ssh
  chmod 700 /home/git/.ssh
  touch /home/git/.ssh/authorized_keys
  chmod 600 /home/git/.ssh/authorized_keys
  chown -R git:git /home/git
  echo "   ✅ Пользователь git создан"
else
  echo "   ✅ Пользователь git уже есть"
fi

# 3. Директории
echo ""
echo "3️⃣  Создание директорий..."
mkdir -p "$GIT_BASE"
mkdir -p "$WORK_TREE_BASE"
mkdir -p "$CONTAINERS_BASE"
mkdir -p "$(dirname "$REGISTRY_FILE")"
mkdir -p "$NGINX_DEPLOY_DIR"
touch "$REGISTRY_FILE"
chmod 644 "$REGISTRY_FILE"
echo "   ✅ $GIT_BASE, $WORK_TREE_BASE, $NGINX_DEPLOY_DIR"

# 4. Права для git
echo ""
echo "4️⃣  Права доступа..."
# git должен иметь доступ к work tree и docker (через группу docker)
usermod -aG docker git 2>/dev/null || true
chown -R git:git "$GIT_BASE"
# root владеет /opt/deploy и registry — post-receive будет запускаться от root или git с sudo
# Для простоты: хук от root, тогда git push идёт как root. Или git с ограничениями.
# Стандарт: push идёт от пользователя (git или по SSH ключу), hook выполняется от этого пользователя.
# Значит git должен уметь: писать в /opt/deploy, вызывать docker, писать в nginx.
# Проще всего: git в группе docker, chmod 2775 для /opt/deploy и /etc/nginx/sites-available/deploy с группой git
chown root:git "$WORK_TREE_BASE"
chmod 2775 "$WORK_TREE_BASE"
chown -R root:git "$(dirname "$REGISTRY_FILE")"
chmod 775 "$(dirname "$REGISTRY_FILE")"
chmod 664 "$REGISTRY_FILE"
chown -R root:git "$NGINX_DEPLOY_DIR"
chmod 2775 "$NGINX_DEPLOY_DIR"

# 5. Docker
echo ""
echo "5️⃣  Docker..."
systemctl enable docker
systemctl start docker
echo "   ✅ Docker запущен"

# 6. Nginx — базовый конфиг для deploy
echo ""
echo "6️⃣  Nginx..."
NGINX_MAIN="/etc/nginx/sites-available/deploy_main"
if [ ! -f "$NGINX_MAIN" ]; then
  cat > "$NGINX_MAIN" << NGINXEOF
# Главный конфиг для deploy-сайтов (Git push -> post-receive)
# Сайты доступны по http://DOMAIN/{page_hash}/

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name $DOMAIN _;

    # Сайты деплоятся в /{page_hash}/
    include /etc/nginx/sites-available/deploy/*.conf;

    # Заглушка для корня
    location / {
        return 200 'Deploy: сайты по /{hash}/';
        add_header Content-Type text/plain;
    }
}
NGINXEOF
  # Отключаем дефолтный nginx конфиг, включаем наш
  rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
  ln -sf "$NGINX_MAIN" /etc/nginx/sites-enabled/deploy_main 2>/dev/null || true
  echo "   ✅ Конфиг deploy создан"
else
  echo "   ✅ Конфиг deploy уже есть"
fi

# 7. Systemd path для авто-reload nginx
echo ""
echo "7️⃣  Авто-reload nginx при изменении конфигов..."
cat > /etc/systemd/system/nginx-reload.path << 'EOF'
[Unit]
Description=Watch for nginx deploy config changes

[Path]
PathChanged=/etc/nginx/sites-available/deploy/
PathModified=/etc/nginx/sites-available/deploy/
Unit=nginx-reload.service

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/nginx-reload.service << 'EOF'
[Unit]
Description=Reload nginx when deploy configs change
After=nginx.service
Requires=nginx.service

[Service]
Type=oneshot
ExecStart=/bin/systemctl reload nginx
User=root
EOF

systemctl daemon-reload
systemctl enable nginx-reload.path
systemctl start nginx-reload.path
echo "   ✅ nginx-reload.path включён"

# 8. post-receive и git_wrap
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p /opt/deploy/scripts
cp "$SCRIPT_DIR/post-receive.template" /opt/deploy/scripts/post-receive
cp "$SCRIPT_DIR/git_wrap.sh" /opt/deploy/scripts/
cp "$SCRIPT_DIR/remove_site.sh" /opt/deploy/scripts/
chmod +x /opt/deploy/scripts/post-receive /opt/deploy/scripts/git_wrap.sh /opt/deploy/scripts/remove_site.sh
echo ""
echo "8️⃣  post-receive + git_wrap + remove_site установлены"

# 9. Проверка nginx
echo ""
echo "9️⃣  Проверка nginx..."
nginx -t 2>/dev/null && systemctl reload nginx || echo "   ⚠️  nginx -t не прошёл, проверь конфиг вручную"

echo ""
echo "✅ Готово."
echo ""
echo "Добавь в /home/git/.ssh/authorized_keys:"
echo '  command="/opt/deploy/scripts/git_wrap.sh" ssh-rsa AAAA...твой_ключ'
echo ""
echo "Push в sites/PAGE_HASH.git — репо создаётся, post-receive ставится и выполняется."
echo ""
