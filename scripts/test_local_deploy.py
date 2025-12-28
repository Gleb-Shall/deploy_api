"""
Локальный тест с полным деплоем
Запускает API, выполняет деплой локально и открывает сайт в браузере
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
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# Добавляем корень проекта в путь
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

# URL API
API_URL = "http://localhost:8000"
LOCAL_DOMAIN = "localhost"
LOCAL_PORT_START = 9000

class ProxyHandler(BaseHTTPRequestHandler):
    """Прокси для перенаправления запросов к Docker контейнерам"""
    
    container_ports = {}  # {hash: port}
    
    def do_GET(self):
        """Обработка GET запросов"""
        path = self.path
        # Извлекаем хэш из пути /{hash}/... или /{hash}
        parts = path.strip('/').split('/', 1)
        
        if len(parts) > 0 and parts[0] in self.container_ports:
            container_hash = parts[0]
            container_port = self.container_ports[container_hash]
            
            # Определяем путь для проксирования
            # Контейнер работает от корня, поэтому убираем хэш из пути
            if len(parts) > 1:
                sub_path = '/' + parts[1]
            else:
                sub_path = '/'
            
            # Проксируем запрос к контейнеру
            import urllib.request
            try:
                container_url = f"http://127.0.0.1:{container_port}{sub_path}"
                
                # Проверяем доступность контейнера перед запросом
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex(('127.0.0.1', container_port))
                sock.close()
                
                if result != 0:
                    # Пробуем несколько раз с задержкой
                    import time
                    for attempt in range(3):
                        time.sleep(1)
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(2)
                        result = sock.connect_ex(('127.0.0.1', container_port))
                        sock.close()
                        if result == 0:
                            break
                    
                    if result != 0:
                        self.send_error(502, f"Container not accessible on port {container_port}. Container may not be running or still starting. Check: docker ps | grep deploy-{container_hash}")
                        return
                
                req = urllib.request.Request(container_url)
                req.add_header('Host', self.headers.get('Host', 'localhost'))
                req.add_header('User-Agent', self.headers.get('User-Agent', 'Proxy'))
                
                with urllib.request.urlopen(req, timeout=30) as response:
                    self.send_response(response.status)
                    # Копируем заголовки (кроме тех, которые не должны передаваться)
                    exclude_headers = ['connection', 'transfer-encoding', 'content-encoding', 'content-length']
                    content_type = response.headers.get('Content-Type', '').lower()
                    
                    # Собираем заголовки для отправки
                    headers_to_send = {}
                    for header, value in response.headers.items():
                        if header.lower() not in exclude_headers:
                            headers_to_send[header] = value
                    
                    # Читаем содержимое
                    content = response.read()
                    
                    # Если это HTML, заменяем абсолютные пути на пути с префиксом хэша
                    if 'text/html' in content_type:
                        try:
                            content_str = content.decode('utf-8', errors='ignore')
                            import re
                            hash_prefix = f'/{container_hash}'
                            
                            # Заменяем абсолютные пути в href="/path" и src="/path" 
                            # (но пропускаем если путь уже содержит хэш)
                            def fix_path(match):
                                full_match = match.group(0)
                                # Если уже содержит хэш, не трогаем
                                if hash_prefix in full_match:
                                    return full_match
                                # Заменяем href="/ или src="/ на href="/{hash}/ или src="/{hash}/
                                return full_match.replace('="/', f'="{hash_prefix}/').replace("='/", f"='{hash_prefix}/")
                            
                            # Заменяем href="/ и src="/
                            content_str = re.sub(r'(href|src)=["\'](/[^"\']*)["\']', fix_path, content_str)
                            
                            # Также заменяем пути в CSS url() - ищем url("/path") или url('/path')
                            def fix_url(match):
                                full_match = match.group(0)
                                if hash_prefix in full_match:
                                    return full_match
                                return full_match.replace('url("/', f'url("{hash_prefix}/').replace("url('/", f"url('{hash_prefix}/")
                            
                            content_str = re.sub(r'url\(["\'](/[^"\')\s]+)["\']?\)', fix_url, content_str)
                            
                            content = content_str.encode('utf-8')
                        except Exception as e:
                            # Если не удалось обработать HTML, отправляем оригинальный контент
                            print(f"Warning: Failed to process HTML: {e}")
                    
                    # Отправляем заголовки
                    for header, value in headers_to_send.items():
                        self.send_header(header, value)
                    
                    # Отправляем Content-Length после всех заголовков
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                return
            except urllib.error.URLError as e:
                # Показываем логи контейнера в ответе для отладки
                import subprocess
                try:
                    logs_result = subprocess.run(
                        ["docker", "logs", f"deploy-{container_hash}", "--tail", "30"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    logs_info = ""
                    if logs_result.returncode == 0:
                        logs_info = f"\n\nContainer logs:\n{logs_result.stdout[-500:]}"  # Последние 500 символов
                except:
                    logs_info = ""
                
                self.send_error(
                    502, 
                    f"Bad Gateway: Cannot connect to container on port {container_port}. "
                    f"Error: {str(e)}{logs_info}\n"
                    f"Check: docker logs deploy-{container_hash}"
                )
                return
            except Exception as e:
                self.send_error(502, f"Bad Gateway: {str(e)}")
                return
        
        self.send_error(404, f"Container not found. Available containers: {list(self.container_ports.keys())}")
    
    def log_message(self, format, *args):
        """Улучшенное логирование для отладки"""
        # Включаем логирование для отладки
        message = format % args
        if '404' not in message and '200' not in message:
            print(f"[Proxy] {self.address_string()} - {message}")

class LocalProxyServer:
    """Локальный прокси-сервер для маршрутизации к контейнерам"""
    
    def __init__(self, port=8080):
        self.port = port
        self.server = None
        self.server_thread = None
        
    def register_container(self, hash_value, container_port):
        """Регистрирует контейнер для проксирования"""
        ProxyHandler.container_ports[hash_value] = container_port
        print(f"   📌 Зарегистрирован контейнер в прокси:")
        print(f"      Хэш: {hash_value}")
        print(f"      Порт контейнера: {container_port}")
        print(f"      URL прокси: http://localhost:{self.port}/{hash_value}")
        
        # Проверяем доступность контейнера
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('127.0.0.1', container_port))
        sock.close()
        
        if result == 0:
            print(f"      ✅ Контейнер доступен на порту {container_port}")
        else:
            print(f"      ⚠️  Контейнер не отвечает на порту {container_port}")
            print(f"      Проверьте: docker ps | grep deploy-{hash_value}")
    
    def start(self):
        """Запускает прокси-сервер"""
        self.server = HTTPServer(('0.0.0.0', self.port), ProxyHandler)
        
        def serve():
            self.server.serve_forever()
        
        self.server_thread = Thread(target=serve, daemon=True)
        self.server_thread.start()
        print(f"   ✅ Прокси-сервер запущен на порту {self.port}")
    
    def stop(self):
        """Останавливает прокси-сервер"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()

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

