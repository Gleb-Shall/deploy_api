"""
Конфигурация Media API (загрузка файлов от чат-бота).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

_MEDIA_API_DIR = Path(__file__).resolve().parent
load_dotenv(_MEDIA_API_DIR / ".env")

MEDIA_HOST = os.getenv("MEDIA_HOST", "127.0.0.1")
MEDIA_PORT = int(os.getenv("MEDIA_PORT", "5052"))

MEDIA_STORAGE_DIR = os.getenv("MEDIA_STORAGE_DIR", "/opt/deploy/media")
MEDIA_MAX_UPLOAD_BYTES = int(os.getenv("MEDIA_MAX_UPLOAD_BYTES", "20971520"))  # 20 MB
MEDIA_MAX_VIDEO_BYTES = int(os.getenv("MEDIA_MAX_VIDEO_BYTES", "524288000"))  # 500 MB
MEDIA_MAX_PDF_PAGES = int(os.getenv("MEDIA_MAX_PDF_PAGES", "50"))

# Базовый URL для ссылок в ответах (без слэша в конце)
MEDIA_PUBLIC_URL = (os.getenv("MEDIA_PUBLIC_URL") or "https://media.automatoria.ru").rstrip("/")

# Тот же ключ что у domain_api (передаётся в X-API-Key)
MEDIA_API_KEY = (os.getenv("API_KEY") or "").strip()
