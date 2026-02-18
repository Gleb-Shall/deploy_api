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
SCRIPTS_DIR="/opt/deploy_api/scripts"
CONTAINERS_BASE="/opt/deploy_api/containers"
REGISTRY_FILE="/opt/deploy/registry.json"
NGINX_DEPLOY_DIR="/etc/nginx/sites-available/deploy"

echo "🚀 Настройка сервера для Git push deploy"
echo "   DOMAIN=$DOMAIN"
echo ""

# 1. Установка пакетов (Ubuntu/Debian)
echo "1️⃣  Установка пакетов..."
apt-get update -qq
apt-get install -y git docker.io nginx jq redis-server redis-tools certbot python3-certbot-nginx

# 2. Пользователь git (если ещё нет)
echo ""
echo "2️⃣  Настройка пользователя git..."
if ! id -u git >/dev/null 2>&1; then
  useradd -m -s /bin/bash git
  mkdir -p /home/git/.ssh
  chmod 700 /home/git/.ssh
  touch /home/git/.ssh/authorized_keys
  chmod 600 /home/git/.ssh/authorized_keys
  chown -R git:git /home/git
  echo "   ✅ Пользователь git создан"
else
  chsh -s /bin/bash git 2>/dev/null || true
  echo "   ✅ Пользователь git уже есть (shell=/bin/bash)"
fi

# 3. Директории
echo ""
echo "3️⃣  Создание директорий..."
mkdir -p "$GIT_BASE"
mkdir -p "$WORK_TREE_BASE"
mkdir -p "$SCRIPTS_DIR"
mkdir -p "$CONTAINERS_BASE"
mkdir -p "$(dirname "$REGISTRY_FILE")"
mkdir -p "$NGINX_DEPLOY_DIR"
echo '{}' > "$REGISTRY_FILE"
chmod 644 "$REGISTRY_FILE"
echo "$DOMAIN" > "$(dirname "$REGISTRY_FILE")/domain.txt" 2>/dev/null || true
echo "   ✅ $GIT_BASE, $WORK_TREE_BASE, $SCRIPTS_DIR, $NGINX_DEPLOY_DIR"

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

# 5. Redis
echo ""
echo "5️⃣  Redis..."
systemctl enable redis-server
systemctl start redis-server
echo "   ✅ Redis запущен"

# 6. Docker
echo ""
echo "6️⃣  Docker..."
systemctl enable docker
systemctl start docker
echo "   ✅ Docker запущен"

# 7. Nginx — базовый конфиг для deploy (HTTP + HTTPS)
echo ""
echo "7️⃣  Nginx..."
NGINX_MAIN="/etc/nginx/sites-available/deploy_main"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-deploy@${DOMAIN}}"
if [ ! -f "$NGINX_MAIN" ]; then
  cat > "$NGINX_MAIN" << NGINXEOF
