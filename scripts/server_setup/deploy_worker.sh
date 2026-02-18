#!/bin/bash
#
# Воркер очереди деплоев. Берёт задачи из Redis, выполняет deploy_single.
# Запускать 2 экземпляра (systemd) — max 2 одновременных деплоя.
#

REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
QUEUE="deploy_queue"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SCRIPT="$SCRIPT_DIR/deploy_single.sh"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [worker $WORKER_ID] $*"; }
WORKER_ID="${WORKER_ID:-$(hostname)}"

while true; do
  JOB=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" BLPOP "$QUEUE" 0 2>/dev/null | tail -1)
  [[ -n "$JOB" ]] || continue
  
  # Парсим JSON: {"hash":"PAGE_HASH","deploy_id":"DEPLOY_ID"}
  # Поддерживаем старый формат (просто PAGE_HASH) для обратной совместимости
  if command -v jq >/dev/null 2>&1 && echo "$JOB" | jq -e . >/dev/null 2>&1; then
    PAGE_HASH=$(echo "$JOB" | jq -r '.hash // empty')
    DEPLOY_ID=$(echo "$JOB" | jq -r '.deploy_id // empty')
    [[ -z "$PAGE_HASH" ]] && PAGE_HASH="$JOB"
  else
    PAGE_HASH="$JOB"
    DEPLOY_ID=""
  fi
  
  log "JOB $PAGE_HASH${DEPLOY_ID:+ (deploy_id: $DEPLOY_ID)} started"
  START=$(date -Iseconds)
  START_SEC=$(date +%s)
  if "$DEPLOY_SCRIPT" "$PAGE_HASH" "$DEPLOY_ID"; then
    log "JOB $PAGE_HASH${DEPLOY_ID:+ (deploy_id: $DEPLOY_ID)} OK"
    RESULT="ok"
    ERROR=""
  else
    log "JOB $PAGE_HASH${DEPLOY_ID:+ (deploy_id: $DEPLOY_ID)} FAILED"
    RESULT="fail"
    ERROR="deploy failed"
  fi
  END=$(date -Iseconds)
  DURATION=$(($(date +%s) - START_SEC))
  ERR_JSON="null"
  [[ -n "$ERROR" ]] && ERR_JSON="\"${ERROR//\"/\\\"}\""
  ENTRY="{\"hash\":\"$PAGE_HASH\",\"deploy_id\":\"${DEPLOY_ID:-}\",\"start\":\"$START\",\"end\":\"$END\",\"result\":\"$RESULT\",\"duration_sec\":$DURATION,\"error\":$ERR_JSON}"

  # Файл логов (все деплои за всё время)
  DEPLOY_LOG="${DEPLOY_LOG:-/var/log/deploy/deploy.log}"
  echo "$ENTRY" >> "$DEPLOY_LOG" 2>/dev/null || true
done
