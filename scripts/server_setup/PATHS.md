# Пути на сервере

Инфраструктура отделена от данных. Все пути заданы в `setup_fresh_server.sh`.

## Переменные (единый источник)

| Переменная | Значение | Используется в |
|------------|----------|----------------|
| GIT_BASE | /var/git/sites | git_wrap, remove_site |
| WORK_TREE_BASE | /opt/deploy | setup |
| SCRIPTS_DIR | /opt/deploy_api/scripts | setup, git_wrap, post-receive, remove_site, systemd |
| CONTAINERS_BASE | /opt/deploy_api/containers | setup |
| REGISTRY_FILE | /opt/deploy/registry.json | post-receive, deploy_single, remove_site |
| NGINX_DEPLOY_DIR | /etc/nginx/sites-available/deploy | post-receive, deploy_single, remove_site |

## Инфраструктура (`/opt/deploy_api/`)

```
/opt/deploy_api/
├── scripts/
│   ├── post-receive
│   ├── git_wrap.sh
│   ├── remove_site.sh
│   ├── deploy_single.sh
│   └── deploy_worker.sh
└── containers/                # (зарезервировано)
```

## Данные (`/opt/deploy/`)

```
/opt/deploy/
├── registry.json
├── {PAGE_HASH}/              # Work tree каждого сайта
└── ...
```

## Git (`/var/git/sites/`)

```
/var/git/sites/
├── {PAGE_HASH}.git/          # Bare репо
└── ...
```

Push URL: `git@СЕРВЕР:sites/{PAGE_HASH}.git`

## Nginx

```
/etc/nginx/sites-available/
├── deploy_main
└── deploy/
    └── {PAGE_HASH}.conf
```

## Systemd

- `/etc/systemd/system/deploy-worker-1.service`
- `/etc/systemd/system/deploy-worker-2.service`
- `/etc/systemd/system/nginx-reload.path`
- `/etc/systemd/system/nginx-reload.service`

## authorized_keys

```
command="/opt/deploy_api/scripts/git_wrap.sh" ssh-rsa AAAA...
```

## Redis

- Очередь: `deploy_queue`
- Очередь для чат-бота: `deploy:notify` (BLPOP для получения событий)
- Подключение: 127.0.0.1:6379 (REDIS_HOST, REDIS_PORT)

## Логи

- `/var/log/deploy/deploy.log` — все деплои (JSONL)
- `/var/log/deploy/worker-1.log`, `worker-2.log` — логи воркеров

---

## Миграция с /opt/deploy/scripts

Если скрипты лежали в `/opt/deploy/scripts/`:

```bash
# Копируем в новое место
sudo mkdir -p /opt/deploy_api/scripts
sudo cp /opt/deploy/scripts/* /opt/deploy_api/scripts/
sudo chmod +x /opt/deploy_api/scripts/*.sh
sudo chmod +x /opt/deploy_api/scripts/post-receive

# Обновляем systemd и authorized_keys (пути в скриптах уже обновлены)
# Перезапускаем воркеры
sudo systemctl restart deploy-worker-1 deploy-worker-2

# Удаляем старую папку
sudo rm -rf /opt/deploy/scripts
```
