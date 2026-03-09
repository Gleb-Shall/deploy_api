# Deploy API — Быстрый справочник команд

**Дата обновления:** 2026-03-09

## Первичная настройка

### 1. Подготовка сервера (первый раз)

```bash
# Параметры
export DEPLOY_SERVER=root@YOUR_SERVER_IP
export DOMAIN=automatoria.ru

# Копируем скрипты на сервер
scp -r server/scripts $DEPLOY_SERVER:/tmp/server_scripts

# Запускаем первичную настройку
ssh $DEPLOY_SERVER "bash /tmp/server_scripts/setup_fresh_server.sh"

# Добавляем SSH ключ (вариант 1)
cat ~/.ssh/id_rsa.pub | ssh $DEPLOY_SERVER \
  "echo 'command=\"/opt/deploy_api/scripts/git_wrap.sh\" \$(cat)' >> /home/git/.ssh/authorized_keys"

# Или используем скрипт (вариант 2)
./tools/add_git_key.sh
```

### 2. Развертывание скриптов и конфигов

```bash
# Копирует скрипты, nginx, systemd, fail2ban на сервер
./tools/deploy_to_server.sh

# Или вручную
scp -r server/scripts root@$DEPLOY_SERVER:/opt/deploy_api/
scp -r server/nginx root@$DEPLOY_SERVER:/opt/deploy_api/
scp -r server/systemd root@$DEPLOY_SERVER:/etc/systemd/system/
scp -r server/fail2ban root@$DEPLOY_SERVER:/etc/fail2ban/filter.d/
```

---

## Деплой сайта

### Создать и задеплоить новый сайт

```bash
# Локально на вашем ПК
cd ~/my-astro-site

# Инициализируем Git
git init
git add .
git commit -m "Initial commit"

# Добавляем remote
git remote add origin git@YOUR_SERVER_IP:sites/mysite.git

# Первый push — триггер деплоя!
git push -u origin main
```

### Проверить статус деплоя

```bash
ssh root@YOUR_SERVER_IP

# Просмотр истории деплоев
bash /opt/deploy_api/server/scripts/deploy_history.sh

# Проверка статуса текущих деплоев
bash /opt/deploy_api/server/scripts/check_deploy_status.sh

# Проверка использования диска
bash /opt/deploy_api/server/scripts/check_sites_disk.sh

# Просмотр логов воркера
systemctl status deploy-worker
journalctl -u deploy-worker -f

# Просмотр очереди Redis
redis-cli -n 0 LLEN deploy_queue
redis-cli -n 0 LRANGE deploy_queue 0 -1
```

### Обновить существующий сайт

```bash
# Локально на вашем ПК — делайте изменения
# Измените код, затем:
git add .
git commit -m "Update description"
git push  # Это триггер нового деплоя!

# Сайт обновится автоматически
```

---

## Кастомный домен

### Добавить кастомный домен к сайту

```bash
# В корне вашего проекта создайте файл 'domain'
echo "example.com" > domain

# Скоммитьте и запушьте
git add domain
git commit -m "Add custom domain"
git push

# На своем DNS хостере убедитесь, что A-запись указывает на IP сервера
# dig example.com → должно показать ваш IP

# При следующем деплое скрипты автоматически:
# 1. Получат SSL сертификат (Let's Encrypt)
# 2. Настроят Nginx для кастомного домена
# 3. Отправят сайт в Google Search Console (если настроено)
```

---

## Управление API

### Деплой Domain API (проверка доменов)

```bash
# На локальной машине из корня проекта
./tools/deploy_domain_api.sh

# На сервере создайте .env с Beget учетными данными
ssh root@YOUR_SERVER_IP
sudo nano /opt/deploy_api/domain_api/.env

# Должны быть:
# BEGET_LOGIN=your_login
# BEGET_PASSWORD=your_api_password
# API_KEY=optional_secret

# Установка systemd сервисов
sudo bash /opt/deploy_api/server/scripts/install_api_services.sh

# Проверка статуса
systemctl status domain-api
journalctl -u domain-api -f
```

### Деплой Screenshot API

```bash
# Из корня проекта
./tools/deploy_screenshot_api.sh

# Или оба API одновременно
./tools/deploy_apis_to_server.sh

# На сервере установите systemd сервис
sudo bash /opt/deploy_api/server/scripts/install_api_services.sh

# Проверка статуса
systemctl status screenshot-api
journalctl -u screenshot-api -f
```

### Использование Domain API

```bash
# Локально (без SSH туннеля)
curl -X POST http://127.0.0.1:5000/api/domain/check \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "domain": "example.ru",
    "period": 1
  }'

# С другого сервера (используя SSH туннель)
ssh -i ~/.ssh/key -N -L 5000:127.0.0.1:5000 root@DEPLOY_SERVER
# Теперь на локальной машине можно обращаться к http://127.0.0.1:5000
```

### Загрузка медиа через API

```bash
# Загрузить файл
curl -X POST http://127.0.0.1:5000/api/media/upload \
  -H "X-API-Key: YOUR_API_KEY" \
  -F "file=@image.jpg"

# Возвращает: {"id": "image_12345"}

# Просмотреть через Nginx
# https://YOUR_DOMAIN/media/picture/image_12345
```

---

## Диагностика и troubleshooting

### Docker проблемы

```bash
ssh root@YOUR_SERVER_IP

# Диагностика Docker
bash /opt/deploy_api/server/scripts/diagnose_docker.sh

# Просмотр контейнеров
docker ps -a

# Просмотр логов контейнера
docker logs CONTAINER_ID
docker logs -f CONTAINER_ID  # в реальном времени

# Удаление старого контейнера
docker stop CONTAINER_ID
docker rm CONTAINER_ID

# Пред-загрузка образов Docker
bash /opt/deploy_api/server/scripts/docker_pull_images.sh
```

