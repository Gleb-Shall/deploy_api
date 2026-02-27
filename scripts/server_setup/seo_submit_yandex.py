#!/usr/bin/env python3
"""
Отправка сайта и sitemap в Яндекс.Вебмастер через API (OAuth).
При необходимости запускает верификацию методом HTML-файл: создаёт файл на сервере,
добавляет location в nginx, дергает API верификации.

Использование:
  YANDEX_CLIENT_ID=... YANDEX_CLIENT_SECRET=... YANDEX_REFRESH_TOKEN=... \\
    python3 seo_submit_yandex.py <domain>

Или один раз сохранить креды в JSON (например /opt/deploy/seo/yandex_webmaster.json):
  {"client_id": "...", "client_secret": "...", "refresh_token": "..."}

Требования:
  - Приложение зарегистрировано в https://oauth.yandex.ru (доступ к API Вебмастера).
  - Пользователь один раз прошёл OAuth → получен refresh_token (см. get_yandex_oauth_token.py).
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
from urllib.error import HTTPError

API_BASE = "https://api.webmaster.yandex.net/v4"
OAUTH_TOKEN_URL = "https://oauth.yandex.ru/token"
NGINX_CUSTOM_DIR = "/etc/nginx/sites-available/deploy/custom"
YANDEX_VERIFICATION_DIR = "/opt/deploy/yandex_verification"


def load_credentials():
    path = os.environ.get("YANDEX_WEBMASTER_CREDENTIALS")
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    cid = os.environ.get("YANDEX_CLIENT_ID")
    secret = os.environ.get("YANDEX_CLIENT_SECRET")
    ref = os.environ.get("YANDEX_REFRESH_TOKEN")
    if cid and secret and ref:
        return {"client_id": cid, "client_secret": secret, "refresh_token": ref}
    return None


def get_access_token(creds):
    import urllib.request
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": creds["refresh_token"],
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
    }).encode("utf-8")
    req = urllib.request.Request(OAUTH_TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    return data.get("access_token")


def api_get(access_token, path):
    import urllib.request
    url = API_BASE + path
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"OAuth {access_token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def api_post(access_token, path, body=None):
    import urllib.request
    url = API_BASE + path
    req = urllib.request.Request(url, method="POST")
    req.add_header("Authorization", f"OAuth {access_token}")
    if body is not None:
        req.data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            return resp.status, json.loads(data.decode()) if data else {}
    except HTTPError as e:
        body = e.read() if e.fp else b""
        return e.code, json.loads(body.decode()) if body else {}


def do_verification_html_file(domain, host_id_encoded, access_token, user_id, verification_uin):
    """Создать файл верификации, добавить location в nginx, перезагрузить nginx, вызвать POST verification."""
    import urllib.request
    dir_path = os.path.join(YANDEX_VERIFICATION_DIR, domain)
    os.makedirs(dir_path, exist_ok=True)
    filename = f"yandex_{verification_uin}.html"
    filepath = os.path.join(dir_path, filename)
    content = (
        "<html><head><meta http-equiv=\"Content-Type\" content=\"text/html; charset=UTF-8\"></head>"
        f"<body>Verification: {verification_uin}</body></html>"
    )
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    conf_path = os.path.join(NGINX_CUSTOM_DIR, f"{domain}.conf")
    if not os.path.isfile(conf_path):
        return False
    with open(conf_path, "r", encoding="utf-8") as f:
        conf = f.read()
    if f"location = /{filename}" in conf:
        pass
    else:
        match = re.search(r"\n(\s+)location / \{", conf)
        if match:
            indent = match.group(1)
            insert = f"\n{indent}location = /{filename} {{\n{indent}    alias {filepath};\n{indent}    default_type text/html;\n{indent}}}\n{indent}"
            conf = conf.replace(f"\n{indent}location / {{", insert + "location / {")
            with open(conf_path, "w", encoding="utf-8") as f:
                f.write(conf)
    try:
        r = subprocess.run(["nginx", "-t"], capture_output=True, timeout=5)
        if r.returncode != 0:
            return False
        subprocess.run(["systemctl", "reload", "nginx"], capture_output=True, timeout=10)
    except Exception:
        return False

    path = f"/user/{user_id}/hosts/{host_id_encoded}/verification?verification_type=HTML_FILE"
    code, _ = api_post(access_token, path)
    return code in (200, 201, 204)


def host_id_from_url(domain):
    return f"https:{domain}:443"


def main():
    creds = load_credentials()
    if not creds:
        print("Set YANDEX_CLIENT_ID, YANDEX_CLIENT_SECRET, YANDEX_REFRESH_TOKEN or YANDEX_WEBMASTER_CREDENTIALS", file=sys.stderr)
        return 1
    if len(sys.argv) < 2:
        return 2
    domain = sys.argv[1].strip().rstrip("/")
    if not domain:
        return 2
    host_url = f"https://{domain}/"
    sitemap_url = f"https://{domain}/sitemap.xml"

    try:
        access_token = get_access_token(creds)
    except Exception as e:
        print(f"Token refresh failed: {e}", file=sys.stderr)
        return 3

    try:
        user = api_get(access_token, "/user")
        user_id = user.get("user_id")
        if not user_id:
            print("No user_id in /user response", file=sys.stderr)
            return 4
    except Exception as e:
        print(f"GET /user failed: {e}", file=sys.stderr)
        return 5

    hosts_path = f"/user/{user_id}/hosts"
    try:
        hosts_data = api_get(access_token, hosts_path)
    except Exception as e:
        print(f"GET hosts failed: {e}", file=sys.stderr)
        return 6

    hosts = hosts_data.get("hosts") or []
    host_id = None
    for h in hosts:
        if h.get("ascii_host_url", "").rstrip("/") == host_url.rstrip("/") or host_id_from_url(domain) == h.get("host_id"):
            host_id = h.get("host_id")
            break
    if not host_id:
        code, body = api_post(access_token, hosts_path, {"host_url": host_url})
        if code == 201:
            host_id = body.get("host_id")
        elif code == 409:
            host_id = body.get("host_id")
        if not host_id:
            print(f"Could not get host_id (add host: {code} {body})", file=sys.stderr)
            return 7

    host_id_enc = urllib.parse.quote(host_id, safe="")
    verification_path = f"/user/{user_id}/hosts/{host_id_enc}/verification"
    try:
        verification_data = api_get(access_token, verification_path)
    except Exception:
        verification_data = {}
    verification_state = (verification_data.get("verification_state") or "").upper()
    verification_uin = verification_data.get("verification_uin") or ""

    if verification_state != "VERIFIED" and verification_uin:
        try:
            if do_verification_html_file(domain, host_id_enc, access_token, user_id, verification_uin):
                verification_state = "VERIFIED"
        except Exception as e:
            print(f"Verification attempt failed: {e}", file=sys.stderr)

    sitemaps_path = f"/user/{user_id}/hosts/{host_id_enc}/user-added-sitemaps"
    code, body = api_post(access_token, sitemaps_path, {"url": sitemap_url})
    if code in (200, 201):
        return 0
    if code == 404 and body.get("error_code") == "HOST_NOT_VERIFIED":
        try:
            v = api_get(access_token, verification_path)
            print(
                f"API: host_id={host_id}, verification_state={v.get('verification_state')!r}. "
                "Если в интерфейсе webmaster.yandex.ru сайт уже верифицирован — возможно, в списке два хоста (с www и без) или API обновится с задержкой.",
                file=sys.stderr,
            )
        except Exception:
            print("Site not verified in Yandex Webmaster (API). If you verified in the UI, check that the host matches (with/without www).", file=sys.stderr)
        return 8
    if code == 409 and body.get("error_code") == "SITEMAP_ALREADY_ADDED":
        return 0
    print(f"Yandex Webmaster API HTTP {code}: {body}", file=sys.stderr)
    return 9


if __name__ == "__main__":
    sys.exit(main())
