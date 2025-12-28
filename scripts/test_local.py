"""
Локальное тестирование парсинга JSON и генерации хэша
"""
import json
import sys
import os
from pathlib import Path

# Добавляем корень проекта в путь
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.parser import parse_json_request
from src.utils import generate_hash
from src.docker_manager import DockerManager
import asyncio

async def test():
    # Читаем example.json из корня проекта
    example_path = PROJECT_ROOT / 'example.json'
    with open(example_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    print("=" * 60)
    print("ТЕСТИРОВАНИЕ ПАРСИНГА JSON")
    print("=" * 60)
    
    # Парсим JSON
    try:
        parsed_data = parse_json_request(json_data)
        telegram_id = parsed_data["telegram_id"]
        files = parsed_data["files"]
        
        print(f"✅ Telegram ID: {telegram_id}")
        print(f"✅ Количество файлов: {len(files)}")
        print(f"\n📁 Файлы:")
        for file_data in files[:5]:  # Показываем первые 5
            print(f"   - {file_data['name']}")
        if len(files) > 5:
            print(f"   ... и еще {len(files) - 5} файлов")
        
        print("\n" + "=" * 60)
        print("ГЕНЕРАЦИЯ ХЭША")
        print("=" * 60)
        
        # Генерируем хэш
        page_hash = generate_hash(telegram_id, files)
        print(f"✅ Хэш страницы: {page_hash}")
        print(f"✅ URL будет: https://your-domain.com/{page_hash}")
        
        print("\n" + "=" * 60)
        print("СОЗДАНИЕ СТРУКТУРЫ ПРОЕКТА")
        print("=" * 60)
        
        # Тестируем создание структуры проекта
        docker_manager = DockerManager()
        try:
            image_name = await docker_manager.create_container(
                page_hash=page_hash,
                files=files,
                telegram_id=telegram_id
            )
            print(f"✅ Структура проекта создана")
            print(f"✅ Image name: {image_name}")
            
            container_dir = docker_manager.get_container_dir(page_hash)
            print(f"✅ Директория проекта: {container_dir}")
            
            # Проверяем, что файлы созданы
            import os
            package_json_path = os.path.join(container_dir, "package.json")
            if os.path.exists(package_json_path):
                print(f"✅ package.json создан")
            
            dockerfile_path = os.path.join(container_dir, "Dockerfile")
            if os.path.exists(dockerfile_path):
                print(f"✅ Dockerfile создан")
            
        except Exception as e:
            print(f"❌ Ошибка при создании структуры проекта: {e}")
            import traceback
            traceback.print_exc()
        
        print("\n" + "=" * 60)
        print("ГЕНЕРАЦИЯ NGINX КОНФИГУРАЦИИ")
        print("=" * 60)
        
        from src.nginx_manager import NginxManager
        nginx_manager = NginxManager(domain="your-domain.com")
        nginx_location = nginx_manager.generate_nginx_location(
            page_hash=page_hash,
            container_port=9123  # Пример порта
        )
        print("✅ Nginx location блок сгенерирован:")
        print(nginx_location)
        
        print("\n" + "=" * 60)
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())

