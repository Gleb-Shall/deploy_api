#!/bin/bash
#
# Проверка, сколько места занимают задеплоенные сайты.
# Запуск на сервере: sudo ./check_sites_disk.sh
#
# Показывает: work tree, git репо, Docker образы/контейнеры, сводку.
#

set -e

REGISTRY_FILE="/opt/deploy/registry.json"
WORK_TREE_BASE="/opt/deploy"
GIT_BASE="/var/git/sites"

echo "=== Work tree (/opt/deploy/*) ==="
total_wt=0
for d in "$WORK_TREE_BASE"/*/; do
  [[ -d "$d" ]] || continue
  name=$(basename "$d")
  # skip if it's not a directory (e.g. registry.json's dir)
  [[ "$name" == "registry.json" ]] && continue
  sz=$(du -sk "$d" 2>/dev/null | cut -f1)
  total_wt=$((total_wt + sz))
  printf "  %-20s %6s MiB\n" "$name" "$((sz / 1024))"
done
echo "  ---"
printf "  %-20s %6s MiB\n" "TOTAL work tree" "$((total_wt / 1024))"
echo ""

echo "=== Git bare repos (/var/git/sites/*.git) ==="
total_git=0
for r in "$GIT_BASE"/*.git; do
  [[ -d "$r" ]] || continue
  name=$(basename "$r" .git)
  sz=$(du -sk "$r" 2>/dev/null | cut -f1)
  total_git=$((total_git + sz))
  printf "  %-20s %6s MiB\n" "$name" "$((sz / 1024))"
done
echo "  ---"
printf "  %-20s %6s MiB\n" "TOTAL git" "$((total_git / 1024))"
echo ""

echo "=== Docker: образы deploy-* ==="
docker images --format "  {{.Repository}}\t{{.Size}}" 2>/dev/null | grep "^  deploy-" || true
echo ""

echo "=== Docker: контейнеры deploy-* ==="
docker ps -a -f "name=deploy-" --format "  {{.Names}}\t{{.Status}}" 2>/dev/null || true
echo ""

echo "=== Docker system (общая сводка) ==="
docker system df 2>/dev/null || true
echo ""

if [[ -f "$REGISTRY_FILE" ]] && command -v jq >/dev/null 2>&1; then
  echo "=== Сайты в registry.json ==="
  jq -r 'keys[]' "$REGISTRY_FILE" 2>/dev/null | while read -r h; do
    [[ -n "$h" && "$h" != "null" ]] && echo "  $h"
  done
fi
echo ""
echo "Удалить один сайт:  sudo /opt/deploy_api/scripts/remove_site.sh PAGE_HASH"
echo "Удалить все сайты:   sudo /opt/deploy_api/scripts/remove_site.sh -A"
