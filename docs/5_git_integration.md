# Git Integration

## Обзор

Система использует **Git hooks** для автоматического деплоя при каждом `git push`. Интеграция реализована через SSH forced command и post-receive hook.

## Архитектура интеграции

### 1. SSH Forced Command

**Файл:** `/home/git/.ssh/authorized_keys`

**Формат:**
```
command="/opt/deploy_api/scripts/git_wrap.sh" ssh-rsa AAAA...публичный_ключ
```

**Как работает:**
- Любой SSH-запрос от пользователя с этим ключом автоматически выполняется через `git_wrap.sh`
- Стандартный Git-протокол работает через этот скрипт
- Пользователь не может выполнять произвольные команды на сервере

### 2. git_wrap.sh

**Путь:** `/opt/deploy_api/scripts/git_wrap.sh`

**Функции:**
1. **Парсинг команды:** Извлекает имя репозитория из `SSH_ORIGINAL_COMMAND`
   - Пример: `git-receive-pack 'sites/abc123.git'` → `abc123.git`
2. **Создание репозитория:** Если репо не существует, создаёт bare-репо
   ```bash
   git init --bare /var/git/sites/{PAGE_HASH}.git
   ```
3. **Установка хука:** Создаёт симлинк на `post-receive` в `hooks/`
   ```bash
   ln -sf /opt/deploy_api/scripts/post-receive {REPO}/hooks/post-receive
   ```
4. **Выполнение:** Запускает `git-receive-pack` с абсолютным путём к репозиторию

**Важно:** Вывод перенаправляется в `/dev/null` для корректной работы Git-протокола.

### 3. post-receive Hook

**Путь:** `/opt/deploy_api/scripts/post-receive` (симлинк в каждом репо)

**Триггер:** Выполняется Git автоматически после успешного `git-receive-pack`

**Входные данные (stdin):**
```
<oldrev> <newrev> <refname>
```
Пример: `abc123 def456 refs/heads/main`

**Процесс:**
1. **Валидация:** Проверяет, что push в `main` или `master`
2. **Извлечение PAGE_HASH:** Из имени репозитория (`basename .git`)
3. **Checkout:** `git checkout -f main` в `/opt/deploy/{PAGE_HASH}/`
4. **Оптимизация package.json:** Создаёт `package.cache.json` только с полями зависимостей
5. **Генерация Dockerfile:** Создаёт Dockerfile для сборки
6. **Очередь:** Добавляет `PAGE_HASH` в Redis очередь `deploy_queue`

**Fallback:** Если Redis недоступен, вызывает `deploy_single.sh` напрямую

## Workflow

### Первый push (создание репозитория)

```
Developer: git push origin main
    ↓
SSH: git@server (forced command)
    ↓
git_wrap.sh:
  - Репо не существует → создаёт bare repo
  - Устанавливает post-receive hook
  - Выполняет git-receive-pack
    ↓
post-receive hook:
  - Checkout кода
  - Генерация Dockerfile
  - Добавление в очередь
    ↓
Deploy Worker:
  - Сборка Docker-образа
  - Запуск контейнера
  - Настройка Nginx
```

### Последующие push (обновление)

```
Developer: git push origin main
    ↓
SSH: git@server (forced command)
    ↓
git_wrap.sh:
  - Репо существует → пропускает создание
  - Выполняет git-receive-pack
    ↓
post-receive hook:
  - Checkout нового кода (перезаписывает старый)
  - Генерация нового Dockerfile
  - Добавление в очередь
    ↓
Deploy Worker:
  - Остановка старого контейнера
  - Сборка нового образа
  - Запуск нового контейнера
  - Обновление Nginx (если нужно)
```

## Безопасность

### Ограничения доступа

1. **SSH forced command:** Пользователь не может выполнять произвольные команды
2. **Только Git-команды:** Разрешены только `git-receive-pack` и `git-upload-pack`
3. **Изоляция репозиториев:** Каждый сайт в отдельном репозитории
4. **Валидация PAGE_HASH:** Проверка формата имени репозитория

### Права доступа

- **Git-репозитории:** `/var/git/sites/` — владелец `git:git`
- **Work trees:** `/opt/deploy/` — владелец `root:git`, права `2775` (setgid)
- **Скрипты:** `/opt/deploy_api/scripts/` — владелец `root:git`

## Поддерживаемые Git-команды

### Push (деплой)
```bash
git push origin main
```
- ✅ Поддерживается
- ✅ Триггерит деплой

### Pull/Fetch (чтение)
```bash
git pull origin main
git fetch origin
```
- ✅ Поддерживается
- ❌ Не триггерит деплой

### Clone
```bash
git clone git@server:sites/PAGE_HASH.git
```
- ✅ Поддерживается
- ❌ Не триггерит деплой

## Особенности

### Только main/master

Система деплоит только ветки `main` или `master`. Push в другие ветки:
- ✅ Принимается Git
- ❌ Не триггерит деплой (post-receive игнорирует)

### Force Push

```bash
git push -f origin main
```
- ✅ Поддерживается
- ⚠️ Может привести к потере истории
- ✅ Триггерит деплой

### Множественные коммиты

```bash
git push origin main  # Несколько коммитов
```
- ✅ Все коммиты принимаются
- ✅ Деплоится только последний (HEAD)

## Отладка

### Проверка SSH-доступа
```bash
ssh git@server
# Должно показать сообщение или выполнить git_wrap.sh
```

### Проверка репозитория
```bash
ssh git@server "ls -la /var/git/sites/"
```

### Ручной запуск post-receive
```bash
cd /var/git/sites/{PAGE_HASH}.git
echo "oldrev newrev refs/heads/main" | hooks/post-receive
```

### Логи
```bash
# Логи Git (если настроены)
tail -f /var/log/git.log

# Логи деплоя
tail -f /var/log/deploy/deploy.log
```

## Интеграция с CI/CD

Система может быть интегрирована с CI/CD системами:

### GitHub Actions
```yaml
- name: Deploy
  run: |
    git remote add deploy git@server:sites/${{ env.PAGE_HASH }}.git
    git push deploy main
```

### GitLab CI
```yaml
deploy:
  script:
    - git remote add deploy git@server:sites/$PAGE_HASH.git
    - git push deploy main
```

### Jenkins
```groovy
sh 'git remote add deploy git@server:sites/${PAGE_HASH}.git'
sh 'git push deploy main'
```

## Преимущества Git-интеграции

1. ✅ **Стандартный Git** — знакомый workflow для разработчиков
2. ✅ **Автоматизация** — деплой при каждом push
3. ✅ **История** — полная история изменений в Git
4. ✅ **Ветвление** — можно экспериментировать в ветках
5. ✅ **Безопасность** — SSH forced command ограничивает доступ
