from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from typing import Optional
import json
import os
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
        logger.info(f"Generated page_hash: {page_hash}")
        
        # Логируем work_dir для отладки
        logger.info(f"DockerManager work_dir: {docker_manager.work_dir}")
        
        # Создаем структуру проекта (локально)
        try:
            logger.info(f"Creating container with page_hash: {page_hash}")
            image_name = await docker_manager.create_container(
                page_hash=page_hash,
                files=files,
                telegram_id=telegram_id
            )
            logger.info(f"Container created, image_name: {image_name}")
        except Exception as e:
            logger.error(f"Error creating container: {str(e)}", exc_info=True)
            raise Exception(f"Ошибка при создании контейнера: {str(e)}")
        
        # Получаем путь к директории проекта
        container_dir = docker_manager.get_container_dir(page_hash)
        logger.info(f"Container dir: {container_dir}")
        
        # Валидация: убеждаемся что container_dir правильный
        if not container_dir or container_dir == "containers":
            logger.error(f"Invalid container_dir: '{container_dir}'")
            raise Exception(f"Неправильный путь container_dir: '{container_dir}'. Ожидается путь к поддиректории с хэшем.")
        
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
            # Используем http:// если USE_HTTPS не установлен в 1
            use_https = os.environ.get("USE_HTTPS", "0") == "1"
            protocol = "https" if use_https else "http"
            full_url = f"{protocol}://{DOMAIN}/{page_hash}"
        
        return DeployResponse(
            telegram_id=telegram_id,
            url=full_url
        )
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing required field: {str(e)}")
    except Exception as e:
        import traceback
        # Логируем полный traceback для отладки
        error_traceback = traceback.format_exc()
        # Логируем через logging (будет видно в docker logs)
        logger.error(f"Deployment failed: {str(e)}")
        logger.error(f"Full traceback:\n{error_traceback}")
        # Также выводим в stdout для гарантии
        print(f"ERROR: {str(e)}", flush=True)
        print(f"TRACEBACK:\n{error_traceback}", flush=True)
        # Возвращаем пользователю более информативное сообщение
        raise HTTPException(
            status_code=500, 
            detail=f"Deployment failed: {str(e)}"
        )


@app.get("/health")
async def health():
    """Проверка здоровья API"""
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

