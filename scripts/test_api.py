"""
Тестирование API endpoint через requests
"""
import requests
import json
import sys
from pathlib import Path

# Добавляем корень проекта в путь
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent

def test_deploy_endpoint():
    url = "http://localhost:8000/deploy"
    
    # Читаем example.json из корня проекта
    example_path = PROJECT_ROOT / 'example.json'
    with open(example_path, 'rb') as f:
        files = {'file': ('example.json', f, 'application/json')}
        
        print("=" * 60)
        print("ТЕСТИРОВАНИЕ API ENDPOINT /deploy")
        print("=" * 60)
        print(f"Отправка запроса на {url}...")
        
        try:
            response = requests.post(url, files=files, timeout=300)
            print(f"\nСтатус код: {response.status_code}")
            print(f"Ответ:")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Telegram ID: {data.get('telegram_id')}")
                print(f"✅ URL: {data.get('url')}")
            else:
                print(f"❌ Ошибка: {response.text}")
                
        except requests.exceptions.ConnectionError:
            print("❌ Не удалось подключиться к серверу.")
            print("   Убедитесь, что сервер запущен: python3 main.py")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    test_deploy_endpoint()

