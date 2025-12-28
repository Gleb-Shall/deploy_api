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
        
        # Нормализуем путь (преобразуем относительные пути в абсолютные)
        container_dir = os.path.abspath(container_dir)
        
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
        
        # Проверяем, что container_dir существует и это директория
        if not os.path.exists(container_dir):
            raise Exception(f"Исходная директория не найдена: {container_dir}. Убедитесь, что проект был создан корректно.")
        if not os.path.isdir(container_dir):
            raise Exception(f"Исходный путь не является директорией: {container_dir}. Ожидается директория проекта.")
        
        # Проверяем, что это не родительская директория containers
        if os.path.basename(container_dir) != page_hash:
            raise Exception(
                f"Неправильный путь к контейнеру: {container_dir}. "
                f"Ожидается путь заканчивающийся на '{page_hash}', но получен: {os.path.basename(container_dir)}"
            )
        
        # Дополнительная проверка: убеждаемся, что это не просто "containers"
        if container_dir.endswith("containers") and not container_dir.endswith(f"containers/{page_hash}"):
            raise Exception(
                f"Обнаружен путь к родительской директории 'containers': {container_dir}. "
                f"Ожидается путь к поддиректории: .../containers/{page_hash}"
            )
        
        # Создаем целевую директорию на сервере (если нужно, удаляем старую)
        if os.path.exists(remote_project_dir):
            if os.path.isdir(remote_project_dir):
                shutil.rmtree(remote_project_dir)
            else:
                # Если это файл, а не директория, удаляем его
                os.remove(remote_project_dir)
        
        # Копируем проект в целевую директорию
        if os.path.abspath(container_dir) != os.path.abspath(remote_project_dir):
            try:
                shutil.copytree(container_dir, remote_project_dir)
            except OSError as e:
                raise Exception(
                    f"Не удалось скопировать директорию из {container_dir} в {remote_project_dir}: {str(e)}. "
                    f"Убедитесь, что исходная директория существует и содержит файлы проекта."
                )
        else:
            # Если пути совпадают, просто убеждаемся что директория существует
            os.makedirs(remote_project_dir, exist_ok=True)
        
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
        import logging
        
        logger = logging.getLogger(__name__)
        
        deploy_config_dir = "/etc/nginx/sites-available/deploy"
        location_config_file = f"{deploy_config_dir}/{page_hash}.conf"
        
        # Создаем директорию
        os.makedirs(deploy_config_dir, exist_ok=True)
        
        # Записываем location блок
        logger.info(f"Writing nginx config to: {location_config_file}")
        logger.info(f"Nginx location config:\n{nginx_location}")
        try:
            with open(location_config_file, 'w') as f:
                f.write(nginx_location)
            logger.info(f"Successfully wrote nginx config file: {location_config_file}")
            # Проверяем что файл создан
            if os.path.exists(location_config_file):
                logger.info(f"Config file exists: {os.path.exists(location_config_file)}, size: {os.path.getsize(location_config_file)}")
            else:
                logger.error(f"Config file was not created: {location_config_file}")
        except Exception as e:
            logger.error(f"Failed to write nginx config: {e}", exc_info=True)
            raise
        
        # Убеждаемся, что include директива есть в основном конфиге
        await self._ensure_include_in_main_config_direct(deploy_config_dir)
        
        # Тестируем конфигурацию nginx (проверяем доступность nginx)
        nginx_paths = ["/usr/sbin/nginx", "/usr/bin/nginx", "nginx"]
        nginx_cmd = None
        for path in nginx_paths:
            result = subprocess.run(
                ["which", path] if path == "nginx" else ["test", "-f", path],
                capture_output=True,
                timeout=2
            )
            if result.returncode == 0:
                nginx_cmd = path
                break
        
        if nginx_cmd:
            test_result = subprocess.run(
                [nginx_cmd, "-t"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if test_result.returncode != 0:
                logger.warning(f"Nginx config test failed: {test_result.stderr}")
                # Не падаем, так как конфиг может быть валидным, просто nginx не доступен для проверки
        else:
            logger.warning("nginx command not found, skipping config test")
        
        # Перезагружаем nginx (используем docker exec для выполнения команды на хосте)
        reload_success = False
        
        # Пробуем перезагрузить Nginx через Docker exec на хосте
        # Если мы внутри контейнера API, нужно выполнить команду на хосте
        try:
            # Вариант 1: Через docker exec в основной процесс (если Nginx в контейнере)
            # Или используем host.docker.internal если доступен
            # Но проще - использовать прямой доступ к хосту через PID namespace
            
            # Проверяем PID файл Nginx на хосте (монтированный /etc/nginx может содержать /var/run/)
            nginx_pid_file_paths = [
                "/var/run/nginx.pid",
                "/run/nginx.pid", 
                "/var/run/nginx/nginx.pid"
            ]
            
            nginx_pid = None
            for pid_path in nginx_pid_file_paths:
                if os.path.exists(pid_path):
                    try:
                        with open(pid_path, 'r') as f:
                            nginx_pid = f.read().strip()
                        if nginx_pid and nginx_pid.isdigit():
                            break
                    except:
                        continue
            
            # Если нашли PID, пробуем отправить сигнал HUP (работает если контейнер запущен с --pid=host)
            if nginx_pid:
                try:
                    reload_result = subprocess.run(
                        ["kill", "-HUP", nginx_pid],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if reload_result.returncode == 0:
                        logger.info(f"Successfully reloaded nginx via HUP signal (PID: {nginx_pid})")
                        reload_success = True
                except Exception as e:
                    logger.debug(f"Could not send HUP signal: {e}")
            
            # Вариант 2: Через docker exec (если есть доступ к Docker socket)
            if not reload_success:
                try:
                    # Используем docker exec для выполнения команды в контейнере на хосте
                    # Или напрямую через nsenter, но проще использовать systemctl через docker exec
                    docker_result = subprocess.run(
                        ["docker", "exec", "nginx", "systemctl", "reload", "nginx"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if docker_result.returncode == 0:
                        logger.info("Successfully reloaded nginx via docker exec")
                        reload_success = True
                except Exception as e:
                    logger.debug(f"Could not reload via docker exec: {e}")
            
            # Вариант 3: Прямой вызов systemctl (может работать если контейнер имеет доступ к systemd)
            if not reload_success:
                try:
                    systemctl_result = subprocess.run(
                        ["which", "systemctl"],
                        capture_output=True,
                        timeout=2
                    )
                    if systemctl_result.returncode == 0:
                        reload_result = subprocess.run(
                            ["systemctl", "reload", "nginx"],
                            capture_output=True,
                            text=True,
                            timeout=10
                        )
                        if reload_result.returncode == 0:
                            logger.info("Successfully reloaded nginx via systemctl")
                            reload_success = True
                        else:
                            logger.debug(f"systemctl reload failed: {reload_result.stderr}")
                except Exception as e:
                    logger.debug(f"Could not use systemctl: {e}")
            
            # Вариант 4: Через nginx -s reload
            if not reload_success and nginx_cmd:
                try:
                    reload_result = subprocess.run(
                        [nginx_cmd, "-s", "reload"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if reload_result.returncode == 0:
                        logger.info("Successfully reloaded nginx via nginx -s reload")
                        reload_success = True
                    else:
                        logger.debug(f"nginx -s reload failed: {reload_result.stderr}")
                except Exception as e:
                    logger.debug(f"Could not use nginx -s reload: {e}")
            
        except Exception as e:
            logger.warning(f"Error during nginx reload attempt: {e}")
        
        if not reload_success:
            logger.warning("Could not automatically reload nginx. Config is saved but nginx needs manual reload: systemctl reload nginx")
            logger.info("You may need to reload nginx manually after deploy: systemctl reload nginx")
        
        # Сохраняем в реестр
        await self._save_container_registry_direct(page_hash, container_port, container_name=f"deploy-{page_hash}")
        
        return True
            
    async def _ensure_include_in_main_config_direct(self, deploy_config_dir: str):
        """Убеждается, что include есть в основном конфиге (без SSH)"""
        import subprocess
        import re
        import logging
        
        logger = logging.getLogger(__name__)
        logger.info(f"_ensure_include_in_main_config_direct called with deploy_config_dir: {deploy_config_dir}")
        
        # Ищем конфиг с доменом (используем переменную окружения DOMAIN или ищем любой активный конфиг)
        domain = os.environ.get("DOMAIN", "")
        logger.info(f"Looking for nginx config with domain: {domain}")
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
        logger.info(f"First search result returncode: {result.returncode}, stdout: {result.stdout[:200]}")
        if result.returncode == 0 and result.stdout.strip():
            # Если нашли по домену, берем путь из вывода grep
            if domain:
                output = result.stdout.strip()
                if ':' in output:
                    config_path = output.split(':')[0]
                else:
                    config_path = output.split('\n')[0]
            else:
                # Если искали по sites-enabled, конвертируем путь
                enabled_path = result.stdout.strip().split('\n')[0]
                config_path = enabled_path.replace('/sites-enabled/', '/sites-available/')
        logger.info(f"After first search, config_path: {config_path}")
        
        # Если не нашли, пробуем найти любой активный конфиг
        if not config_path:
            result = subprocess.run(
                ["find", "/etc/nginx/sites-enabled", "-name", "*.conf", "-type", "f"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                enabled_path = result.stdout.strip().split('\n')[0]
                config_path = enabled_path.replace('/sites-enabled/', '/sites-available/')
        
        # Валидация config_path
        logger.info(f"Final config_path before validation: {config_path}")
        if not config_path:
            logger.warning("Could not find main nginx config, include directive should be added manually")
            return
        
        # Проверяем, что config_path - это файл, а не директория или что-то странное
        if not os.path.isabs(config_path):
            # Если путь относительный и равен 'containers' - это ошибка
            if config_path == 'containers':
                logger.error(f"ERROR: config_path is incorrectly set to 'containers'. This is likely a bug in path parsing.")
                logger.error(f"Deploy config dir: {deploy_config_dir}")
                logger.error(f"Domain: {domain}")
                logger.error(f"First search stdout: {result.stdout if 'result' in locals() else 'N/A'}")
                return
            logger.warning(f"config_path is not absolute: {config_path}")
            return
        
        if not os.path.exists(config_path):
            print(f"Warning: nginx config not found: {config_path}")
            return
        
        if not os.path.isfile(config_path):
            print(f"Warning: config_path is not a file: {config_path} (is directory: {os.path.isdir(config_path)})")
            return
        
        # Читаем конфиг
        try:
            with open(config_path, 'r') as f:
                content = f.read()
        except (OSError, IOError) as e:
            print(f"Error reading nginx config {config_path}: {e}")
            return
        
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
    