# Главный конфиг для deploy-сайтов (Git push -> post-receive)
# Сайты: https://DOMAIN/{page_hash}/

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name $DOMAIN _;

    # Сайты деплоятся в /{page_hash}/
    include /etc/nginx/sites-available/deploy/*.conf;

    # ACME challenge для Let's Encrypt
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Заглушка для корня
    location / {
        return 200 'Deploy: сайты по /{hash}/';
        add_header Content-Type text/plain;
    }
}
NGINXEOF
  mkdir -p /var/www/certbot
  rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
  ln -sf "$NGINX_MAIN" /etc/nginx/sites-enabled/deploy_main 2>/dev/null || true
  nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true
  echo "   ✅ Конфиг deploy создан"
  if [ ! -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "   Получение SSL-сертификата (Let's Encrypt)..."
    certbot --nginx -d "$DOMAIN" --redirect --non-interactive --agree-tos -m "$CERTBOT_EMAIL" 2>/dev/null && \
      echo "   ✅ SSL включён (редирект 80→443)" || echo "   ⚠️  certbot не выполнен — проверь DOMAIN и порт 80"
  else
    certbot --nginx -d "$DOMAIN" --redirect --non-interactive 2>/dev/null || true
    echo "   ✅ SSL уже настроен"
  fi
else
  echo "   ✅ Конфиг deploy уже есть"
  # Добавляем HTTPS, если сертификата ещё нет
  if [ ! -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "   Получение SSL-сертификата..."
    certbot --nginx -d "$DOMAIN" --redirect --non-interactive --agree-tos -m "$CERTBOT_EMAIL" 2>/dev/null && \
      echo "   ✅ SSL включён" || echo "   ⚠️  certbot не выполнен"
  fi
fi

# 8. Systemd path для авто-reload nginx
echo ""
echo "8️⃣  Авто-reload nginx при изменении конфигов..."
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

# 9. post-receive, git_wrap, deploy worker (инфраструктура в /opt/deploy_api)
SCRIPT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$SCRIPTS_DIR"
cp "$SCRIPT_SRC/post-receive.template" "$SCRIPTS_DIR/post-receive"
cp "$SCRIPT_SRC/git_wrap.sh" "$SCRIPTS_DIR/"
cp "$SCRIPT_SRC/remove_site.sh" "$SCRIPTS_DIR/"
cp "$SCRIPT_SRC/deploy_single.sh" "$SCRIPTS_DIR/"
cp "$SCRIPT_SRC/deploy_worker.sh" "$SCRIPTS_DIR/"
cp "$SCRIPT_SRC/check_deploy_status.sh" "$SCRIPTS_DIR/"
cp "$SCRIPT_SRC/manage_ports_queue.sh" "$SCRIPTS_DIR/"
cp "$SCRIPT_SRC/docker_pull_images.sh" "$SCRIPTS_DIR/" 2>/dev/null || true
cp "$SCRIPT_SRC/docker_pull_images.service" "$SCRIPT_SRC/docker_pull_images.timer" /etc/systemd/system/ 2>/dev/null || true
chmod +x "$SCRIPTS_DIR"/post-receive "$SCRIPTS_DIR"/git_wrap.sh "$SCRIPTS_DIR"/remove_site.sh "$SCRIPTS_DIR"/deploy_single.sh "$SCRIPTS_DIR"/deploy_worker.sh "$SCRIPTS_DIR"/check_deploy_status.sh "$SCRIPTS_DIR"/manage_ports_queue.sh
chmod +x "$SCRIPTS_DIR"/docker_pull_images.sh 2>/dev/null || true
chown -R root:git "$(dirname "$SCRIPTS_DIR")" 2>/dev/null || true
chmod 755 "$SCRIPTS_DIR"
echo ""
echo "9️⃣  post-receive + git_wrap + remove_site + deploy_worker установлены в $SCRIPTS_DIR"

# 10. Базовые образы Docker
echo ""
echo "🔟  Базовые образы (node, nginx)..."
[ -x "$SCRIPTS_DIR/docker_pull_images.sh" ] && "$SCRIPTS_DIR/docker_pull_images.sh" || echo "   ⚠️  docker_pull_images.sh не найден"

# 11. Deploy workers (2 экземпляра, max 2 одновременных деплоя)
echo ""
echo "1️⃣1️⃣  Deploy workers (очередь Redis, 2 воркера)..."
mkdir -p /var/log/deploy
chmod 755 /var/log/deploy
touch /var/log/deploy/deploy.log
chmod 644 /var/log/deploy/deploy.log
for i in 1 2; do
  cat > "/etc/systemd/system/deploy-worker-${i}.service" << EOF
[Unit]
Description=Deploy worker $i
After=redis-server.service docker.service

[Service]
Type=simple
Environment=WORKER_ID=$i
ExecStart=$SCRIPTS_DIR/deploy_worker.sh
Restart=always
User=root
StandardOutput=append:/var/log/deploy/worker-${i}.log
StandardError=append:/var/log/deploy/worker-${i}.log

[Install]
WantedBy=multi-user.target
EOF
  systemctl enable "deploy-worker-${i}"
  systemctl start "deploy-worker-${i}"
done
echo "   ✅ deploy-worker-1, deploy-worker-2 запущены (логи: /var/log/deploy/worker-*.log)"

# 12. Docker pull timer + проверка nginx
echo ""
echo "1️⃣2️⃣  Docker pull (еженедельно) + nginx..."
systemctl daemon-reload 2>/dev/null || true
systemctl enable docker_pull_images.timer 2>/dev/null || true
systemctl start docker_pull_images.timer 2>/dev/null || true
nginx -t 2>/dev/null && systemctl reload nginx || echo "   ⚠️  nginx -t не прошёл, проверь конфиг вручную"

echo ""

echo ""
echo "Очередь деплоев: Redis (deploy_queue), max 2 одновременных."
echo ""
echo "✅ Готово."
echo ""
echo "Добавь в /home/git/.ssh/authorized_keys:"
echo "  command=\"$SCRIPTS_DIR/git_wrap.sh\" ssh-rsa AAAA...твой_ключ"
echo ""
echo "Push в sites/PAGE_HASH.git — репо создаётся, post-receive ставится и выполняется."
echo ""
