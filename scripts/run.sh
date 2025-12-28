#!/bin/bash
# Скрипт для запуска API в виртуальном окружении

# Получаем директорию скрипта и переходим в корень проекта
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$PROJECT_ROOT"

# Проверяем, существует ли виртуальное окружение
if [ ! -d "venv" ]; then
    echo "Создание виртуального окружения..."
    python3 -m venv venv
fi

# Активируем виртуальное окружение
source venv/bin/activate

# Обновляем pip
pip install --upgrade pip --quiet

# Устанавливаем зависимости если нужно
if [ ! -f "venv/.installed" ]; then
    echo "Установка зависимостей..."
    pip install -r requirements.txt
    touch venv/.installed
fi

# Запускаем сервер
echo "Запуск сервера на http://0.0.0.0:8000"
python run.py

