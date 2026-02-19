"""
REST API для работы с доменами через Beget.
"""
import re
import hmac
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from functools import wraps
from config import API_HOST, API_PORT, API_DEBUG, API_KEY, MAX_DOMAIN_PRICE, BEGET_DNS_APEX_IP, PURCHASE_RATE_LIMIT
from beget_client import BegetClient, BegetAPIError
import traceback

# Валидация: домен .ru (в т.ч. sub.example.ru), период 1–10 лет, IP для DNS
DOMAIN_RU_RE = re.compile(r"^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+ru$", re.IGNORECASE)
PERIOD_MIN, PERIOD_MAX = 1, 10


def _is_valid_ip(ip: str) -> bool:
    if not ip or not isinstance(ip, str):
        return False
    ip = ip.strip()
    if not ip:
        return False
    # IPv4 простой формат; при необходимости добавить ipaddress.ip_address(ip)
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        if not p.isdigit() or not (0 <= int(p) <= 255):
            return False
    return True

client = BegetClient()

app = Flask(__name__)
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


@app.route('/api/domain/purchase', methods=['POST'])
@limiter.limit(PURCHASE_RATE_LIMIT)
@require_api_key
def purchase_domain():
    """
    Покупка домена (Beget addVirtual: регистрация, списание с баланса).
    Body: { "domain": "example.ru", "period": 1, "api_ip": "1.2.3.4" } — api_ip опционально:
    после покупки выставится A-запись корня домена на этот IP (через Beget dns/changeRecords).
    Можно задать BEGET_DNS_APEX_IP в .env вместо api_ip в запросе.
    """
    try:
        # Блокируем покупку в режиме дебага
        if API_DEBUG:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'DEBUG_MODE',
                    'message': 'Покупка доменов отключена в режиме дебага (API_DEBUG=True)'
                }
            }), 403
        
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'MISSING_DATA',
                    'message': 'Тело запроса не может быть пустым'
                }
            }), 400
        
        if 'domain' not in data or 'period' not in data:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'MISSING_REQUIRED_FIELDS',
                    'message': 'Поля domain и period обязательны'
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
            period = int(data['period'])
            if not (PERIOD_MIN <= period <= PERIOD_MAX):
                return jsonify({
                    'success': False,
                    'error': {'code': 'INVALID_PERIOD', 'message': f'period должен быть от {PERIOD_MIN} до {PERIOD_MAX}'}
                }), 400
        except (TypeError, ValueError):
            return jsonify({
                'success': False,
                'error': {'code': 'INVALID_PERIOD', 'message': 'period должен быть числом'}
            }), 400
        set_dns_ip = data.get('api_ip') or data.get('set_dns_ip') or BEGET_DNS_APEX_IP or None
        if set_dns_ip and not _is_valid_ip(set_dns_ip):
            return jsonify({
                'success': False,
                'error': {'code': 'INVALID_API_IP', 'message': 'api_ip/set_dns_ip должен быть корректным IPv4'}
            }), 400

        # Проверяем доступность и возможность оплаты перед покупкой
        check_result = client.check_domain(domain=domain, period=period)
        if not check_result.get('available'):
            return jsonify({
                'success': False,
                'error': {
                    'code': 'DOMAIN_NOT_AVAILABLE',
                    'message': f'Домен {domain} недоступен для регистрации',
                    'details': check_result.get('error_text', check_result.get('result'))
                }
            }), 400
        if not check_result.get('can_purchase'):
            return jsonify({
                'success': False,
                'error': {
                    'code': 'CANNOT_PURCHASE',
                    'message': 'Невозможно оплатить домен (недостаточно средств или способ оплаты недоступен)',
                    'details': check_result.get('error_text'),
                    'balance': check_result.get('balance'),
                    'pay_type': check_result.get('pay_type')
                }
            }), 400
        
        # Проверяем максимальную цену
        price = check_result.get('price')
        if price is not None:
            try:
                # Преобразуем цену в число (может быть строка или число)
                price_float = float(price)
                if price_float > MAX_DOMAIN_PRICE:
                    return jsonify({
                        'success': False,
                        'error': {
                            'code': 'PRICE_EXCEEDS_LIMIT',
                            'message': f'Цена домена ({price_float} руб.) превышает максимально допустимую ({MAX_DOMAIN_PRICE} руб.)',
                            'domain_price': price_float,
                            'max_allowed_price': MAX_DOMAIN_PRICE
                        }
                    }), 400
            except (ValueError, TypeError):
                # Если цена не число, пропускаем проверку (может быть премиум домен без цены)
                # Но всё равно предупреждаем
                app.logger.warning(f"Не удалось преобразовать цену домена {domain} в число: {price}")
        
        result = client.purchase_domain(domain=domain, period=period, set_dns_ip=set_dns_ip)
        
        dns_propagated = result.get('dns_propagated', False)
        resp = {
            'success': True,
            'domain': result['domain'],
            'service_id': result.get('service_id'),
            'dns_propagated': dns_propagated,
            'message': (
                'Домен заказан, A-запись применена и видна в DNS'
                if dns_propagated
                else (
                    'Домен заказан' + (
                        ', A-запись установлена, ожидание применения DNS (таймаут или ещё не видна)'
                        if result.get('dns_set') else ''
                    )
                )
            ),
        }
        if result.get('dns_set') is not None:
            resp['dns_set'] = result['dns_set']
        if result.get('dns_error'):
            resp['dns_error'] = result['dns_error']
        return jsonify(resp)
        
    except BegetAPIError as e:
        # Обработка ошибок, связанных с ценой/балансом
        error_code = e.error_code or 'UNKNOWN_ERROR'
        error_text = e.error_text or str(e)
        
        # Специальная обработка ошибок, связанных с ценой/премиум-доменами
        price_related_keywords = ['price', 'premium', 'премиум', 'цена', 'дорог', 'стоимость', 'balance', 'баланс', 'недостаточно']
        is_price_error = any(keyword.lower() in error_text.lower() for keyword in price_related_keywords)
        
        if is_price_error:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'PRICE_ERROR',
                    'message': f'Ошибка при покупке домена {domain}. Возможно, домен является премиум-доменом с высокой ценой или недостаточно средств на балансе.',
                    'details': error_text,
                    'suggestion': 'Проверьте баланс аккаунта регистратора или попробуйте другой домен. Премиум-домены имеют индивидуальную цену.'
                }
            }), 400
        
        # Остальные ошибки обрабатываются через error handler
        raise
    except Exception as e:
        app.logger.error(f"Error purchasing domain: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': {
                'code': 'INTERNAL_ERROR',
                'message': str(e)
            }
        }), 500


if __name__ == '__main__':
    app.run(
        host=API_HOST,
        port=API_PORT,
        debug=API_DEBUG
    )
