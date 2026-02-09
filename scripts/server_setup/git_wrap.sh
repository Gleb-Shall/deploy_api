#!/bin/bash
# Push → если репо нет: создаёт, ставит post-receive → receive-pack → post-receive выполняется
# Вывод в /dev/null — иначе git protocol ломается (bad line length character)

GIT_BASE="/var/git/sites"
HOOK="/opt/deploy/scripts/post-receive"

exec 3>&1 4>&2 1>/dev/null 2>/dev/null
mkdir -p /opt/deploy/scripts
if [ ! -f "$HOOK" ]; then
  for t in /opt/deploy/scripts/post-receive.template /tmp/deploy_api/scripts/server_setup/post-receive.template "$(dirname "$0")/post-receive.template"; do
    [ -f "$t" ] && cp "$t" "$HOOK" && chmod +x "$HOOK" && break
  done
fi

CMD="${SSH_ORIGINAL_COMMAND:-}"
REPO=$(echo "$CMD" | grep -oE "'[^']+\.git'|\"[^\"]+\.git\"|[^ ]+\.git" | tail -1 | tr -d "'\"")
[ -z "$CMD" ] && exec 1>&3 2>&4 && exec git-shell
[ -z "$REPO" ] && exec 1>&3 2>&4 && exec sh -c "$CMD"

if [[ "$REPO" == /* ]]; then
  RP="$REPO"
else
  RP="$GIT_BASE/${REPO#sites/}"
fi

if [ ! -d "$RP" ]; then
  mkdir -p "$(dirname "$RP")"
  git init --bare "$RP"
  [ -f "$HOOK" ] && ln -sf "$HOOK" "$RP/hooks/post-receive"
  chown -R git:git "$RP" || true
fi

# receive-pack ищет репо по пути — подставляем абсолютный
CMD="${CMD//$REPO/$RP}"

exec 1>&3 2>&4
exec sh -c "$CMD"
