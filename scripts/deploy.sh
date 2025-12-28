#!/bin/bash

# Скрипт для деплоя API на сервер

set -e

echo "🚀 Деплой Deploy API на сервер"

# Проверяем переменные окружения
if [ -z "$SSH_HOST" ] || [ -z "$SSH_USER" ]; then
    echo "❌ Ошибка: SSH_HOST и SSH_USER должны быть установлены"
    exit 1
fi

# Собираем Docker образ
echo "📦 Сборка Docker образа..."
docker build -t deploy-api:latest .

# Сохраняем образ в tar файл
echo "💾 Сохранение образа..."
docker save deploy-api:latest | gzip > deploy-api.tar.gz

# Копируем образ на сервер
echo "📤 Копирование образа на сервер..."
scp -i "${SSH_KEY_PATH:-~/.ssh/id_rsa}" deploy-api.tar.gz ${SSH_USER}@${SSH_HOST}:/tmp/

# Деплоим на сервер
echo "🔧 Деплой на сервер..."
ssh -i "${SSH_KEY_PATH:-~/.ssh/id_rsa}" ${SSH_USER}@${SSH_HOST} << 'EOF'
set -e

# Загружаем образ
echo "📥 Загрузка образа..."
docker load < /tmp/deploy-api.tar.gz

# Останавливаем старый контейнер
echo "🛑 Остановка старого контейнера..."
docker stop deploy-api 2>/dev/null || true
docker rm deploy-api 2>/dev/null || true

# Создаем директории
mkdir -p /root/deploy_api/containers

# Запускаем новый контейнер
echo "▶️  Запуск нового контейнера..."
docker run -d \
  --name deploy-api \
  --restart unless-stopped \
  -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /root/deploy_api/containers:/app/containers \
  -e DOMAIN="${DOMAIN:-your-domain.com}" \
  -e SSH_HOST="${SSH_HOST}" \
  -e SSH_USER="${SSH_USER}" \
  -e RUN_ON_SERVER=1 \
  deploy-api:latest

# Очищаем
rm -f /tmp/deploy-api.tar.gz
docker image prune -f

echo "✅ Деплой завершен!"
EOF

# Удаляем локальный tar файл
rm -f deploy-api.tar.gz

echo "✅ Готово! API доступен на http://${SSH_HOST}:8000"