def start_api_server():
    """Запускает API сервер в отдельном процессе"""
    print("🚀 Запуск API сервера...")
    server_process = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "run.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "LOCAL_TEST": "1"}  # Флаг для локального теста
    )
    return server_process

def check_docker_available():
    """Проверяет доступность Docker и Docker daemon"""
    try:
        # Проверяем установлен ли Docker
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            timeout=5
        )
        if result.returncode != 0:
            return False, "Docker не установлен"
        
        # Проверяем запущен ли Docker daemon
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5
        )
        if result.returncode != 0:
            return False, "Docker daemon не запущен. Запустите Docker Desktop или docker daemon"
        
        return True, "Docker доступен"
    except FileNotFoundError:
        return False, "Docker не установлен. Установите Docker Desktop"
    except subprocess.TimeoutExpired:
        return False, "Таймаут при проверке Docker"
    except Exception as e:
        return False, f"Ошибка проверки Docker: {str(e)}"

def get_container_port_from_api_response(hash_part):
    """Получает порт контейнера на основе хэша (должен совпадать с логикой в deploy_manager)"""
    return 9000 + (abs(hash(hash_part)) % 999)

def get_container_port_from_docker(hash_part):
    """Получает реальный порт контейнера из Docker"""
    import subprocess
    container_name = f"deploy-{hash_part}"
    
    # Используем docker port для получения точного порта
    port_result = subprocess.run(
        ["docker", "port", container_name],
        capture_output=True,
        text=True,
        timeout=10
    )
    
    if port_result.returncode == 0 and port_result.stdout.strip():
        # Парсим порт из формата "8000/tcp -> 127.0.0.1:9886"
        for line in port_result.stdout.strip().split('\n'):
            if '->' in line and '127.0.0.1' in line:
                port_str = line.split('->')[1].split(':')[-1].strip()
                try:
                    return int(port_str)
                except ValueError:
                    pass
    
    # Если docker port не сработал, пытаемся через docker ps
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Ports}}"],
        capture_output=True,
        text=True,
        timeout=10
    )
    
    if result.returncode == 0 and result.stdout.strip():
        # Парсим порт из формата "127.0.0.1:9123->8000/tcp"
        ports_str = result.stdout.strip()
        if '->' in ports_str:
            # Извлекаем хост-порт
            host_part = ports_str.split('->')[0]
            if ':' in host_part:
                port = host_part.split(':')[-1]
                try:
                    return int(port)
                except ValueError:
                    pass
    
    # Если не удалось получить из Docker, вычисляем
    print(f"   ⚠️  Не удалось получить порт из Docker, используем вычисленный")
    return get_container_port_from_api_response(hash_part)

