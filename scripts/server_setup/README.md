# Git push → deploy

Push в несуществующий репо → создаётся репо, ставится post-receive, post-receive выполняется.

Используется pnpm, Redis-очередь, 2 воркера (max 2 одновременных деплоя).

## Обновление скриптов на сервере

Из корня репозитория:
```bash
./local_develope/deploy_to_server.sh
```
Копирует все скрипты в `/opt/deploy_api/scripts/`, systemd units, перезапускает воркеры. Сервер по умолчанию: `root@45.90.35.151` (переменная `DEPLOY_SERVER`).

**Только воркеры (пересоздать юниты, добавить CERTBOT_EMAIL):** на сервере после копирования скриптов можно выполнить:
```bash
sudo /opt/deploy_api/scripts/install_deploy_workers.sh
# или с email для certbot:
sudo CERTBOT_EMAIL=admin@example.com /opt/deploy_api/scripts/install_deploy_workers.sh
```
Скрипт создаёт/обновляет `deploy-worker-1.service` и `deploy-worker-2.service`, перезапускает воркеры.

## Переменные окружения

| Переменная       | Где используется        | По умолчанию        | Описание |
|------------------|-------------------------|---------------------|----------|
| **DOMAIN**       | setup_fresh_server.sh   | your-domain.com     | Основной домен сервера (превью: `https://DOMAIN/{hash}/`). При setup записывается в `/opt/deploy/domain.txt`. |
| **CERTBOT_EMAIL**| setup_fresh_server.sh, deploy_single.sh (воркеры) | deploy@${DOMAIN} или из `/opt/deploy/domain.txt`, иначе deploy@<кастомный_домен> | Email для Let's Encrypt (основной и кастомные домены). Чтобы задать свой — укажи при setup или в systemd-юнитах воркеров (см. ниже). |
| **REDIS_HOST**   | deploy_worker, deploy_single, post-receive | 127.0.0.1 | Хост Redis (очередь деплоев). |
| **REDIS_PORT**   | то же                  | 6379                 | Порт Redis. |

**CERTBOT_EMAIL для кастомных доменов:** при первом деплое с файлом `domain` в репо certbot запрашивает сертификат для этого домена. Email берётся в порядке: 1) переменная окружения **CERTBOT_EMAIL** (в окружении воркера), 2) `deploy@<содержимое /opt/deploy/domain.txt>`, 3) `deploy@<кастомный_домен>`. Чтобы везде использовать один email, при установке сервера запусти setup с email:  
`sudo CERTBOT_EMAIL=admin@example.com DOMAIN=example.com bash scripts/server_setup/setup_fresh_server.sh`  
— тогда он попадёт в конфиг nginx для основного домена и в юниты воркеров (для certbot при деплое кастомных доменов).

## Настройка (один раз)

1. Скопируй `scripts/server_setup` на сервер.

2. На сервере (задай DOMAIN, при желании CERTBOT_EMAIL):
```bash
sudo DOMAIN=example.com bash scripts/server_setup/setup_fresh_server.sh
# или с email для Let's Encrypt (основной + кастомные домены):
sudo CERTBOT_EMAIL=admin@example.com DOMAIN=example.com bash scripts/server_setup/setup_fresh_server.sh
```
Setup установит: пакеты, git (shell=/bin/bash), Redis, Docker, nginx, SSL, воркеры, базовые образы. Сайты: `https://DOMAIN/{hash}/`. Кастомные домены: файл `domain` в корне репо, A-запись на сервер → certbot при деплое.

3. Добавь SSH-ключ (локально): `./local_develope/add_git_key.sh root@СЕРВЕР`

Или вручную в `/home/git/.ssh/authorized_keys`:
```
command="/opt/deploy_api/scripts/git_wrap.sh" ssh-rsa AAAA...твой_ключ
```

## Push

```bash
git remote add origin git@СЕРВЕР:sites/PAGE_HASH.git
git push -u origin main
```

Репо создаётся, post-receive ставится и сразу выполняется (checkout → docker build → nginx).

