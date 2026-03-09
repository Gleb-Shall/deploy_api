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
│   ├── deploy_worker.sh
│   ├── seo_submit_google.py   # опционально: GSC (OAuth или GOOGLE_APPLICATION_CREDENTIALS)
│   ├── install_deploy_workers.sh
│   ├── check_deploy_status.sh
│   ├── manage_ports_queue.sh
│   └── docker_pull_images.sh
├── domain_api/                # Domain API (Beget)
│   ├── api.py
│   ├── beget_client.py
│   ├── config.py
│   ├── requirements.txt
│   ├── .env                   # Переменные окружения
│   └── venv/                  # Виртуальное окружение Python
└── containers/                # (зарезервировано)
```

## Данные (`/opt/deploy/`)

```
/opt/deploy/
├── registry.json
├── domain.txt                # основной домен (для certbot email и т.п.)
├── seo/                      # креды для SEO API (не в git)
│   ├── google_oauth.json     # OAuth пользователя для GSC (GOOGLE_OAUTH_CREDENTIALS)
│   ├── google-sa.json        # опционально: сервисный аккаунт (GOOGLE_APPLICATION_CREDENTIALS)
│   └── yandex_webmaster.json # опционально: креды Яндекс.Вебмастер
├── indexnow-keys/            # ключи IndexNow по домену (Yandex SEO)
│   └── {домен}               # один файл на кастомный домен
├── google_verification/      # файлы верификации Google (по домену)
│   └── {домен}/
│       └── <token>           # файл для Site Verification API (google-site-verification: <token>)
├── yandex_verification/      # файлы верификации Яндекс.Вебмастер (по домену)
│   └── {домен}/
├── ports_queue_even.txt
├── ports_queue_odd.txt
└── {PAGE_HASH}/              # Work tree каждого сайта
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
    ├── {PAGE_HASH}.conf      # превью по /{hash}/
    └── custom/
        └── {домен}.conf      # кастомный домен (listen 80 + certbot 443)
```

## Systemd

- `/etc/systemd/system/deploy-worker-1.service`, `deploy-worker-2.service` — создаются при `setup_fresh_server.sh` или скриптом `install_deploy_workers.sh` (удобно после обновления скриптов или для смены CERTBOT_EMAIL).
- `/etc/systemd/system/nginx-reload.path`
- `/etc/systemd/system/nginx-reload.service`
- `/etc/systemd/system/domain-api.service` (опционально)

## authorized_keys

```
command="/opt/deploy_api/scripts/git_wrap.sh" ssh-rsa AAAA...
```

## Redis

- Очередь: `deploy_queue`
- Подключение: 127.0.0.1:6379 (REDIS_HOST, REDIS_PORT)

## Логи

- `/var/log/deploy/deploy.log` — все деплои (JSONL)
- `/var/log/deploy/worker-1.log`, `worker-2.log` — логи воркеров
- `/var/log/deploy/domain-api.log` — логи Domain API (опционально)

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
