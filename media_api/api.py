"""
Media API — загрузка файлов от чат-бота.
Порт 5052. Поддерживает: изображения, PDF (→ PNG по страницам), DOCX/PPTX/XLSX/XLS (→ TXT),
TXT, DOC, видео (mp4/mov/avi/webm) — стриминг с Range support.
"""
import hmac
import os
import re
import traceback
from functools import wraps

from flask import Flask, Response, jsonify, make_response, request, send_file, stream_with_context
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import (
    MEDIA_API_KEY,
    MEDIA_HOST,
    MEDIA_MAX_PDF_PAGES,
    MEDIA_MAX_UPLOAD_BYTES,
    MEDIA_MAX_VIDEO_BYTES,
    MEDIA_PORT,
    MEDIA_PUBLIC_URL,
    MEDIA_STORAGE_DIR,
)
from processors import ProcessingError, docx_to_text, pdf_extract_text, pdf_to_pages, pptx_to_text, xlsx_to_text, xls_to_text
from storage import delete_file, get_file_info, save_file

MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_XLS  = "application/vnd.ms-excel"
MIME_DOC  = "application/msword"

_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MEDIA_MAX_VIDEO_BYTES

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per hour", "30 per minute"],
)


# ── Auth ──────────────────────────────────────────────────────────────────────

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if MEDIA_API_KEY:
            provided = (request.headers.get("X-API-Key") or request.args.get("api_key") or "").strip()
            if not provided or not hmac.compare_digest(provided, MEDIA_API_KEY):
                return jsonify({"success": False, "error": {"code": "UNAUTHORIZED", "message": "Неверный API ключ"}}), 401
        return f(*args, **kwargs)
    return decorated


# ── Helpers ───────────────────────────────────────────────────────────────────

def _file_url(file_id: str) -> str:
    return f"{MEDIA_PUBLIC_URL}/file/{file_id}"


def _player_url(file_id: str) -> str:
    return f"{MEDIA_PUBLIC_URL}/video/{file_id}"


def _err(code: str, message: str, status: int):
    return jsonify({"success": False, "error": {"code": code, "message": message}}), status


def _save_as_document(content: bytes, mime: str, original_name: str):
    file_id, _ = save_file(MEDIA_STORAGE_DIR, content, mime, original_name, "document")
    return jsonify({
        "success": True,
        "data": {"type": "document", "url": _file_url(file_id), "original": original_name},
    })


def _convert_to_text_document(text_bytes: bytes, original_name: str):
    txt_name = original_name.rsplit(".", 1)[0] + ".txt"
    file_id, _ = save_file(MEDIA_STORAGE_DIR, text_bytes, "text/plain", txt_name, "document")
    text = text_bytes.decode("utf-8", errors="replace").strip()
    resp_data = {"type": "document", "url": _file_url(file_id), "original": original_name}
    if text:
        resp_data["text"] = text[:32_000]
    return jsonify({"success": True, "data": resp_data})


