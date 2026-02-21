#!/bin/bash
#
# Создаёт или обновляет systemd-юниты воркеров деплоя (deploy-worker-1, deploy-worker-2).
# Запуск: sudo [CERTBOT_EMAIL=admin@example.com] bash scripts/server_setup/install_deploy_workers.sh
#
# Удобно после обновления скриптов на сервере или чтобы добавить/сменить CERTBOT_EMAIL
# без повторного полного setup_fresh_server.sh.

set -e

SCRIPTS_DIR="${SCRIPTS_DIR:-/opt/deploy_api/scripts}"

if [[ ! -x "$SCRIPTS_DIR/deploy_worker.sh" ]]; then
  echo "Ошибка: $SCRIPTS_DIR/deploy_worker.sh не найден или не исполняемый." >&2
  exit 1
fi

mkdir -p /var/log/deploy
touch /var/log/deploy/deploy.log 2>/dev/null || true
chmod 644 /var/log/deploy/deploy.log 2>/dev/null || true

for i in 1 2; do
  WORKER_ENV="Environment=WORKER_ID=$i"
  [[ -n "${CERTBOT_EMAIL:-}" ]] && WORKER_ENV="Environment=WORKER_ID=$i
Environment=CERTBOT_EMAIL=$CERTBOT_EMAIL"
  cat > "/etc/systemd/system/deploy-worker-${i}.service" << EOF
[Unit]
Description=Deploy worker $i
After=redis-server.service docker.service

[Service]
Type=simple
$WORKER_ENV
ExecStart=$SCRIPTS_DIR/deploy_worker.sh
Restart=always
User=root
StandardOutput=append:/var/log/deploy/worker-${i}.log
StandardError=append:/var/log/deploy/worker-${i}.log

[Install]
WantedBy=multi-user.target
EOF
  echo "  deploy-worker-${i}.service записан"
done

systemctl daemon-reload
systemctl enable deploy-worker-1 deploy-worker-2 2>/dev/null || true
systemctl restart deploy-worker-1 deploy-worker-2
echo "✅ Воркеры перезапущены (логи: /var/log/deploy/worker-*.log)"
