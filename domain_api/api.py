"""
REST API для работы с доменами через Beget.
"""
import re
import hmac
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from functools import wraps
from config import (
    API_HOST,
    API_PORT,
    API_DEBUG,
    API_KEY,
    MAX_DOMAIN_PRICE,
    MEDIA_STORAGE_DIR,
    MEDIA_MAX_UPLOAD_BYTES,
    MEDIA_PUBLIC_URL,
)
from beget_client import BegetClient, BegetAPIError
from flask import send_file
import traceback

from media_storage import save_picture, get_picture_paths, delete_picture

# Валидация: домен .ru (в т.ч. sub.example.ru), период 1–10 лет
DOMAIN_RU_RE = re.compile(r"^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+ru$", re.IGNORECASE)
PERIOD_MIN, PERIOD_MAX = 1, 10

client = BegetClient()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MEDIA_MAX_UPLOAD_BYTES
# Отключаем CORS полностью - API только для локального использования
# CORS(app)  # Закомментировано для безопасности

# Rate limiting для защиты от злоупотреблений
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per hour", "10 per minute"]
)


def check_local_only():
    """Проверяет, что запрос приходит только с localhost"""
    if API_HOST == '127.0.0.1' or API_HOST == 'localhost':
        # Проверяем, что запрос действительно с localhost
        remote_addr = request.environ.get('REMOTE_ADDR', '')
        # Разрешаем только localhost (127.0.0.1, ::1, localhost)
        allowed_hosts = ['127.0.0.1', '::1', 'localhost']
        if remote_addr not in allowed_hosts:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'FORBIDDEN',
                    'message': 'Доступ разрешён только с localhost'
                }
            }), 403
    return None


@app.before_request
def before_request():
    """Проверка перед каждым запросом"""
    # Проверяем доступ только с localhost
    error_response = check_local_only()
    if error_response:
        return error_response


def require_api_key(f):
    """Декоратор для проверки API ключа"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if API_KEY:
            # Предпочтительно X-API-Key (api_key в URL может попасть в логи)
            provided_key = request.headers.get('X-API-Key') or request.args.get('api_key')
            if not provided_key or not hmac.compare_digest(provided_key, API_KEY):
                return jsonify({
                    'success': False,
                    'error': {
                        'code': 'UNAUTHORIZED',
                        'message': 'Неверный или отсутствующий API ключ'
                    }
                }), 401
        return f(*args, **kwargs)
    return decorated_function


@app.errorhandler(BegetAPIError)
def handle_beget_error(error):
    """Обработчик ошибок Beget API"""
    return jsonify({
        'success': False,
        'error': {
            'code': error.error_code,
            'message': error.error_text
        }
    }), 400


@app.errorhandler(Exception)
def handle_general_error(error):
    """Обработчик общих ошибок"""
    app.logger.error(f"Unhandled error: {traceback.format_exc()}")
    return jsonify({
        'success': False,
        'error': {
            'code': 'INTERNAL_ERROR',
            'message': str(error)
        }
    }), 500


@app.route('/health', methods=['GET'])
def health():
    """Проверка работоспособности API"""
    return jsonify({
        'success': True,
        'status': 'ok'
    })


@app.route('/api/domain/check', methods=['POST'])
@limiter.limit("20 per minute")  # Ограничение: 20 проверок в минуту
@require_api_key
def check_domain():
    """
    Проверка доступности домена
    
    Request body:
    {
        "domain": "example.ru",
        "is_transfer": false,  # опционально
        "currency": "RUR"      # опционально
    }
    
    Response:
    {
        "success": true,
        "available": true,
        "domain": "example.ru",
        "price": 199,
        "renew_price": 199,
        "currency": "RUR",
        "is_premium": false
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'domain' not in data:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'MISSING_DOMAIN',
                    'message': 'Параметр domain обязателен'
                }
            }), 400
        
        domain = data['domain']
        if not isinstance(domain, str) or not domain.strip():
            return jsonify({
                'success': False,
                'error': {'code': 'INVALID_DOMAIN', 'message': 'domain должен быть непустой строкой'}
            }), 400
        domain = domain.strip().lower()
        if not DOMAIN_RU_RE.match(domain):
            return jsonify({
                'success': False,
                'error': {'code': 'INVALID_DOMAIN', 'message': 'Поддерживаются только домены вида name.ru'}
            }), 400
        try:
            period = int(data.get('period', 1))
            if not (PERIOD_MIN <= period <= PERIOD_MAX):
                period = 1
        except (TypeError, ValueError):
            period = 1
        result = client.check_domain(domain=domain, period=period)
        
        # Проверяем максимальную цену
        price = result.get('price')
        if price:
            try:
                price_float = float(price)
                if price_float > MAX_DOMAIN_PRICE:
                    result['price_exceeds_limit'] = True
                    result['max_allowed_price'] = MAX_DOMAIN_PRICE
                    result['warning'] = f'Цена домена ({price_float} руб.) превышает максимально допустимую ({MAX_DOMAIN_PRICE} руб.)'
            except (ValueError, TypeError):
                pass  # Если цена не число, пропускаем проверку
        
        return jsonify({
            'success': True,
            **result
        })
        
    except BegetAPIError:
        raise
    except Exception as e:
        app.logger.error(f"Error checking domain: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': {
                'code': 'INTERNAL_ERROR',
                'message': str(e)
            }
        }), 500


