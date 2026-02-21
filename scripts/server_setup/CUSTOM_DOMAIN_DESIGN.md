# Кастомный домен для сайта

**Реализовано.** Цель: деплоить сайт на кастомном домене (например `https://mysite.example.com`). При указании кастомного домена превью по `https://DOMAIN/{hash}/` отключается. A-запись предполагается уже настроенной → certbot вызывается сразу при деплое.

---

## Где хранить «кастомный домен» для сайта

### Вариант 1: Файл в репозитории (твой вариант)

**Идея:** в корне проекта файл без расширения, например `domain` или `.deploy-domain`. Одна строка — домен или пусто.

```
# В репо сайта:
domain          # содержимое: mysite.example.com  или пусто
```

**Плюсы:** версионируется в git, меняется коммитом, один источник правды, не нужен отдельный API.  
**Минусы:** чтобы сменить/убрать домен — нужен новый коммит.

**Реализация:** после `git checkout` в post-receive или в deploy_single читаем `$WORK_TREE/domain` (или `.deploy-domain`). Если файл есть и не пустой — считаем значение кастомным доменом для этого `PAGE_HASH`.

---

### Вариант 2: Конфиг в репозитории (JSON/YAML)

**Идея:** файл `deploy.json` или `deploy.yaml` в корне с полем `domain` (и позже — другие опции).

```json
{ "domain": "mysite.example.com" }
```

**Плюсы:** структурированно, легко добавить позже `ssl: true`, `redirect_www` и т.д.  
**Минусы:** ещё один файл/формат, парсинг (jq/yq).

---

### Вариант 3: Только registry на сервере

**Идея:** в `/opt/deploy/registry.json` для каждого `PAGE_HASH` хранить поле `custom_domain`. Значение задаётся вручную или отдельным скриптом/API.

**Плюсы:** не трогаем репо, можно менять домен без push.  
**Минусы:** откуда значение берётся при первом деплое? Нужен либо ручной ввод, либо отдельный «привяжи домен» flow.

---

### Вариант 4: Переменная окружения / CI

**Идея:** домен задаётся при деплое (env в CI, или скрипт на сервере перед вызовом post-receive).

**Плюсы:** гибко.  
**Минусы:** не в репо, при push из разных мест значение может быть разным, сложнее воспроизводимость.

---

## Рекомендация для первой фазы

**Вариант 1 (файл в репо)** — самый прозрачный и простой для старта: один файл, одна строка, поведение «есть домен → деплой на него, нет — как сейчас».

- Имя файла: `domain` или `.deploy-domain` (скрытый чуть аккуратнее).
- Читать в **deploy_single.sh** из `$WORK_TREE/domain` после того как work tree уже актуален (он заполняется в post-receive до постановки в очередь, так что к моменту деплоя файл уже есть).
- Альтернатива: читать в post-receive и передавать в Redis вместе с `PAGE_HASH` (например, поле `custom_domain` в payload), а в deploy_single только использовать. Тогда deploy_single не лезет в work tree за конфигом — решать тебе.

---

## Как отобразить кастомный домен в nginx (без SSL в первой фазе)

Сейчас все сайты висят на одном `server` с `server_name $DOMAIN` и под путями `location /{PAGE_HASH}/`.

Для кастомного домена нужен **отдельный server-блок**: свой `server_name` и `location /` с `proxy_pass` на тот же контейнер (тот же порт), чтобы корень домена вёл на сайт.

Варианты размещения конфига:

1. **Отдельная папка под кастомные домены**, например:
   - `/etc/nginx/sites-available/deploy/custom/` — один файл на домен: `mysite.example.com.conf`.
   - В каждом файле — один `server { server_name ...; location / { proxy_pass http://127.0.0.1:PORT/; ... } }`.
   - В `deploy_main` добавить второй `include`:  
     `include /etc/nginx/sites-available/deploy/custom/*.conf;`  
     (либо включать эти конфиги из основного конфига deploy).

2. **Один файл на сайт с двумя блоками:** в `deploy_single.sh` генерировать не только текущий `PAGE_HASH.conf` (location под основным доменом), но и при наличии кастомного домена — файл в `deploy/custom/ИМЯ_ДОМЕНА.conf` с полным `server { ... }` для этого домена.

Имя файла в `custom/` лучше делать по домену с заменой `*` на `_` (nginx не любит `*` в именах файлов), например `mysite.example.com.conf`.

Порт контейнера известен только в deploy_single, поэтому генерировать server-блок для кастомного домена логично там же: после выделения порта и записи `PAGE_HASH.conf` при непустом `custom_domain` писать ещё и `custom/CUSTOM_DOMAIN.conf` с `proxy_pass http://127.0.0.1:${PORT}/`.

Итог по nginx для первой фазы (только домен, без certbot):

