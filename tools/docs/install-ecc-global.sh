#!/usr/bin/env bash
# Установка ecc-universal для Cursor — по официальной инструкции.
#
# По документации Cursor читает правила и агентов только из ПРОЕКТНОЙ папки .cursor/
# (см. .cursor/MIGRATION.md: "Project .cursor/ only"). Глобально из ~/.cursor/
# гарантированно работают только команды (⌘⇧J).
#
# Использование:
#   ./docs/install-ecc-global.sh [typescript|python|golang ...]
#     → Установка в ПРОЕКТ (рекомендуется): создаёт .cursor/ в корне репозитория.
#     Так Cursor точно подхватит rules, agents, skills, commands.
#
#   ./docs/install-ecc-global.sh --global [typescript|python|golang ...]
#     → Дополнительно копирует в ~/.cursor/ (команды там работают везде;
#     rules/agents в ~/.cursor/ могут не подхватываться — зависит от версии Cursor).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_GLOBAL=false
LANGS=()

for arg in "$@"; do
    if [[ "$arg" == "--global" ]]; then
        INSTALL_GLOBAL=true
    else
        LANGS+=("$arg")
    fi
done
[[ ${#LANGS[@]} -eq 0 ]] && LANGS=(typescript)

if [[ ! -d "$REPO_ROOT/node_modules/ecc-universal" ]]; then
    echo "Error: ecc-universal not found. Run: npm install ecc-universal" >&2
    exit 1
fi

# --- 1) Официальная установка в проект (из корня репо) ---
# Так в Cursor создаётся .cursor/ в корне проекта — как в README.
echo "Installing to project .cursor/ (official way)..."
(cd "$REPO_ROOT" && ./node_modules/ecc-universal/install.sh --target cursor "${LANGS[@]}")
echo ""

# --- 2) По желанию — копирование в ~/.cursor ---
if $INSTALL_GLOBAL; then
    CURSOR_SRC="$REPO_ROOT/node_modules/ecc-universal/.cursor"
    DEST_DIR="${HOME}/.cursor"
    echo "Copying to $DEST_DIR/ (global; commands work everywhere, rules/agents may be project-only)..."
    mkdir -p "$DEST_DIR/rules" "$DEST_DIR/agents" "$DEST_DIR/skills" "$DEST_DIR/commands"
    for f in "$CURSOR_SRC/rules"/common-*.md "$CURSOR_SRC/rules"/context-*.md "$CURSOR_SRC/rules"/hooks-guidance.md; do
        [[ -f "$f" ]] && cp "$f" "$DEST_DIR/rules/"
    done
    for lang in "${LANGS[@]}"; do
        for f in "$CURSOR_SRC/rules"/${lang}-*.md; do
            [[ -f "$f" ]] && cp "$f" "$DEST_DIR/rules/"
        done
    done
    cp -r "$CURSOR_SRC/agents/." "$DEST_DIR/agents/"
    cp -r "$CURSOR_SRC/skills/." "$DEST_DIR/skills/"
    cp -r "$CURSOR_SRC/commands/." "$DEST_DIR/commands/"
    [[ -f "$CURSOR_SRC/mcp.json" ]] && cp "$CURSOR_SRC/mcp.json" "$DEST_DIR/mcp.json"
    echo "Done. Global: $DEST_DIR/"
fi

echo ""
echo "Готово. В этом проекте Cursor использует .cursor/ в корне репо (rules, agents, skills, commands)."
