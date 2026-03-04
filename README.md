# Git Push Deploy

Деплой Astro-сайтов через `git push`. Push в bare-репо → checkout → Docker build → nginx. Очередь Redis, до 2 одновременных деплоев, pnpm.

## Структура проекта

```
├── domain_api/                   # API доменов (Beget) + медиа (картинки чат-бота) на порту 5000
├── screenshot_api/               # API скриншотов Playwright (модуль генерации), порт 5051
├── local_develope/               # Локальные скрипты: деплой на сервер, domain_api, ключи
│   ├── deploy_to_server.sh      # Копирует скрипты в /opt/deploy_api/scripts/, перезапускает воркеры
│   ├── deploy_domain_api.sh     # Деплой domain_api + nginx для media.<DOMAIN> → 5000
│   └── deploy_screenshot_api.sh  # Деплой screenshot_api (порт 5051)
├── scripts/
│   └── server_setup/
│       ├── setup_fresh_server.sh  # Первичная настройка сервера (один раз)
│       ├── post-receive.template  # Хук: checkout → очередь → deploy (копируется как post-receive)
│       ├── git_wrap.sh            # Обёртка для push: создаёт репо, ставит post-receive
│       ├── deploy_single.sh       # Деплой одного сайта (вызывается воркером)
│       ├── deploy_worker.sh       # Воркер очереди Redis
│       ├── remove_site.sh         # Удаление сайта (-A = удалить все)
│       ├── seo_submit_google.py   # Опционально: GSC — сайт в твоём аккаунте + верификация + sitemap (OAuth) или только sitemap (сервисный аккаунт)
│       ├── install_deploy_workers.sh
│       ├── PATHS.md
│       └── README.md
└── ...
```

## Быстрый старт

### 1. Сервер: первичная настройка (один раз)

```bash
export DOMAIN=automatoria.ru
scp -r scripts/server_setup root@СЕРВЕР:/tmp/
ssh root@СЕРВЕР "cd /tmp/server_setup && sudo bash setup_fresh_server.sh"
```

Добавь в `/home/git/.ssh/authorized_keys`:
```
command="/opt/deploy_api/scripts/git_wrap.sh" ssh-rsa AAAA...твой_ключ
```

### 2. Локально: создать проект и запушить

```bash
python3 scripts/parse_json_to_folder.py
cd parsed_project/ХЭШ
git init && git add . && git commit -m "Initial"
git remote add origin git@СЕРВЕР:sites/ХЭШ.git
git push -u origin main
```

При первом push git_wrap создаёт bare-репо, ставит post-receive. Push попадает в очередь Redis, воркер собирает Docker и настраивает nginx. Сайт: `https://DOMAIN/ХЭШ/`. Кастомный домен: в корне репо файл `domain` (одна строка — домен), A-запись на сервер → при деплое SSL и SEO (пинг Google/Bing, IndexNow для Яндекса, при желании sitemap в конфиге Astro). Чтобы сайт появился в **твоём** Google Search Console: один раз получи refresh_token через `get_google_oauth_token.py`, положи креды в `GOOGLE_OAUTH_CREDENTIALS` на сервере — при деплое сайт добавится в аккаунт, пройдёт верификацию и отправится sitemap.

**Обновление скриптов на сервере** (после изменений в репо):
```bash
./local_develope/deploy_to_server.sh
```
Копирует все скрипты в `/opt/deploy_api/scripts/`, systemd units, перезапускает воркеры. Сервер: `DEPLOY_SERVER` (по умолчанию `root@45.90.35.151`).

## Архитектура

- **Инфраструктура:** `/opt/deploy_api/scripts/` — скрипты
- **Данные:** `/opt/deploy/` — registry, work tree каждого сайта
- **Git:** `/var/git/sites/` — bare-репо
- **Очередь:** Redis `deploy_queue`, 2 воркера (max 2 деплоя одновременно)

Подробнее: `scripts/server_setup/PATHS.md`, `scripts/server_setup/README.md`

---

## Domain API — проверка доменов (.ru, Beget)

Отдельный микросервис в `domain_api/`: проверка доступности и цены домена через Beget. Не связан с деплоем сайтов — свой порт, свой `.env`, можно не ставить.

| Возможность | Описание |
|-------------|----------|
| **Проверка** | Реальная цена и доступность домена (в т.ч. премиум), зона .ru |

### Эндпоинт

```bash
# Проверка домена (X-API-Key опционален, если задан в .env)
curl -X POST http://127.0.0.1:5000/api/domain/check \
  -H "Content-Type: application/json" \
  -d '{"domain": "example.ru", "period": 1}'
```

Ответ: `available`, `can_purchase`, `price`, `balance`.

### Доступ с другого сервера (чат-бот и т.п.)

API слушает только `127.0.0.1:5000`. Чтобы дергать его с другой машины без открытия порта — **SSH-туннель** с сервера, где крутится клиент:

```bash
ssh -i ~/.ssh/domain_api_tunnel -N -L 5000:127.0.0.1:5000 root@СЕРВЕР_С_API
```

Тогда на машине с чат-ботом `http://127.0.0.1:5000` будет вести на Domain API. Можно оформить как systemd-сервис (см. `domain_api/README.md`).

### Установка и конфиг

- **Локально:** `cd domain_api && cp .env.example .env`, заполнить `BEGET_LOGIN`, `BEGET_PASSWORD`, затем `pip install -r requirements.txt` и `python api.py`.
- **На сервере:** из корня проекта `./local_develope/deploy_domain_api.sh`, затем создать `.env` на сервере в `/opt/deploy_api/domain_api/`.
- **Автозапуск (systemd):** на сервере после деплоя выполнить `sudo bash scripts/server_setup/install_api_services.sh` — поднимет сервисы `domain_api` и `screenshot_api`, они будут стартовать при загрузке системы.

Подробнее: **`domain_api/README.md`**.

---

## Медиа и скриншоты

**Картинки от чат-бота** — на том же порту, что и Domain API (5000):

- **Upload:** `POST http://127.0.0.1:5000/api/media/upload` (multipart `file`, заголовок `X-API-Key` как у domain API)
- **Просмотр:** `https://media.automatoria.ru/picture/{id}` (nginx проксирует на 127.0.0.1:5000)

Хранение: `MEDIA_STORAGE_DIR` в `.env` domain_api (по умолчанию `/opt/deploy/media`).

**Скриншоты Playwright (модуль генерации)** — отдельный сервис на порту 5051:

- **Upload:** `POST http://127.0.0.1:5051/api/screenshots` (multipart `file` или raw body)
- **Просмотр:** `GET http://127.0.0.1:5051/screenshot/<id>`

Подробнее: `screenshot_api/README.md`. Деплой: `./local_develope/deploy_screenshot_api.sh`. Nginx для media — входит в `deploy_domain_api.sh`.

---

## Cursor IDE (ecc-universal)

Правила, агенты, команды и MCP для Cursor ставятся в `.cursor/` в корне репо (официальный способ):

```bash
npm install
npm run cursor:install -- typescript
# или несколько языков:
npm run cursor:install -- python golang
```

Эквивалент вызова из доки: `./install.sh --target cursor python golang` (скрипт запускается из корня проекта, чтобы создавалась именно проектная `.cursor/`).

**Подробнее:** см. `docs/README.md` — скрипты для локальной разработки (не нужны на сервере).

## Удаление сайта

```bash
sudo /opt/deploy_api/scripts/remove_site.sh PAGE_HASH
sudo /opt/deploy_api/scripts/remove_site.sh -A    # удалить все
```
