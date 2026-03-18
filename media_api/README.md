# Media API — загрузка файлов от чат-бота

Отдельный микросервис для загрузки, хранения и выдачи файлов. Используется чат-ботом для работы с вложениями.

- **Порт:** 5052 (только `127.0.0.1` — не открыт в интернет)
- **Доступ:** только с сервера напрямую или через SSH-туннель
- **Auth:** заголовок `X-API-Key` (тот же ключ что у domain_api)

## Доступ через SSH-туннель

Если чат-бот работает на другой машине:

```bash
# Пробросить порт 5052 с сервера на локальную машину
ssh -N -L 5052:127.0.0.1:5052 root@45.90.35.151

# Теперь обращаться как к локальному сервису
curl -X POST http://127.0.0.1:5052/api/media/upload ...
```

Если чат-бот на том же сервере — просто используй `http://127.0.0.1:5052` напрямую.

## Поддерживаемые типы файлов

| Тип | MIME | Что происходит |
|-----|------|----------------|
| Изображение | `image/*` | Сохраняется как есть |
| PDF | `application/pdf` | Каждая страница → отдельный PNG (до 50 страниц) |
| DOCX | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | Текст → `.txt` |

## Структура

```
media_api/
├── api.py          — Flask приложение (порт 5052)
├── storage.py      — хранение файлов на диске
├── processors.py   — конвертация PDF и DOCX
├── config.py       — конфигурация
└── requirements.txt
```

## Установка

```bash
cd media_api
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Создайте `.env`:
```
API_KEY=your_api_key_here
MEDIA_PORT=5052
MEDIA_STORAGE_DIR=/opt/deploy/media
MEDIA_PUBLIC_URL=https://media.automatoria.ru
```

## API для чат-бота

Все примеры используют `http://127.0.0.1:5052` — напрямую с сервера или через SSH-туннель.

---

### POST /api/media/upload — загрузка файла

Принимает `multipart/form-data`, поле `file`.

**Загрузка изображения:**

```bash
curl -X POST http://127.0.0.1:5052/api/media/upload \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@photo.jpg"
```

Ответ:
```json
{
  "success": true,
  "data": {
    "type": "image",
    "url": "http://127.0.0.1:5052/file/a1b2c3d4e5f6..."
  }
}
```

---

**Загрузка PDF:**

```bash
curl -X POST http://127.0.0.1:5052/api/media/upload \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@document.pdf"
```

Ответ — массив PNG по страницам:
```json
{
  "success": true,
  "data": {
    "type": "pdf_pages",
    "pages": [
      {"page": 1, "url": "http://127.0.0.1:5052/file/aa11bb22..."},
      {"page": 2, "url": "http://127.0.0.1:5052/file/cc33dd44..."},
      {"page": 3, "url": "http://127.0.0.1:5052/file/ee55ff66..."}
    ]
  }
}
```

---

**Загрузка DOCX:**

```bash
curl -X POST http://127.0.0.1:5052/api/media/upload \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@contract.docx"
```

Ответ — ссылка на `.txt` с извлечённым текстом:
```json
{
  "success": true,
  "data": {
    "type": "document",
    "url": "http://127.0.0.1:5052/file/ff99ee88...",
    "original": "contract.docx"
  }
}
```

---

### GET /file/\<file_id\> — получить файл (публичный, без ключа)

```bash
curl http://127.0.0.1:5052/file/a1b2c3d4e5f6...
```

Возвращает файл с правильным `Content-Type`. Изображения кэшируются на год (`immutable`), документы — на сутки.

---

### DELETE /api/media/file/\<file_id\> — удалить файл

```bash
curl -X DELETE http://127.0.0.1:5052/api/media/file/a1b2c3d4e5f6... \
  -H "X-API-Key: YOUR_KEY"
```

Ответ при успехе:
```json
{"success": true}
```

Ответ если не найден:
```json
{"success": false, "error": {"code": "NOT_FOUND", "message": "Файл не найден"}}
```

---

### GET /health — проверка состояния

```bash
curl http://127.0.0.1:5052/health
```

```json
{"status": "ok", "service": "media_api"}
```

---

## Коды ошибок

| Код | HTTP | Описание |
|-----|------|----------|
| `MISSING_FILE` | 400 | Поле `file` отсутствует в запросе |
| `INVALID_FILE` | 400 | Файл не выбран или нет имени |
| `EMPTY_FILE` | 400 | Файл пустой |
| `UNSUPPORTED_TYPE` | 400 | MIME-тип не поддерживается |
| `PROCESSING_ERROR` | 422 | Ошибка конвертации (PDF повреждён, DOCX зашифрован и т.д.) |
| `SAVE_ERROR` | 500 | Ошибка записи на диск |
| `UNAUTHORIZED` | 401 | Неверный или отсутствующий `X-API-Key` |
| `NOT_FOUND` | 404 | Файл не найден |

---

## Конфигурация

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `API_KEY` | — | Ключ авторизации (тот же что у domain_api) |
| `MEDIA_PORT` | `5052` | Порт Flask |
| `MEDIA_HOST` | `127.0.0.1` | Хост Flask |
| `MEDIA_STORAGE_DIR` | `/opt/deploy/media` | Директория хранения файлов |
| `MEDIA_MAX_UPLOAD_BYTES` | `20971520` (20 MB) | Максимальный размер файла |
| `MEDIA_MAX_PDF_PAGES` | `50` | Максимум страниц в PDF |
| `MEDIA_PUBLIC_URL` | `https://media.automatoria.ru` | Базовый URL в ответах |

## Хранилище на диске

```
/opt/deploy/media/
├── files/     — бинарные файлы (изображения, PNG страниц, TXT)
└── meta/      — JSON-метаданные (mime, имя, размер, дата)
```

## Обратная совместимость

Старые ссылки вида `https://media.automatoria.ru/picture/<id>` автоматически редиректятся на `/file/<id>` через nginx (HTTP 301).

## Управление сервисом

```bash
systemctl status media_api
systemctl restart media_api
journalctl -u media_api -f
```
