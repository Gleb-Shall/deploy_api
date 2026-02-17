# Git Push Deploy

Деплой Astro-сайтов через `git push`. Push в bare-репо → checkout → Docker build → nginx. Очередь Redis, до 2 одновременных деплоев, pnpm.

## Структура проекта

```
├── example.json
├── example.json.example
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
