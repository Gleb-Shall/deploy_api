# Настройка Domain API на сервере

## Быстрая установка

### 1. Деплой на сервер

Из корня проекта:
```bash
./local_develope/deploy_domain_api.sh
```

Скрипт автоматически:
- Копирует файлы на сервер в `/opt/deploy_api/domain_api/`
- Копирует `.env.example` как шаблон
- Создаёт виртуальное окружение Python
- Устанавливает зависимости
- Создаёт systemd service

### 2. Настройка переменных окружения

**После деплоя** создайте `.env` файл на сервере:

```bash
sudo cp /opt/deploy_api/domain_api/.env.example /opt/deploy_api/domain_api/.env
sudo nano /opt/deploy_api/domain_api/.env
sudo chmod 600 /opt/deploy_api/domain_api/.env
```

**Обязательные переменные:**
```bash
BEGET_LOGIN=your_login       # Логин от панели Beget
BEGET_PASSWORD=your_api_pwd  # Пароль для API (настраивается в панели отдельно)
```

**Пароль API Beget:** панель https://cp.beget.com → настройки → пароль для API. Документация: https://beget.com/ru/kb/api/obshhij-princzip-raboty-s-api

**Рекомендуемые переменные:**
```bash
# API_KEY - секретный ключ для защиты API
# Сгенерируйте: openssl rand -hex 32
API_KEY=your_strong_random_api_key_here

# Максимальная цена домена (по умолчанию 200)
MAX_DOMAIN_PRICE=200

# Режим дебага (True блокирует покупку доменов)
API_DEBUG=False
```

**Безопасность:**
- `API_HOST=127.0.0.1` - API доступен только локально (не меняйте!)
- `API_PORT=5000` - порт (можно изменить при необходимости)
- `.env` файл **НЕ передаётся** через скрипт деплоя, создаётся вручную на сервере

### 3. Запуск сервиса

```bash
# Запустить
sudo systemctl start domain-api

# Включить автозапуск
sudo systemctl enable domain-api

# Проверить статус
sudo systemctl status domain-api

# Просмотр логов
sudo journalctl -u domain-api -f
# или
tail -f /var/log/deploy/domain-api.log
```

### 4. Проверка работы

```bash
# Health check
curl http://127.0.0.1:5000/health

# Проверка домена (нужен API_KEY если установлен)
curl -X POST http://127.0.0.1:5000/api/domain/check \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{"domain": "example.ru"}'
```

### Nginx (опционально)

**Nginx не обязателен** для работы API. Сервис слушает только `127.0.0.1:5000` — проверки с самого сервера (`curl http://127.0.0.1:5000/...`) работают без nginx.

Nginx нужен, только если вы хотите открыть API наружу по домену с HTTPS (reverse proxy). Тогда:

1. Скопируйте `nginx.conf.example` в `/etc/nginx/sites-available/domain_api`.
2. Замените `api.yourdomain.com` на ваш домен, настройте SSL (certbot).
3. Включите конфиг: `sudo ln -s /etc/nginx/sites-available/domain_api /etc/nginx/sites-enabled/` и `sudo nginx -t && sudo systemctl reload nginx`.

## Структура на сервере

```
/opt/deploy_api/
└── domain_api/
    ├── api.py              # Основной файл API
    ├── beget_client.py     # Клиент Beget
    ├── config.py           # Конфигурация
    ├── requirements.txt    # Зависимости
    ├── .env                # Переменные окружения (создаётся вручную из .env.example)
    ├── .env.example        # Пример конфигурации
    └── venv/               # Виртуальное окружение Python

/etc/systemd/system/
└── domain-api.service      # Systemd service

/var/log/deploy/
└── domain-api.log          # Логи API
```

## Обновление

Для обновления кода:
```bash
./local_develope/deploy_domain_api.sh
sudo systemctl restart domain-api
```

## Удаление

```bash
# Остановить и удалить сервис
sudo systemctl stop domain-api
sudo systemctl disable domain-api
sudo rm /etc/systemd/system/domain-api.service
sudo systemctl daemon-reload

# Удалить файлы (опционально)
sudo rm -rf /opt/deploy_api/domain_api
```

## Troubleshooting

### Сервис не запускается

```bash
# Проверьте логи
sudo journalctl -u domain-api -n 50

# Проверьте .env файл
sudo cat /opt/deploy_api/domain_api/.env

# Проверьте Python
/opt/deploy_api/domain_api/venv/bin/python --version

# Проверьте зависимости
/opt/deploy_api/domain_api/venv/bin/pip list
```

### API не отвечает

```bash
# Проверьте, что сервис запущен
sudo systemctl status domain-api

# Проверьте порт
sudo netstat -tlnp | grep 5000
# Должно быть: tcp 0 0 127.0.0.1:5000

# Проверьте доступность локально
curl http://127.0.0.1:5000/health
```

### Ошибки Beget API

```bash
# Проверьте credentials в .env
sudo grep BEGET_ /opt/deploy_api/domain_api/.env

# Логи
sudo journalctl -u domain-api -f
```
