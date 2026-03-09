#!/usr/bin/env python3
"""
Однократное получение refresh_token для Google Search Console и Site Verification API.

1. В Google Cloud Console: APIs & Services → Credentials → Create OAuth 2.0 Client ID
   — тип «Desktop app» (или «Web application» с redirect_uri http://localhost:8080/).
2. Включи API: «Google Search Console API», «Google Site Verification API».
3. Запусти скрипт (локально), передай client_id и client_secret.
4. Открой в браузере выведенный URL, войди в свой Google-аккаунт, подтверди доступ.
5. После редиректа на localhost скрипт получит code и обменяет на refresh_token.
   Сохрани креды в /opt/deploy/seo/google_oauth.json на сервере или в переменных окружения воркеров.

Запуск:
  python3 get_google_oauth_token.py
  # введи client_id, client_secret по запросу; открой URL; при редиректе code подхватится
  # либо:
  GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python3 get_google_oauth_token.py
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

REDIRECT_PORT = 8080
SCOPES = (
    "https://www.googleapis.com/auth/webmasters "
    "https://www.googleapis.com/auth/siteverification"
)
OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Глобально для передачи code из HTTP handler в main
_code_result = None


class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _code_result
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code = (params.get("code") or [None])[0]
        error = (params.get("error") or [None])[0]
        # Устанавливаем результат только если в URL есть code или error (редирект от Google)
        if code:
            _code_result = ("ok", code)
        elif error:
            _code_result = ("error", error)
        # Иначе (favicon, лишние запросы) — не трогаем _code_result, просто отвечаем 200
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><p>Authorization received. You can close this tab.</p></body></html>"
        )

    def log_message(self, format, *args):
        pass


def main():
    global _code_result
    client_id = os.environ.get("GOOGLE_CLIENT_ID") or input("GOOGLE_CLIENT_ID: ").strip()
    client_secret = (
        os.environ.get("GOOGLE_CLIENT_SECRET") or input("GOOGLE_CLIENT_SECRET: ").strip()
    )
    if not client_id or not client_secret:
        print("Need client_id and client_secret", file=sys.stderr)
        return 1

    redirect_uri = f"http://localhost:{REDIRECT_PORT}/"
    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = OAUTH_AUTH_URL + "?" + urllib.parse.urlencode(auth_params)
    print("Открой в браузере и авторизуйся (войди в тот Google-аккаунт, к которому привязать сайты):")
    print(auth_url)
    print()
    print(f"Скрипт ждёт редирект на {redirect_uri} ...")

    server = HTTPServer(("", REDIRECT_PORT), OAuthHandler)
    # Ждём запрос с code (редирект от Google); первые запросы могут быть без code (favicon и т.п.)
    for _ in range(30):
        server.handle_request()
        if _code_result is not None:
            break

    if _code_result is None:
        print("Редирект не получен.", file=sys.stderr)
        return 2
    status, value = _code_result
    if status != "ok":
        print(f"Ошибка авторизации: {value}", file=sys.stderr)
        return 3
    code = value

    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }).encode("utf-8")
    req = urllib.request.Request(OAUTH_TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"Exchange failed: {e}", file=sys.stderr)
        return 4

    refresh = data.get("refresh_token")
    if not refresh:
        print("No refresh_token in response (try revoke access and run again with prompt=consent):", data, file=sys.stderr)
        return 5
    print()
    print("refresh_token получен (сохрани в секрете):")
    print(refresh)
    out = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh,
    }
    print()
    print("Полный JSON для GOOGLE_OAUTH_CREDENTIALS:")
    print(json.dumps(out, indent=2))
    path = os.environ.get("GOOGLE_OAUTH_CREDENTIALS", "google_oauth.json")
    if path != "google_oauth.json" or os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"\nСохранено в {path}")
    else:
        print("\nЧтобы сохранить в файл: GOOGLE_OAUTH_CREDENTIALS=/path/to/google_oauth.json python3 get_google_oauth_token.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
