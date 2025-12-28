#!/bin/bash
# Быстрая активация виртуального окружения

# Получаем директорию скрипта и переходим в корень проекта
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$PROJECT_ROOT"

if [ ! -d "venv" ]; then
    echo "❌ Виртуальное окружение не найдено. Запустите сначала: ./scripts/setup.sh"
    exit 1
fi

source venv/bin/activate
echo "✅ Виртуальное окружение активировано"
echo "Для деактивации выполните: deactivate"