# --- Медиа (картинки от чат-бота) на том же порту 5000 ---


@app.route('/api/media/upload', methods=['POST'])
@limiter.limit("60 per minute")
@require_api_key
def media_upload():
    """
    Загрузка картинки (multipart/form-data, поле file).
    Ответ: { "success": true, "data": { "id": "...", "url": "https://media.../picture/<id>" } }
    """
    if "file" not in request.files:
        return jsonify({"success": False, "error": {"code": "MISSING_FILE", "message": "Поле file обязательно"}}), 400
    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"success": False, "error": {"code": "INVALID_FILE", "message": "Файл не выбран"}}), 400
    mime = (file.mimetype or "").lower().strip()
    if not mime.startswith("image/"):
        return jsonify({"success": False, "error": {"code": "UNSUPPORTED_TYPE", "message": "Только изображения"}}), 400
    content = file.read()
    if not content:
        return jsonify({"success": False, "error": {"code": "EMPTY_FILE", "message": "Файл пустой"}}), 400
    try:
        pic_id, _, _, _ = save_picture(MEDIA_STORAGE_DIR, content, mime, file.filename)
    except Exception as e:
        app.logger.error(f"Media save error: {traceback.format_exc()}")
        return jsonify({"success": False, "error": {"code": "SAVE_ERROR", "message": str(e)}}), 500
    return jsonify({
        "success": True,
        "data": {"id": pic_id, "url": f"{MEDIA_PUBLIC_URL}/picture/{pic_id}"},
    })


@app.route('/api/media/picture/<pic_id>', methods=['DELETE'])
@limiter.limit("30 per minute")
@require_api_key
def delete_media_picture(pic_id):
    """Удаление картинки по id. Ответ: { "success": true } или 404."""
    if delete_picture(MEDIA_STORAGE_DIR, pic_id):
        return jsonify({"success": True})
    return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Картинка не найдена"}}), 404


@app.route('/picture/<pic_id>', methods=['GET'])
def get_picture(pic_id):
    """Отдача картинки по id (для media.automatoria.ru/picture/<id>)."""
    info = get_picture_paths(MEDIA_STORAGE_DIR, pic_id)
    if not info:
        return jsonify({"success": False, "error": {"code": "NOT_FOUND", "message": "Картинка не найдена"}}), 404
    resp = send_file(info["path"], mimetype=info["mime"], conditional=True, max_age=31536000)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


if __name__ == '__main__':
    app.run(
        host=API_HOST,
        port=API_PORT,
        debug=API_DEBUG
    )
