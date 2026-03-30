"""
Media API — загрузка файлов от чат-бота.
Порт 5052. Поддерживает: изображения, PDF (→ PNG по страницам), DOCX/PPTX/XLSX/XLS (→ TXT),
TXT, DOC, видео (mp4/mov/avi) — сохраняются как есть.
"""
import hmac
import traceback
from functools import wraps

from flask import Flask, jsonify, request, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import (
    MEDIA_API_KEY,
    MEDIA_HOST,
    MEDIA_MAX_PDF_PAGES,
    MEDIA_MAX_UPLOAD_BYTES,
    MEDIA_PORT,
    MEDIA_PUBLIC_URL,
    MEDIA_STORAGE_DIR,
)
from processors import ProcessingError, docx_to_text, pdf_to_pages, pptx_to_text, xlsx_to_text, xls_to_text
from storage import delete_file, get_file_info, save_file

MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_XLS  = "application/vnd.ms-excel"
MIME_DOC  = "application/msword"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MEDIA_MAX_UPLOAD_BYTES

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


def _err(code: str, message: str, status: int):
    return jsonify({"success": False, "error": {"code": code, "message": message}}), status


def _save_as_document(content: bytes, mime: str, original_name: str):
    """Сохраняет файл как есть и возвращает ответ типа document."""
    file_id, _ = save_file(MEDIA_STORAGE_DIR, content, mime, original_name, "document")
    return jsonify({
        "success": True,
        "data": {"type": "document", "url": _file_url(file_id), "original": original_name},
    })


def _convert_to_text_document(text_bytes: bytes, original_name: str):
    """Сохраняет извлечённый текст и возвращает ответ типа document."""
    txt_name = original_name.rsplit(".", 1)[0] + ".txt"
    file_id, _ = save_file(MEDIA_STORAGE_DIR, text_bytes, "text/plain", txt_name, "document")
    return jsonify({
        "success": True,
        "data": {"type": "document", "url": _file_url(file_id), "original": original_name},
    })


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
      video/*         → сохраняется как есть
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
            result_pages = []
            for i, (png_bytes, png_mime) in enumerate(pages_data, start=1):
                page_name = f"{original_name}_page{i}.png"
                file_id, _ = save_file(MEDIA_STORAGE_DIR, png_bytes, png_mime, page_name, "pdf_page")
                result_pages.append({"page": i, "url": _file_url(file_id)})
            return jsonify({
                "success": True,
                "data": {"type": "pdf_pages", "pages": result_pages},
            })

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

        # ── TXT — сохранить как есть ──
        if mime == "text/plain":
            return _save_as_document(content, mime, original_name)

        # ── DOC — сохранить как есть (старый бинарный формат) ──
        if mime == MIME_DOC:
            return _save_as_document(content, mime, original_name)

        # ── Видео — сохранить как есть ──
        if mime.startswith("video/"):
            return _save_as_document(content, mime, original_name)

        return _err("UNSUPPORTED_TYPE", f"Тип {mime!r} не поддерживается. Допустимы: image/*, PDF, DOCX, PPTX, XLSX, XLS, TXT, DOC, video/*", 400)

    except ProcessingError as e:
        return _err("PROCESSING_ERROR", str(e), 422)
    except Exception:
        app.logger.error(f"Upload error: {traceback.format_exc()}")
        return _err("SAVE_ERROR", "Внутренняя ошибка при сохранении файла", 500)


@app.route("/file/<file_id>", methods=["GET"])
def serve_file(file_id: str):
    """Публичная отдача файла по id."""
    info = get_file_info(MEDIA_STORAGE_DIR, file_id)
    if not info:
        return _err("NOT_FOUND", "Файл не найден", 404)

    resp = send_file(info["path"], mimetype=info["mime"], conditional=True)
    if info["mime"].startswith("image/"):
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


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
