"""
Конфигурация API для сохранения скриншотов Playwright (модуль генерации).
Отдельный порт от domain_api.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

_SCREENSHOT_API_DIR = Path(__file__).resolve().parent
load_dotenv(_SCREENSHOT_API_DIR / ".env")

SCREENSHOT_HOST = os.getenv("SCREENSHOT_HOST", "127.0.0.1")
SCREENSHOT_PORT = int(os.getenv("SCREENSHOT_PORT", "5051"))
SCREENSHOT_STORAGE_DIR = os.getenv("SCREENSHOT_STORAGE_DIR", "/opt/deploy/screenshots")
SCREENSHOT_MAX_UPLOAD_BYTES = int(os.getenv("SCREENSHOT_MAX_UPLOAD_BYTES", "20971520"))  # 20 MB
# Если задан — загрузка только с заголовком X-API-Key
SCREENSHOT_API_KEY = (os.getenv("SCREENSHOT_API_KEY") or "").strip()
# Полный URL скриншотов в ответе upload (без слэша в конце)
SCREENSHOT_PUBLIC_URL = (os.getenv("SCREENSHOT_PUBLIC_URL") or "https://media.automatoria.ru/screenshots").rstrip("/")
