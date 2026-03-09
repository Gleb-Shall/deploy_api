#!/bin/bash
#
# Показать последние N деплоев из Redis.
# Использование: ./deploy_history.sh [N]
#

N="${1:-20}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"

redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" LRANGE deploy:history 0 $((N - 1)) 2>/dev/null | while read -r line; do
  [ -n "$line" ] && echo "$line" | jq -r '"\(.hash) | \(.start) - \(.end) | \(.result) | \(.duration_sec)s"' 2>/dev/null || echo "$line"
done
