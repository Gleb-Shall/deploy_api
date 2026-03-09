#!/usr/bin/env python3
"""
Парсит JSON (example.json) и создаёт папку с проектом для git push.
Использование: python3 scripts/parse_json_to_folder.py [output_dir]
"""
import hashlib
import json
import sys
from pathlib import Path


def parse_json(data):
    """Извлекает telegram_id и files из JSON."""
    if "files" not in data:
        raise ValueError("Missing 'files' field in JSON")
    files_list = data["files"]
    if not isinstance(files_list, list) or len(files_list) == 0:
        raise ValueError("'files' must be a non-empty list")

    first = files_list[0]
    telegram_id = first.get("telegram id") or first.get("telegram_id")
    if not telegram_id:
        raise ValueError("First item must contain 'telegram id' or 'telegram_id'")

    project_files = []
    for item in files_list[1:]:
        if "name" not in item or "content" not in item:
            raise ValueError("Each file must have 'name' and 'content'")
        project_files.append({"name": item["name"], "content": item["content"]})

    return str(telegram_id), project_files


def generate_hash(telegram_id, files):
    """Хэш из telegram_id и файлов (первые 12 символов SHA256)."""
    s = str(telegram_id)
    for f in sorted(files, key=lambda x: x["name"]):
        s += f["name"]
        s += json.dumps(f["content"], sort_keys=True) if isinstance(f["content"], dict) else str(f["content"])
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def prepare_content(content):
    """Строка для записи в файл."""
    return json.dumps(content, indent=2, ensure_ascii=False) if isinstance(content, dict) else str(content)


def main():
    root = Path(__file__).parent.parent
    example_path = root / "example.json"
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "parsed_project"

    if not example_path.exists():
        print(f"Файл {example_path} не найден")
        sys.exit(1)

    with open(example_path) as f:
        data = json.load(f)

    telegram_id, files = parse_json(data)
    page_hash = generate_hash(telegram_id, files)
    out = output_dir / page_hash
    out.mkdir(parents=True, exist_ok=True)

    for f in files:
        path = out / f["name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prepare_content(f["content"]), encoding="utf-8")
        print(f"  {f['name']}")

    print(f"\n✅ Проект: {out}")
    print(f"   Хэш: {page_hash}")
    print(f"\nДальше: cd {out} && git init && git add . && git commit -m 'Initial'")
    print(f"  git remote add origin git@сервер:sites/{page_hash}.git")
    print(f"  git push -u origin main")


if __name__ == "__main__":
    main()
