"""
Локальный тест без реального деплоя на сервер
Создает локальный веб-сервер для проверки работы сайта
"""
import json
import sys
import os
import subprocess
import time
import webbrowser
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from threading import Thread

# Добавляем корень проекта в путь
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.parser import parse_json_request
from src.utils import generate_hash
from src.docker_manager import DockerManager
import asyncio

class CustomHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP Handler с поддержкой SPA"""
    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

async def create_test_site():
    """Создает тестовый сайт из example.json"""
    print("=" * 60)
    print("СОЗДАНИЕ ТЕСТОВОГО САЙТА")
    print("=" * 60)
    
    # Читаем example.json
    example_path = PROJECT_ROOT / 'example.json'
    print(f"📄 Чтение файла: {example_path.name}")
    
    with open(example_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    # Парсим JSON
    parsed_data = parse_json_request(json_data)
    telegram_id = parsed_data["telegram_id"]
    files = parsed_data["files"]
    
    print(f"✅ Telegram ID: {telegram_id}")
    print(f"✅ Файлов: {len(files)}")
    
    # Генерируем хэш
    page_hash = generate_hash(telegram_id, files)
    print(f"✅ Хэш: {page_hash}")
    
    # Создаем структуру проекта
    docker_manager = DockerManager()
    image_name = await docker_manager.create_container(
        page_hash=page_hash,
        files=files,
        telegram_id=telegram_id
    )
    
    container_dir = docker_manager.get_container_dir(page_hash)
    print(f"✅ Проект создан: {container_dir}")
    
    return container_dir, page_hash

def run_local_server(directory, port=8080):
    """Запускает локальный веб-сервер"""
    os.chdir(directory)
    
    server = HTTPServer(('localhost', port), CustomHTTPHandler)
    print(f"\n🌐 Локальный сервер запущен на http://localhost:{port}")
    print(f"   Рабочая директория: {directory}")
    
    def server_serve():
        server.serve_forever()
    
    server_thread = Thread(target=server_serve, daemon=True)
    server_thread.start()
    
    return server

async def main():
    """Главная функция"""
    print("=" * 60)
    print("ЛОКАЛЬНЫЙ ТЕСТ САЙТА")
    print("=" * 60)
    print("\nЭтот скрипт:")
    print("1. Создаст структуру проекта из example.json")
    print("2. Запустит локальный веб-сервер")
    print("3. Откроет сайт в браузере для проверки")
    print("\n⚠️  ВАЖНО: Это только проверка структуры проекта.")
    print("   Для полного теста деплоя используйте test_browser.py")
    print("\n" + "=" * 60)
    
    try:
        # Создаем тестовый сайт
        container_dir, page_hash = await create_test_site()
        
        # Запускаем локальный сервер
        print("\n" + "=" * 60)
        print("ЗАПУСК ЛОКАЛЬНОГО СЕРВЕРА")
        print("=" * 60)
        
        server = run_local_server(container_dir, port=8080)
        
        url = f"http://localhost:8080"
        print(f"\n✅ Сервер запущен!")
        print(f"   URL: {url}")
        print(f"   Хэш проекта: {page_hash}")
        print(f"\n💡 Откройте этот URL в браузере")
        
        # Открываем в браузере
        try:
            user_input = input("\n❓ Открыть сайт в браузере? (y/n): ").strip().lower()
            if user_input in ['y', 'yes', 'да', 'д', '']:
                print("🔗 Открываю браузер...")
                webbrowser.open(url)
        except KeyboardInterrupt:
            pass
        
        print("\n" + "=" * 60)
        print("СЕРВЕР РАБОТАЕТ")
        print("=" * 60)
        print(f"\n🌐 Сайт доступен на: {url}")
        print("   Для остановки нажмите Ctrl+C\n")
        
        # Ждем
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n🛑 Остановка сервера...")
            server.shutdown()
            print("✅ Сервер остановлен")
            
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

