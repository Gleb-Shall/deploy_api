#!/bin/bash
#
# Ставит systemd-сервисы domain_api (порт 5000) и screenshot_api (порт 5051).
# Запуск на сервере: sudo bash scripts/server_setup/install_api_services.sh
#
# Требуется: проект в /opt/deploy_api, в domain_api/ и screenshot_api/ установлены
# зависимости (pip install -r requirements.txt) и при необходимости настроены .env.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_API="${DEPLOY_API:-/opt/deploy_api}"

for name in domain_api screenshot_api; do
  if [[ ! -f "$SCRIPT_DIR/${name}.service" ]]; then
    echo "Ошибка: не найден $SCRIPT_DIR/${name}.service" >&2
    exit 1
  fi
  if [[ ! -d "$DEPLOY_API/$name" ]]; then
    echo "Пропуск $name: нет каталога $DEPLOY_API/$name"
    continue
  fi
  cp "$SCRIPT_DIR/${name}.service" "/etc/systemd/system/${name}.service"
  echo "  ${name}.service установлен"
done

systemctl daemon-reload
for name in domain_api screenshot_api; do
  if [[ -d "$DEPLOY_API/$name" ]]; then
    systemctl enable "$name" 2>/dev/null || true
    systemctl restart "$name"
    echo "  $name: включён и перезапущен"
  fi
done
echo "✅ Готово. Статус: systemctl status domain_api screenshot_api"
