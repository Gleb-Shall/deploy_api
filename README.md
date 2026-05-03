# Git Push Deploy — Платформа автоматического деплоя статических Astro-сайтов

Полностью автоматический деплой Astro-сайтов через `git push`. Инфраструктура основана на Git hooks, Redis очереди и Docker. Сайты доступны по адресу `https://automatoria.ru/{hash}/` или по кастомному домену с автоматическим HTTPS.

## Как это работает

```
git push → SSH forced command (git_wrap.sh) → bare-репо → post-receive hook → Redis queue →
deploy worker → Docker build → контейнер → nginx reverse proxy
```

**Особенности:**
- До 2 одновременных деплоев (очередь Redis)
- Автоматический HTTPS через Let's Encrypt
- Кастомные домены через файл `domain` в корне проекта
- Поддержка pnpm, npm, yarn
- Интеграция с Google Search Console и Яндекс Индекс
- Микросервисы: Domain API (домены + защита от скрейпинга), Screenshot API (скриншоты), Media API (файлы от чат-бота: изображения, PDF→PNG, DOCX→TXT), Versioning API (rollback/forward версий сайтов)
- **Многоуровневая защита от парсинга:** CSS обфускация, fingerprinting, canary ссылки, domain lock

## Структура проекта

```
deploy_api/
├── domain_api/                          # Flask API: доменные проверки + защита от парсинга, порт 5000
│   ├── api.py                           # Flask приложение (Beget API, fingerprinting, CSS delivery)
│   ├── canary.py                        # Canary links для детекции кражи HTML
│   ├── fingerprint.py                   # Fingerprint scoring + AES-GCM CSS шифрование
│   ├── beget_client.py                  # Клиент для Beget API
│   ├── config.py                        # Конфигурация
│   ├── requirements.txt                 # Python зависимости
│   ├── .env.example                     # Шаблон окружения (BEGET_LOGIN, BEGET_PASSWORD)
│   ├── README.md                        # Документация Domain API
│   └── QUICKSTART.md                    # Быстрый старт
│
├── screenshot_api/                      # Flask API: скриншоты Playwright, порт 5051
│   ├── api.py                           # Flask приложение
│   ├── requirements.txt                 # Python зависимости
│   ├── .env.example                     # Шаблон окружения
│   └── README.md                        # Документация Screenshot API
│
├── media_api/                           # Flask API: файлы от чат-бота, порт 5052
│   ├── api.py                           # Flask приложение
│   ├── storage.py                       # Хранение файлов на диске
│   ├── processors.py                    # PDF→PNG (pymupdf), DOCX→TXT (python-docx)
│   ├── config.py                        # Конфигурация
│   ├── requirements.txt                 # Python зависимости
│   └── README.md                        # Документация Media API (для чат-бота)
│
├── versioning_api/                      # (в репо survey-server-client) Flask API: rollback/forward версий, порт 5061
│   ├── app.py                           # Flask приложение (rollback, forward, status)
│   ├── rollback.sh                      # Откат сайта на один git-коммит назад
│   ├── forward.sh                       # Перемотка вперёд (отмена rollback)
│   └── rollback_common.sh               # Утилиты: trigger_redeploy, mutex, pointer
│
├── server/                              # Серверная часть (scripts, configs, docs)
│   ├── scripts/                         # Bash/Python скрипты деплоя
│   │   ├── setup_fresh_server.sh        # ⭐ Первичная настройка сервера (один раз)
│   │   ├── git_wrap.sh                  # SSH forced command: создание репо и пост-receive хук
│   │   ├── post-receive.template        # Git hook: checkout + очередь + деплой
│   │   ├── deploy_worker.sh             # Демон очереди Redis (max 2 деплоя одновременно)
│   │   ├── deploy_single.sh             # ⭐ Деплой одного сайта, извлечение CSS bundle
│   │   ├── obfuscate_css.js             # Node.js скрипт: переименование CSS классов, удаление <style>
│   │   ├── remove_site.sh               # Удаление сайта (-A для удаления всех)
│   │   ├── install_deploy_workers.sh    # Установка systemd сервисов для воркеров
│   │   ├── install_api_services.sh      # Установка systemd сервисов domain_api и screenshot_api
│   │   ├── docker_pull_images.sh        # Предварительная загрузка Docker образов
│   │   ├── seo_submit_google.py         # SEO: добавление сайта в Google Search Console
│   │   ├── seo_submit_yandex.py         # SEO: отправка в Яндекс Индекс (IndexNow)
│   │   ├── get_google_oauth_token.py    # Генерация OAuth токена для Google API
│   │   ├── deploy_history.sh            # История деплоев
│   │   ├── check_deploy_status.sh       # Проверка статуса деплоев
│   │   ├── diagnose_docker.sh           # Диагностика Docker проблем
│   │   └── manage_ports_queue.sh        # Управление портами для контейнеров
│   │
│   │   # ⚠️  rollback.sh, forward.sh, rollback_common.sh — НЕ здесь.
│   │   #     Они живут в репо survey-server-client/server/scripts/ и
│   │   #     деплоятся его CI/CD. deploy_single.sh и deploy_worker.sh
│   │   #     туда НЕ копируются — только rollback/forward скрипты.
│   │
│   ├── nginx/                           # Nginx конфигурация
│   │   ├── deploy_main                  # Основной конфиг nginx (reverse proxy, SSL)
│   │   └── antibot.conf                 # Anti-scraping и anti-DDoS конфигурация
│   │
│   ├── fail2ban/                        # Fail2ban конфигурация
│   │   └── *.conf                       # Фильтры от скрейпинга и атак
│   │
│   ├── systemd/                         # Systemd unit файлы
│   │   ├── deploy-worker.service        # Сервис для deploy_worker.sh
│   │   ├── domain-api.service           # Сервис для Domain API
│   │   └── screenshot-api.service       # Сервис для Screenshot API
│   │
│   └── docs/                            # Техническая документация
│       ├── PATHS.md                     # Описание путей на сервере
│       ├── DEPLOY_FLOW.md               # Детальное описание потока деплоя
│       └── README.md                    # Индекс документации
│
├── tools/                               # Локальные скрипты для разработчика
│   ├── deploy_to_server.sh              # ⭐ Обновляет скрипты на сервере (deploy_api, nginx, systemd, fail2ban)
│   ├── deploy_domain_api.sh             # Деплой domain_api на сервер + nginx для media.<DOMAIN>
│   ├── deploy_screenshot_api.sh         # Деплой screenshot_api на сервер
│   ├── deploy_apis_to_server.sh         # Одновременный деплой обоих APIs
│   ├── add_git_key.sh                   # Добавление SSH ключа в authorized_keys на сервере
│   ├── parse_json_to_folder.py          # Парсинг JSON в структуру проекта
│   ├── stress_deploy.sh                 # Тестирование нагрузки (stress test)
│   └── example.json.example             # Шаблон для parse_json_to_folder.py
│
├── docs/                                # Архитектурные диаграммы (PlantUML и Markdown)
│   ├── 1_deployment_pipeline.puml       # Диаграмма потока деплоя
│   ├── 2_component_diagram.puml         # Архитектурная диаграмма компонентов
│   ├── 3_vcs_sequence.puml              # Диаграмма последовательности работы с Git
│   ├── 4_versioning_model.md            # Модель версионирования
│   ├── 5_git_integration.md             # Git интеграция и безопасность
│   ├── 6_infrastructure.md              # Инфраструктурная схема
│   └── README.md                        # Как использовать диаграммы
│
├── .cursor/                             # Cursor IDE конфигурация (правила, агенты, MCP)
├── .git/                                # Git репозиторий
├── .gitignore                           # Игнорируемые файлы
└── README.md                            # Этот файл
```