def _stream_video(file_path: str, mime: str) -> Response:
    """Отдаёт видео с поддержкой Range-запросов (HTTP 206) для браузерного плеера."""
    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("Range")

    if not range_header:
        resp = send_file(file_path, mimetype=mime, conditional=True)
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    match = _RANGE_RE.match(range_header)
    if not match:
        r = make_response("", 416)
        r.headers["Content-Range"] = f"bytes */{file_size}"
        return r

    byte_start = int(match.group(1))
    byte_end = int(match.group(2)) if match.group(2) else file_size - 1
    byte_end = min(byte_end, file_size - 1)

    if byte_start > byte_end or byte_start >= file_size:
        r = make_response("", 416)
        r.headers["Content-Range"] = f"bytes */{file_size}"
        return r

    chunk_size = byte_end - byte_start + 1

    def _generate():
        with open(file_path, "rb") as f:
            f.seek(byte_start)
            remaining = chunk_size
            while remaining > 0:
                data = f.read(min(65536, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {byte_start}-{byte_end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
        "Content-Type": mime,
        "Cache-Control": "public, max-age=86400",
    }
    return Response(stream_with_context(_generate()), status=206, headers=headers)


_VIDEO_PLAYER_HTML = """\
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Video</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0d0d0d;display:flex;align-items:center;justify-content:center;min-height:100vh}}
.wrap{{width:100%;max-width:960px;padding:16px}}
video{{width:100%;border-radius:8px;display:block;background:#000;box-shadow:0 4px 32px rgba(0,0,0,.7)}}
.meta{{color:#555;font-size:11px;margin-top:8px;text-align:center;font-family:monospace}}
</style>
</head>
<body>
<div class="wrap">
<video controls autoplay preload="metadata" src="{src}">
  Ваш браузер не поддерживает воспроизведение видео.
</video>
<p class="meta">{file_id}</p>
</div>
</body>
</html>
"""


# ── Error handlers ─────────────────────────────────────────────────────────────

@app.errorhandler(413)
def request_entity_too_large(e):
    max_mb = MEDIA_MAX_VIDEO_BYTES // 1024 // 1024
    return jsonify({"success": False, "error": {"code": "FILE_TOO_LARGE", "message": f"Файл слишком большой. Максимум {max_mb} MB для видео"}}), 413


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.route("/api/media/upload", methods=["POST"])
@limiter.limit("60 per minute")
@require_api_key
def upload():
    """
    Загрузка файла (multipart/form-data, поле file).

    Поддерживаемые типы:
      image/*         → сохраняется как есть
      PDF             → каждая страница конвертируется в PNG
      DOCX            → извлекается текст, сохраняется как .txt
      PPTX            → извлекается текст слайдов, сохраняется как .txt
      XLSX            → извлекается текст ячеек, сохраняется как .txt
      XLS             → извлекается текст ячеек, сохраняется как .txt
      TXT             → сохраняется как есть
      DOC             → сохраняется как есть
      video/*         → стриминг с Range support, возвращает url + player_url
    """
    if "file" not in request.files:
        return _err("MISSING_FILE", "Поле file обязательно", 400)

    file = request.files["file"]
    if not file or not file.filename:
        return _err("INVALID_FILE", "Файл не выбран", 400)

    content = file.read()
    if not content:
        return _err("EMPTY_FILE", "Файл пустой", 400)

    mime = (file.mimetype or "").lower().strip()
    original_name = file.filename

    # Для не-видео — жёсткий лимит 20 MB
    if not mime.startswith("video/") and len(content) > MEDIA_MAX_UPLOAD_BYTES:
        max_mb = MEDIA_MAX_UPLOAD_BYTES // 1024 // 1024
        return _err("FILE_TOO_LARGE", f"Файл слишком большой. Максимум {max_mb} MB", 413)

    try:
        # ── Изображение ──
        if mime.startswith("image/"):
            file_id, _ = save_file(MEDIA_STORAGE_DIR, content, mime, original_name, "image")
            return jsonify({
                "success": True,
                "data": {"type": "image", "url": _file_url(file_id)},
            })

        # ── PDF → PNG по страницам ──
        if mime == "application/pdf":
            pages_data = pdf_to_pages(content, max_pages=MEDIA_MAX_PDF_PAGES)
            extracted_text = pdf_extract_text(content)
            result_pages = []
            for i, (png_bytes, png_mime) in enumerate(pages_data, start=1):
                page_name = f"{original_name}_page{i}.png"
                file_id, _ = save_file(MEDIA_STORAGE_DIR, png_bytes, png_mime, page_name, "pdf_page")
                result_pages.append({"page": i, "url": _file_url(file_id)})
            resp_data = {"type": "pdf_pages", "pages": result_pages}
            if extracted_text:
                resp_data["text"] = extracted_text
            return jsonify({"success": True, "data": resp_data})

        # ── DOCX → TXT ──
        if mime == MIME_DOCX:
            text_bytes, _ = docx_to_text(content)
            return _convert_to_text_document(text_bytes, original_name)

        # ── PPTX → TXT ──
        if mime == MIME_PPTX:
            text_bytes, _ = pptx_to_text(content)
            return _convert_to_text_document(text_bytes, original_name)

        # ── XLSX → TXT ──
        if mime == MIME_XLSX:
            text_bytes, _ = xlsx_to_text(content)
            return _convert_to_text_document(text_bytes, original_name)

        # ── XLS → TXT ──
        if mime == MIME_XLS:
            text_bytes, _ = xls_to_text(content)
            return _convert_to_text_document(text_bytes, original_name)

        # ── TXT / MD — сохранить как есть ──
        if mime in ("text/plain", "text/markdown", "text/x-markdown"):
            return _save_as_document(content, mime, original_name)

        # ── DOC — сохранить как есть (старый бинарный формат) ──
        if mime == MIME_DOC:
            return _save_as_document(content, mime, original_name)

        # ── Видео — стриминг с Range support ──
        if mime.startswith("video/"):
            if len(content) > MEDIA_MAX_VIDEO_BYTES:
                max_mb = MEDIA_MAX_VIDEO_BYTES // 1024 // 1024
                return _err("FILE_TOO_LARGE", f"Видео слишком большое. Максимум {max_mb} MB", 413)
            file_id, _ = save_file(MEDIA_STORAGE_DIR, content, mime, original_name, "video")
            return jsonify({
                "success": True,
                "data": {
                    "type": "video",
                    "url": _file_url(file_id),
                    "player_url": _player_url(file_id),
                    "original": original_name,
                },
            })

        return _err(
            "UNSUPPORTED_TYPE",
            f"Тип {mime!r} не поддерживается. Допустимы: image/*, PDF, DOCX, PPTX, XLSX, XLS, TXT, DOC, video/*",
            400,
        )

    except ProcessingError as e:
        return _err("PROCESSING_ERROR", str(e), 422)
    except Exception:
        app.logger.error(f"Upload error: {traceback.format_exc()}")
        return _err("SAVE_ERROR", "Внутренняя ошибка при сохранении файла", 500)


@app.route("/file/<file_id>", methods=["GET"])
def serve_file(file_id: str):
    """Публичная отдача файла по id. Видео — с Range support для стриминга."""
    info = get_file_info(MEDIA_STORAGE_DIR, file_id)
    if not info:
        return _err("NOT_FOUND", "Файл не найден", 404)

    mime = info["mime"]

    if mime.startswith("video/"):
        return _stream_video(info["path"], mime)

    resp = send_file(info["path"], mimetype=mime, conditional=True)
    if mime.startswith("image/"):
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/video/<file_id>", methods=["GET"])
def video_player(file_id: str):
    """Публичная HTML-страница с видеоплеером."""
    info = get_file_info(MEDIA_STORAGE_DIR, file_id)
    if not info:
        return _err("NOT_FOUND", "Видео не найдено", 404)
    if not info["mime"].startswith("video/"):
        return _err("NOT_VIDEO", "Файл не является видео", 400)

    html = _VIDEO_PLAYER_HTML.format(src=_file_url(file_id), file_id=file_id)
    return Response(html, mimetype="text/html")


@app.route("/api/media/file/<file_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
@require_api_key
def delete(file_id: str):
    """Удаление файла по id."""
    if delete_file(MEDIA_STORAGE_DIR, file_id):
        return jsonify({"success": True})
    return _err("NOT_FOUND", "Файл не найден", 404)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "media_api"})


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host=MEDIA_HOST, port=MEDIA_PORT, debug=False)
