# Инфраструктурная схема

## Диаграмма

Инфраструктура представлена в виде PlantUML диаграммы:

**6_infrastructure.puml** — Системные скрипты и их взаимодействие (deployment, network, storage)

## Обзор архитектуры

Система развернута на **одном сервере** с использованием Docker-контейнеров, Nginx как reverse proxy, и Redis для очереди задач.

## Серверная инфраструктура

### Физический сервер

- **ОС:** Ubuntu/Debian Linux
- **IP:** 45.90.35.151 (или другой)
- **Домен:** automatoria.ru (или другой)
- **Пользователи:** `root`, `git`

## Компоненты системы

### 1. Git Infrastructure

**Bare Repositories:**
- **Путь:** `/var/git/sites/{PAGE_HASH}.git`
- **Тип:** Bare Git repositories
- **Владелец:** `git:git`
- **Количество:** Один репозиторий на сайт

**SSH Server:**
- **Порт:** 22 (стандартный SSH)
- **Пользователь:** `git`
- **Forced Command:** `/opt/deploy_api/scripts/git_wrap.sh`
- **Ключи:** В `/home/git/.ssh/authorized_keys`

### 2. Queue System (Redis)

**Redis Server:**
- **Порт:** 6379 (стандартный)
- **Хост:** 127.0.0.1
- **Использование:**
  - `deploy_queue` (List) — очередь задач деплоя
  - `deploy:notify` (List) — уведомления о деплоях
- **Протокол:** BLPOP (блокирующее чтение)

**Deploy Workers:**
- **Количество:** 2 экземпляра (systemd services)
- **Имена:** `deploy-worker-1`, `deploy-worker-2`
- **Максимум параллельных деплоев:** 2
- **Логи:** `/var/log/deploy/worker-1.log`, `worker-2.log`

### 3. Build System (Docker)

**Docker Daemon:**
- **Версия:** docker.io (из репозитория Ubuntu/Debian)
- **Builder:** Default builder (BuildKit)
- **Кэш:**
  - `pnpm store` — `/root/.local/share/pnpm/store` (общий для всех сайтов)
  - `Astro cache` — `/app/.astro` (отдельный для каждого сайта по PAGE_HASH)

**Base Images:**
- **deploy-node:20-alpine** ← `node:20-alpine`
- **deploy-nginx:alpine** ← `nginx:alpine`
- **Обновление:** Каждое воскресенье в 03:00 (systemd timer)

**Docker Images (per site):**
- **Имя:** `deploy-{PAGE_HASH}`
- **Размер:** ~50-200 MB (зависит от сайта)
- **Хранение:** Локально на сервере
- **Жизненный цикл:** Удаляется при деплое новой версии

### 4. Runtime Containers

**Docker Containers:**
- **Имя:** `deploy-{PAGE_HASH}`
- **Порт:** 9000-9998 (вычисляется из PAGE_HASH или берётся из registry)
- **Внутренний порт:** 8000 (nginx в контейнере)
- **Сеть:** Host network (127.0.0.1:PORT)
- **Restart Policy:** `unless-stopped`
- **Количество:** Один контейнер на сайт

**Container Structure:**
```
deploy-{PAGE_HASH}
├── Base: nginx:alpine
├── Content: /usr/share/nginx/html (dist/ from Astro)
└── Config: /etc/nginx/conf.d/default.conf (auto-generated)
```

### 5. Web Server (Nginx)

**Nginx:**
- **Порт:** 80 (HTTP), 443 (HTTPS)
- **Конфигурация:**
  - Главный файл: `/etc/nginx/sites-available/deploy_main`
  - Сайты: `/etc/nginx/sites-available/deploy/{PAGE_HASH}.conf`
