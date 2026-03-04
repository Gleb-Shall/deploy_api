"""
Конфигурация для работы с Beget API (домены).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем .env только из папки domain_api
_DOMAIN_API_DIR = Path(__file__).resolve().parent
load_dotenv(_DOMAIN_API_DIR / ".env")

# Beget API
BEGET_LOGIN = os.getenv('BEGET_LOGIN')
BEGET_PASSWORD = os.getenv('BEGET_PASSWORD')
BEGET_API_BASE = os.getenv('BEGET_API_BASE', 'https://api.beget.com/api')

# API server
API_HOST = os.getenv('API_HOST', '127.0.0.1')
API_PORT = int(os.getenv('API_PORT', 5000))
API_DEBUG = os.getenv('API_DEBUG', 'False').lower() == 'true'

if API_HOST == '0.0.0.0':
    import warnings
    warnings.warn(
        "API_HOST=0.0.0.0 делает API доступным из интернета! "
        "Установлено 127.0.0.1 для безопасности.",
        UserWarning
    )
    API_HOST = '127.0.0.1'

API_KEY = (os.getenv('API_KEY') or '').strip()
# Порог цены для предупреждения в ответе check (price_exceeds_limit, warning)
MAX_DOMAIN_PRICE = int(os.getenv('MAX_DOMAIN_PRICE', '200'))

# Медиа (картинки от чат-бота) — тот же порт 5000
MEDIA_STORAGE_DIR = os.getenv('MEDIA_STORAGE_DIR', '/opt/deploy/media')
MEDIA_MAX_UPLOAD_BYTES = int(os.getenv('MEDIA_MAX_UPLOAD_BYTES', '10485760'))  # 10 MB
# Базовый URL для ссылки в ответе upload (без слэша в конце)
MEDIA_PUBLIC_URL = (os.getenv('MEDIA_PUBLIC_URL') or 'https://media.automatoria.ru').rstrip('/')

# Валидация
if not BEGET_LOGIN or not BEGET_PASSWORD:
    raise ValueError(
        "Задайте BEGET_LOGIN и BEGET_PASSWORD в .env. "
        "Пароль API настраивается в панели Beget (отдельно от пароля входа)."
    )
