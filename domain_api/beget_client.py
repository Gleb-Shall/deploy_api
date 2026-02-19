"""
Клиент для работы с Beget API (домены).
Документация: https://beget.com/ru/kb/api/funkczii-dlya-raboty-s-domenami
"""
import logging
import socket
import time
import requests
import json
from typing import Dict, Optional, Any

from config import (
    BEGET_LOGIN,
    BEGET_PASSWORD,
    BEGET_API_BASE,
    DNS_PROPAGATION_TIMEOUT,
    DNS_PROPAGATION_INTERVAL,
    DNS_APEX_TTL,
)

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

    def purchase_domain(
        self,
        domain: str,
        period: int = 1,
        set_dns_ip: Optional[str] = None,
        **kwargs
    ) -> Dict:
        """
        Регистрирует домен через Beget API addVirtual.
        addVirtual = «добавить домен»: при добавлении свободного домена Beget
        регистрирует его и списывает оплату с баланса. Контакты берутся из аккаунта.

        Args:
            domain: Полное имя домена (например, example.ru).
            period: Не передаётся в addVirtual (Beget регистрирует на 1 год).
            set_dns_ip: Если задан — после покупки выставить A-запись корня домена на этот IP.

        Returns:
            domain: имя домена
            service_id: ID домена в системе Beget (число).
            result: 'success'
            dns_set: True, если A-запись успешно установлена; False при ошибке или без set_dns_ip.
            dns_error: сообщение об ошибке DNS (если set_dns_ip был задан и произошла ошибка).
        """
        hostname, zone = self._domain_to_hostname_zone(domain)
        if zone != 'ru':
            raise BegetAPIError('UNSUPPORTED_ZONE', 'Поддерживается только .ru')

        raw = self._request('domain', 'addVirtual', {
            'hostname': hostname,
            'zone_id': ZONE_ID_RU,
        })

        # addVirtual возвращает ID домена в Beget (тот же id, что в domain/getList).
        # Используется для delete, getSubdomainList и в панели Beget. Формат: число или обёртка.
        def _to_id(v):
            if v is None:
                return None
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return int(v)
            if isinstance(v, str) and v.isdigit():
                return int(v)
            return v

        service_id = None
        if isinstance(raw, (int, float)):
            service_id = int(raw)
        elif isinstance(raw, str) and raw.isdigit():
            service_id = int(raw)
        elif isinstance(raw, dict):
            service_id = raw.get('id') or raw.get('domain_id')
            if service_id is None and 'answer' in raw:
                ans = raw['answer']
                if isinstance(ans, (int, float, str)):
                    service_id = _to_id(ans)
                elif isinstance(ans, dict):
                    service_id = ans.get('id') or ans.get('domain_id') or ans.get('result')
            service_id = _to_id(service_id)

        dns_set = False
        dns_error = None
        dns_propagated = False
        if set_dns_ip and isinstance(set_dns_ip, str) and set_dns_ip.strip():
            ip = set_dns_ip.strip()
            try:
                self.add_apex_a_record(domain, ip, ttl=DNS_APEX_TTL)
                dns_set = True
                dns_propagated = self.wait_for_dns(domain, ip)
                if not dns_propagated:
                    dns_error = 'Запись установлена, но за таймаут не применилась (проверьте позже)'
            except BegetAPIError as e:
                dns_error = f"{e.error_code}: {e.error_text}"
                logger.warning("Не удалось установить DNS после покупки %s: %s", domain, dns_error)

        return {
            'domain': domain,
            'service_id': service_id,
            'result': 'success',
            'dns_set': dns_set,
            'dns_propagated': dns_propagated,
            'dns_error': dns_error,
        }

    # --- DNS (после покупки домена можно выставить A-запись на свой сервер) ---

    def get_dns_data(self, fqdn: str) -> Any:
        """
        Возвращает текущие DNS-записи домена (Beget dns/getData).
        fqdn: полное имя домена, например example.ru.
        """
        raw = self._request('dns', 'getData', {'fqdn': fqdn})
        if isinstance(raw, dict) and 'answer' in raw:
            raw = raw.get('answer', raw)
        if isinstance(raw, dict) and 'result' in raw:
            raw = raw.get('result', raw)
        return raw

    def change_dns_records(self, fqdn: str, records: Dict[str, Any]) -> Any:
        """
        Обновляет DNS-записи домена (Beget dns/changeRecords).
        records: словарь типа записей, например {"A": [{"priority": 10, "value": "1.2.3.4"}]}.
        """
        return self._request('dns', 'changeRecords', {'fqdn': fqdn, 'records': records})

    def add_apex_a_record(self, domain: str, ip: str, ttl: Optional[int] = None) -> None:
        """
        Добавляет A-запись для корня домена (apex), указывающую на ip.
        ttl: опционально, в секундах (малый TTL — быстрее применение; если Beget не поддерживает — игнорируется).
        """
        fqdn = domain.lower().strip()
        data = self.get_dns_data(fqdn)
        if not isinstance(data, dict):
            raise BegetAPIError('INVALID_RESPONSE', f'getData вернул не объект: {type(data)}')
        records = dict(data)
        a_list = list(records.get('A') or [])
        if not isinstance(a_list, list):
            a_list = []
        a_list = [r for r in a_list if isinstance(r, dict) and r.get('value') != ip]
        rec = {'priority': 10, 'value': ip}
        if ttl is not None:
            rec['ttl'] = ttl
        a_list.append(rec)
        records['A'] = a_list[:10]
        self.change_dns_records(fqdn, records)
        logger.info("DNS A-запись для %s установлена на %s (ttl=%s)", fqdn, ip, ttl)

    def wait_for_dns(
        self,
        domain: str,
        expected_ip: str,
        timeout_sec: int = DNS_PROPAGATION_TIMEOUT,
        interval_sec: int = DNS_PROPAGATION_INTERVAL,
    ) -> bool:
        """
        Ожидает, пока домен начнёт резолвиться в expected_ip (проверка через системный резолвер).
        Возвращает True, если запись применилась до таймаута, иначе False.
        """
        fqdn = domain.lower().strip()
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                # Резолвим A-записи (AF_INET)
                addrs = socket.getaddrinfo(fqdn, None, socket.AF_INET)
                for _fam, _typ, _proto, _canon, sockaddr in addrs:
                    resolved_ip = sockaddr[0] if sockaddr else None
                    if resolved_ip == expected_ip:
                        logger.info("DNS для %s применился: %s", fqdn, expected_ip)
                        return True
            except (socket.gaierror, OSError) as e:
                logger.debug("DNS resolve %s: %s", fqdn, e)
            time.sleep(interval_sec)
        logger.warning("Таймаут ожидания DNS для %s (ожидали %s)", fqdn, expected_ip)
        return False
