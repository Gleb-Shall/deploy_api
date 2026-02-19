# Быстрый старт Domain API

## 1. Деплой на сервер

```bash
# Из корня проекта
./local_develope/deploy_domain_api.sh
```

## 2. Настройка переменных

**Перед деплоем** создайте и заполните `.env` файл локально:

```bash
cd domain_api
cp .env.example .env
nano .env
```

**Минимальная конфигурация (обязательно):**
```bash
BEGET_LOGIN=ваш_логин          # Логин от панели Beget
BEGET_PASSWORD=пароль_для_api  # Пароль API (в панели настраивается отдельно)
```

**Рекомендуемая конфигурация:**
```bash
BEGET_LOGIN=ваш_логин
BEGET_PASSWORD=ваш_пароль_api

# API_KEY - секретный ключ для защиты API (см. README.md раздел "API_KEY")
# Сгенерируйте: openssl rand -hex 32
API_KEY=ваш_случайный_ключ_64_символа

# Максимальная цена домена (по умолчанию 200)
MAX_DOMAIN_PRICE=200

# Режим дебага (True блокирует покупку)
API_DEBUG=False
```

**Важно:** `.env` файл автоматически отправляется на сервер при деплое, но **НЕ коммитится** в git.

## 3. Запуск

```bash
sudo systemctl start domain-api
sudo systemctl enable domain-api  # автозапуск
```

## 4. Проверка

```bash
# Статус
sudo systemctl status domain-api

# Health check
curl http://127.0.0.1:5000/health

# Проверка домена
curl -X POST http://127.0.0.1:5000/api/domain/check \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ваш_ключ" \
  -d '{"domain": "example.ru"}'
```

## Готово! ✅

API работает на `127.0.0.1:5000` и доступен только локально.

Подробнее: [SETUP.md](SETUP.md) | [README.md](README.md)
