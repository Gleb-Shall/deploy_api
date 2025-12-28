from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from typing import Optional
import json
import os

from src.models import DeployRequest, DeployResponse
from src.parser import parse_json_request
from src.docker_manager import DockerManager
from src.nginx_manager import NginxManager
from src.deploy_manager import DeployManager
from src.utils import generate_hash

app = FastAPI(title="Deploy API", version="1.0.0")

# Конфигурация из переменных окружения
DOMAIN = os.environ.get("DOMAIN", "your-domain.com")

# Менеджеры
docker_manager = DockerManager()
nginx_manager = NginxManager(domain=DOMAIN)
# DeployManager работает в двух режимах:
# - LOCAL_TEST=1: локальный Docker для тестирования
# - RUN_ON_SERVER=1: прямой доступ к Docker на сервере (по умолчанию в продакшене)
deploy_manager = DeployManager()


@app.get("/")
async def root():
    return {"message": "Deploy API is running"}


@app.post("/deploy", response_model=DeployResponse)
async def deploy(file: UploadFile = File(...)):
    """
    Принимает JSON файл, парсит его, создает Docker контейнер и деплоит сайт.
    """
    try:
        # Читаем JSON файл
        content = await file.read()
        json_data = json.loads(content.decode('utf-8'))
        
        # Парсим JSON
        parsed_data = parse_json_request(json_data)
        telegram_id = parsed_data["telegram_id"]
        files = parsed_data["files"]
        
        # Генерируем уникальный хэш для страницы
        page_hash = generate_hash(telegram_id, files)
        
        # Создаем структуру проекта (локально)
        image_name = await docker_manager.create_container(
            page_hash=page_hash,
            files=files,
            telegram_id=telegram_id
        )
        
        # Получаем путь к директории проекта
        container_dir = docker_manager.get_container_dir(page_hash)
        
        # Деплоим контейнер (локально или на сервере, в зависимости от режима)
        # Контейнер будет иметь имя deploy-{page_hash} и уникальный порт
        container_port = await deploy_manager.deploy_container(
            container_id=image_name,
            page_hash=page_hash,
            container_dir=container_dir
        )
        
        # Генерируем location блок для nginx
        nginx_location = nginx_manager.generate_nginx_location(
            page_hash=page_hash,
            container_port=container_port
        )
        
        # Настраиваем nginx (локально пропускается, на сервере настраивается)
        await deploy_manager.configure_nginx(
            page_hash=page_hash,
            container_port=container_port,
            nginx_location=nginx_location
        )
        
        # Формируем полную ссылку (локально или на сервере)
        # LOCAL_TEST=1: локальное тестирование (возвращаем localhost URL)
        # RUN_ON_SERVER=1: продакшн режим (контейнер на сервере)
        if os.environ.get("LOCAL_TEST") == "1":
            # Для локального теста возвращаем localhost URL
            full_url = f"http://localhost:8080/{page_hash}"
        else:
            # Продакшн режим: контейнер запущен на сервере
            full_url = f"https://{DOMAIN}/{page_hash}"
        
        return DeployResponse(
            telegram_id=telegram_id,
            url=full_url
        )
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing required field: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deployment failed: {str(e)}")


@app.get("/health")
async def health():
    """Проверка здоровья API"""
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

