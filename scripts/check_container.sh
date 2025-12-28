#!/bin/bash
# Скрипт для проверки содержимого контейнера

CONTAINER_NAME=${1:-"deploy-1d2637e8889b"}

echo "Проверка контейнера: $CONTAINER_NAME"
echo ""

echo "=== Статус контейнера ==="
docker ps --filter "name=$CONTAINER_NAME"

echo ""
echo "=== Логи контейнера (последние 30 строк) ==="
docker logs "$CONTAINER_NAME" --tail 30

echo ""
echo "=== Содержимое /usr/share/nginx/html в контейнере ==="
docker exec "$CONTAINER_NAME" ls -la /usr/share/nginx/html/ 2>/dev/null || echo "Контейнер не запущен или nginx не используется"

echo ""
echo "=== HTML файлы ==="
docker exec "$CONTAINER_NAME" find /usr/share/nginx/html -name "*.html" 2>/dev/null | head -5

echo ""
echo "=== CSS файлы ==="
docker exec "$CONTAINER_NAME" find /usr/share/nginx/html -name "*.css" 2>/dev/null | head -5

echo ""
echo "=== Проверка index.html ==="
docker exec "$CONTAINER_NAME" head -50 /usr/share/nginx/html/index.html 2>/dev/null | grep -E "(style|link|css)" || echo "Файл не найден или нет стилей"

