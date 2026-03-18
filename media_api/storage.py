"""Сохранение и выдача файлов на диске (без SQL)."""
import json
import os
import re
import uuid
from datetime import datetime, timezone

ID_RE = re.compile(r"^[a-zA-Z0-9_-]{8,128}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def storage_paths(base_dir: str) -> dict:
    base = os.path.abspath(base_dir)
    return {
        "base": base,
        "files": os.path.join(base, "files"),
        "meta": os.path.join(base, "meta"),
    }


def ensure_dirs(base_dir: str):
    p = storage_paths(base_dir)
    os.makedirs(p["files"], exist_ok=True)
    os.makedirs(p["meta"], exist_ok=True)


def gen_id() -> str:
    return uuid.uuid4().hex


def write_atomic(path: str, data: bytes):
    tmp = f"{path}.tmp.{uuid.uuid4().hex}"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def save_file(
    base_dir: str,
    content: bytes,
    mime_type: str,
    filename: str,
    file_type: str,
) -> tuple[str, str]:
    """
    Сохраняет файл атомарно.

    file_type: 'image' | 'pdf_page' | 'document'

    Возвращает (file_id, file_path).
    """
    ensure_dirs(base_dir)
    p = storage_paths(base_dir)
    file_id = gen_id()
    file_path = os.path.join(p["files"], file_id)
    meta_path = os.path.join(p["meta"], f"{file_id}.json")
    write_atomic(file_path, content)
    meta = {
        "id": file_id,
        "mime_type": mime_type,
        "filename": filename,
        "file_type": file_type,
        "size_bytes": len(content),
        "created_at": _now_iso(),
    }
    write_atomic(meta_path, json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    return file_id, file_path


def get_file_info(base_dir: str, file_id: str) -> dict | None:
    """
    Возвращает {"path": ..., "mime": ..., "filename": ..., "file_type": ...}
    или None если файл не найден / невалидный id.
    """
    if not ID_RE.match(file_id):
        return None
    p = storage_paths(base_dir)
    file_path = os.path.join(p["files"], file_id)
    meta_path = os.path.join(p["meta"], f"{file_id}.json")
    if not os.path.isfile(file_path) or not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return {
            "path": file_path,
            "mime": (meta.get("mime_type") or "application/octet-stream").strip(),
            "filename": meta.get("filename", ""),
            "file_type": meta.get("file_type", ""),
        }
    except Exception:
        return {"path": file_path, "mime": "application/octet-stream", "filename": "", "file_type": ""}


def delete_file(base_dir: str, file_id: str) -> bool:
    """Удаляет файл и его meta. Возвращает True если удалено, False если не найдено."""
    if not ID_RE.match(file_id):
        return False
    p = storage_paths(base_dir)
    file_path = os.path.join(p["files"], file_id)
    meta_path = os.path.join(p["meta"], f"{file_id}.json")
    if not os.path.isfile(file_path) or not os.path.isfile(meta_path):
        return False
    try:
        os.remove(file_path)
        os.remove(meta_path)
        return True
    except OSError:
        return False
