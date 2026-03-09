#!/usr/bin/env bash
# Переименовывает .cursor/rules/*.md в .mdc — Cursor отображает правила в настройках только для .mdc.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RULES_DIR="$SCRIPT_DIR/../.cursor/rules"
[[ ! -d "$RULES_DIR" ]] && exit 0
for f in "$RULES_DIR"/*.md; do
  [[ -f "$f" ]] && mv "$f" "${f%.md}.mdc"
done
echo "Rules renamed to .mdc in .cursor/rules/"
