#!/usr/bin/env python3
"""
Тест скриншота задеплоенного сайта с обходом fingerprint-защиты.

Требования:
  pip install playwright requests
  playwright install chromium

Переменные окружения (опционально):
  SCREENSHOT_API_URL  — базовый URL screenshot API (default: http://127.0.0.1:5051)
  SCREENSHOT_API_KEY  — X-API-Key для screenshot API
  TARGET_URL          — URL страницы для скриншота
  OUTPUT_PATH         — куда сохранить PNG (default: /tmp/screenshot_result.png)

Использование:
  python3 screenshot_test.py
"""

import os
import sys
import time
import urllib.request
import urllib.error
import json

from playwright.sync_api import sync_playwright

SCREENSHOT_API_URL = os.getenv("SCREENSHOT_API_URL", "http://127.0.0.1:5051").rstrip("/")
SCREENSHOT_API_KEY = os.getenv("SCREENSHOT_API_KEY", "")
TARGET_URL = os.getenv("TARGET_URL", "https://automatoria.ru/example5/")
OUTPUT_PATH = os.getenv("OUTPUT_PATH", "/tmp/screenshot_result.png")


def _json_post(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=b"", method="POST")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _upload_screenshot(png_bytes: bytes) -> dict:
    boundary = "----FormBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="screenshot.png"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + png_bytes + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{SCREENSHOT_API_URL}/api/screenshots",
        data=body,
        method="POST",
    )
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    if SCREENSHOT_API_KEY:
        req.add_header("X-API-Key", SCREENSHOT_API_KEY)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def main():
    t_start = time.perf_counter()

    # ── Step 1: получить одноразовый screenshot-токен ─────────────────────────
    t0 = time.perf_counter()
    token_headers = {}
    if SCREENSHOT_API_KEY:
        token_headers["X-API-Key"] = SCREENSHOT_API_KEY
    try:
        token_resp = _json_post(f"{SCREENSHOT_API_URL}/api/screenshot-token", token_headers)
    except Exception as exc:
        print(f"[ERROR] Не удалось получить токен: {exc}", file=sys.stderr)
        sys.exit(1)

    token = token_resp.get("token")
    if not token:
        print(f"[ERROR] Токен не получен: {token_resp}", file=sys.stderr)
        sys.exit(1)
    t_token = time.perf_counter() - t0
    print(f"[1] Токен получен за {t_token*1000:.0f} мс  (ttl={token_resp.get('ttl')}s)")

    # ── Step 2: скриншот через Playwright ─────────────────────────────────────
    t0 = time.perf_counter()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # Добавить X-Screenshot-Token ко всем запросам на fingerprint-key
        def add_token_header(route, request):
            headers = {**request.headers, "X-Screenshot-Token": token}
            route.continue_(headers=headers)

        page.route("**/api/fingerprint-key**", add_token_header)

        t_goto_start = time.perf_counter()
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30_000)
        t_goto = time.perf_counter() - t_goto_start
        print(f"[2a] page.goto() за {t_goto*1000:.0f} мс")

        # Ждём появления <style> — значит CSS расшифрован и вставлен
        t_css_start = time.perf_counter()
        try:
            page.wait_for_function(
                "() => document.head.querySelector('style') !== null",
                timeout=10_000,
            )
            t_css = time.perf_counter() - t_css_start
            print(f"[2b] CSS инжектирован за {t_css*1000:.0f} мс")
        except Exception:
            print("[2b] CSS так и не появился — защита не сработала или сайт не защищён")

        t_shot_start = time.perf_counter()
        png_bytes = page.screenshot(full_page=True)
        t_shot = time.perf_counter() - t_shot_start
        print(f"[2c] Скриншот за {t_shot*1000:.0f} мс  ({len(png_bytes)//1024} КБ)")

        browser.close()

    t_playwright = time.perf_counter() - t0
    print(f"[2] Playwright итого: {t_playwright*1000:.0f} мс")

    # Сохранить локально
    with open(OUTPUT_PATH, "wb") as f:
        f.write(png_bytes)
    print(f"[2d] Сохранён локально: {OUTPUT_PATH}")

    # ── Step 3: загрузить на screenshot API ───────────────────────────────────
    t0 = time.perf_counter()
    try:
        upload_resp = _upload_screenshot(png_bytes)
        t_upload = time.perf_counter() - t0
        url = upload_resp.get("data", {}).get("url", "—")
        print(f"[3] Загружен за {t_upload*1000:.0f} мс  → {url}")
    except Exception as exc:
        t_upload = time.perf_counter() - t0
        print(f"[3] Ошибка загрузки за {t_upload*1000:.0f} мс: {exc}")

    # ── Итого ─────────────────────────────────────────────────────────────────
    t_total = time.perf_counter() - t_start
    print(f"\n✅ Полный цикл: {t_total*1000:.0f} мс")


if __name__ == "__main__":
    main()
