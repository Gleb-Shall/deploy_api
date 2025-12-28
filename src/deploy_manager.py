"""
Менеджер для деплоя контейнеров на сервер
"""
import subprocess
import os
import json
from pathlib import Path
from typing import Optional
import tempfile
import shutil


class DeployManager:
    """
    Менеджер деплоя контейнеров.
    
    Работает в двух режимах:
    - LOCAL_TEST=1: локальный Docker для тестирования
    - RUN_ON_SERVER=1: прямой доступ к Docker на сервере (по умолчанию)
    
    Все операции выполняются напрямую через Docker (SSH не используется).
    """
    
    def __init__(self):
        # Параметры SSH больше не нужны - все работает через Docker напрямую
        pass
    
    def _is_running_on_server(self) -> bool:
        """Проверяет, работает ли API на целевом сервере"""
        # Если явно указано, что работаем на сервере
        if os.environ.get("RUN_ON_SERVER") == "1":
            return True
        
        # Проверяем доступность Docker socket (если доступен, значит мы на сервере)
        import socket
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.1)
            result = sock.connect_ex('/var/run/docker.sock')
            sock.close()
            if result == 0:
                return True
        except:
            pass
        
        return False
    
    async def deploy_container(
        self,
        container_id: str,
        page_hash: str,
        container_dir: str
    ) -> int:
        """
        Деплоит контейнер на сервер. Если контейнер уже существует, обновляет его.
        
        Args:
            container_id: ID образа или имя контейнера
            page_hash: Уникальный хэш страницы
            container_dir: Локальная директория с проектом
            
        Returns:
            Порт контейнера на хосте
        """
        # Проверяем локальный режим тестирования
        if os.environ.get("LOCAL_TEST") == "1":
            return await self._deploy_container_local(container_id, page_hash, container_dir)
        
        # По умолчанию работаем на сервере (RUN_ON_SERVER=1) - используем прямые команды Docker
        # Если RUN_ON_SERVER не установлен, но доступен Docker socket, тоже работаем напрямую
        if self._is_running_on_server():
            return await self._deploy_container_direct(container_id, page_hash, container_dir)
        
        # Если ни локальный режим, ни серверный - ошибка
        raise Exception(
            "Не определен режим работы. "
            "Установите LOCAL_TEST=1 для локального тестирования или "
            "RUN_ON_SERVER=1 для работы на сервере."
        )
    
    async def _deploy_container_direct(
        self,
        container_id: str,
        page_hash: str,
        container_dir: str
    ) -> int:
        """
        Прямой деплой контейнера на сервере (без SSH, API работает на том же сервере).
        
        Args:
            container_id: ID образа или имя контейнера
            page_hash: Уникальный хэш страницы
            container_dir: Локальная директория с проектом
            
        Returns:
            Порт контейнера на хосте
        """
        import subprocess
        import shutil
        
        # Проверяем доступность Docker daemon
        check_result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10
        )
        if check_result.returncode != 0:
            raise Exception(
                "Docker daemon не запущен на сервере. "
                "Проверьте: systemctl status docker"
            )
        
        remote_project_dir = f"/opt/deploy/{page_hash}"
        container_name = f"deploy-{page_hash}"
        
        # Создаем директорию на сервере
        os.makedirs(remote_project_dir, exist_ok=True)
        
        # Копируем проект в целевую директорию
        if os.path.abspath(container_dir) != os.path.abspath(remote_project_dir):
            if os.path.exists(remote_project_dir):
                shutil.rmtree(remote_project_dir)
            shutil.copytree(container_dir, remote_project_dir)
        
        # Собираем Docker образ на сервере
        build_result = subprocess.run(
            ["docker", "build", "-t", container_id, "."],
            cwd=remote_project_dir,
            capture_output=True,
            text=True,
            timeout=600
        )
        
        if build_result.returncode != 0:
            error_msg = build_result.stderr or build_result.stdout or "Unknown error"
            raise Exception(f"Failed to build Docker image on server: {error_msg}")
        
        # Проверяем, существует ли контейнер
        check_container = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name=^{container_name}$", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        container_exists = check_container.returncode == 0 and container_name in check_container.stdout
        
        if container_exists:
            # Останавливаем и удаляем существующий контейнер
            subprocess.run(
                ["docker", "stop", container_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30
            )
            subprocess.run(
                ["docker", "rm", container_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )
        
        # Получаем порт из реестра или генерируем новый
        host_port = await self._get_container_port(page_hash, container_name)
        
        # Запускаем контейнер
        run_result = subprocess.run(
            [
                "docker", "run", "-d",
                "--name", container_name,
                "-p", f"127.0.0.1:{host_port}:8000",
                "--restart", "unless-stopped",
                container_id
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if run_result.returncode != 0:
            error_msg = run_result.stderr or run_result.stdout or "Unknown error"
            raise Exception(f"Failed to run container on server: {error_msg}")
        
        return host_port

    async def _deploy_container_local(
        self,
        container_id: str,
        page_hash: str,
        container_dir: str
    ) -> int:
        """
        Локальный деплой контейнера (для тестирования без SSH).
        
        Args:
            container_id: ID образа или имя контейнера
            page_hash: Уникальный хэш страницы
            container_dir: Локальная директория с проектом
            
        Returns:
            Порт контейнера на хосте
        """
        import subprocess
        
        # Проверяем доступность Docker daemon
        check_result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10
        )
        if check_result.returncode != 0:
            raise Exception(
                "Docker daemon не запущен. "
                "Запустите Docker Desktop и дождитесь его полного запуска, затем повторите попытку."
            )
        
        container_name = f"deploy-{page_hash}"
        
        # Останавливаем старый контейнер если есть
        subprocess.run(
            ["docker", "stop", container_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        subprocess.run(
            ["docker", "rm", container_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Собираем Docker образ локально
        build_result = subprocess.run(
            ["docker", "build", "-t", container_id, "."],
            cwd=container_dir,
            capture_output=True,
            text=True,
            timeout=600  # 10 минут на сборку
        )
        
        if build_result.returncode != 0:
            error_msg = build_result.stderr or build_result.stdout or "Unknown error"
            raise Exception(f"Failed to build Docker image locally: {error_msg}")
        
        # Генерируем порт на основе хэша (в диапазоне 9000-9999)
        host_port = 9000 + (abs(hash(page_hash)) % 999)
        
        # Проверяем, свободен ли порт
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        port_in_use = sock.connect_ex(('127.0.0.1', host_port)) == 0
        sock.close()
        
        if port_in_use:
            # Если порт занят, используем случайный (Docker сам назначит)
            port_mapping = "127.0.0.1:0:8000"
        else:
            # Используем вычисленный порт
            port_mapping = f"127.0.0.1:{host_port}:8000"
        
        # Запускаем контейнер локально
        run_result = subprocess.run(
            [
                "docker", "run", "-d",
                "--name", container_name,
                "-p", port_mapping,
                container_id
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if run_result.returncode != 0:
            error_msg = run_result.stderr or run_result.stdout or "Unknown error"
            raise Exception(f"Failed to run container locally: {error_msg}")
        
        # Получаем реальный порт, который назначил Docker
        port_result = subprocess.run(
            ["docker", "port", container_name],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if port_result.returncode == 0 and port_result.stdout.strip():
            # Парсим порт из вывода docker port
            # Формат: "8000/tcp -> 127.0.0.1:9886"
            for line in port_result.stdout.strip().split('\n'):
                if '->' in line and '127.0.0.1' in line:
                    port_str = line.split('->')[1].split(':')[-1].strip()
                    try:
                        real_port = int(port_str)
                        return real_port
                    except ValueError:
                        pass
        
        # Если не удалось получить порт из docker port, возвращаем вычисленный
        return host_port
    
    async def _get_container_port(self, page_hash: str, container_name: str) -> int:
        """
        Получает или генерирует порт для контейнера.
        Если контейнер уже был зарегистрирован, использует тот же порт.
        """
        # Всегда используем прямой доступ (локально или на сервере)
        return await self._get_container_port_direct(page_hash, container_name)
    
    async def _get_container_port_direct(self, page_hash: str, container_name: str) -> int:
        """Получает порт напрямую на сервере (без SSH)"""
        registry_file = "/opt/deploy/registry.json"
        
        # Читаем реестр
        if os.path.exists(registry_file):
            try:
                with open(registry_file, 'r') as f:
                    registry = json.load(f)
                if page_hash in registry:
                    port = registry[page_hash].get("container_port")
                    if port and isinstance(port, int):
                            # Проверяем, что порт свободен
                            import socket
                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(0.1)
                            port_in_use = sock.connect_ex(('127.0.0.1', port)) == 0
                            sock.close()
                            if not port_in_use:
                                return port
            except Exception:
                pass
        
        # Генерируем новый порт
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('', 0))
        port = sock.getsockname()[1]
        sock.close()
        return port
    
    async def configure_nginx(
        self,
        page_hash: str,
        container_port: int,
        nginx_location: str
    ) -> bool:
        """
        Настраивает nginx на сервере, добавляя location блок для /{hash}.
        
        Args:
            page_hash: Уникальный хэш страницы
            container_port: Порт контейнера
            nginx_location: Location блок nginx
            
        Returns:
            True если успешно
        """
        # В локальном режиме пропускаем настройку nginx
        if os.environ.get("LOCAL_TEST") == "1":
            return True
        
        # Всегда используем прямой доступ (работаем на сервере)
        return await self._configure_nginx_direct(page_hash, container_port, nginx_location)
    
    async def _configure_nginx_direct(
        self,
        page_hash: str,
        container_port: int,
        nginx_location: str
    ) -> bool:
        """Настраивает nginx напрямую на сервере (без SSH)"""
        import subprocess
        
        deploy_config_dir = "/etc/nginx/sites-available/deploy"
        location_config_file = f"{deploy_config_dir}/{page_hash}.conf"
        
        # Создаем директорию
        os.makedirs(deploy_config_dir, exist_ok=True)
        
        # Записываем location блок
        with open(location_config_file, 'w') as f:
            f.write(nginx_location)
        
        # Убеждаемся, что include директива есть в основном конфиге
        await self._ensure_include_in_main_config_direct(deploy_config_dir)
        
        # Тестируем конфигурацию nginx
        test_result = subprocess.run(
            ["nginx", "-t"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if test_result.returncode != 0:
            raise Exception(f"Nginx config test failed: {test_result.stderr}")
        
        # Перезагружаем nginx
        reload_result = subprocess.run(
            ["systemctl", "reload", "nginx"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if reload_result.returncode != 0:
            raise Exception(f"Failed to reload nginx: {reload_result.stderr}")
        
        # Сохраняем в реестр
        await self._save_container_registry_direct(page_hash, container_port, container_name=f"deploy-{page_hash}")
        
        return True
            
    async def _ensure_include_in_main_config_direct(self, deploy_config_dir: str):
        """Убеждается, что include есть в основном конфиге (без SSH)"""
        import subprocess
        import re
        
        # Ищем конфиг с доменом (используем переменную окружения DOMAIN или ищем любой активный конфиг)
        domain = os.environ.get("DOMAIN", "")
        if domain:
            # Ищем конфиг с указанным доменом
            result = subprocess.run(
                ["grep", "-r", f"server_name.*{domain}", "/etc/nginx/sites-available/"],
                capture_output=True,
                text=True,
                timeout=5
            )
        else:
            # Если домен не указан, ищем любой активный конфиг
            result = subprocess.run(
                ["ls", "/etc/nginx/sites-enabled/*.conf"],
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )
        
        config_path = None
        if result.returncode == 0 and result.stdout.strip():
            # Если нашли по домену, берем путь из вывода grep
            if domain:
                config_path = result.stdout.strip().split(':')[0]
            else:
                # Если искали по sites-enabled, конвертируем путь
                enabled_path = result.stdout.strip().split('\n')[0]
                config_path = enabled_path.replace('/sites-enabled/', '/sites-available/')
        
        # Если не нашли, пробуем найти любой активный конфиг
        if not config_path:
            result = subprocess.run(
                ["ls", "/etc/nginx/sites-enabled/*.conf"],
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                enabled_path = result.stdout.strip().split('\n')[0]
                config_path = enabled_path.replace('/sites-enabled/', '/sites-available/')
        
        if not config_path or not os.path.exists(config_path):
            print("Warning: Could not find main nginx config, include directive should be added manually")
            return
        
        # Читаем конфиг
        with open(config_path, 'r') as f:
            content = f.read()
        
        include_line = f"    include {deploy_config_dir}/*.conf;"
        
        # Проверяем, есть ли уже include
        if deploy_config_dir in content:
            return  # Уже есть
        
        # Добавляем include перед последней закрывающей скобкой server блока
        # Ищем последний server блок и добавляем перед его закрывающей скобкой
        lines = content.split('\n')
        server_blocks = []
        in_server = False
        depth = 0
        server_start = 0
        
        for i, line in enumerate(lines):
            if 'server {' in line:
                in_server = True
                server_start = i
                depth = 1
            elif in_server:
                if '{' in line:
                    depth += line.count('{')
                if '}' in line:
                    depth -= line.count('}')
                if depth == 0:
                    # Конец server блока
                    server_blocks.append((server_start, i))
                    in_server = False
        
        if server_blocks:
            # Добавляем в последний server блок
            last_block_end = server_blocks[-1][1]
            lines.insert(last_block_end, include_line)
            
            # Записываем обратно
            with open(config_path, 'w') as f:
                f.write('\n'.join(lines))
    
    async def _save_container_registry_direct(self, page_hash: str, container_port: int, container_name: str):
        """Сохраняет информацию о контейнере в реестр (без SSH)"""
        registry_file = "/opt/deploy/registry.json"
        os.makedirs(os.path.dirname(registry_file), exist_ok=True)
        
        registry = {}
        if os.path.exists(registry_file):
            try:
                with open(registry_file, 'r') as f:
                    registry = json.load(f)
            except:
                pass
        
        registry[page_hash] = {
            "container_port": container_port,
            "container_name": container_name
        }
        
        with open(registry_file, 'w') as f:
            json.dump(registry, f, indent=2)
    

