# Deploy API — Архитектурная кодекарта

**Дата обновления:** 2026-03-09

**Точки входа:**
- `server/scripts/setup_fresh_server.sh` — первичная настройка сервера
- `server/scripts/git_wrap.sh` — SSH forced command для git push
- `server/scripts/deploy_worker.sh` — демон очереди Redis
- `domain_api/api.py` — Flask API для проверки доменов (порт 5000)
- `screenshot_api/api.py` — Flask API для скриншотов (порт 5051)
- `tools/deploy_to_server.sh` — обновление скриптов на сервере

---

## Архитектурная диаграмма

```
                    LOCAL DEVELOPMENT
                            |
                    git push origin main
                            |
        ================================
        |                              |
    SSH TUNNEL                   SERVER SIDE
        |                              |
     .ssh/key                  git_wrap.sh (forced command)
        |                              |
        |                    Creates/updates bare-repo
        |                              |
        |                    Triggers post-receive hook
        |                              |
        |                   [Redis Queue: deploy_queue]
        |                              |
        |                    deploy_worker.sh (daemon)
        |                              |
        |                    deploy_single.sh (for each site)
        |                         |      |
        |                      npm      Docker
        |                     build     build
        |                         |      |
        |                    [Docker Container]
        |                              |
        +----> Nginx Reverse Proxy <---+
               (SSL + proxying)
                     |
              https://DOMAIN/HASH
              or
              https://CUSTOM_DOMAIN
```

---

## Ключевые модули

### 1. Развертывание и инициализация

| Модуль | Назначение | Экспорты | Зависимости |
|--------|-----------|----------|------------|
| `server/scripts/setup_fresh_server.sh` | Первичная настройка сервера (Docker, Redis, Nginx, Git) | Структура папок `/opt/deploy_api/`, `/var/git/sites/`, `/opt/deploy/` | Ubuntu, Docker, Redis, Nginx, Git |
| `server/scripts/git_wrap.sh` | SSH forced command — обработка push и создание bare-репо | Новое bare-репо в `/var/git/sites/` | bash, git, openssl (для генерации хеша) |
| `server/scripts/post-receive.template` | Git hook — добавление задачи в очередь Redis | Redis queue: `deploy_queue` | Redis CLI |
| `tools/deploy_to_server.sh` | Копирование скриптов и конфигов на сервер | Обновленные файлы в `/opt/deploy_api/` | scp, systemctl |

### 2. Основной workflow: деплой сайта

| Модуль | Назначение | Экспорты | Зависимости |
|--------|-----------|----------|------------|
| `server/scripts/deploy_worker.sh` | Демон для обработки очереди Redis (max 2 одновременно) | Запуск `deploy_single.sh`, контроль параллелизма | Redis, bash, systemctl |
| `server/scripts/deploy_single.sh` | Деплой одного сайта (git clone, npm build, Docker, Nginx) | Docker контейнер, Nginx конфиг, работающий сайт | git, npm/pnpm, Docker, openssl (SSL), Nginx |
| `server/scripts/seo_submit_google.py` | Отправка сайта в Google Search Console | Добавление в GSC, верификация, sitemap | Python, Google API client, OAuth токен |
| `server/scripts/seo_submit_yandex.py` | Отправка в Яндекс Индекс (IndexNow) | Уведомление поисковика | Python, requests |

### 3. Управление инфраструктурой

| Модуль | Назначение | Экспорты | Зависимости |
|--------|-----------|----------|------------|
| `server/scripts/remove_site.sh` | Удаление сайта (Docker, Nginx, Git репо, файлы) | Очистка всех артефактов | docker, systemctl, rm |
| `server/scripts/install_deploy_workers.sh` | Установка systemd сервисов для воркеров | Systemd units: `deploy-worker*.service` | systemctl, sed |
| `server/scripts/install_api_services.sh` | Установка systemd сервисов для API | Systemd units: `domain-api.service`, `screenshot-api.service` | systemctl, sed |
| `server/scripts/docker_pull_images.sh` | Предварительная загрузка Docker образов | Образы в локальном Docker | docker pull |

### 4. Микросервис: Domain API (проверка доменов)

| Модуль | Назначение | Экспорты | Зависимости |
|--------|-----------|----------|------------|
| `domain_api/api.py` | Flask приложение на порту 5000 | HTTP endpoints для проверки доменов | Flask, Python 3.8+ |
| `domain_api/beget_client.py` | Клиент для Beget API | Функции check_domain(), get_balance() | requests, .env (BEGET_LOGIN, BEGET_PASSWORD) |
| `domain_api/config.py` | Конфигурация из .env | BEGET_LOGIN, BEGET_PASSWORD, API_KEY, MAX_DOMAIN_PRICE, MEDIA_STORAGE_DIR | python-dotenv |

