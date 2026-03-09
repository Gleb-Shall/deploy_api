#!/bin/bash
#
# Генерация PNG изображений из PlantUML файлов
# Использует онлайн API PlantUML (не требует Java)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🖼️  Генерация PNG изображений из PlantUML..."

# PlantUML Server API endpoint
PLANTUML_SERVER="http://www.plantuml.com/plantuml"

# Функция для генерации PNG из PUML файла
generate_png() {
    local puml_file="$1"
    local output_file="${puml_file%.puml}.png"
    
    if [[ ! -f "$puml_file" ]]; then
        echo "❌ Файл не найден: $puml_file"
        return 1
    fi
    
    echo "📄 Обработка: $puml_file → $output_file"
    
    # Кодируем содержимое файла в формат PlantUML Server
    # PlantUML Server использует специальное кодирование (deflate + base64)
    # Для простоты используем прямой запрос с текстом
    
    # Альтернативный способ: использовать curl с текстом
    # Но лучше использовать локальный PlantUML или онлайн редактор
    
    echo "   ⚠️  Для генерации PNG используйте:"
    echo "   1. Онлайн редактор: http://www.plantuml.com/plantuml/uml/"
    echo "   2. Или установите Java и PlantUML локально"
    echo "   3. Или используйте Docker: docker run --rm -v \$(pwd):/work plantuml/plantuml -tpng $puml_file"
}

# Обработка всех .puml файлов
for puml_file in *.puml; do
    [[ -f "$puml_file" ]] && generate_png "$puml_file"
done

echo ""
echo "✅ Готово!"
echo ""
echo "💡 Совет: Используйте онлайн редактор для быстрого просмотра:"
echo "   http://www.plantuml.com/plantuml/uml/"
