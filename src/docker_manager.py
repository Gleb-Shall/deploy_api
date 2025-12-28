"""
Менеджер для работы с Docker контейнерами
"""
import os
import shutil
import tempfile
from typing import List, Dict, Any
from pathlib import Path
import subprocess
import json


class DockerManager:
    """Управление созданием и запуском Docker контейнеров"""
    
    def __init__(self, work_dir: str = None):
        if work_dir is None:
            # Определяем корень проекта (два уровня вверх от src/)
            current_dir = Path(__file__).parent
            project_root = current_dir.parent
            work_dir = str(project_root / "containers")
        self.work_dir = work_dir
        os.makedirs(work_dir, exist_ok=True)
    
    async def create_container(
        self,
        page_hash: str,
        files: List[Dict[str, Any]],
        telegram_id: str
    ) -> str:
        """
        Создает Docker контейнер для проекта.
        
        Args:
            page_hash: Уникальный хэш страницы
            files: Список файлов проекта
            telegram_id: ID телеграм пользователя
            
        Returns:
            ID контейнера или путь к образу
        """
        # Валидация входных данных
        if not page_hash:
            raise ValueError("page_hash не может быть пустым")
        if not self.work_dir or self.work_dir == "containers":
            raise ValueError(f"Неправильный work_dir: '{self.work_dir}'. Убедитесь, что DockerManager инициализирован корректно.")
        
        # Создаем временную директорию для проекта
        project_dir = os.path.join(self.work_dir, page_hash)
        
        # Валидация: убеждаемся что project_dir правильный
        if not project_dir or project_dir == self.work_dir or project_dir == "containers":
            raise ValueError(f"Неправильный project_dir: '{project_dir}'. work_dir: '{self.work_dir}', page_hash: '{page_hash}'")
        
        os.makedirs(project_dir, exist_ok=True)
        
        try:
            # Сохраняем все файлы проекта
            await self._save_files(project_dir, files)
            
            # Создаем Dockerfile
            await self._create_dockerfile(project_dir)
            
            # Создаем .dockerignore
            await self._create_dockerignore(project_dir)
            
            # Собираем Docker образ (имя образа использует хэш для уникальности)
            image_name = f"deploy-{page_hash}"
            await self._build_image(project_dir, image_name)
            
            # Возвращаем image_name, который будет использован как container_id
            return image_name
            
        except Exception as e:
            # Очистка в случае ошибки
            if os.path.exists(project_dir):
                shutil.rmtree(project_dir)
            raise Exception(f"Failed to create container: {str(e)}")
    
    async def _save_files(self, project_dir: str, files: List[Dict[str, Any]]):
        """Сохраняет файлы проекта в директорию"""
        from src.utils import prepare_file_content
        
        # Валидация project_dir
        if not project_dir or project_dir == "containers":
            raise ValueError(f"Неправильный project_dir: '{project_dir}'. Ожидается путь к поддиректории проекта.")
        
        has_package_json = False
        page_hash = None
        
        for file_data in files:
            file_name = file_data["name"]
            
            # Проверяем, что имя файла не пустое и не является директорией
            if not file_name or file_name.strip() == "":
                raise ValueError(f"Пустое имя файла в проекте")
            
            # Нормализуем путь (убираем ведущие / и ..)
            file_name = file_name.lstrip('/')
            if '..' in file_name:
                raise ValueError(f"Небезопасный путь к файлу: {file_data['name']}")
            
            file_path = os.path.join(project_dir, file_name)
            file_dir = os.path.dirname(file_path)
            
            # Проверяем, что путь не выходит за пределы project_dir
            if not os.path.abspath(file_path).startswith(os.path.abspath(project_dir)):
                raise ValueError(f"Путь к файлу выходит за пределы проекта: {file_name}")
            
            # Проверяем, что мы не пытаемся создать файл там, где уже есть директория
            if os.path.exists(file_path) and os.path.isdir(file_path):
                raise ValueError(
                    f"Не удалось создать файл '{file_name}': по этому пути уже существует директория. "
                    f"Полный путь: {file_path}"
                )
            
            # Проверяем наличие package.json
            if file_name == "package.json":
                has_package_json = True
            
            # Если это astro.config.mjs, модифицируем его для правильной работы
            if file_name == "astro.config.mjs":
                content = prepare_file_content(file_data["content"])
                # Извлекаем page_hash из директории проекта
                page_hash = os.path.basename(project_dir)
                # Добавляем base path если нужно (для работы под /{hash}/)
                # Но лучше оставить без base, так как nginx делает rewrite
                # content = content.replace('export default defineConfig({', 
                #     f'export default defineConfig({{\n  base: "/{page_hash}/",')
            else:
                content = prepare_file_content(file_data["content"])
            
            # Создаем директории если нужно
            if file_dir:
                os.makedirs(file_dir, exist_ok=True)
            
            # Записываем файл
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            except (OSError, IOError) as e:
                raise ValueError(
                    f"Не удалось создать файл '{file_name}': {str(e)}. "
                    f"Полный путь: {file_path}"
                )
        
        if not has_package_json:
            raise ValueError("package.json is required in project files")
    
    async def _create_dockerfile(self, project_dir: str):
        """Создает Dockerfile для Astro проекта"""
        dockerfile_content = """FROM node:20-alpine AS builder

WORKDIR /app

# Копируем package.json и package-lock.json (если есть) и устанавливаем зависимости
COPY package*.json ./
RUN npm install

# Копируем остальные файлы
COPY . .

# Собираем проект
RUN npm run build

# Проверяем что сборка прошла успешно
RUN test -d dist || (echo "ERROR: dist directory not found after build" && exit 1)
RUN ls -la dist/ || echo "Cannot list dist directory"

# Production образ - используем nginx для отдачи статики
FROM nginx:alpine

# Копируем собранные статические файлы
COPY --from=builder /app/dist /usr/share/nginx/html

# Создаем конфигурацию nginx
RUN echo 'server { \\
    listen 8000; \\
    server_name _; \\
    root /usr/share/nginx/html; \\
    index index.html; \\
    \\
    # Включаем gzip \\
    gzip on; \\
    gzip_vary on; \\
    gzip_min_length 1024; \\
    gzip_types text/plain text/css text/xml text/javascript application/javascript application/xml+rss application/json; \\
    \\
    # Отдача статических файлов с правильными MIME типами \\
    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot|webp)$ { \\
        expires 1y; \\
        add_header Cache-Control "public, immutable"; \\
        access_log off; \\
        try_files $uri =404; \\
    } \\
    \\
    # SPA routing - все запросы на index.html \\
    location / { \\
        try_files $uri $uri/ /index.html; \\
    } \\
    \\
    # Логирование для отладки \\
    access_log /var/log/nginx/access.log; \\
    error_log /var/log/nginx/error.log; \\
}' > /etc/nginx/conf.d/default.conf

EXPOSE 8000

CMD ["nginx", "-g", "daemon off;"]
"""
        
        dockerfile_path = os.path.join(project_dir, "Dockerfile")
        with open(dockerfile_path, 'w', encoding='utf-8') as f:
            f.write(dockerfile_content)
    
    async def _create_dockerignore(self, project_dir: str):
        """Создает .dockerignore файл"""
        dockerignore_content = """node_modules
npm-debug.log
.env
.git
.gitignore
*.md
.DS_Store
# НЕ исключаем .astro и dist - они нужны для builder stage
"""
        
        dockerignore_path = os.path.join(project_dir, ".dockerignore")
        with open(dockerignore_path, 'w', encoding='utf-8') as f:
            f.write(dockerignore_content)
    
    async def _build_image(self, project_dir: str, image_name: str):
        """
        Собирает Docker образ.
        В продакшене это будет делаться на сервере через SSH.
        """
        # Здесь можно добавить локальную сборку для тестирования
        # или просто сохранить метаданные для последующей сборки на сервере
        pass
    
    def get_container_dir(self, page_hash: str) -> str:
        """Возвращает путь к директории контейнера"""
        return os.path.join(self.work_dir, page_hash)

