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

# JS Challenge (anti-scraping protection)
CHALLENGE_SECRET = os.getenv('CHALLENGE_SECRET', '')
CHALLENGE_DIFFICULTY = int(os.getenv('CHALLENGE_DIFFICULTY', '4'))
CHALLENGE_TOKEN_TTL = int(os.getenv('CHALLENGE_TOKEN_TTL', '300'))  # seconds

# Redis for challenge nonce storage
REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))

# Anti-scraping: preview protection
CANARY_REDIRECT_URL = os.getenv('CANARY_REDIRECT_URL', 'https://en.wikipedia.org/wiki/Web_scraping')

# Allowed origins for /api/fingerprint-key (comma-separated, no trailing slash)
_raw_origins = os.getenv('ALLOWED_ORIGINS', 'https://automatoria.ru,https://preview.automatoria.ru,https://www.automatoria.ru')
ALLOWED_ORIGINS = tuple(v.strip().rstrip('/') for v in _raw_origins.split(',') if v.strip())
FINGERPRINT_KEY_TTL = int(os.getenv('FINGERPRINT_KEY_TTL', '300'))
SCREENSHOT_TOKEN_TTL = int(os.getenv('SCREENSHOT_TOKEN_TTL', '120'))

# Валидация
if not BEGET_LOGIN or not BEGET_PASSWORD:
    raise ValueError(
        "Задайте BEGET_LOGIN и BEGET_PASSWORD в .env. "
        "Пароль API настраивается в панели Beget (отдельно от пароля входа)."
    )
