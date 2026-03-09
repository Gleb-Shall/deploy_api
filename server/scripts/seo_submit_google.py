#!/usr/bin/env python3
"""
Опционально: добавление сайта в Google Search Console (к аккаунту пользователя) и отправка sitemap.

Два режима:

1) OAuth пользователя (сайт привязывается к твоему Google-аккаунту):
   GOOGLE_OAUTH_CREDENTIALS=/path/to/google_oauth.json python3 seo_submit_google.py <domain>
   или GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN в окружении.
   Скрипт: добавляет свойство в GSC, получает токен верификации (файл), создаёт файл на сервере,
   добавляет location в nginx, вызывает Site Verification API, отправляет sitemap.

2) Сервисный аккаунт (только отправка sitemap; свойство должно быть уже добавлено вручную):
   GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json python3 seo_submit_google.py <domain>

Требования: pip install google-auth (для сервисного аккаунта). Для OAuth пользователя — только stdlib.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

NGINX_CUSTOM_DIR = "/etc/nginx/sites-available/deploy/custom"
GOOGLE_VERIFICATION_DIR = "/opt/deploy/google_verification"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
WEBMASTERS_BASE = "https://www.googleapis.com/webmasters/v3"
SITE_VERIFICATION_BASE = "https://www.googleapis.com/siteVerification/v1"


def load_user_credentials():
    path = os.environ.get("GOOGLE_OAUTH_CREDENTIALS")
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    cid = os.environ.get("GOOGLE_CLIENT_ID")
    secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    ref = os.environ.get("GOOGLE_REFRESH_TOKEN")
    if cid and secret and ref:
        return {"client_id": cid, "client_secret": secret, "refresh_token": ref}
    return None


def get_user_access_token(creds):
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


def _user_request(access_token, method, url, data=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {access_token}")
    if data is not None:
        req.data = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read()
        return resp.status, json.loads(body.decode()) if body else {}


def add_site_to_search_console(access_token, site_url):
    site_enc = urllib.parse.quote(site_url, safe="")
    url = f"{WEBMASTERS_BASE}/sites/{site_enc}"
    req = urllib.request.Request(url, method="PUT")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Length", "0")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return True
        return False


def get_verification_token(access_token, site_url):
    url = f"{SITE_VERIFICATION_BASE}/token"
    body = {
        "site": {"type": "SITE", "identifier": site_url},
        "verificationMethod": "FILE",
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    return data.get("token")


def place_verification_file_and_nginx(domain, token):
    dir_path = os.path.join(GOOGLE_VERIFICATION_DIR, domain)
    os.makedirs(dir_path, exist_ok=True)
    filepath = os.path.join(dir_path, token)
    content = f"google-site-verification: {token}"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    conf_path = os.path.join(NGINX_CUSTOM_DIR, f"{domain}.conf")
    if not os.path.isfile(conf_path):
        return False
    with open(conf_path, "r", encoding="utf-8") as f:
        conf = f.read()
    if f"location = /{token}" in conf:
        pass
    else:
        match = re.search(r"\n(\s+)location / \{", conf)
        if match:
            indent = match.group(1)
            insert = (
                f"\n{indent}location = /{token} {{\n"
                f"{indent}    alias {filepath};\n"
                f"{indent}    default_type text/html;\n"
                f"{indent}}}\n{indent}"
            )
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
    return True


def verify_site(access_token, site_url):
    url = f"{SITE_VERIFICATION_BASE}/webResource?verificationMethod=FILE"
    body = {"site": {"type": "SITE", "identifier": site_url}}
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError:
        return False


def submit_sitemap_user(access_token, site_url, sitemap_url):
    site_enc = urllib.parse.quote(site_url, safe="")
    feedpath_enc = urllib.parse.quote(sitemap_url, safe="")
    url = f"{WEBMASTERS_BASE}/sites/{site_enc}/sitemaps/{feedpath_enc}"
    req = urllib.request.Request(url, method="PUT")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Length", "0")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return True
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        if e.code == 403:
            print(
                f"GSC sitemap PUT 403: {body[:500]}",
                file=sys.stderr,
            )
            print(
                "Сайт уже добавлен и верифицирован. 403 при sitemap часто временный — подожди 1–2 минуты и сделай повторный push/деплой или добавь sitemap вручную в Search Console.",
                file=sys.stderr,
            )
        raise


def run_user_flow(domain):
    site_url = f"https://{domain}/"
    sitemap_url = f"https://{domain}/sitemap.xml"
    creds = load_user_credentials()
    if not creds:
        return None
    access_token = get_user_access_token(creds)

    add_site_to_search_console(access_token, site_url)
    token = get_verification_token(access_token, site_url)
    if not token:
        print("Site Verification getToken: пустой token", file=sys.stderr)
        return 10
    if not place_verification_file_and_nginx(domain, token):
        print("Не удалось записать файл верификации или обновить nginx", file=sys.stderr)
        return 11
    if not verify_site(access_token, site_url):
        print(f"Site Verification insert не прошёл (проверь доступность файла по https://{domain}/{token})", file=sys.stderr)
        return 12
    # Небольшая пауза: GSC иногда отдаёт 403 на sitemap сразу после верификации
    time.sleep(2)
    try:
        submit_sitemap_user(access_token, site_url, sitemap_url)
    except Exception as e:
        print(f"GSC sitemap PUT: {e}", file=sys.stderr)
        return 13
    return 0


def run_service_account_flow(domain):
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path or not os.path.isfile(creds_path):
        return 1
    site_url = f"https://{domain}/"
    sitemap_url = f"https://{domain}/sitemap.xml"
    try:
        from google.oauth2 import service_account
    except ImportError:
        print("google-auth not installed; pip install google-auth", file=sys.stderr)
        return 3
    with open(creds_path, "r", encoding="utf-8") as f:
        key_data = json.load(f)
    client_email = key_data.get("client_email", "")
    credentials = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/webmasters"],
    )
    from google.auth.transport.requests import AuthorizedSession
    session = AuthorizedSession(credentials)
    site_enc = urllib.parse.quote(site_url, safe="")
    feedpath_enc = urllib.parse.quote(sitemap_url, safe="")
    url = f"{WEBMASTERS_BASE}/sites/{site_enc}/sitemaps/{feedpath_enc}"
    resp = session.put(url, timeout=15)
    if resp.status_code in (200, 201):
        return 0
    if resp.status_code == 403 and client_email:
        print(
            f"GSC: нет доступа к свойству {site_url} — добавь сервисный аккаунт вручную (API не умеет добавлять пользователей):",
            file=sys.stderr,
        )
        print(
            f"  1) Открой https://search.google.com/search-console → выбери свойство {site_url}",
            file=sys.stderr,
        )
        print(
            f"  2) Настройки → Пользователи и права → Добавить пользователя",
            file=sys.stderr,
        )
        print(f"  3) Вставь этот email и выбери «Владелец» или «Полный доступ»: {client_email}", file=sys.stderr)
    else:
        print(f"GSC API HTTP {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
    return 4


def main():
    if len(sys.argv) < 2:
        return 2
    domain = sys.argv[1].strip().rstrip("/")
    if not domain:
        return 2

    user_creds = load_user_credentials()
    if user_creds:
        result = run_user_flow(domain)
        if result is not None:
            return result

    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return run_service_account_flow(domain)

    print(
        "Задай GOOGLE_OAUTH_CREDENTIALS (или GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET + GOOGLE_REFRESH_TOKEN) "
        "либо GOOGLE_APPLICATION_CREDENTIALS",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