def test_deploy(proxy_server):
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
                timeout=300
            )
            
            print(f"\n📊 Статус ответа: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                telegram_id = data.get('telegram_id')
                url = data.get('url')
                
                print(f"\n✅ ДЕПЛОЙ ЗАВЕРШЕН!")
                print(f"   Telegram ID: {telegram_id}")
                print(f"   URL из API: {url}")
                
                # Парсим хэш из URL
                hash_part = url.split('/')[-1].split('?')[0]  # Убираем query параметры если есть
                
                # Если это локальный URL из API, извлекаем порт из URL или вычисляем
                if 'localhost' in url or LOCAL_DOMAIN in url:
                    # Ждем немного, чтобы контейнер точно запустился
                    print(f"\n⏳ Ожидание запуска контейнера...")
                    
                    # Ждем пока контейнер запустится и приложение станет доступным
                    max_wait = 60  # максимум 60 секунд
                    wait_interval = 2
                    waited = 0
                    container_ready = False
                    
                    while waited < max_wait and not container_ready:
                        time.sleep(wait_interval)
                        waited += wait_interval
                        
                        # Пытаемся получить порт
                        container_port = get_container_port_from_docker(hash_part)
                        
                        # Проверяем доступность
                        import socket
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(1)
                        result = sock.connect_ex(('127.0.0.1', container_port))
                        sock.close()
                        
                        if result == 0:
                            # Порт доступен, пробуем HTTP запрос
                            try:
                                import urllib.request
                                req = urllib.request.Request(f"http://127.0.0.1:{container_port}/", timeout=2)
                                with urllib.request.urlopen(req) as response:
                                    if response.status == 200:
                                        container_ready = True
                                        print(f"   ✅ Приложение готово (ждали {waited}с)")
                                        break
                            except:
                                pass
                        
                        if waited % 10 == 0:
                            print(f"   ⏳ Ожидание... ({waited}с)")
                    
                    if not container_ready:
                        print(f"   ⚠️  Приложение может быть еще не готово, но продолжаем...")
                        
                        # Показываем логи контейнера для отладки
                        import subprocess
                        logs_result = subprocess.run(
                            ["docker", "logs", f"deploy-{hash_part}", "--tail", "20"],
                            capture_output=True,
                            text=True,
                            timeout=10
                        )
                        if logs_result.returncode == 0 and logs_result.stdout.strip():
                            print(f"   📋 Последние логи контейнера:")
                            for line in logs_result.stdout.strip().split('\n')[-10:]:
                                print(f"      {line}")
                    
                    # Пытаемся получить реальный порт из Docker
                    container_port = get_container_port_from_docker(hash_part)
                    
                    # Проверяем, что контейнер запущен и доступен
                    import subprocess
                    check_result = subprocess.run(
                        ["docker", "ps", "--filter", f"name=deploy-{hash_part}", "--format", "{{.Names}}\t{{.Ports}}\t{{.Status}}"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    
                    if check_result.returncode == 0 and check_result.stdout.strip():
                        print(f"   ✅ Контейнер запущен: {check_result.stdout.strip()}")
                    else:
                        print(f"   ⚠️  Контейнер не найден")
                        print(f"   Проверьте: docker ps | grep deploy-{hash_part}")
                    
                    print(f"   📌 Порт контейнера: {container_port}")
                    
                    # Регистрируем контейнер в прокси
                    proxy_server.register_container(hash_part, container_port)
                    local_url = f"http://localhost:{proxy_server.port}/{hash_part}"
                else:
                    # URL с реального сервера - это нормально, используем его
                    local_url = url
                
                print("\n" + "=" * 60)
                print("РЕЗУЛЬТАТ")
                print("=" * 60)
                print(f"\n🌐 Сайт доступен по адресу:")
                print(f"   {local_url}")
                print(f"\n💡 Откройте этот URL в браузере для проверки")
                
                # Спрашиваем, открыть ли в браузере
                try:
                    user_input = input("\n❓ Открыть сайт в браузере? (y/n): ").strip().lower()
                    if user_input in ['y', 'yes', 'да', 'д', '']:
                        print("🔗 Открываю браузер...")
                        webbrowser.open(local_url)
                        print(f"   ✅ Открыт: {local_url}")
                except KeyboardInterrupt:
                    print("\n\n⚠️ Прервано пользователем")
                
                return local_url
            else:
                print(f"\n❌ ОШИБКА ДЕПЛОЯ!")
                print(f"   Статус: {response.status_code}")
                print(f"   Ответ: {response.text}")
                return None
                
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Не удалось подключиться к серверу на {API_URL}")
        print("   Убедитесь, что сервер запущен")
        return None
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    """Главная функция"""
    print("=" * 60)
    print("ЛОКАЛЬНЫЙ ТЕСТ ДЕПЛОЯ")
    print("=" * 60)
    print("\nЭтот скрипт:")
    print("1. Запустит API сервер локально")
    print("2. Отправит запрос на деплой")
    print("3. Запустит Docker контейнер локально")
    print("4. Настроит прокси для доступа к сайту")
    print("5. Откроет сайт в браузере")
    print("\n" + "=" * 60)
    
    # Проверяем Docker
    docker_available, docker_message = check_docker_available()
    if not docker_available:
        print(f"\n⚠️  {docker_message}")
        print("\n💡 Для полноценного тестирования:")
        print("   1. Установите Docker Desktop (если не установлен)")
        print("   2. Запустите Docker Desktop")
        print("   3. Дождитесь полного запуска Docker")
        print("   4. Запустите тест снова")
        print("\n❓ Продолжить тест без Docker? (API будет работать, но контейнер не запустится)")
        try:
            user_input = input("   Введите 'y' для продолжения или 'n' для выхода: ").strip().lower()
            if user_input not in ['y', 'yes', 'да', 'д']:
                print("   Тест отменен")
                return
        except KeyboardInterrupt:
            print("\n   Тест отменен")
            return
    else:
        print(f"✅ {docker_message}")
    
    server_process = None
    proxy_server = None
    
    try:
        # Запускаем прокси-сервер
        print("\n🌐 Запуск локального прокси-сервера...")
        proxy_server = LocalProxyServer(port=8080)
        proxy_server.start()
        
        # Запускаем API сервер
        server_process = start_api_server()
        
        # Ждем запуска сервера
        if not wait_for_server(API_URL):
            print("❌ Сервер не запустился за отведенное время")
            if server_process:
                server_process.terminate()
            return
        
        # Тестируем деплой
        url = test_deploy(proxy_server)
        
        if url:
            print("\n" + "=" * 60)
            print("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
            print("=" * 60)
            print(f"\n🌐 Сайт доступен на: {url}")
            print(f"📡 API доступен на: {API_URL}")
            print(f"📚 Документация API: {API_URL}/docs")
            print(f"\n💡 Серверы продолжают работать.")
            print("   Для остановки нажмите Ctrl+C")
            
            # Ждем, пока пользователь не остановит
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n\n🛑 Остановка серверов...")
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
        # Останавливаем серверы
        if server_process:
            print("\n🛑 Остановка API сервера...")
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
            print("✅ API сервер остановлен")
        
        if proxy_server:
            print("🛑 Остановка прокси-сервера...")
            proxy_server.stop()
            print("✅ Прокси-сервер остановлен")

if __name__ == "__main__":
    main()

