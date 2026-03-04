"""Сохранение и выдача картинок на диске (без SQL)."""
import json
import os
import re
import uuid
from datetime import datetime, timezone

ID_RE = re.compile(r"^[a-zA-Z0-9_-]{8,128}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def storage_paths(base_dir: str):
    base = os.path.abspath(base_dir)
    pictures = os.path.join(base, "pictures")
    meta = os.path.join(base, "meta")
    return {"base": base, "pictures": pictures, "meta": meta}


def ensure_dirs(base_dir: str):
    p = storage_paths(base_dir)
    os.makedirs(p["pictures"], exist_ok=True)
    os.makedirs(p["meta"], exist_ok=True)


def gen_id() -> str:
    return uuid.uuid4().hex


def write_atomic(path: str, data: bytes):
    tmp = f"{path}.tmp.{uuid.uuid4().hex}"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def save_picture(base_dir: str, content: bytes, mime_type: str, filename: str):
    ensure_dirs(base_dir)
    p = storage_paths(base_dir)
    pic_id = gen_id()
    picture_path = os.path.join(p["pictures"], pic_id)
    meta_path = os.path.join(p["meta"], f"{pic_id}.json")
    write_atomic(picture_path, content)
    meta = {
        "id": pic_id,
        "mime_type": mime_type,
        "filename": filename,
        "size_bytes": len(content),
        "created_at": _now_iso(),
    }
    write_atomic(meta_path, json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    return pic_id, picture_path, meta_path, mime_type


def get_picture_paths(base_dir: str, pic_id: str):
    if not ID_RE.match(pic_id):
        return None
    p = storage_paths(base_dir)
    picture_path = os.path.join(p["pictures"], pic_id)
    meta_path = os.path.join(p["meta"], f"{pic_id}.json")
    if not os.path.isfile(picture_path) or not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        mime = (meta.get("mime_type") or "application/octet-stream").strip()
    except Exception:
        mime = "application/octet-stream"
    return {"path": picture_path, "mime": mime}


def delete_picture(base_dir: str, pic_id: str) -> bool:
    """Удаляет картинку и её meta. Возвращает True если удалено, False если не найдено."""
    if not ID_RE.match(pic_id):
        return False
    p = storage_paths(base_dir)
    picture_path = os.path.join(p["pictures"], pic_id)
    meta_path = os.path.join(p["meta"], f"{pic_id}.json")
    if not os.path.isfile(picture_path) or not os.path.isfile(meta_path):
        return False
    try:
        os.remove(picture_path)
        os.remove(meta_path)
        return True
    except OSError:
        return False
