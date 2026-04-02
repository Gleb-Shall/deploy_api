# Контекст проекта deploy_api

## Что это

Платформа автоматического деплоя статических Astro-сайтов через `git push`.
Сервер: `root@45.90.35.151` (пароль в `.env` на сервере, спроси у пользователя если нужен)

```
git push → post-receive hook → Redis queue → deploy worker → Docker build → nginx
```

Сайты доступны по `https://automatoria.ru/{hash}/` или кастомному домену.

## Серверная инфраструктура

| Сервер | IP | Что крутится |
|--------|-----|-------------|
| **deploy** | `45.90.35.151` | domain_api (5000), screenshot_api (5051), media_api (5052), nginx, Redis, Docker воркеры |
| **media** | `178.72.171.111` | screenshot_api (5051), media_api (5052), nginx (media.automatoria.ru) |

**Деплой deploy сервера:** CI/CD при push в main (`.github/workflows/deploy.yml`)
**Деплой media сервера:** CI/CD при push в main (job `deploy-media`, зависит от `deploy`) или вручную: `./tools/deploy_media_server.sh`

> Для CI/CD нужны GitHub secrets: `DEPLOY_SERVER_IP`, `DEPLOY_SSH_KEY`, `MEDIA_SERVER_IP`, `MEDIA_SSH_KEY`

## Структура проекта

```
deploy_api/
├── domain_api/       — Flask API, порт 5000 (домены Beget + JS challenge антибот)
├── screenshot_api/   — Flask API, порт 5051 (скриншоты Playwright)
├── media_api/        — Flask API, порт 5052 (файлы чат-бота: image/PDF→PNG/DOCX→TXT)
├── server/
│   ├── scripts/      — bash/python скрипты сервера
│   ├── nginx/        — nginx конфиги (antibot.conf, deploy_main)
│   ├── fail2ban/     — fail2ban конфиги
│   ├── systemd/      — systemd unit файлы
│   └── docs/         — техдокументация
├── tools/            — локальные скрипты деплоя на сервер
├── docs/             — архитектурные диаграммы PlantUML
└── README.md
```

## Сервер — текущее состояние

**Сервис domain-api:** `systemctl status domain-api` (active, порт 5000)
**Сервис media_api:** `systemctl status media_api` (active, порт 5052)
**Конфиги nginx:** `/etc/nginx/sites-available/deploy/*.conf` (по одному на сайт)
**Кастомные домены:** `/etc/nginx/sites-available/deploy/custom/*.conf`
**Очередь деплоя:** Redis, два воркера (`deploy-worker-1`, `deploy-worker-2`)

## Защита от парсинга (реализовано)

**Уровень 1 — nginx UA-фильтрация** (`server/nginx/antibot.conf`):
- Блокирует: scrapy, python-requests, python-urllib, libwww-perl, mechanize, curl, nikto, массканнеры, пустой UA → 403
- Rate limit: 20r/s на IP, burst=50

**Уровень 2 — fail2ban** (`server/fail2ban/`):
- `nginx-honeypot`: GET `/_hp_/` → бан на 24ч
- `nginx-ratelimit`: 10× ответ 429 за минуту → бан на 1ч

**Уровень 3 — CSS обфускация + fingerprint-based AES delivery** (`domain_api/api.py`):
- При деплое: `obfuscate_css.js` переименовывает CSS-классы, удаляет `<style>` из HTML, кладёт CSS bundle в Redis
- nginx `sub_filter` инжектирует `<script src=/api/preview-js?h=HASH>` и 5 canary-ссылок в каждую страницу
- `GET /api/preview-js` — fingerprint collector + CSS decryptor JS (публичный)
- `POST /api/fingerprint-key` — проверяет fingerprint (20+ сигналов), блокирует headless (`navigator.webdriver=true` → score≥5 → 403), шифрует CSS AES-128-GCM, возвращает ключ
- `GET /r/<token>` — canary redirect: логирует referer/IP/UA в Redis, редиректит на Wikipedia
- **Обычный Playwright заблокирован** (`navigator.webdriver=true` → немедленный 403)

**Уровень 4 — Domain lock** (внутри `preview-js`):
- Если `hostname !== automatoria.ru` → `window.location.replace('https://automatoria.ru')`
- Украденный HTML не откроется на чужом домене

**Screenshot bypass для генератора** (`domain_api/api.py`):
- `POST /api/internal/screenshot-token` (localhost only) — выдаёт одноразовый токен (TTL 120s, Redis)
- Генератор добавляет `X-Screenshot-Token: <token>` через `page.route()` перед скриншотом
- Токен сжигается атомарно через `getdel` — повторное использование невозможно
- Интеграция в генераторе:
  ```python
  token = requests.post("http://127.0.0.1:5000/api/internal/screenshot-token").json()["token"]
  await page.route("**/api/fingerprint-key", lambda r: r.continue_(
      headers={**r.request.headers, "X-Screenshot-Token": token}
  ))
  await page.goto(url, wait_until="networkidle")
  await page.wait_for_function("() => document.head.querySelector('style') !== null", timeout=5000)
  ```

**Что НЕ защищает:** Playwright + stealth-плагин (подделывает все fingerprint сигналы). Против него — только Cloudflare Bot Management.

## Ключевые файлы на сервере

| Файл | Путь |
|------|------|
| nginx antibot | `/etc/nginx/conf.d/antibot.conf` |
| nginx главный | `/etc/nginx/sites-available/deploy_main` |
| deploy скрипт | `/opt/deploy_api/scripts/deploy_single.sh` |
| domain API | `/opt/deploy_api/domain_api/api.py` |
| fail2ban jail | `/etc/fail2ban/jail.d/nginx-antibot.conf` |

## Workflow синхронизации с сервером

```bash
# Подтянуть изменённый файл с сервера в git
scp root@45.90.35.151:/path/to/file ./local/path
cd ~/Documents/GitHub/deploy_api && git add . && git commit -m "..."

# Отправить скрипты на сервер
./tools/deploy_to_server.sh
```

## MCP инструменты

- **Exa** — подключён глобально, используй для веб-поиска
- **Gmail, Google Calendar** — подключены

## Git

Репо: `~/Documents/GitHub/deploy_api`
Remote: GitHub (origin/main)