## Удаление сайта

```bash
sudo /opt/deploy_api/scripts/remove_site.sh PAGE_HASH
```

По умолчанию удаляется и bare git репо — при следующем push git_wrap создаст его заново. Флаг `--keep-repo` оставляет репо.

Удалить **все** сайты: `remove_site.sh -A [--keep-repo]`

## Redis и воркеры

**Redis** — хранилище ключ-значение в памяти. Здесь используется как **очередь**: список `deploy_queue`.

**Как это работает:**

1. **post-receive** после checkout и создания Dockerfile не запускает сборку сам, а кладёт `PAGE_HASH` в очередь: `RPUSH deploy_queue 1d2637e8889b`. Push завершается быстро.

2. **Воркер** (`deploy_worker.sh`) — скрипт в бесконечном цикле. Он вызывает `BLPOP deploy_queue 0` — **блокирующее** ожидание элемента из очереди. `0` значит ждать без таймаута, пока не появится задача.

3. Как только в очереди появляется `PAGE_HASH`, Redis отдаёт его одному из воркеров. Тот вызывает `deploy_single.sh` и выполняет полный деплой (docker build, контейнер, nginx).

4. **Два воркера** (`deploy-worker-1`, `deploy-worker-2`) — два параллельных процесса. Одновременно может выполняться максимум 2 деплоя. Остальные ожидают в очереди.

**Схема:** push → RPUSH в Redis → BLPOP у воркера → deploy_single → готово.

## Логи и уведомления

**Файл логов** — все деплои за всё время (JSONL, одна строка = один деплой):
```bash
tail -f /var/log/deploy/deploy.log
```

**Логи воркеров:** `/var/log/deploy/worker-1.log`, `worker-2.log` или `journalctl -u deploy-worker-1 -u deploy-worker-2 -f`

## Сайт не открывается

1. **Контейнер** — `docker ps | grep deploy-PAGE_HASH`
2. **Nginx** — `ls /etc/nginx/sites-available/deploy/PAGE_HASH.conf`, `nginx -t`
3. **URL** — `https://DOMAIN/PAGE_HASH/` (слэш в конце)
4. **Astro base** — в `astro.config.mjs` нужен `base: '/PAGE_HASH/'`, иначе ассеты 404
5. **HTTPS-блок** — если nginx имеет отдельный server для 443 (certbot), в нём тоже должен быть `include .../deploy/*.conf`. Проверка: `grep -A5 "listen 443" /etc/nginx/sites-enabled/*`

**Логи воркеров:** `/var/log/deploy/worker-1.log`, `worker-2.log` или `journalctl -u deploy-worker-1 -u deploy-worker-2 -f`

## Очистка кэша Docker

Полная очистка (build cache, unused images, volumes):
```bash
docker system prune -a --volumes -f
```

Только build cache (слои, pnpm store):
```bash
docker builder prune -a -f
```

После очистки перезапусти деплой (push или `redis-cli RPUSH deploy_queue PAGE_HASH`).

## Docker build

Используется default builder: один общий кэш (pnpm store, Astro, слои Docker) для всех воркеров. Распределение нагрузки по CPU — планировщик ОС.

## Обновление образов Docker (еженедельно)

Скрипт `docker_pull_images.sh` тянет `node:20-alpine` и `nginx:alpine`, помечает как `deploy-node:20-alpine` и `deploy-nginx:alpine` — default builder не обращается к registry при build. Systemd timer запускает скрипт каждое воскресенье в 3:00.

**Установка на сервере:**
```bash
# Скопировать скрипт и unit-файлы
cp docker_pull_images.sh /opt/deploy_api/scripts/
chmod +x /opt/deploy_api/scripts/docker_pull_images.sh

cp docker_pull_images.service docker_pull_images.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable docker_pull_images.timer
systemctl start docker_pull_images.timer
```

**Проверка:** `systemctl list-timers | grep docker`  
**Ручной запуск:** `systemctl start docker_pull_images.service`
