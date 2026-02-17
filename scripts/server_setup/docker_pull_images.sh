#!/bin/bash
#
# Обновление базовых образов Docker для деплоя.
# Тянет образы и помечает deploy-node/deploy-nginx — default builder не лезет в registry (build не крашится).
#

set -e

# registry:tag → локальный тег (BuildKit не лезет в registry при FROM)
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

pull_and_tag() {
  local src="$1" local_tag="$2"
  if docker pull "$src"; then
    docker tag "$src" "$local_tag"
    log "OK: $src → $local_tag"
  else
    log "FAIL: $src"
    exit 1
  fi
}

pull_and_tag "node:20-alpine" "deploy-node:20-alpine"
pull_and_tag "nginx:alpine"   "deploy-nginx:alpine"
log "Done."
