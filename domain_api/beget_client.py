"""
Клиент для работы с Beget API (домены).
Только проверка доступности и цены (checkDomainToRegister). Регистрация доменов через API недоступна.
Документация: https://beget.com/ru/kb/api/funkczii-dlya-raboty-s-domenami
"""
import logging
import requests
import json
from typing import Dict, Optional, Any

from config import BEGET_LOGIN, BEGET_PASSWORD, BEGET_API_BASE

logger = logging.getLogger(__name__)


def _extract_error_message(obj: dict, fallback: Optional[dict] = None, top_level: bool = False) -> str:
    """Извлекает текст ошибки из ответа Beget (разные форматы)."""
    for key in ('error_text', 'message', 'error', 'error_message', 'result'):
        val = obj.get(key)
        if val is not None and isinstance(val, str) and val.strip():
            return val.strip()
    if isinstance(fallback, dict):
        for key in ('error_text', 'message', 'error', 'error_message'):
            val = fallback.get(key)
            if val is not None and isinstance(val, str) and val.strip():
                return val.strip()
    # Проверяем вложенный answer (Beget иногда кладёт ошибку туда)
    if isinstance(obj.get('answer'), dict):
        for key in ('error_text', 'message', 'error', 'error_message'):
            val = obj['answer'].get(key)
            if val is not None and isinstance(val, str) and val.strip():
                return val.strip()
    return 'Unknown error'


class BegetAPIError(Exception):
    """Исключение для ошибок Beget API"""
    def __init__(self, error_code: str, error_text: str, response: Any = None):
        self.error_code = error_code
        self.error_text = error_text
        self.response = response
        super().__init__(f"{error_code}: {error_text}")


# Поддерживается только .ru (zone_id в Beget = 1)
ZONE_ID_RU = 1


class BegetClient:
    """Клиент для работы с Beget API (домены .ru)."""

    def __init__(self, login: str = None, password: str = None):
        self.login = login or BEGET_LOGIN
        self.password = password or BEGET_PASSWORD
        self.base_url = BEGET_API_BASE.rstrip('/')

    def _request(
        self,
        section: str,
        method: str,
        input_data: Optional[Dict] = None
    ) -> Any:
        """
        Выполняет GET-запрос к Beget API.
        Beget использует: /api/section/method?login=...&passwd=...&output_format=json&input_data=...
        """
        url = f"{self.base_url}/{section}/{method}"
        params = {
            'login': self.login,
            'passwd': self.password,
            'output_format': 'json',
        }
        if input_data is not None:
            params['input_format'] = 'json'
            params['input_data'] = json.dumps(input_data)

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            result = response.json()

            # Beget иногда возвращает ошибку в структуре answer/status
            if isinstance(result, dict):
                if result.get('status') == 'error':
                    msg = _extract_error_message(result, fallback=result)
                    if msg == 'Unknown error':
                        msg = f"Unknown error. Beget response: {json.dumps(result, ensure_ascii=False)[:500]}"
                    logger.warning("Beget API error (top-level): %s", result)
                    raise BegetAPIError('API_ERROR', msg, result)
                if 'answer' in result and isinstance(result['answer'], dict):
                    ans = result['answer']
                    if ans.get('status') == 'error':
                        msg = _extract_error_message(ans, fallback=result)
                        if msg == 'Unknown error':
                            msg = f"Unknown error. Beget response: {json.dumps(result, ensure_ascii=False)[:500]}"
                        logger.warning("Beget API error (answer): %s", result)
                        raise BegetAPIError('API_ERROR', msg, result)

            return result
        except requests.RequestException as e:
            raise BegetAPIError('NETWORK_ERROR', str(e))
        except json.JSONDecodeError as e:
            raise BegetAPIError('INVALID_RESPONSE', f'Invalid JSON: {str(e)}')

    def _domain_to_hostname_zone(self, domain: str) -> tuple:
        """Разбивает домен на hostname (без зоны) и зону. Поддерживается только .ru."""
        if not isinstance(domain, str):
            raise ValueError(f"Домен должен быть строкой: {domain}")
        domain = domain.strip().lower()
        if '/' in domain or ' ' in domain:
            raise ValueError(f"Некорректное имя домена: {domain}")
        parts = domain.split('.')
        if len(parts) < 2:
            raise ValueError(f"Домен должен содержать зону: {domain}")
        zone = parts[-1]
        hostname = '.'.join(parts[:-1])
        if zone == 'рф' or zone == 'xn--p1ai':
            zone = 'rf'
        return hostname, zone

    def check_domain(
        self,
        domain: str,
        period: int = 1,
        **kwargs
    ) -> Dict:
        """
        Проверяет доступность домена и возвращает реальную цену (включая премиум).
        Возвращает реальную цену (включая премиум-домены).

        Returns:
            {
                'domain': str,
                'available': bool,
                'result': str,
                'error_code': str | None,
                'error_text': str | None,
                'price': float | None,
                'renew_price': float | None,
                'currency': 'RUR',
                'is_premium': bool,
                'balance': float | None,
                'pay_type': str | None  # 'money' | 'bonus_domain' | null
            }
        """
        hostname, zone = self._domain_to_hostname_zone(domain)
        if zone != 'ru':
            return {
                'domain': domain,
                'available': False,
                'result': f'Поддерживается только зона .ru, получено: .{zone}',
                'error_code': 'UNSUPPORTED_ZONE',
                'error_text': 'Поддерживается только .ru',
                'price': None,
                'renew_price': None,
                'currency': 'RUR',
                'is_premium': False,
            }

        # Beget: hostname (без зоны), zone_id (ru=1), period (годы)
        input_data = {
            'hostname': hostname,
            'zone_id': ZONE_ID_RU,
            'period': period,
        }
        logger.debug("Beget checkDomainToRegister input_data=%s", input_data)
        try:
            data = self._request('domain', 'checkDomainToRegister', input_data)
        except BegetAPIError as e:
            return {
                'domain': domain,
                'available': False,
                'result': e.error_text,
                'error_code': e.error_code,
                'error_text': e.error_text,
                'price': None,
                'renew_price': None,
                'currency': 'RUR',
                'is_premium': False,
            }

        # Beget возвращает: {"status":"success","answer":{"status":"success","result":{...}}}
        if isinstance(data, dict) and 'answer' in data and isinstance(data['answer'], dict):
            ans = data['answer']
            if 'result' in ans and isinstance(ans['result'], dict):
                data = ans['result']
            else:
                data = ans

        may_be_registered = bool(data.get('may_be_registered'))
        pay_type = data.get('pay_type')
        in_system = bool(data.get('in_system'))
        # available = домен свободен (по WHOIS) и не занят в нашем аккаунте Beget
        # pay_type/balance отдельно — можно ли оплатить с этого аккаунта
        available = may_be_registered and not in_system
        can_purchase = available and pay_type in ('money', 'bonus_domain')

        price = data.get('price')
        if price is not None:
            try:
                price = float(price)
            except (TypeError, ValueError):
                price = None

        renew_price = None  # цену продления не запрашиваем (только домен)

        return {
            'domain': domain,
            'available': available,
            'can_purchase': can_purchase,
            'result': 'Available' if available else (data.get('result') or 'Domain not available'),
            'error_code': None if available else 'DOMAIN_NOT_AVAILABLE',
            'error_text': None if available else ('' if may_be_registered else 'Domain already exists'),
            'price': price,
            'renew_price': renew_price,
            'currency': 'RUR',
            'is_premium': False,
            'balance': data.get('balance'),
            'pay_type': pay_type,
        }