## Быстрый старт

### Требования

- Linux сервер (Ubuntu 20.04+) с Docker, Redis, Git, Nginx
- SSH доступ как `root`
- Домен (или используйте `automatoria.ru/{hash}/`)
- (опционально) Beget аккаунт для покупки доменов и управления SSL
- (опционально) Google API ключ для SEO (добавление сайтов в Search Console)

### Шаг 1: Первичная настройка сервера (один раз)

На вашем ПК выполните:

```bash
export DEPLOY_SERVER=root@YOUR_SERVER_IP
export DOMAIN=automatoria.ru

# Копируем скрипты в /tmp на сервере
scp -r server/scripts $DEPLOY_SERVER:/tmp/server_scripts

# Запускаем первичную настройку
ssh $DEPLOY_SERVER "bash /tmp/server_scripts/setup_fresh_server.sh"
```

**setup_fresh_server.sh установит:**
- Docker
- Redis для очереди деплоев
- Nginx (базовая конфигурация)
- Git users и структуру папок
- Systemd сервисы для воркеров

После завершения добавьте ваш SSH ключ в `/home/git/.ssh/authorized_keys` на сервере (с forced command):

```bash
cat ~/.ssh/id_rsa.pub | ssh $DEPLOY_SERVER \
  "echo 'command=\"/opt/deploy_api/scripts/git_wrap.sh\" \$(cat)' >> /home/git/.ssh/authorized_keys"
```

