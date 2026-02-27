#!/usr/bin/env python3
"""
Однократное получение refresh_token для Яндекс.Вебмастер API.

1. Зарегистрируй приложение: https://oauth.yandex.ru — укажи права доступа к API Вебмастера.
2. Получи client_id и client_secret.
3. Запусти этот скрипт (локально), передай client_id и client_secret.
4. Открой в браузере выведенный URL, авторизуйся, скопируй code из редиректа (параметр code= в URL страницы «Подтвердите доступ» или из адресной строки после редиректа).
5. Вставь code в скрипт — получишь refresh_token. Сохрани его в /opt/deploy/seo/yandex_webmaster.json на сервере или в переменных окружения воркеров.

Запуск:
  python3 get_yandex_oauth_token.py
  # введи client_id, client_secret по запросу; открой URL; введи code
  # либо:
  YANDEX_CLIENT_ID=... YANDEX_CLIENT_SECRET=... python3 get_yandex_oauth_token.py
"""
import json
import os
import sys

OAUTH_AUTH_URL = "https://oauth.yandex.ru/authorize"
OAUTH_TOKEN_URL = "https://oauth.yandex.ru/token"


def main():
    client_id = os.environ.get("YANDEX_CLIENT_ID") or input("YANDEX_CLIENT_ID: ").strip()
    client_secret = os.environ.get("YANDEX_CLIENT_SECRET") or input("YANDEX_CLIENT_SECRET: ").strip()
    if not client_id or not client_secret:
        print("Need client_id and client_secret", file=sys.stderr)
        return 1

    auth_url = f"{OAUTH_AUTH_URL}?response_type=code&client_id={client_id}"
    print("Открой в браузере и авторизуйся:")
    print(auth_url)
    print()
    print("После подтверждения тебя перенаправит на страницу с адресом вида ...?code=XXXXX")
    print("Скопируй значение code (или вставь сюда полный URL редиректа).")
    code_input = input("code или URL: ").strip()
    code = code_input
    if "code=" in code_input:
        for part in code_input.replace("?", "&").split("&"):
            if part.startswith("code="):
                code = part.split("=", 1)[1]
                break
    if not code:
        print("Code not found", file=sys.stderr)
        return 2

    import urllib.request
    import urllib.parse
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")
    req = urllib.request.Request(OAUTH_TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"Exchange failed: {e}", file=sys.stderr)
        return 3

    refresh = data.get("refresh_token")
    if not refresh:
        print("No refresh_token in response:", data, file=sys.stderr)
        return 4
    print()
    print("refresh_token (сохрани в секрете):")
    print(refresh)
    out = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh,
    }
    path = os.environ.get("YANDEX_WEBMASTER_CREDENTIALS", "yandex_webmaster.json")
    if path != "yandex_webmaster.json" or os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"Сохранено в {path}")
    else:
        print("Чтобы сохранить в файл: YANDEX_WEBMASTER_CREDENTIALS=/opt/deploy/seo/yandex_webmaster.json python3 get_yandex_oauth_token.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
