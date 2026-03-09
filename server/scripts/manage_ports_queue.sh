#!/bin/bash
#
# Управление очередями портов для деплоя
# Использование:
#   ./manage_ports_queue.sh init      - инициализировать очереди портов
#   ./manage_ports_queue.sh rebuild   - пересобрать очереди из свободных портов
#

set -e

PORTS_QUEUE_EVEN="/opt/deploy/ports_queue_even.txt"
PORTS_QUEUE_ODD="/opt/deploy/ports_queue_odd.txt"
REGISTRY_FILE="/opt/deploy/registry.json"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [manage_ports_queue] $*"; }

# Функция инициализации очередей портов (чётные и нечётные)
init_ports_queue() {
  mkdir -p "$(dirname "$PORTS_QUEUE_EVEN")"
  
  # Генерируем чётные порты (9000, 9002, 9004, ...)
  local port=9000
  > "$PORTS_QUEUE_EVEN"
  while [[ $port -le 9998 ]]; do
    echo "$port" >> "$PORTS_QUEUE_EVEN"
    port=$((port + 2))
  done
  
  # Генерируем нечётные порты (9001, 9003, 9005, ...)
  port=9001
  > "$PORTS_QUEUE_ODD"
  while [[ $port -le 9998 ]]; do
    echo "$port" >> "$PORTS_QUEUE_ODD"
    port=$((port + 2))
  done
  
  log "Очереди портов инициализированы (чётные: $(wc -l < "$PORTS_QUEUE_EVEN"), нечётные: $(wc -l < "$PORTS_QUEUE_ODD"))"
}

# Функция пересборки очередей (просто переинициализация)
# Если очередь пуста, значит либо все порты заняты, либо что-то пошло не так
# В любом случае - просто переинициализируем (проверка занятости происходит при выделении порта)
rebuild_ports_queue() {
  log "Очередь портов пуста, переинициализируем..."
  init_ports_queue
}

# Основная логика
case "${1:-}" in
  init)
    init_ports_queue
    ;;
  rebuild)
    rebuild_ports_queue
    ;;
  *)
    echo "Usage: $0 {init|rebuild}" >&2
    echo "  init    - инициализировать очереди портов (все порты 9000-9998)" >&2
    echo "  rebuild - переинициализировать очереди (если очередь пуста)" >&2
    exit 1
    ;;
esac
