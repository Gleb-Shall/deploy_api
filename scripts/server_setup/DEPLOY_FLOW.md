# Детальная логика деплоя

## 1. Точка входа: git push

```
git push origin main
  → SSH git@server
  → authorized_keys: command="/opt/deploy_api/scripts/git_wrap.sh"
  → git_wrap.sh
```

## 2. git_wrap.sh

| Шаг | Действие |
|-----|----------|
| 1 | stdout/stderr → /dev/null (чтобы не сломать git protocol) |
| 2 | Если post-receive нет → копирует из template |
| 3 | Парсит CMD: `git-receive-pack 'sites/eee555.git'` → REPO=eee555.git |
| 4 | RP = /var/git/sites/eee555.git |
| 5 | Если репо нет → `git init --bare`, `ln -sf post-receive` в hooks |
| 6 | chown git:git |
| 7 | exec git-receive-pack с абсолютным путём к репо |

**Важно:** Выполняется от пользователя, который делает SSH (обычно git).

## 3. post-receive (хук)

Запускается Git при receive-pack. Читает из stdin: `oldrev newrev refname`.

| Шаг | Действие |
|-----|----------|
| 1 | REPO_ROOT = GIT_DIR (задаётся Git) = /var/git/sites/eee555.git |
| 2 | PAGE_HASH = basename(REPO_ROOT, .git) = eee555 |
| 3 | Валидация: только main/master, PAGE_HASH по regex |
| 4 | WORK_TREE = /opt/deploy/eee555 |
| 5 | mkdir -p WORK_TREE |
| 6 | git checkout -f main → в WORK_TREE |
| 7 | Создаёт Dockerfile в WORK_TREE |
| 8 | Создаёт .dockerignore |
| 9 | RPUSH deploy_queue eee555 |
| 10 | Если Redis недоступен → вызывает deploy_single напрямую |

**Кто выполняет:** пользователь git (через SSH).

**Права:** git должен писать в /opt/deploy (chown root:git, chmod 2775).

## 4. deploy_worker (systemd, 2 экземпляра)

| Шаг | Действие |
|-----|----------|
| 1 | BLPOP deploy_queue 0 — блокирующее ожидание |
| 2 | Получает JOB (PAGE_HASH) |
| 3 | Запускает deploy_single.sh "$JOB" |
| 4 | Записывает результат в deploy.log и deploy:notify |
| 5 | Повтор |

**Кто выполняет:** root (User=root в systemd).

## 5. deploy_single.sh

| Шаг | Действие | Зависимости |
|-----|----------|-------------|
| 1 | PAGE_HASH из $1 | — |
| 2 | WORK_TREE = /opt/deploy/$PAGE_HASH | Должен существовать (создан post-receive) |
| 3 | **Docker build** | default builder, общий кэш (pnpm, Astro, слои), планировщик ОС распределяет нагрузку |
| 4 | docker stop/rm старый контейнер | — |
| 5 | PORT: из registry или 9000 + cksum(PAGE_HASH) % 999 | jq, registry.json |
| 6 | Обновить registry.json | jq |
| 7 | docker run -d -p 127.0.0.1:PORT:8000 | — |
| 8 | Записать nginx config в /etc/nginx/sites-available/deploy/$PAGE_HASH.conf | — |
| 9 | nginx -t && systemctl reload nginx | — |

**Порядок порта:** Сначала читаем registry (для повторного деплоя — тот же порт). Если пусто — вычисляем. Потом обновляем registry. Контейнер слушает на 127.0.0.1:PORT, nginx проксирует на него.

## 6. Nginx

**deploy_main** (создаётся setup):
- listen 80
- include deploy/*.conf
- Каждый $PAGE_HASH.conf содержит location /$PAGE_HASH/ → proxy_pass на 127.0.0.1:PORT

**URL:** https://DOMAIN/eee555/ → nginx → контейнер (без префикса eee555 в path).

**Astro:** Требует `base: '/eee555/'` в astro.config.

## Ускорение Astro build

**Почему ~8–9 сек:** каждый push = новая Docker-сборка, Astro строит проект с нуля. Первый build всегда «холодный».

**Что уже сделано в deploy:**
- Кэш **pnpm store** — `pnpm install` почти мгновенный при тех же зависимостях
- Кэш **Astro** — монтируется BuildKit cache (`id=astro-$PAGE_HASH`), повторные push одного сайта собираются быстрее

**Рекомендации для проектов (astro.config):**

1. **Отключить source maps в production:**
   ```js
   vite: { build: { sourcemap: false } }
   ```

2. **Картинки без Sharp (если оптимизация не нужна):**
   ```js
   import { passthroughImageService } from 'astro/config';
   image: { service: passthroughImageService() }
   ```

3. **Не делать API-вызовы в дочерних компонентах** при SSG — поднимать fetch в родитель и передавать данные пропсами.

4. **Vite 6+** — по умолчанию Oxc minifier (~30–90x быстрее Terser).

## Возможные проблемы

### A. Docker build "requires exactly 1 argument"
**Статус:** На сервере пользователя Docker не принимает путь. Даже при ручном запуске с путём — та же ошибка.
**Причина:** Ошибка/баг Docker на сервере, не в скриптах.
**Варианты:** Переустановка Docker, откат на старую версию, другой builder.

### B. post-receive выполняется от git
**Проверка:** git может писать в /opt/deploy? (chmod 2775, группа git)
**Проверка:** git в группе docker? (usermod -aG docker git)

### C. deploy_main и HTTPS
Если certbot создал отдельный server {} для 443, в нём тоже должен быть `include deploy/*.conf`. Иначе сайты не откроются по HTTPS.

### D. BLPOP возвращает два значения
`BLPOP deploy_queue 0` → ("deploy_queue", "eee555"). `tail -1` даёт значение. Корректно.

### E. Реестр при первом деплое
registry.json может быть пустым или `{}`. deploy_single обрабатывает это: при пустом/невалидном JSON используется `{}`, порт вычисляется.
