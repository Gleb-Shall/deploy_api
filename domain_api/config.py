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
MAX_DOMAIN_PRICE = int(os.getenv('MAX_DOMAIN_PRICE', '200'))
# Опционально: IP для A-записи корня домена после покупки (если не передан в запросе)
BEGET_DNS_APEX_IP = (os.getenv('BEGET_DNS_APEX_IP') or '').strip()

# Лимит покупок: "N per hour" или "N per minute" (защита от случайного цикла/злоупотребления)
PURCHASE_RATE_LIMIT = os.getenv('PURCHASE_RATE_LIMIT', '5 per hour')

# Ожидание применения DNS после установки A-записи (секунды)
DNS_PROPAGATION_TIMEOUT = int(os.getenv('DNS_PROPAGATION_TIMEOUT', '120'))
DNS_PROPAGATION_INTERVAL = int(os.getenv('DNS_PROPAGATION_INTERVAL', '5'))
# TTL для A-записи (секунды; малый TTL — быстрее применение; если не задан — не передаём в Beget)
DNS_APEX_TTL = int(os.getenv('DNS_APEX_TTL')) if os.getenv('DNS_APEX_TTL') else None

# Валидация
if not BEGET_LOGIN or not BEGET_PASSWORD:
    raise ValueError(
        "Задайте BEGET_LOGIN и BEGET_PASSWORD в .env. "
        "Пароль API настраивается в панели Beget (отдельно от пароля входа)."
    )
