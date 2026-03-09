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
    CHALLENGE_SECRET,
    CHALLENGE_DIFFICULTY,
    CHALLENGE_TOKEN_TTL,
    REDIS_HOST,
    REDIS_PORT,
)
from beget_client import BegetClient, BegetAPIError
from flask import send_file
import traceback
import hashlib
import time
import redis as redis_lib
import jwt as pyjwt

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
    # Challenge endpoints are public (accessed via nginx proxy from browser)
    if request.path.startswith('/api/challenge'):
        return None
    # Все остальные — только с localhost
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




# ============================================================
# Anti-Scraping: JS Challenge endpoints
# ============================================================

def _redis_client():
    """Get Redis client for challenge nonce storage."""
    try:
        r = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


@app.route('/api/challenge', methods=['GET'])
@limiter.limit("30 per minute")
def get_challenge():
    """Issue a PoW challenge."""
    challenge = hashlib.sha256(
        f"{time.time()}{request.remote_addr}".encode()
    ).hexdigest()
    expires_in = 60

    r = _redis_client()
    if r:
        r.setex(f"challenge:{challenge}", expires_in, "pending")

    return jsonify({
        "success": True,
        "challenge": challenge,
        "difficulty": CHALLENGE_DIFFICULTY,
        "expires_in": expires_in,
    })


@app.route('/api/challenge-token', methods=['POST'])
@limiter.limit("20 per minute")
def verify_challenge():
    """Verify PoW solution, issue short-lived access token."""
    if not CHALLENGE_SECRET:
        return jsonify({"success": False, "error": {"code": "NOT_CONFIGURED", "message": "Challenge secret not set"}}), 503

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": {"code": "INVALID_JSON", "message": "JSON body required"}}), 400

    challenge = (data.get("challenge") or "").strip()
    nonce = str(data.get("nonce") or "").strip()

    if not challenge or not nonce:
        return jsonify({"success": False, "error": {"code": "MISSING_FIELDS", "message": "challenge and nonce required"}}), 400

    if len(nonce) > 20:
        return jsonify({"success": False, "error": {"code": "INVALID_NONCE", "message": "nonce too long"}}), 400

    r = _redis_client()
    if r:
        key = f"challenge:{challenge}"
        val = r.get(key)
        if not val:
            return jsonify({"success": False, "error": {"code": "CHALLENGE_EXPIRED", "message": "Challenge expired or already used"}}), 400
        r.delete(key)

    attempt = hashlib.sha256(f"{challenge}{nonce}".encode()).hexdigest()
    required_prefix = "0" * CHALLENGE_DIFFICULTY
    if not attempt.startswith(required_prefix):
        return jsonify({"success": False, "error": {"code": "INVALID_SOLUTION", "message": "PoW verification failed"}}), 400

    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + CHALLENGE_TOKEN_TTL,
        "sub": "antibot",
        "ip": request.remote_addr,
    }
    token = pyjwt.encode(payload, CHALLENGE_SECRET, algorithm="HS256")

    return jsonify({
        "success": True,
        "token": token,
        "expires_in": CHALLENGE_TOKEN_TTL,
    })


@app.route('/api/challenge-verify', methods=['GET'])
@limiter.limit("60 per minute")
def verify_token():
    """Verify antibot token — used by nginx auth_request. Returns 200 or 401."""
    if not CHALLENGE_SECRET:
        return "", 200

    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        token = request.cookies.get("ab_token")
    if not token:
        token = request.args.get("token")

    if not token:
        return jsonify({"error": "No token"}), 401

    try:
        pyjwt.decode(token, CHALLENGE_SECRET, algorithms=["HS256"])
        return "", 200
    except pyjwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except pyjwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401

if __name__ == '__main__':
    app.run(
        host=API_HOST,
        port=API_PORT,
        debug=API_DEBUG
    )
