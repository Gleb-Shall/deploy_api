# Git Push Deploy

Деплой Astro-сайтов через `git push`. Post-receive хук собирает Docker и настраивает nginx.

## Структура

```
├── example.json          # Пример JSON с проектом
├── example.json.example  # Шаблон (без секретов)
├── scripts/
│   ├── parse_json_to_folder.py   # Локально: JSON → папка проекта
│   └── server_setup/             # Настройка сервера
│       ├── setup_fresh_server.sh # Первичная настройка (git, docker, nginx)
│       ├── post-receive.template # Хук для deploy при push
│       ├── create_bare_repo.sh   # Создать bare repo (если не авто)
│       └── README.md
└── parsed_project/       # Выход parse_json (игнор Git)
```

## Быстрый старт

### 1. Локально: создать проект из JSON

```bash
python3 scripts/parse_json_to_folder.py
cd parsed_project/ХЭШ
git init && git add . && git commit -m "Initial"
git remote add origin git@СЕРВЕР:/var/git/sites/ХЭШ.git
git push -u origin main
```

### 2. Сервер: первичная настройка (один раз)

```bash
export DOMAIN=example.com
sudo bash scripts/server_setup/setup_fresh_server.sh
```

### 3. Bare repo

Если репо создаётся автоматически при первом push — добавь в логику установку `post-receive` из `/opt/deploy/scripts/post-receive.template`.

Иначе вручную: `sudo bash scripts/server_setup/create_bare_repo.sh ХЭШ`

## Один post-receive на все репо

Можно использовать симлинк вместо копии в каждый репо:

```bash
ln -sf /opt/deploy/scripts/post-receive /var/git/sites/ХЭШ.git/hooks/post-receive
chmod +x /var/git/sites/ХЭШ.git/hooks/post-receive
```

См. `scripts/server_setup/README.md` для деталей.
