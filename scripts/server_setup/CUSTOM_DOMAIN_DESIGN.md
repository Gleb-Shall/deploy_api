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

---

## SEO для кастомного домена

После успешного деплоя с кастомным доменом скрипт **deploy_single.sh** автоматически уведомляет поисковики:

- **Google, Bing:** пинг sitemap — запросы к `https://www.google.com/ping?sitemap=<url>` и `https://www.bing.com/ping?sitemap=<url>`. Пингуются пути `sitemap.xml` и `sitemap-index.xml` (подходит для Astro с @astrojs/sitemap).
- **Yandex:** протокол **IndexNow** — запрос к `https://yandex.com/indexnow?url=...&key=...&keyLocation=...`. Ключ при первом деплое генерируется и сохраняется в `/opt/deploy/indexnow-keys/<домен>`, по адресу `https://<домен>/indexnow-key.txt` его отдаёт nginx (location в конфиге кастомного домена). Уведомление отправляется при каждом деплое; при удалении сайта ключ удаляется.

**Что сделать в проекте сайта (репо):**

1. **Sitemap:** подключить генерацию sitemap (например, для Astro — [@astrojs/sitemap](https://docs.astro.build/en/guides/integrations-guide/sitemap/)), чтобы при сборке появлялись `sitemap.xml` и/или `sitemap-index.xml` в `dist/`.
2. **robots.txt (по желанию):** в корне выдачи добавить `Sitemap: https://<кастомный_домен>/sitemap.xml` (или sitemap-index.xml).

**Яндекс:** пинг sitemap у Яндекса недоступен; используется **IndexNow** (см. выше) — ключ и отдача по `/indexnow-key.txt` настраиваются деплоем автоматически. Дополнительно можно добавить сайт в [Яндекс.Вебмастер](https://webmaster.yandex.ru/) и указать sitemap.

---

## SEO с аккаунтами Google и Yandex

Если есть аккаунты в **Google Search Console** и **Яндекс.Вебмастер**, можно усилить индексацию через официальные API (в дополнение к пингу и IndexNow).

### Google Search Console API

- **Что даёт:** явная отправка sitemap в свойство сайта (как «добавить sitemap» в интерфейсе), плюс при желании — [проверка URL](https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect).
- **Как:** сервисный аккаунт в Google Cloud:
  1. В [Google Cloud Console](https://console.cloud.google.com/) создать сервисный аккаунт, выдать ключ (JSON).
  2. В [Search Console](https://search.google.com/search-console) добавить свойство для каждого кастомного домена (URL-prefix, например `https://example.com/`).
  3. В настройках свойства (Пользователи и права) добавить **email сервисного аккаунта** с правом «Владелец» или «Полный доступ».
  4. На сервере задать путь к JSON-ключу, например в юнитах воркеров:  
     `Environment="GOOGLE_APPLICATION_CREDENTIALS=/opt/deploy/seo/google-sa.json"`  
     (файл должен быть доступен процессу воркера).
- **API:** `PUT https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/sitemaps/{feedpath}`  
  Требуется OAuth2 с областью `https://www.googleapis.com/auth/webmasters`.  
  `siteUrl` и `feedpath` — в URL-кодированном виде (например, `https%3A%2F%2Fexample.com%2F` и `https%3A%2F%2Fexample.com%2Fsitemap.xml`).

**Два режима в деплое:**

1. **OAuth пользователя** (сайт привязывается к твоему Google-аккаунту): задай `GOOGLE_OAUTH_CREDENTIALS` (путь к JSON с `client_id`, `client_secret`, `refresh_token`) или переменные `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`. Один раз получи refresh_token локально: `python3 get_google_oauth_token.py` (см. пошаговую настройку ниже). При деплое **deploy_single.sh** вызывает `seo_submit_google.py`: добавление свойства в GSC (PUT sites), получение токена верификации (файл), создание файла в `/opt/deploy/google_verification/<домен>/`, добавление location в nginx, вызов Site Verification API insert, отправка sitemap.
2. **Сервисный аккаунт** (только sitemap; свойство должно быть добавлено вручную в GSC): задай `GOOGLE_APPLICATION_CREDENTIALS` (путь к JSON-ключу). Нужен пакет: `pip install google-auth`. Скрипт: `scripts/server_setup/seo_submit_google.py`.

**Как настроить Google Cloud Console для OAuth пользователя (один раз):**

1. Открой [Google Cloud Console](https://console.cloud.google.com/), выбери проект (или создай новый).
2. **Включи API:** слева **APIs & Services** → **Library**. Найди и включи:
   - **Google Search Console API** → Enable;
   - **Google Site Verification API** → Enable.
3. **OAuth consent screen:** **APIs & Services** → **OAuth consent screen**. Выбери тип **External** (если не корпоративный аккаунт), заполни название приложения и email поддержки, сохрани. В разделе **Scopes** можно ничего не добавлять — скрипт запрашивает scope при авторизации.
4. **Создай OAuth 2.0 Client ID:** **APIs & Services** → **Credentials** → **Create Credentials** → **OAuth client ID**.  
   - Application type: **Desktop app**.  
   - Name: любое (например `Deploy GSC`).  
   - Нажми **Create**. В списке появятся **Client ID** и **Client secret** — скопируй их (они понадобятся для `get_google_oauth_token.py`).
5. **Redirect URI для Desktop app:** у типа «Desktop app» Google по умолчанию разрешает `http://localhost` и `http://localhost:PORT`. Скрипт `get_google_oauth_token.py` слушает `http://localhost:8080/`. Для **Desktop app** дополнительно указывать redirect URI в консоли не обязательно — localhost уже допустим. Если создал клиента типа **Web application**, зайди в созданный клиент (Credentials → клик по имени) → в **Authorized redirect URIs** добавь `http://localhost:8080/` и сохрани.
6. Локально запусти:  
   `GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python3 scripts/server_setup/get_google_oauth_token.py`  
   Открой в браузере выведенный URL, войди в свой Google-аккаунт, подтверди доступ. После редиректа скрипт получит код и выведет (или сохранит в файл) `refresh_token`. Положи креды на сервер в `/opt/deploy/seo/google_oauth.json` и задай в воркерах `Environment="GOOGLE_OAUTH_CREDENTIALS=/opt/deploy/seo/google_oauth.json"`.

### Yandex Webmaster API

- **Что даёт:** программное добавление сайта, отправка sitemap, статистика индексации.
- **Как:** приложение в [OAuth Яндекса](https://oauth.yandex.com/), получение `client_id`; пользователь один раз авторизуется — приложение получает `access_token` и `refresh_token`. Дальше запросы к `https://api.webmaster.yandex.net/v4/` от имени пользователя (user_id из `/v4/user`).
- **Ограничение:** только OAuth пользователя (нет сервисных аккаунтов), поэтому нужно хранить и обновлять токен (refresh_token → access_token). Интеграция в деплой возможна, но сложнее, чем у Google.

**Практика:** для автоматического деплоя обычно достаточно пинга (Google/Bing) и IndexNow (Yandex). Подключение GSC API имеет смысл, если хочешь гарантированно «добавить sitemap» в свойство после каждого деплоя; Yandex API — если нужна автоматизация добавления сайта и sitemap в Вебмастер без ручного ввода.
