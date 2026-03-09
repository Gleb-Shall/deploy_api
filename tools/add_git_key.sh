#!/bin/bash
#
# Добавляет SSH-ключ в authorized_keys пользователя git на сервере.
# Использование: ./add_git_key.sh [SERVER]
# SERVER по умолчанию: root@185.23.34.88
#

SERVER="${1:-root@185.23.34.88}"
KEY_FILE="${HOME}/.ssh/id_rsa.pub"
[ -f "${HOME}/.ssh/id_ed25519.pub" ] && KEY_FILE="${HOME}/.ssh/id_ed25519.pub"

if [ ! -f "$KEY_FILE" ]; then
  echo "SSH-ключ не найден: ~/.ssh/id_rsa.pub или ~/.ssh/id_ed25519.pub"
  exit 1
fi

KEY=$(cat "$KEY_FILE")
LINE="command=\"/opt/deploy_api/scripts/git_wrap.sh\" $KEY"

echo "Добавляю ключ для пользователя git на $SERVER..."
ssh "$SERVER" "mkdir -p /home/git/.ssh && chmod 700 /home/git/.ssh && echo '$LINE' >> /home/git/.ssh/authorized_keys && chmod 600 /home/git/.ssh/authorized_keys && chown -R git:git /home/git/.ssh && echo 'OK'"