- **SSL/TLS:** Certbot (Let's Encrypt)
- **Proxy:** Reverse proxy к Docker-контейнерам

**Nginx Config Structure:**
```nginx
# deploy_main
server {
    listen 80;
    listen 443 ssl;
    server_name DOMAIN;
    
    include /etc/nginx/sites-available/deploy/*.conf;
}

# deploy/{PAGE_HASH}.conf
location /{PAGE_HASH}/ {
    proxy_pass http://127.0.0.1:{PORT}/;
    # ... proxy headers
}
```

### 6. Storage

**Work Trees:**
- **Путь:** `/opt/deploy/{PAGE_HASH}/`
- **Содержимое:** Checked out code, Dockerfile, .dockerignore
- **Владелец:** `root:git`
- **Права:** `2775` (setgid)

**Registry:**
- **Путь:** `/opt/deploy/registry.json`
- **Формат:** JSON mapping PAGE_HASH → port, container_name
- **Владелец:** `root:git`

**Logs:**
- **Деплои:** `/var/log/deploy/deploy.log` (JSONL)
- **Воркеры:** `/var/log/deploy/worker-*.log`
- **Nginx:** `/var/log/nginx/access.log`, `error.log`

**Scripts:**
- **Путь:** `/opt/deploy_api/scripts/`
- **Владелец:** `root:git`

## Сетевая архитектура

```
Internet
    ↓
[Domain DNS] → Server IP (45.90.35.151)
    ↓
[Nginx:80/443] → SSL/TLS (Certbot)
    ↓
[127.0.0.1:PORT] → Docker Container (deploy-{PAGE_HASH})
    ↓
[Nginx in Container:8000] → Static Files (/usr/share/nginx/html)
```

## Docker Compose (концептуально)

Хотя система не использует Docker Compose, структуру можно представить так:

```yaml
version: '3.8'

services:
  # Redis Queue
  redis:
    image: redis:alpine
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped

  # Deploy Workers (2 instances)
  deploy-worker-1:
    image: alpine:latest
    command: /opt/deploy_api/scripts/deploy_worker.sh
    environment:
      - WORKER_ID=worker-1
      - REDIS_HOST=127.0.0.1
      - REDIS_PORT=6379
    volumes:
      - /opt/deploy_api/scripts:/opt/deploy_api/scripts:ro
      - /opt/deploy:/opt/deploy:rw
      - /var/run/docker.sock:/var/run/docker.sock
      - /var/log/deploy:/var/log/deploy
    restart: unless-stopped

  deploy-worker-2:
    image: alpine:latest
    command: /opt/deploy_api/scripts/deploy_worker.sh
    environment:
      - WORKER_ID=worker-2
      - REDIS_HOST=127.0.0.1
      - REDIS_PORT=6379
    volumes:
      - /opt/deploy_api/scripts:/opt/deploy_api/scripts:ro
      - /opt/deploy:/opt/deploy:rw
      - /var/run/docker.sock:/var/run/docker.sock
      - /var/log/deploy:/var/log/deploy
    restart: unless-stopped

  # Nginx Reverse Proxy
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /etc/nginx/sites-available:/etc/nginx/sites-available:ro
      - /etc/nginx/sites-enabled:/etc/nginx/sites-enabled:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
      - /var/log/nginx:/var/log/nginx
    restart: unless-stopped

  # Site Containers (динамически создаются)
  # deploy-{PAGE_HASH}:
  #   image: deploy-{PAGE_HASH}
  #   ports:
  #     - "127.0.0.1:{PORT}:8000"
  #   restart: unless-stopped

volumes:
  redis_data:
```

**Примечание:** В реальности система использует systemd services, а не Docker Compose.

## Systemd Services

**Deploy Workers:**
```ini
[Unit]
Description=Deploy Worker 1
After=redis.service docker.service

[Service]
Type=simple
User=root
ExecStart=/opt/deploy_api/scripts/deploy_worker.sh
Environment=WORKER_ID=worker-1
Restart=always

[Install]
WantedBy=multi-user.target
```

**Docker Pull Timer:**
```ini
[Unit]
Description=Weekly Docker base image pull

[Timer]
OnCalendar=Sun *-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

## Масштабирование

### Текущие ограничения

- **Один сервер:** Все компоненты на одной машине
- **2 параллельных деплоя:** Максимум через 2 воркера
- **Локальное хранилище:** Все данные на диске сервера

### Возможности масштабирования

1. **Горизонтальное масштабирование воркеров:**
   - Добавить больше `deploy-worker-N` services
   - Увеличить параллельность деплоев

2. **Распределённый Redis:**
   - Redis Cluster для высокой доступности
   - Sentinel для failover

3. **Множественные серверы:**
   - Load balancer перед несколькими серверами
   - Shared storage для work trees (NFS, Ceph)

4. **Docker Swarm/Kubernetes:**
   - Оркестрация контейнеров
   - Автомасштабирование

## Мониторинг

**Логи:**
- `/var/log/deploy/deploy.log` — все деплои (JSONL)
- `/var/log/deploy/worker-*.log` — логи воркеров
- `/var/log/nginx/` — логи Nginx

**Метрики:**
- Redis: `redis-cli INFO`
- Docker: `docker stats`
- Disk: `df -h`, `du -sh /opt/deploy/*`

**Health Checks:**
- Redis: `redis-cli PING`
- Docker: `docker ps`
- Nginx: `nginx -t`, `systemctl status nginx`

## Резервное копирование

**Что бэкапить:**
- Git-репозитории: `/var/git/sites/`
- Registry: `/opt/deploy/registry.json`
- Логи: `/var/log/deploy/`

**Что НЕ нужно бэкапить:**
- Work trees: Пересоздаются при деплое
- Docker-образы: Пересобираются из Git
- Контейнеры: Пересоздаются при деплое

## Безопасность

**Firewall:**
- Открыты порты: 22 (SSH), 80 (HTTP), 443 (HTTPS)
- Закрыты: 6379 (Redis), Docker ports (только localhost)

**Изоляция:**
- Контейнеры слушают только на 127.0.0.1
- Nginx как единственная точка входа
- Git-доступ только через SSH forced command

**SSL/TLS:**
- Certbot автоматически обновляет сертификаты
- HTTPS принудительно (redirect с HTTP)
