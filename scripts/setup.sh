#!/bin/bash
# Скрипт для настройки виртуального окружения

# Получаем директорию скрипта и переходим в корень проекта
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$PROJECT_ROOT"

echo "Настройка виртуального окружения..."

# Создаем виртуальное окружение если его нет
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Виртуальное окружение создано"
else
    echo "✅ Виртуальное окружение уже существует"
fi

# Активируем виртуальное окружение
source venv/bin/activate

# Обновляем pip
echo "Обновление pip..."
pip install --upgrade pip --quiet

# Устанавливаем зависимости
echo "Установка зависимостей..."
pip install -r requirements.txt

echo ""
echo "✅ Настройка завершена!"
echo ""
echo "Для активации виртуального окружения выполните:"
echo "  source venv/bin/activate"
echo ""
echo "Или запустите сервер через:"
echo "  ./scripts/run.sh"
echo ""