### Redis очередь

```bash
# Проверка размера очереди
redis-cli -n 0 LLEN deploy_queue

# Просмотр всех задач
redis-cli -n 0 LRANGE deploy_queue 0 -1

# Очистка очереди (осторожно!)
redis-cli -n 0 DEL deploy_queue

# Проверка подключения
redis-cli PING  # должно вернуть PONG
```

### Nginx

```bash
# Проверка синтаксиса конфига
sudo nginx -t

# Перезагрузка конфига (без перезагрузки сервиса)
sudo systemctl reload nginx

# Логи Nginx
sudo journalctl -u nginx -f

# Просмотр активных соединений
sudo netstat -tlnp | grep :80
sudo netstat -tlnp | grep :443
```

### SSL сертификаты

```bash
# Просмотр существующих сертификатов
ls /etc/letsencrypt/live/

# Информация о сертификате
sudo openssl x509 -in /etc/letsencrypt/live/DOMAIN/fullchain.pem -text

# Обновление всех сертификатов
sudo certbot renew

# Удаление сертификата (если сайт удален)
sudo certbot delete --cert-name DOMAIN
```

### Логи

```bash
# Deploy worker
journalctl -u deploy-worker -f

# Domain API
journalctl -u domain-api -f

# Screenshot API
journalctl -u screenshot-api -f

# Nginx
journalctl -u nginx -f

# System logs
journalctl -p err -f  # только ошибки
journalctl -n 100    # последние 100 строк
```

---

## Управление сайтами

### Удалить сайт

```bash
# По хешу сайта
sudo /opt/deploy_api/server/scripts/remove_site.sh PAGE_HASH

# Удалить все сайты
sudo /opt/deploy_api/server/scripts/remove_site.sh -A

# Это удалит:
# - Docker контейнер
# - Work tree в /opt/deploy/
# - Nginx конфиг
# - SSL сертификат (если был)
# - Git репо в /var/git/sites/
```

### Просмотр информации о сайте

```bash
# Список всех контейнеров
docker ps -a

# Просмотр работающих сайтов
ls -la /opt/deploy/

# Просмотр Git репо
ls -la /var/git/sites/

# Информация о порте контейнера
docker inspect CONTAINER_ID | grep -A 5 PortBindings
```

---

## Работа с локальными скриптами

### Парсинг JSON в проекты

```bash
# Используйте tools/example.json.example как шаблон
cd tools
cp example.json.example example.json
# Отредактируйте example.json с вашими данными

# Парсинг
python3 parse_json_to_folder.py

# Сгенерируются папки с проектами в parsed_project/
```

### Stress-тест

```bash
# Тестирование нагрузки (несколько одновременных деплоев)
bash tools/stress_deploy.sh
```

---

## Обновление скриптов

### После изменений в репо

```bash
# Обновляйте скрипты на сервере
./tools/deploy_to_server.sh

# Это скопирует:
# - server/scripts/ → /opt/deploy_api/scripts/
# - server/nginx/ → /opt/deploy_api/nginx/ и /etc/nginx/
# - server/systemd/ → /etc/systemd/system/
# - server/fail2ban/ → /etc/fail2ban/filter.d/

# И перезапустит сервисы воркеров
```

---

## Переменные окружения

### На сервере (.env файлы)

**Domain API** (`/opt/deploy_api/domain_api/.env`):
```
BEGET_LOGIN=your_login
BEGET_PASSWORD=your_api_password
API_KEY=optional_secret_key
MAX_DOMAIN_PRICE=200  # Максимальная цена покупки в руб.
API_DEBUG=False       # True чтобы блокировать покупку
MEDIA_STORAGE_DIR=/opt/deploy/media
```

**Screenshot API** (`/opt/deploy_api/screenshot_api/.env`):
```
SCREENSHOT_API_KEY=optional_secret_key
SCREENSHOT_STORAGE_DIR=/opt/deploy/screenshots
PORT=5051
```

**Глобальные** (для скриптов деплоя):
```
DOMAIN=automatoria.ru        # Главный домен
DEPLOY_SERVER=root@IP        # SSH адрес сервера
GITHUB_TOKEN=xxx             # Опционально для GitHub API
GOOGLE_OAUTH_CREDENTIALS=xxx # Опционально для Google Search Console
```

---

## Helpful one-liners

```bash
# Обновить все скрипты и перезагрузить воркеры
./tools/deploy_to_server.sh && echo "✓ Обновление завершено"

# Просмотреть все деплои за последний час
journalctl -u deploy-worker -n 1000 --since "1 hour ago"

# Проверить все сайты
ssh root@YOUR_SERVER_IP "ls -la /opt/deploy/ | wc -l"

# Удалить все незавершённые задачи из очереди
ssh root@YOUR_SERVER_IP "redis-cli -n 0 DEL deploy_queue"

# Посмотреть самые тяжелые сайты по диску
ssh root@YOUR_SERVER_IP "du -sh /opt/deploy/* | sort -h"

# Переподключить сервис воркера
ssh root@YOUR_SERVER_IP "sudo systemctl restart deploy-worker"

# Просмотреть ошибки в логах
ssh root@YOUR_SERVER_IP "journalctl -p err -n 50"
```

---

## Полезные ссылки

- **Главная документация:** `/README.md`
- **Архитектура:** `/docs/CODEMAP.md`
- **Диаграммы:** `/docs/` (PlantUML файлы)
- **Domain API docs:** `/domain_api/README.md`
- **Screenshot API docs:** `/screenshot_api/README.md`
- **Техническая документация:** `/server/docs/`
- **Траблшутинг:** `/README.md#troubleshooting`
