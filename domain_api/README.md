# Domain API (Beget)

API для проверки доступности и покупки доменов через Beget. Реальная цена домена (включая премиум) доступна без партнёрства. Оплата — с баланса аккаунта Beget.

## Не мешает другим частям проекта

- Вся логика в папке `domain_api/`
- Свой `.env`, свой порт `127.0.0.1:5000`
- Скрипты деплоя сайтов не используют domain_api

## Структура

```
domain_api/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── config.py
├── beget_client.py
├── api.py
└── nginx.conf.example   # опционально
```

## Данные для работы с Beget

В `.env` нужны:

| Переменная      | Описание |
|-----------------|----------|
| **BEGET_LOGIN** | Логин от панели Beget (cp.beget.com) |
| **BEGET_PASSWORD** | Пароль для API (отдельно от пароля входа) |

**Пароль API:** в панели Beget в настройках создаётся отдельный пароль для API. Документация: https://beget.com/ru/kb/api/obshhij-princzip-raboty-s-api

**Особенности:**
- Проверка домена возвращает реальную цену (включая премиум)
- Покупка списывает средства с баланса; контакты берутся из аккаунта
- DNS по API: https://beget.com/ru/kb/api/funkczii-upravleniya-dns (A, MX, TXT, CNAME — подходит для SSL)

## Установка

```bash
cd domain_api
cp .env.example .env
# заполните BEGET_LOGIN и BEGET_PASSWORD
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Деплой на сервер: из корня проекта `./local_develope/deploy_domain_api.sh`

**После деплоя** создайте `.env` на сервере:
```bash
sudo cp /opt/deploy_api/domain_api/.env.example /opt/deploy_api/domain_api/.env
sudo nano /opt/deploy_api/domain_api/.env  # заполните BEGET_LOGIN и BEGET_PASSWORD
sudo chmod 600 /opt/deploy_api/domain_api/.env
```

## Конфигурация .env

- **BEGET_LOGIN**, **BEGET_PASSWORD** — обязательно
- **API_KEY** — рекомендуется (защита endpoints)
- **MAX_DOMAIN_PRICE** — макс. цена покупки в рублях (по умолчанию 200)
- **API_DEBUG=True** — блокирует покупку доменов

## API

- **POST /api/domain/check** — проверка домена. Тело: `{"domain": "example.ru", "period": 1}`. Возвращает доступность и цену.
- **POST /api/domain/purchase** — покупка. Тело: `{"domain": "example.ru", "period": 1}`. Оплата с баланса Beget.

Заголовок `X-API-Key` или параметр `api_key` — если в .env задан API_KEY.

## Безопасность

По умолчанию API слушает только `127.0.0.1:5000`. Для доступа извне используйте Nginx reverse proxy (см. nginx.conf.example) и обязательно задайте API_KEY.

## Запуск

```bash
python api.py
```

На сервере: `sudo systemctl start domain-api`, логи: `journalctl -u domain-api -f`.
