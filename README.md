# Git Push Deploy

Деплой Astro-сайтов через `git push`. Push в bare-репо → checkout → Docker build → nginx. Очередь Redis, до 2 одновременных деплоев, pnpm.

## Структура проекта

```
├── example.json
├── example.json.example
├── domain_api/                   # Опционально: API проверки/покупки доменов (Beget), не влияет на деплой
├── scripts/
│   ├── parse_json_to_folder.py   # JSON → папка проекта (локально)
│   ├── stress_deploy.sh          # Стресс-тест: параллельный push N сайтов
│   └── server_setup/
│       ├── setup_fresh_server.sh # Первичная настройка сервера
│       ├── post-receive.template # Хук: checkout → очередь → deploy
│       ├── git_wrap.sh           # Обёртка для push: создаёт репо, ставит post-receive
│       ├── deploy_single.sh      # Деплой одного сайта (вызывается воркером)
│       ├── deploy_worker.sh      # Воркер очереди Redis
│       ├── remove_site.sh        # Удаление сайта (-A = удалить все)
│       ├── PATHS.md              # Пути на сервере
│       └── README.md
└── parsed_project/               # Выход parse_json (в .gitignore)
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

При первом push git_wrap создаёт bare-репо, ставит post-receive. Push попадает в очередь Redis, воркер собирает Docker и настраивает nginx. Сайт: `https://DOMAIN/ХЭШ/`.

## Архитектура

- **Инфраструктура:** `/opt/deploy_api/scripts/` — скрипты
- **Данные:** `/opt/deploy/` — registry, work tree каждого сайта
- **Git:** `/var/git/sites/` — bare-репо
- **Очередь:** Redis `deploy_queue`, 2 воркера (max 2 деплоя одновременно)

Подробнее: `scripts/server_setup/PATHS.md`, `scripts/server_setup/README.md`

---

## Domain API — проверка и покупка доменов (.ru, Beget)

Отдельный микросервис в `domain_api/`: проверка доступности домена и покупка через Beget. Не связан с деплоем сайтов — свой порт, свой `.env`, можно не ставить.

| Возможность | Описание |
|-------------|----------|
| **Проверка** | Реальная цена и доступность домена (в т.ч. премиум), только зона .ru |
| **Покупка** | Регистрация домена, списание с баланса Beget, контакты из аккаунта |
| **DNS** | После покупки можно автоматически выставить A-запись на твой IP и дождаться применения |

### Эндпоинты

```bash
# Проверка домена (нужен X-API-Key, если задан в .env)
curl -X POST http://127.0.0.1:5000/api/domain/check \
  -H "Content-Type: application/json" \
  -d '{"domain": "example.ru", "period": 1}'

# Покупка (опционально api_ip — после покупки выставится A-запись и ответ придёт после применения DNS)
curl -X POST http://127.0.0.1:5000/api/domain/purchase \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_KEY" \
  -d '{"domain": "example.ru", "period": 1, "api_ip": "1.2.3.4"}'
```

Ответ проверки: `available`, `can_purchase`, `price`, `balance`. Ответ покупки: `domain`, `service_id`, `dns_propagated` (true, когда запись уже видна в DNS).

### Доступ с другого сервера (чат-бот и т.п.)

API слушает только `127.0.0.1:5000`. Чтобы дергать его с другой машины без открытия порта — **SSH-туннель** с сервера, где крутится клиент:

```bash
ssh -i ~/.ssh/domain_api_tunnel -N -L 5000:127.0.0.1:5000 root@СЕРВЕР_С_API
```

Тогда на машине с чат-ботом `http://127.0.0.1:5000` будет вести на Domain API. Можно оформить как systemd-сервис (см. `domain_api/README.md`).

### Установка и конфиг

- **Локально:** `cd domain_api && cp .env.example .env`, заполнить `BEGET_LOGIN`, `BEGET_PASSWORD`, затем `pip install -r requirements.txt` и `python api.py`.
- **На сервере:** из корня проекта `./local_develope/deploy_domain_api.sh`, затем создать `.env` на сервере в `/opt/deploy_api/domain_api/`.

Подробнее: **`domain_api/README.md`**, **`domain_api/SETUP.md`**.

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
