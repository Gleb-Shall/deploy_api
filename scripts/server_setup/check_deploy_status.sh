#!/bin/bash
#
# Проверка статуса деплоя: ok / fail / (пусто = ещё в очереди или не запускался)
# Использование: ./check_deploy_status.sh PAGE_HASH
#

PAGE_HASH="$1"
[[ -n "$PAGE_HASH" ]] || { echo "Usage: $0 PAGE_HASH" >&2; exit 1; }

REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"

STATUS=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" HGET deploy:status "$PAGE_HASH" 2>/dev/null)
echo "${STATUS:-pending}"
