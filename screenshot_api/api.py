"""
API для сохранения скриншотов Playwright (модуль генерации).
Отдельный порт от domain_api; только эндпоинты скриншотов.
"""
import hmac
import json
import os
import re
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, send_file

from config import (
    SCREENSHOT_HOST,
    SCREENSHOT_PORT,
    SCREENSHOT_STORAGE_DIR,
    SCREENSHOT_MAX_UPLOAD_BYTES,
    SCREENSHOT_API_KEY,
    SCREENSHOT_PUBLIC_URL,
)

ID_RE = re.compile(r"^[a-zA-Z0-9_-]{8,128}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths():
    base = os.path.abspath(SCREENSHOT_STORAGE_DIR)
    return {
        "pictures": os.path.join(base, "pictures"),
        "meta": os.path.join(base, "meta"),
    }


def _ensure_dirs():
    p = _paths()
    os.makedirs(p["pictures"], exist_ok=True)
    os.makedirs(p["meta"], exist_ok=True)


def _gen_id() -> str:
    return uuid.uuid4().hex


def _write_atomic(path: str, data: bytes):
    tmp = f"{path}.tmp.{uuid.uuid4().hex}"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if SCREENSHOT_API_KEY:
            key = request.headers.get("X-API-Key") or request.args.get("api_key")
            if not key or not hmac.compare_digest(key, SCREENSHOT_API_KEY):
                return jsonify({"success": False, "error": "UNAUTHORIZED"}), 401
        return f(*args, **kwargs)
    return decorated


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = SCREENSHOT_MAX_UPLOAD_BYTES


@app.get("/health")
def health():
    return jsonify({"success": True, "status": "ok", "ts": _now_iso()})


@app.post("/api/screenshots")
@require_api_key
def upload_screenshot():
    """
    Сохранение скриншота Playwright.
    Multipart: поле file (изображение) или body — raw image bytes.
    Ответ: { "success": true, "data": { "id": "...", "url": "https://media.../screenshots/<id>" } }
    """
    _ensure_dirs()
    p = _paths()
    content = None
    filename = "screenshot.png"
    mime = "image/png"

    if request.files and "file" in request.files:
        file = request.files["file"]
        if file and file.filename:
            content = file.read()
            mime = (file.mimetype or mime).lower().strip()
            filename = file.filename or filename
    if content is None and request.data:
        content = request.data
        mime = (request.content_type or mime).split(";")[0].strip().lower()
        if not mime.startswith("image/"):
            mime = "image/png"

    if not content:
        return jsonify({"success": False, "error": "MISSING_FILE"}), 400
    if mime and not mime.startswith("image/"):
        return jsonify({"success": False, "error": "UNSUPPORTED_TYPE"}), 400

    pic_id = _gen_id()
    picture_path = os.path.join(p["pictures"], pic_id)
    meta_path = os.path.join(p["meta"], f"{pic_id}.json")
    _write_atomic(picture_path, content)
    meta = {
        "id": pic_id,
        "mime_type": mime or "image/png",
        "filename": filename,
        "size_bytes": len(content),
        "created_at": _now_iso(),
    }
    _write_atomic(meta_path, json.dumps(meta, ensure_ascii=False).encode("utf-8"))

    return jsonify({
        "success": True,
        "data": {"id": pic_id, "url": f"{SCREENSHOT_PUBLIC_URL}/{pic_id}"},
    })


@app.get("/screenshot/<pic_id>")
def get_screenshot(pic_id: str):
    if not ID_RE.match(pic_id):
        return jsonify({"success": False, "error": "INVALID_ID"}), 400
    p = _paths()
    picture_path = os.path.join(p["pictures"], pic_id)
    meta_path = os.path.join(p["meta"], f"{pic_id}.json")
    if not os.path.isfile(picture_path) or not os.path.isfile(meta_path):
        return jsonify({"success": False, "error": "NOT_FOUND"}), 404
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        mime = (meta.get("mime_type") or "image/png").strip()
    except Exception:
        mime = "image/png"
    resp = send_file(picture_path, mimetype=mime, conditional=True, max_age=86400)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


if __name__ == "__main__":
    _ensure_dirs()
    app.run(host=SCREENSHOT_HOST, port=SCREENSHOT_PORT, debug=False)