**Endpoints:**
- `POST /api/domain/check` — проверка доступности и цены домена
- `POST /api/media/upload` — загрузка медиа файлов (картинки, и т.д.)
- `GET /media/picture/{id}` — получение загруженного файла

### 5. Микросервис: Screenshot API (скриншоты)

| Модуль | Назначение | Экспорты | Зависимости |
|--------|-----------|----------|------------|
| `screenshot_api/api.py` | Flask приложение на порту 5051 | HTTP endpoints для скриншотов | Flask, Playwright, Python 3.8+ |

**Endpoints:**
- `POST /api/screenshots` — загрузка скриншота
- `GET /screenshot/{id}` — получение скриншота

### 6. Инфраструктура: Nginx и конфигурация

| Модуль | Назначение | Экспорты | Зависимости |
|--------|-----------|----------|------------|
| `server/nginx/deploy_main` | Основной конфиг Nginx (reverse proxy, SSL) | Конфиг в `/etc/nginx/sites-available/` | Nginx, certbot (Let's Encrypt) |
| `server/nginx/antibot.conf` | Anti-scraping и anti-DDoS конфигурация | Включается в deploy_main | Nginx rate limiting |
| `server/systemd/deploy-worker.service` | Systemd unit для deploy_worker.sh | Сервис с автозапуском | systemd |
| `server/systemd/domain-api.service` | Systemd unit для Domain API | Сервис с автозапуском | systemd, Python venv |
| `server/systemd/screenshot-api.service` | Systemd unit для Screenshot API | Сервис с автозапуском | systemd, Python venv |

---

## Поток данных

### Деплой сайта (git push → live)

```
1. Локальный компьютер: git push origin main
                              |
                              v
2. SSH соединение с СЕРВЕР:git@... (порт 22)
   ↓ Forced command выполняет:
3. server/scripts/git_wrap.sh
   - Создает bare-репо /var/git/sites/HASH.git
   - Устанавливает post-receive hook
   - Выполняет git-receive-pack
                              |
                              v
4. server/scripts/post-receive.template запускается автоматически
   - Читает последний коммит
   - Добавляет задачу в Redis: LPUSH deploy_queue HASH
                              |
                              v
5. server/scripts/deploy_worker.sh (daemon, слушает Redis)
   - BLPOP deploy_queue (блокирует до появления задачи)
   - Запускает deploy_single.sh HASH
                              |
                              v
6. server/scripts/deploy_single.sh HASH
   - git clone /var/git/sites/HASH.git /opt/deploy/HASH
   - cd /opt/deploy/HASH && npm install && npm run build
   - Проверяет файл 'domain' (если есть → кастомный домен)
   - Создает Dockerfile (на основе /dist/)
   - docker build -t site-HASH .
   - docker run -d site-HASH (слушает на PORT)
   - Генерирует Nginx конфиг
   - Запрашивает SSL сертификат (certbot)
   - Проверяет файл domain и отправляет в Google Search Console (опционально)
                              |
                              v
7. Nginx перенаправляет трафик
   https://DOMAIN/HASH → localhost:CONTAINER_PORT (Docker)
   или
   https://CUSTOM_DOMAIN → localhost:CONTAINER_PORT
                              |
                              v
8. Сайт LIVE! Доступен для пользователей
```

### API: проверка домена

```
Клиент → POST /api/domain/check
         (X-API-Key заголовок)
            |
            v
domain_api/api.py
  - Валидирует заголовок X-API-Key
  - Парсит JSON: {"domain": "example.ru", "period": 1}
  - Вызывает beget_client.check_domain()
            |
            v
domain_api/beget_client.py
  - HTTP запрос к Beget API
  - Парсит ответ
  - Возвращает: available, can_purchase, price, balance
            |
            v
domain_api/api.py
  - Форматирует ответ JSON
  - Возвращает клиенту
```

---

## Пути и структура на сервере

```
/
├── opt/
│   ├── deploy_api/
│   │   ├── scripts/          ← скрипты из server/scripts/
│   │   ├── domain_api/       ← из domain_api/
│   │   ├── screenshot_api/   ← из screenshot_api/
│   │   └── nginx/            ← конфиги из server/nginx/
│   │
│   └── deploy/
│       ├── HASH/             ← работающее дерево сайта
│       │   ├── dist/         ← собранные файлы Astro
│       │   ├── Dockerfile    ← сгенерирован из deploy_single.sh
│       │   └── docker.log
│       │
│       ├── media/            ← загруженные медиа файлы
│       │   └── picture_ID.ext
│       │
│       └── screenshots/      ← скриншоты
│           └── screenshot_ID.png
│
├── var/
│   └── git/
│       └── sites/
│           └── HASH.git/     ← bare-репо для каждого сайта
│
├── etc/
│   ├── nginx/
│   │   └── sites-available/  ← конфиги для каждого домена
│   │
│   └── letsencrypt/
│       └── live/
│           └── DOMAIN/       ← SSL сертификаты
│
└── etc/systemd/system/
    ├── deploy-worker.service        ← сервис воркера
    ├── domain-api.service           ← сервис Domain API
    └── screenshot-api.service       ← сервис Screenshot API
```

---

## Внешние зависимости

| Компонент | Версия | Назначение |
|-----------|--------|-----------|
| **Docker** | 20.10+ | Контейнеризация Astro сайтов |
| **Redis** | 6.0+ | Очередь деплоев (deploy_queue) |
| **Nginx** | 1.18+ | Reverse proxy, SSL termination |
| **Git** | 2.25+ | Версионирование, bare-репозитории |
| **certbot** | 1.0+ | Получение SSL сертификатов (Let's Encrypt) |
| **Python** | 3.8+ | Domain API, Screenshot API |
| **Flask** | 2.0+ | Web framework для микросервисов |
| **Beget API** | - | Проверка доменов (.ru) |
| **Google API** | - | Интеграция с Search Console (опционально) |

---

## Связанные области

- **Frontend:** Astro-сайты (собираются в `/dist/`, затем в Docker)
- **Database:** None (state в файловой системе и Redis)
- **External APIs:** Beget (доменные проверки), Google Search Console (SEO), Яндекс Индекс (SEO)
- **Операционная система:** Linux (Ubuntu 20.04+)

---

## Локальная разработка

**Скрипты из `tools/`:**
- `deploy_to_server.sh` — синхронизация скриптов на сервер
- `deploy_domain_api.sh` — деплой Domain API
- `deploy_screenshot_api.sh` — деплой Screenshot API
- `deploy_apis_to_server.sh` — одновременный деплой обоих API
- `add_git_key.sh` — добавление SSH ключа
- `parse_json_to_folder.py` — создание проектов из JSON
- `stress_deploy.sh` — тестирование нагрузки

**Важные команды:**

```bash
# Просмотр статуса воркера
systemctl status deploy-worker

# Просмотр логов воркера
journalctl -u deploy-worker -f

# Проверка Redis очереди
redis-cli -n 0 LLEN deploy_queue
redis-cli -n 0 LRANGE deploy_queue 0 -1

# Проверка Docker контейнеров
docker ps
docker logs CONTAINER_ID

# Проверка Nginx
sudo nginx -t
sudo systemctl reload nginx
journalctl -u nginx -f
```

---

## Безопасность

1. **SSH:** Forced command в `authorized_keys` ограничивает доступ только к `git_wrap.sh`
2. **API Keys:** Domain API использует `X-API-Key` заголовок (опционально)
3. **SSL:** Автоматическое получение сертификатов через Let's Encrypt
4. **Fail2ban:** Защита от скрейпинга и DDoS (конфиги в `server/fail2ban/`)
5. **Redis:** Только локальное соединение (127.0.0.1:6379)

---

## Масштабирование

- **Несколько воркеров:** `install_deploy_workers.sh` может создать несколько systemd сервисов (deploy-worker-1, deploy-worker-2, и т.д.)
- **Балансировка:** Redis очередь обеспечивает справедливое распределение задач
- **Максимум параллельных деплоев:** Настраивается в код (по умолчанию 2)

---

## Версионирование

- **Git-based:** Каждый сайт имеет собственное bare-репо в `/var/git/sites/HASH.git`
- **История:** Все коммиты хранятся в Git
- **Откат:** Можно откатиться на предыдущий коммит через `git reset` + новый push
- **Снимки:** Docker образы сохраняют версию каждого деплоя

---

## Связанная документация

- `/server/docs/PATHS.md` — детальное описание всех путей на сервере
- `/server/docs/DEPLOY_FLOW.md` — пошаговое описание потока деплоя
- `/domain_api/README.md` — документация Domain API
- `/screenshot_api/README.md` — документация Screenshot API
- `/docs/` — архитектурные диаграммы (PlantUML)
- `/README.md` — основная документация проекта
