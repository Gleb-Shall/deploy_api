# GitHub Secrets

Все секреты прописываются в **Settings → Secrets and variables → Actions** репозитория.

## Обязательные секреты

| Secret | Значение | Для чего |
|--------|----------|----------|
| `DEPLOY_SERVER_IP` | `178.72.171.111` | IP deploy-сервера — SSH подключение в CI/CD job `deploy` |
| `DEPLOY_SSH_KEY` | Приватный ключ `~/.ssh/id_ed25519` | Аутентификация на deploy-сервере |
| `MEDIA_SERVER_IP` | IP media-сервера | IP media-сервера — SSH подключение в CI/CD job `deploy-media` |
| `MEDIA_SSH_KEY` | Приватный ключ для media-сервера | Аутентификация на media-сервере |

> **Текущий статус:** `DEPLOY_SERVER_IP` и `DEPLOY_SSH_KEY` — настроены. `MEDIA_SERVER_IP` и `MEDIA_SSH_KEY` — **не настроены**, из-за этого job `Deploy Media Server` падает с ошибкой `missing server host`.

## Как добавить секрет

```
GitHub репо → Settings → Secrets and variables → Actions → New repository secret
```

## Как получить значение DEPLOY_SSH_KEY / MEDIA_SSH_KEY

```bash
cat ~/.ssh/id_ed25519
```

Скопировать всё содержимое, включая `-----BEGIN OPENSSH PRIVATE KEY-----` и `-----END OPENSSH PRIVATE KEY-----`.

## Переменные окружения на серверах (не GitHub secrets)

Эти переменные хранятся в `.env` файлах на самих серверах, а не в GitHub:

| Переменная | Файл на сервере | Для чего |
|------------|----------------|----------|
| `CHALLENGE_SECRET` | `/opt/deploy_api/domain_api/.env` | JWT-секрет для `/api/challenge-token` (PoW антибот). Генерировать: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `REDIS_URL` | `/opt/deploy_api/domain_api/.env` | Подключение к Redis (по умолчанию `redis://localhost:6379`) |
| `BEGET_LOGIN` | `/opt/deploy_api/domain_api/.env` | Логин Beget API для управления DNS |
| `BEGET_PASSWORD` | `/opt/deploy_api/domain_api/.env` | Пароль Beget API |
