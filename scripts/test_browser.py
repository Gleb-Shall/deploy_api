"""
Полноценный тест для проверки работы API и деплоя
Запускает локальный сервер, выполняет деплой и показывает результат
"""
import requests
import json
import sys
import time
import webbrowser
import subprocess
import signal
import os
from pathlib import Path
from threading import Thread

# Добавляем корень проекта в путь
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

# URL API
API_URL = "http://localhost:8000"

def wait_for_server(url, timeout=30):
    """Ожидает запуска сервера"""
    print(f"⏳ Ожидание запуска сервера на {url}...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(f"{url}/health", timeout=2)
            if response.status_code == 200:
                print("✅ Сервер запущен!")
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    return False

def start_server():
    """Запускает API сервер в отдельном процессе"""
    print("🚀 Запуск API сервера...")
    server_process = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "run.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(PROJECT_ROOT)
    )
    return server_process

def test_deploy():
    """Тестирует процесс деплоя"""
    print("\n" + "=" * 60)
    print("ТЕСТИРОВАНИЕ ДЕПЛОЯ")
    print("=" * 60)
    
    # Читаем example.json
    example_path = PROJECT_ROOT / 'example.json'
    print(f"📄 Чтение файла: {example_path.name}")
    
    try:
        with open(example_path, 'rb') as f:
            files = {'file': (example_path.name, f, 'application/json')}
            
            print(f"📤 Отправка запроса на {API_URL}/deploy...")
            response = requests.post(
                f"{API_URL}/deploy",
                files=files,
                timeout=300  # Долгий таймаут для деплоя
            )
            
            print(f"\n📊 Статус ответа: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                telegram_id = data.get('telegram_id')
                url = data.get('url')
                
                print(f"\n✅ ДЕПЛОЙ УСПЕШЕН!")
                print(f"   Telegram ID: {telegram_id}")
                print(f"   URL: {url}")
                print("\n" + "=" * 60)
                print("РЕЗУЛЬТАТ")
                print("=" * 60)
                print(f"\n🌐 Сайт доступен по адресу:")
                print(f"   {url}")
                print(f"\n💡 Откройте этот URL в браузере для проверки")
                
                # Спрашиваем, открыть ли в браузере
                try:
                    user_input = input("\n❓ Открыть сайт в браузере? (y/n): ").strip().lower()
                    if user_input in ['y', 'yes', 'да', 'д']:
                        print("🔗 Открываю браузер...")
                        webbrowser.open(url)
                except KeyboardInterrupt:
                    print("\n\n⚠️ Прервано пользователем")
                
                return True
            else:
                print(f"\n❌ ОШИБКА ДЕПЛОЯ!")
                print(f"   Статус: {response.status_code}")
                print(f"   Ответ: {response.text}")
                return False
                
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Не удалось подключиться к серверу на {API_URL}")
        print("   Убедитесь, что сервер запущен")
        return False
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Главная функция"""
    print("=" * 60)
    print("ТЕСТИРОВАНИЕ DEPLOY API")
    print("=" * 60)
    print("\nЭтот скрипт:")
    print("1. Запустит API сервер локально")
    print("2. Отправит тестовый запрос на деплой")
    print("3. Покажет результат и URL для проверки в браузере")
    print("\n" + "=" * 60)
    
    server_process = None
    try:
        # Запускаем сервер
        server_process = start_server()
        
        # Ждем запуска сервера
        if not wait_for_server(API_URL):
            print("❌ Сервер не запустился за отведенное время")
            if server_process:
                server_process.terminate()
            return
        
        # Тестируем деплой
        success = test_deploy()
        
        if success:
            print("\n" + "=" * 60)
            print("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
            print("=" * 60)
            print("\n💡 Сервер продолжает работать.")
            print("   Для остановки нажмите Ctrl+C")
            print(f"   API доступен на: {API_URL}")
            print(f"   Документация API: {API_URL}/docs")
            
            # Ждем, пока пользователь не остановит
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n\n🛑 Остановка сервера...")
        else:
            print("\n" + "=" * 60)
            print("❌ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО С ОШИБКАМИ")
            print("=" * 60)
            
    except KeyboardInterrupt:
        print("\n\n🛑 Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Останавливаем сервер
        if server_process:
            print("\n🛑 Остановка сервера...")
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
            print("✅ Сервер остановлен")

if __name__ == "__main__":
    main()