Или используйте скрипт:

```bash
./tools/add_git_key.sh
```

### Шаг 2: Разверните скрипты и конфиги

```bash
git push origin main
```

CI/CD автоматически синхронизирует `server/scripts/` → `/opt/deploy_api/scripts/` на сервере и перезапускает API сервисы. Ручного запуска `deploy_to_server.sh` не требуется.

> Для первичной настройки nginx, systemd и fail2ban конфигов по-прежнему можно использовать `./tools/deploy_to_server.sh` (выполняется один раз).

### Шаг 3: Создайте и задеплойте первый сайт

Локально на вашем ПК:

```bash
# Создайте Astro проект или используйте существующий
cd ~/my-astro-site

# Инициализируйте Git
git init
git add .
git commit -m "Initial commit"

# Добавьте remote
git remote add origin git@YOUR_SERVER_IP:sites/mysite.git

# Первый push!
git push -u origin main
```

**Что происходит при push:**

1. SSH запускает `git_wrap.sh` (forced command)
2. `git_wrap.sh` создаёт bare-репо если его ещё нет, устанавливает `post-receive` хук
3. `post-receive` хук добавляет задачу в Redis очередь
4. `deploy_worker.sh` забирает задачу из очереди и запускает `deploy_single.sh`
5. `deploy_single.sh`:
   - Клонирует последний коммит в work tree
   - Выполняет `npm/pnpm install` и `npm run build`
   - Создаёт Docker контейнер для сайта
   - Настраивает nginx для проксирования трафика

**Результат:** Сайт доступен по адресу `https://YOUR_DOMAIN/SITE_HASH/`

### Шаг 4: (опционально) Кастомный домен

Чтобы использовать кастомный домен вместо хеша:

1. В корне вашего проекта создайте файл `domain` с одной строкой:

```
example.com
```

2. Скоммитьте и запушьте:

```bash
echo "example.com" > domain
git add domain
git commit -m "Add custom domain"
git push
```

3. Убедитесь, что A-запись домена указывает на IP вашего сервера:

```bash
dig example.com
# example.com.    300 IN A YOUR_SERVER_IP
```

4. При следующем деплое скрипты автоматически:
   - Получат SSL сертификат через Let's Encrypt
   - Настроят nginx для кастомного домена
   - Отправят сайт в поисковые системы (Google, Яндекс, Bing)

**Обновление скриптов на сервере** (после изменений в вашем локальном репо):

```bash
git push origin main
```

CI/CD автоматически синхронизирует `server/scripts/` → `/opt/deploy_api/scripts/` и перезапустит API сервисы. Ручного запуска `deploy_to_server.sh` не требуется.

## Архитектура системы

### Компоненты

**На сервере:**

| Компонент | Назначение | Расположение |
|-----------|-----------|--------------|
| **Git** | Bare-репозитории для каждого сайта | `/var/git/sites/` |
| **Redis** | Очередь деплоев (max 2 одновременно) | Port 6379 |
| **Docker** | Контейнеры для сайтов (Astro build) | Managed by Docker |
| **Nginx** | Reverse proxy + SSL termination | Port 80, 443 |
| **Deploy Worker** | Демон, обрабатывающий очередь | systemd: `deploy-worker` |

**Пути на сервере:**