- Основной доступ по-прежнему: `https://DOMAIN/{hash}/`.
- Если задан кастомный домен: дополнительный server-блок (пока только `listen 80`), `server_name` = этот домен, `location /` → proxy на тот же контейнер. SSL и редирект 80→443 добавим во второй фазе (certbot).

---

## Краткий план первой фазы (только кастомный домен)

1. **Конфиг в репо:** файл `domain` (или `.deploy-domain`) в корне проекта, одна строка — домен или пусто.
2. **Чтение:** в deploy_single.sh в начале (после проверки work tree) читать `WORK_TREE/domain`, обрезать пробелы; если пусто — переменная `CUSTOM_DOMAIN` пустая, иначе — значение.
3. **Nginx:**  
   - Как сейчас: писать `NGINX_DEPLOY_DIR/${PAGE_HASH}.conf` с location `/${PAGE_HASH}/`.  
   - Если `CUSTOM_DOMAIN` задан: дополнительно писать `NGINX_DEPLOY_DIR/custom/${CUSTOM_DOMAIN}.conf` (или имя с подчёркиваниями вместо точек) с одним server-блоком: `listen 80`, `server_name CUSTOM_DOMAIN`, `location / { proxy_pass http://127.0.0.1:PORT/; ... }`.
4. **deploy_main:** добавить `include .../deploy/custom/*.conf;` (или эквивалент), чтобы эти server-блоки подхватывались.
5. **Удаление:** в remove_site.sh при удалении сайта удалять и `deploy/custom/ИМЯ_ДОМЕНА.conf`, если для этого PAGE_HASH был записан кастомный домен (можно хранить маппинг в registry или просто удалять все `custom/*.conf`, в которых proxy_pass на порт этого сайта — проще всего при удалении читать registry, брать порт, искать в custom/ конфиги с этим портом и удалять их; ещё проще — в registry писать `custom_domain` при деплое и в remove_site удалять файл по имени из registry).

Упрощение для первой итерации: в registry при деплое с кастомным доменом сохранять `custom_domain`; в remove_site по registry удалять `custom/${custom_domain}.conf`.

---

## Реализованная логика

- **Файл в репо:** в корне проекта файл `domain`, одна строка — кастомный домен или пусто.
- **Чтение:** в `deploy_single.sh` после запуска контейнера читается `$WORK_TREE/domain`.
- **Если кастомный домен задан:**
  - Удаляется `deploy/${PAGE_HASH}.conf` (превью на основном домене по `/{hash}/` больше не создаётся).
  - Создаётся `deploy/custom/${CUSTOM_DOMAIN}.conf` — отдельный server-блок (listen 80, затем certbot добавляет 443).
  - Вызывается `certbot --nginx -d CUSTOM_DOMAIN` (A-запись уже указывает на сервер).
  - В `registry.json` для этого `PAGE_HASH` пишется `custom_domain`.
- **Если файл domain пустой или отсутствует:** как раньше — создаётся только `deploy/${PAGE_HASH}.conf` (превью по `/{hash}/`), конфиг кастомного домена (если был) удаляется.
- **remove_site.sh:** по registry удаляет `deploy/custom/${custom_domain}.conf` и `deploy/${PAGE_HASH}.conf`.
- **setup_fresh_server.sh:** в `deploy_main` добавлен `include .../deploy/custom/*.conf;`, создаётся каталог `deploy/custom/`.
- **Astro base path:** в post-receive при наличии непустого файла `domain` задаётся `base: '/'`, иначе `base: '/{PAGE_HASH}/'`. Для кастомного домена nginx проксирует на корень контейнера (`proxy_pass http://127.0.0.1:PORT/`).

**Переменные окружения для certbot (кастомный домен):** при первом деплое с кастомным доменом certbot вызывается в `deploy_single.sh`. Email для Let's Encrypt берётся в порядке: 1) **CERTBOT_EMAIL** в окружении воркера (systemd), 2) `deploy@<содержимое /opt/deploy/domain.txt>`, 3) `deploy@<кастомный_домен>`. Рекомендуется задать **CERTBOT_EMAIL** при установке сервера: `sudo CERTBOT_EMAIL=admin@example.com DOMAIN=example.com bash setup_fresh_server.sh` — тогда setup пропишет его в юниты воркеров. Либо вручную добавить в `/etc/systemd/system/deploy-worker-1.service` и `deploy-worker-2.service`: `Environment=CERTBOT_EMAIL=admin@example.com`, затем `systemctl daemon-reload && systemctl restart deploy-worker-1 deploy-worker-2`.

**Уже настроенный сервер (без этого апдейта):** в конец `/etc/nginx/sites-available/deploy_main` добавить строку  
`include /etc/nginx/sites-available/deploy/custom/*.conf;`  
и выполнить `mkdir -p /etc/nginx/sites-available/deploy/custom`.