| Путь | Содержимое |
|------|-----------|
| `/opt/deploy_api/scripts/` | Bash/Python скрипты деплоя |
| `/opt/deploy_api/domain_api/` | Domain API (Flask, порт 5000) |
| `/opt/deploy_api/screenshot_api/` | Screenshot API (Flask, порт 5051) |
| `/opt/deploy_api/media_api/` | Media API (Flask, порт 5052) |
| `/opt/deploy/` | Worktrees и Docker контейнеры сайтов |
| `/opt/deploy/media/` | Медиа файлы от API |
| `/opt/deploy/screenshots/` | Скриншоты от API |
| `/var/git/sites/` | Bare Git репозитории |

Подробнее: `/server/docs/PATHS.md`, `/server/docs/DEPLOY_FLOW.md`

### Поток деплоя

1. **Push локально:** `git push origin main`
2. **SSH forced command:** `git_wrap.sh` создаёт bare-репо (если его нет) и ставит `post-receive` хук
3. **Git hook запускается:** `post-receive.template` добавляет задачу в Redis очередь (`LPUSH deploy_queue`)
4. **Deploy worker берёт задачу:** `deploy_worker.sh` получает задачу из очереди и запускает `deploy_single.sh`
5. **Сборка сайта:**
   - `deploy_single.sh` клонирует репо в work tree
   - Выполняет `npm/pnpm install && npm run build`
   - Проверяет наличие файла `domain` для кастомного домена
   - Получает SSL сертификат (Let's Encrypt)
6. **Docker контейнер:** Собирается образ с app и запускается контейнер (port слушает)
7. **Nginx:** Настраивается reverse proxy на `https://DOMAIN/HASH/` или `https://CUSTOM_DOMAIN/`
8. **SEO:** Сайт отправляется в поисковые системы (Google, Яндекс, Bing)

### Параллелизм

- **Max 2 деплоя одновременно** (настраивается в Redis очереди)
- При большой очереди остальные задачи ждут свободного worker'а
- Deploy worker'ов можно добавить через systemd (установка в `install_deploy_workers.sh`)

---

## Защита от парсинга и кражи HTML

Система состоит из **4 уровней защиты**:

### Уровень 1: Nginx UA-фильтрация и rate limiting

**Файл:** `/server/nginx/antibot.conf` (подключается глобально)

Блокирует известные парсеры по User-Agent:
- `scrapy, python-requests, python-urllib, libwww-perl, mechanize, curl, nikto`
- Пустой User-Agent
- Все скрейпер-сканнеры

Rate limiting (на каждую страницу отдельно):
- 20 запросов в секунду с одного IP
- Burst: 50 запросов
- Ответ 429 за превышение

**Fail2ban действия:**
- `/_hp_/` (honeypot) → бан на 24 часа
- 10× ответ 429 за минуту → бан на 1 час

### Уровень 2: CSS обфускация

**Файлы:**
- `/server/scripts/obfuscate_css.js` — Node.js скрипт переименования CSS классов
- `/domain_api/api.py` — endpoint `/api/css-bundle` (localhost only)

**Как работает:**
1. `deploy_single.sh` копирует `obfuscate_css.js` из `/opt/deploy_api/scripts/` в work tree перед Docker build
2. Docker запускает `obfuscate_css.js` в builder stage:
   - Переименовывает все CSS классы: `.button` → `._a1b2c3`
   - Удаляет все `<style>` теги из HTML
   - Сохраняет CSS bundle в файл `/css_bundle.txt`
3. `deploy_single.sh` извлекает `css_bundle.txt` из контейнера → хранит в Redis
4. Браузер загружает чистый HTML **без стилей** → выглядит сломанным без fingerprint JS

**Результат:** HTML украсть бесполезно — без CSS выглядит как мусор.

### Уровень 3: Canary ссылки (детекция кражи HTML)

**Файл:** `/domain_api/canary.py` — логирование попыток доступа

**Как работает:**
1. При деплое `deploy_single.sh` генерирует **5 canary-токенов** и сохраняет их в Redis:
   - `canary:page:PAGE_HASH` — JSON массив токенов для страницы
   - `canary:token:TOKEN` — метаданные каждого токена
2. Токены **не встроены в HTML** — `preview-js` скрипт подгружает их из Redis через API и инжектирует скрытые ссылки через JS (невидимо для curl-парсеров)
3. Каждая ссылка уникальна: `GET /r/<token>` логирует referer/IP/UA в Redis:
   ```json
   {"token": "abc123...", "page_hash": "xyz789", "referer": "attacker.com", "ip": "...", "ts": 1699564800}
   ```
4. Ссылка редиректит на Wikipedia → не очевидно для пользователя

**Endpoint:** `GET /r/<token>` (nginx: location ~^/r/([a-zA-Z0-9_-]+)$)

### Уровень 4: Fingerprint-based AES-GCM CSS доставка

**Файлы:**
- `/domain_api/fingerprint.py` — scoring headless сигналов, шифрование AES
- `/domain_api/api.py` — endpoints `/api/preview-js` и `/api/fingerprint-key`

**Как работает:**

1. **Инжекция preview-js:** nginx через `sub_filter` добавляет в каждую HTML страницу:
   ```html
   <script src="/api/preview-js?h=PAGE_HASH"></script>
   ```

2. **Сбор fingerprint (20+ сигналов):**
   ```javascript
   {
     webdriver: navigator.webdriver,           // 5 pts if true
     plugins_count: navigator.plugins.length,   // 2 pts if 0
     pdf_viewer: navigator.pdfViewerEnabled,
     webgl_renderer: "SwiftShader" || "llvmpipe",  // 3 pts (bot indicator)
     canvas_hash: <hash>,                      // 2 pts if blank
     screen_width, screen_height, color_depth,
     timezone, platform, language,
     cpu_cores, memory_gb, touch_points,
     audio_error, session_storage
   }
   ```

3. **Валидация и блокировка:**
   - POST `/api/fingerprint-key` с отправленным fingerprint
   - Server подсчитывает score. Если score >= 5 → **403 Forbidden**
   - **Headless браузеры (Playwright, Puppeteer) немедленно блокируются** (`navigator.webdriver=true`)

4. **Шифрование CSS:**
   - Если валидация пройдена → server шифрует CSS AES-128-GCM
   - Возвращает: `{aes_key, iv, ciphertext}` (все hex-encoded)
   - Browser расшифровывает через Web Crypto API → инжектирует `<style>` в DOM

5. **Domain lock:**
   - `preview-js` проверяет `window.location.hostname`
   - Если не `automatoria.ru` или `preview.automatoria.ru` → редирект на `https://automatoria.ru`
   - **Украденный HTML не откроется на другом домене**

**Endpoints:**
- `GET /api/preview-js?h=PAGE_HASH` — минифицированный JS (публичный)
- `POST /api/fingerprint-key` — валидация, шифрование CSS (публичный из браузера)
- `POST /api/css-bundle` — сохранение bundle в Redis (localhost only)

### Уровень 4b: Screenshot bypass для генератора

**Endpoint:** `POST /api/internal/screenshot-token` (localhost only)

**Проблема:** Генератор скриншотов использует Playwright, который имеет `navigator.webdriver=true` → заблокирован на уровне 4.

**Решение:**
1. Генератор запрашивает одноразовый токен:
   ```bash
   token=$(curl -X POST http://127.0.0.1:5000/api/internal/screenshot-token | jq -r .token)
   ```
2. Токен хранится в Redis с TTL 120 секунд
3. Генератор добавляет заголовок `X-Screenshot-Token: <token>` к запросу `/api/fingerprint-key`
4. Server проверяет токен → пропускает headless проверку
5. Токен **атомарно удаляется** через `getdel` → повторное использование невозможно

**Интеграция в Playwright:**
```python
token = requests.post("http://127.0.0.1:5000/api/internal/screenshot-token").json()["token"]
await page.route("**/api/fingerprint-key", lambda r: r.continue_(
    headers={**r.request.headers, "X-Screenshot-Token": token}
))
```

### Что защищает и что не защищает

**Защищает от:**
- ✅ Автоматических скрейперов (scrapy, requests, curl)
- ✅ Простых headless браузеров (Playwright без stealth-плагина)
- ✅ Кражи и переиспользования HTML на другом домене
- ✅ Парсеров, собирающих DOM структуру

**НЕ защищает от:**
- ❌ Playwright + stealth-плагин (подделывает все fingerprint сигналы)
- ❌ Cloudflare Bot Management (зарезервировано на случай DDoS)
- ❌ Ручного копипаста (требует ввода CAPTCHA)

**Следующий уровень защиты:**
- Cloudflare Bot Management (при необходимости максимальной защиты)

---

## Domain API — Проверка доменов (.ru, Beget) и защита от парсинга

Микросервис для проверки доступности и цены доменов через Beget API. **Опционален** — нужен только если вы хотите проверять домены перед покупкой.

### Настройка

**Локально (разработка):**

```bash
cd domain_api
cp .env.example .env
# Заполните BEGET_LOGIN и BEGET_PASSWORD (получите в панели Beget)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python api.py
```

**На сервере:**

```bash
# Из корня проекта
./tools/deploy_domain_api.sh

# Затем создайте .env на сервере
ssh root@YOUR_SERVER_IP
sudo nano /opt/deploy_api/domain_api/.env
# Заполните BEGET_LOGIN, BEGET_PASSWORD и CHALLENGE_SECRET
sudo chmod 600 /opt/deploy_api/domain_api/.env
```

Обязательные переменные в `.env`:

| Переменная | Описание |
|------------|----------|
| `BEGET_LOGIN` | Логин Beget API |
| `BEGET_PASSWORD` | Пароль Beget API |
| `CHALLENGE_SECRET` | Секрет для `/api/challenge-token`. Без него endpoint возвращает 503. Генерация: `python3 -c "import secrets; print(secrets.token_hex(32))"` |

**Автозапуск (systemd):**

```bash
sudo bash /opt/deploy_api/server/scripts/install_api_services.sh
# Теперь сервис domain-api запускается автоматически при загрузке
systemctl status domain-api
```

### API Endpoints — Beget

**Проверка домена:**

```bash
curl -X POST http://127.0.0.1:5000/api/domain/check \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "domain": "example.ru",
    "period": 1
  }'
```

**Ответ:**

```json
{
  "success": true,
  "data": {
    "domain": "example.ru",
    "available": true,
    "can_purchase": true,
    "price": 299,
    "currency": "RUB",
    "balance": 10000
  }
}
```

### API Endpoints — Anti-Scraping

**GET /api/preview-js?h=PAGE_HASH** — Fingerprint collector + CSS decryptor (публичный)
- Минифицированный JavaScript, инжектируемый nginx через `sub_filter`
- Собирает 20+ сигналов браузера, отправляет POST на `/api/fingerprint-key`
- Включает domain lock (редирект на automatoria.ru)

**POST /api/fingerprint-key** — Валидация fingerprint, шифрование CSS (публичный)
- Request: `{page_hash: "...", fingerprint: {...}}`
- Response (при успехе): `{aes_key: "...", iv: "...", ciphertext: "...", success: true}`
- Ответ 403 если обнаружен headless браузер (webdriver=true)
- Требует валидный CSS bundle в Redis (установлен при деплое)

**POST /api/css-bundle** — Сохранение CSS bundle в Redis (localhost only, использует API Key)
- Вызывается `deploy_single.sh` после Docker build
- Request: `{page_hash: "...", css_data: "..."}`
- CSS хранится 30 дней

**GET /r/<token>** — Canary redirect (публичный)
- Логирует referrer → выявляет украденный HTML
- Редиректит на Wikipedia (CANARY_REDIRECT_URL)

**GET /api/challenge** — Получить challenge для proof-of-work (публичный)
- Response: `{challenge: "...", difficulty: N}`

**POST /api/challenge-token** — Проверить решение challenge, получить access token (публичный)
- Request: `{challenge: "...", solution: "..."}`
- Response: `{token: "...", ttl: N}`
- Требует `CHALLENGE_SECRET` в `.env` — без него возвращает 503

**POST /api/internal/screenshot-token** — Одноразовый bypass для скриншотов (localhost only)
- Response: `{token: "...", ttl: 120}`
- Используется генератором скриншотов Playwright
- Токен сжигается при первом использовании

### Доступ с другого сервера

Domain API слушает только `127.0.0.1:5000` (не открыт в интернет). Для доступа с другой машины используйте **SSH туннель:**

```bash
# На машине, которая будет дергать API
ssh -i ~/.ssh/key -N -L 5000:127.0.0.1:5000 root@YOUR_SERVER_IP

# Теперь на локальной машине можно обращаться к http://127.0.0.1:5000
```

Или оформите как systemd сервис (см. `domain_api/README.md`).

**Подробнее:** `domain_api/README.md`

---

## Screenshot API — Скриншоты Playwright

Микросервис для загрузки и хранения скриншотов. Используется генератором для сохранения скриншотов страниц.

### Настройка

```bash
cd screenshot_api
pip install -r requirements.txt
python api.py
```

На сервере используйте `./tools/deploy_screenshot_api.sh` и установите systemd сервис через `install_api_services.sh`.

### API Endpoints

**Загрузка скриншота:**

```bash
curl -X POST http://127.0.0.1:5051/api/screenshots \
  -H "X-API-Key: YOUR_API_KEY" \
  -F "file=@screenshot.png"
```

**Получение скриншота:**

```bash
curl -X GET http://127.0.0.1:5051/screenshot/SCREENSHOT_ID
```

**Подробнее:** `screenshot_api/README.md`

---

## Media API — файлы от чат-бота

Отдельный микросервис на порту 5052. Поддерживает изображения, PDF (→ PNG по страницам) и DOCX (→ TXT).

**Загрузка:**

```bash
curl -X POST https://media.automatoria.ru/api/media/upload \
  -H "X-API-Key: YOUR_API_KEY" \
  -F "file=@image.jpg"       # или document.pdf / contract.docx
```

**Просмотр:**

```
https://media.automatoria.ru/file/{id}
```

**Подробнее:** `media_api/README.md`

---

## Управление сайтами

### Просмотр деплоев

```bash
ssh root@YOUR_SERVER_IP
bash /opt/deploy_api/server/scripts/deploy_history.sh
```

### Проверка статуса

```bash
bash /opt/deploy_api/server/scripts/check_deploy_status.sh
bash /opt/deploy_api/server/scripts/check_sites_disk.sh
```

### Удаление сайта

```bash
# Удалить конкретный сайт по хешу
sudo /opt/deploy_api/server/scripts/remove_site.sh PAGE_HASH

# Удалить все сайты
sudo /opt/deploy_api/server/scripts/remove_site.sh -A
```

---

## Разработка

### Локальное тестирование

Для локального тестирования используйте инструменты в `tools/`:

```bash
# Парсинг JSON в структуру проекта
python3 tools/parse_json_to_folder.py

# Stress-тест деплоев
bash tools/stress_deploy.sh

# Добавление SSH ключа на сервер
bash tools/add_git_key.sh
```

### Диагностика проблем

На сервере есть полезные диагностические скрипты:

```bash
# Проверка Docker
bash /opt/deploy_api/server/scripts/diagnose_docker.sh

# Проверка очереди Redis
redis-cli -n 0 LLEN deploy_queue
redis-cli -n 0 LRANGE deploy_queue 0 -1
```

### Документация

- **Архитектурные диаграммы:** `/docs/` (PlantUML и Markdown)
- **Техническая документация:** `/server/docs/`
- **API документация:** `domain_api/README.md`, `screenshot_api/README.md`

Для просмотра PlantUML диаграмм используйте онлайн редактор: http://www.plantuml.com/plantuml/uml/

---

## Troubleshooting

### Деплой зависает или не запускается

```bash
# Проверьте очередь Redis
redis-cli -n 0 LLEN deploy_queue

# Проверьте статус worker'а
systemctl status deploy-worker
journalctl -u deploy-worker -f
```

### Docker ошибки

```bash
# Диагностика Docker
bash /opt/deploy_api/server/scripts/diagnose_docker.sh

# Пред загрузка образов
bash /opt/deploy_api/server/scripts/docker_pull_images.sh
```

### Nginx не проксирует трафик

```bash
# Проверьте конфиг nginx
sudo nginx -t

# Перезагрузите nginx
sudo systemctl reload nginx

# Логи nginx
sudo journalctl -u nginx -f
```

### Не получается подключиться по кастомному домену

1. Проверьте A-запись домена: `dig YOUR_DOMAIN`
2. Проверьте, был ли файл `domain` в репо при последнем push
3. Проверьте наличие SSL сертификата: `ls /etc/letsencrypt/live/YOUR_DOMAIN/`
4. Проверьте nginx конфигурацию: `sudo grep -r YOUR_DOMAIN /etc/nginx/`
