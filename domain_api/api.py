"""
REST API для работы с доменами через Beget.
"""
import re
import hmac
import secrets
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from functools import wraps
from config import (
    API_HOST,
    API_PORT,
    API_DEBUG,
    API_KEY,
    MAX_DOMAIN_PRICE,
    CHALLENGE_SECRET,
    CHALLENGE_DIFFICULTY,
    CHALLENGE_TOKEN_TTL,
    REDIS_HOST,
    REDIS_PORT,
    CANARY_REDIRECT_URL,
    FINGERPRINT_KEY_TTL,
    SCREENSHOT_TOKEN_TTL,
    ALLOWED_ORIGINS,
    DOMAIN_CHECK_ALLOWED_IPS,
)
from canary import resolve_canary_token, log_canary_hit
from fingerprint import score_headless, encrypt_css, HEADLESS_SCORE_THRESHOLD
from beget_client import BegetClient, BegetAPIError
import traceback
import hashlib
import time
import redis as redis_lib
import jwt as pyjwt

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'analytics.db')

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS analytics_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                path TEXT NOT NULL,
                session_id TEXT NOT NULL,
                referrer TEXT,
                target_data TEXT,
                ip TEXT,
                user_agent TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
init_db()

_ANALYTICS_JS = """
(function(){
  var s=document.currentScript;
  var sid = null;
  if(s){
    sid = s.getAttribute('data-site-id') || new URL(s.src).searchParams.get('site_id');
  }else{
    var scripts=document.getElementsByTagName('script');
    for(var i=0;i<scripts.length;i++){
      if(scripts[i].src && scripts[i].src.indexOf('/api/app-state.js')!==-1){
        sid=new URL(scripts[i].src).searchParams.get('site_id');
        break;
      }
    }
  }
  if(!sid)return;
  var sess=sessionStorage.getItem('_asid');
  if(!sess){sess=Math.random().toString(36).substring(2)+Date.now().toString(36);sessionStorage.setItem('_asid',sess);}
  var api='https://automatoria.ru/api/app-state/sync';
  
  function send(type, data) {
    var d={
      site_id:sid,
      event_type:type,
      path:window.location.pathname,
      session_id:sess,
      referrer:document.referrer||'',
      target_data: data||''
    };
    try{
      if(navigator.sendBeacon) navigator.sendBeacon(api, JSON.stringify(d));
      else fetch(api, {method:'POST', body:JSON.stringify(d), keepalive:true});
    }catch(e){}
  }
  
  send('pageview');
  
  document.addEventListener('click', function(e){
    var el = e.target.closest('a, button');
    if(el){
      var text = (el.innerText || el.value || '').substring(0, 50).trim();
      var href = el.href || '';
      var data = JSON.stringify({text: text, href: href});
      send('click', data);
    }
  });
})();"""

# Валидация: домен .ru (в т.ч. sub.example.ru), период 1–10 лет
DOMAIN_RU_RE = re.compile(r"^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+ru$", re.IGNORECASE)
PERIOD_MIN, PERIOD_MAX = 1, 10

client = BegetClient()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB для JSON-запросов
# Отключаем CORS полностью - API только для локального использования
# CORS(app)  # Закомментировано для безопасности

# Rate limiting для защиты от злоупотреблений
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per hour", "10 per minute"]
)


def check_local_only():
    """Проверяет, что запрос приходит только с localhost"""
    if API_HOST == '127.0.0.1' or API_HOST == 'localhost':
        # Проверяем, что запрос действительно с localhost
        remote_addr = request.environ.get('REMOTE_ADDR', '')
        # Разрешаем только localhost (127.0.0.1, ::1, localhost)
        allowed_hosts = ['127.0.0.1', '::1', 'localhost']
        if remote_addr not in allowed_hosts:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'FORBIDDEN',
                    'message': 'Доступ разрешён только с localhost'
                }
            }), 403
    return None


@app.before_request
def before_request():
    """Проверка перед каждым запросом"""
    # Public endpoints (accessed from browser via nginx proxy)
    if request.path.startswith('/api/challenge'):
        return None
    if request.path.startswith('/r/'):
        return None
    if request.path in ('/api/fingerprint-key', '/api/preview-js', '/api/app-state.js', '/api/app-state/sync'):
        return None
    # Domain check — accessible from whitelisted IPs (still requires API key via decorator)
    if request.path == '/api/domain/check':
        remote_addr = request.environ.get('REMOTE_ADDR', '')
        allowed = ['127.0.0.1', '::1', 'localhost'] + list(DOMAIN_CHECK_ALLOWED_IPS)
        if remote_addr not in allowed:
            return jsonify({
                'success': False,
                'error': {'code': 'FORBIDDEN', 'message': 'IP не в белом списке'}
            }), 403
        return None
    # Все остальные — только с localhost
    error_response = check_local_only()
    if error_response:
        return error_response


def require_api_key(f):
    """Декоратор для проверки API ключа"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if API_KEY:
            # Предпочтительно X-API-Key (api_key в URL может попасть в логи)
            provided_key = request.headers.get('X-API-Key') or request.args.get('api_key')
            if not provided_key or not hmac.compare_digest(provided_key, API_KEY):
                return jsonify({
                    'success': False,
                    'error': {
                        'code': 'UNAUTHORIZED',
                        'message': 'Неверный или отсутствующий API ключ'
                    }
                }), 401
        return f(*args, **kwargs)
    return decorated_function


@app.errorhandler(BegetAPIError)
def handle_beget_error(error):
    """Обработчик ошибок Beget API"""
    return jsonify({
        'success': False,
        'error': {
            'code': error.error_code,
            'message': error.error_text
        }
    }), 400


@app.errorhandler(Exception)
def handle_general_error(error):
    """Обработчик общих ошибок"""
    app.logger.error(f"Unhandled error: {traceback.format_exc()}")
    return jsonify({
        'success': False,
        'error': {
            'code': 'INTERNAL_ERROR',
            'message': str(error)
        }
    }), 500


@app.route('/health', methods=['GET'])
def health():
    """Проверка работоспособности API"""
    return jsonify({
        'success': True,
        'status': 'ok'
    })


@app.route('/api/domain/check', methods=['POST'])
@limiter.limit("20 per minute")  # Ограничение: 20 проверок в минуту
@require_api_key
def check_domain():
    """
    Проверка доступности домена
    
    Request body:
    {
        "domain": "example.ru",
        "is_transfer": false,  # опционально
        "currency": "RUR"      # опционально
    }
    
    Response:
    {
        "success": true,
        "available": true,
        "domain": "example.ru",
        "price": 199,
        "renew_price": 199,
        "currency": "RUR",
        "is_premium": false
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'domain' not in data:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'MISSING_DOMAIN',
                    'message': 'Параметр domain обязателен'
                }
            }), 400
        
        domain = data['domain']
        if not isinstance(domain, str) or not domain.strip():
            return jsonify({
                'success': False,
                'error': {'code': 'INVALID_DOMAIN', 'message': 'domain должен быть непустой строкой'}
            }), 400
        domain = domain.strip().lower()
        if not DOMAIN_RU_RE.match(domain):
            return jsonify({
                'success': False,
                'error': {'code': 'INVALID_DOMAIN', 'message': 'Поддерживаются только домены вида name.ru'}
            }), 400
        try:
            period = int(data.get('period', 1))
            if not (PERIOD_MIN <= period <= PERIOD_MAX):
                period = 1
        except (TypeError, ValueError):
            period = 1
        result = client.check_domain(domain=domain, period=period)
        
        # Проверяем максимальную цену
        price = result.get('price')
        if price:
            try:
                price_float = float(price)
                if price_float > MAX_DOMAIN_PRICE:
                    result['price_exceeds_limit'] = True
                    result['max_allowed_price'] = MAX_DOMAIN_PRICE
                    result['warning'] = f'Цена домена ({price_float} руб.) превышает максимально допустимую ({MAX_DOMAIN_PRICE} руб.)'
            except (ValueError, TypeError):
                pass  # Если цена не число, пропускаем проверку
        
        return jsonify({
            'success': True,
            **result
        })
        
    except BegetAPIError:
        raise
    except Exception as e:
        app.logger.error(f"Error checking domain: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': {
                'code': 'INTERNAL_ERROR',
                'message': str(e)
            }
        }), 500



# ============================================================
# Anti-Scraping: JS Challenge endpoints
# ============================================================

def _redis_client():
    """Get Redis client for challenge nonce storage."""
    try:
        r = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


@app.route('/api/challenge', methods=['GET'])
@limiter.limit("30 per minute")
def get_challenge():
    """Issue a PoW challenge."""
    challenge = hashlib.sha256(
        f"{time.time()}{request.remote_addr}".encode()
    ).hexdigest()
    expires_in = 60

    r = _redis_client()
    if r:
        r.setex(f"challenge:{challenge}", expires_in, "pending")

    return jsonify({
        "success": True,
        "challenge": challenge,
        "difficulty": CHALLENGE_DIFFICULTY,
        "expires_in": expires_in,
    })


@app.route('/api/challenge-token', methods=['POST'])
@limiter.limit("20 per minute")
def verify_challenge():
    """Verify PoW solution, issue short-lived access token."""
    if not CHALLENGE_SECRET:
        return jsonify({"success": False, "error": {"code": "NOT_CONFIGURED", "message": "Challenge secret not set"}}), 503

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": {"code": "INVALID_JSON", "message": "JSON body required"}}), 400

    challenge = (data.get("challenge") or "").strip()
    nonce = str(data.get("nonce") or "").strip()

    if not challenge or not nonce:
        return jsonify({"success": False, "error": {"code": "MISSING_FIELDS", "message": "challenge and nonce required"}}), 400

    if len(nonce) > 20:
        return jsonify({"success": False, "error": {"code": "INVALID_NONCE", "message": "nonce too long"}}), 400

    r = _redis_client()
    if r:
        key = f"challenge:{challenge}"
        val = r.get(key)
        if not val:
            return jsonify({"success": False, "error": {"code": "CHALLENGE_EXPIRED", "message": "Challenge expired or already used"}}), 400
        r.delete(key)

    attempt = hashlib.sha256(f"{challenge}{nonce}".encode()).hexdigest()
    required_prefix = "0" * CHALLENGE_DIFFICULTY
    if not attempt.startswith(required_prefix):
        return jsonify({"success": False, "error": {"code": "INVALID_SOLUTION", "message": "PoW verification failed"}}), 400

    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + CHALLENGE_TOKEN_TTL,
        "sub": "antibot",
        "ip": request.remote_addr,
    }
    token = pyjwt.encode(payload, CHALLENGE_SECRET, algorithm="HS256")

    return jsonify({
        "success": True,
        "token": token,
        "expires_in": CHALLENGE_TOKEN_TTL,
    })


@app.route('/api/challenge-verify', methods=['GET'])
@limiter.limit("60 per minute")
def verify_token():
    """Verify antibot token — used by nginx auth_request. Returns 200 or 401."""
    if not CHALLENGE_SECRET:
        return "", 200

    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        token = request.cookies.get("ab_token")
    if not token:
        token = request.args.get("token")

    if not token:
        return jsonify({"error": "No token"}), 401

    try:
        pyjwt.decode(token, CHALLENGE_SECRET, algorithms=["HS256"])
        return "", 200
    except pyjwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except pyjwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401

# ============================================================
# Anti-Scraping: Canary redirect
# ============================================================

@app.route('/r/<token>', methods=['GET'])
@limiter.limit("30 per minute")
def canary_redirect(token: str):
    """Canary link — logs referrer (detects stolen HTML), redirects to Wikipedia."""
    from flask import redirect
    r = _redis_client()
    if r and token:
        meta = resolve_canary_token(r, token)
        page_hash = (meta or {}).get("page_hash", "")
        log_canary_hit(
            r,
            token=token,
            page_hash=page_hash,
            referer=request.headers.get("Referer", ""),
            ip=request.remote_addr or "",
            ua=request.headers.get("User-Agent", ""),
        )
    return redirect(CANARY_REDIRECT_URL, code=302)


# ============================================================
# Anti-Scraping: Fingerprint-based AES key for CSS delivery
# ============================================================

# Minified fingerprint collector + CSS decryptor injected via nginx sub_filter.
# Placeholders replaced per-request in /api/preview-js:
#   {{page_hash}}      — site hash
#   {{canary_tokens}}  — JSON array of canary tokens from Redis
_PREVIEW_JS = r"""(function(){'use strict';
var H='{{page_hash}}',A='https://automatoria.ru';
var _h=window.location.hostname;
if(_h!=='automatoria.ru'&&_h!=='preview.automatoria.ru'&&_h!=='www.automatoria.ru'){window.location.replace('https://automatoria.ru');return;}
function hx(h){var b=new Uint8Array(h.length/2);for(var i=0;i<h.length;i+=2)b[i/2]=parseInt(h.substr(i,2),16);return b;}
function fp(){var f={};f.webdriver=!!navigator.webdriver;f.plugins_count=navigator.plugins?navigator.plugins.length:-1;f.pdf_viewer=!!navigator.pdfViewerEnabled;f.language=navigator.language||'';f.platform=navigator.platform||'';f.cpu_cores=navigator.hardwareConcurrency||0;f.memory_gb=navigator.deviceMemory||0;f.touch_points=navigator.maxTouchPoints||0;f.timezone=(Intl.DateTimeFormat().resolvedOptions()||{}).timeZone||'';f.screen_width=screen.width;f.screen_height=screen.height;f.color_depth=screen.colorDepth;try{var c=document.createElement('canvas');c.width=240;c.height=60;var x=c.getContext('2d');x.textBaseline='top';x.font='14px Arial';x.fillStyle='#f60';x.fillRect(125,1,62,20);x.fillStyle='#069';x.fillText('Cwm fjordbank glyphs vext quiz',2,15);x.fillStyle='rgba(102,204,0,0.7)';x.fillText('Cwm fjordbank glyphs vext quiz',4,17);var u=c.toDataURL(),h=0;for(var i=0;i<u.length;i++){h=((h<<5)-h)+u.charCodeAt(i);h|=0;}f.canvas_hash=h.toString(16);f.canvas_blank=u.length<200;}catch(e){f.canvas_hash='';f.canvas_blank=true;}try{var g=document.createElement('canvas').getContext('webgl')||document.createElement('canvas').getContext('experimental-webgl');if(g){var d=g.getExtension('WEBGL_debug_renderer_info');f.webgl_renderer=d?g.getParameter(d.UNMASKED_RENDERER_WEBGL):'';f.webgl_vendor=d?g.getParameter(d.UNMASKED_VENDOR_WEBGL):'';}else{f.webgl_renderer='';f.webgl_vendor='';}}catch(e){f.webgl_renderer='';f.webgl_vendor='';}try{f.audio_error=!(window.AudioContext||window.webkitAudioContext);}catch(e){f.audio_error=true;}try{sessionStorage.setItem('_t','1');sessionStorage.removeItem('_t');f.session_storage=true;}catch(e){f.session_storage=false;}return f;}
function injectCSS(k,iv,ct){var kb=hx(k),ib=hx(iv),cb=hx(ct);crypto.subtle.importKey('raw',kb,{name:'AES-GCM'},false,['decrypt']).then(function(key){return crypto.subtle.decrypt({name:'AES-GCM',iv:ib},key,cb);}).then(function(d){var s=document.createElement('style');s.textContent=new TextDecoder().decode(d);document.head.appendChild(s);}).catch(function(){});}
async function sp(c,d){var p='0'.repeat(d),e=new TextEncoder();for(var n=0;n<1e7;n++){var b=await crypto.subtle.digest('SHA-256',e.encode(c+n));var x=Array.from(new Uint8Array(b)).map(function(v){return v.toString(16).padStart(2,'0');}).join('');if(x.startsWith(p))return n;}return null;}
function ic(ts){if(!ts||!ts.length)return;var d=document.createElement('div');d.style.cssText='position:absolute;overflow:hidden;width:0;height:0';d.setAttribute('aria-hidden','true');ts.forEach(function(t){var a=document.createElement('a');a.href=A+'/r/'+t;d.appendChild(a);});if(document.body)document.body.appendChild(d);else document.addEventListener('DOMContentLoaded',function(){document.body&&document.body.appendChild(d);});}
ic({{canary_tokens}});
var ck='_css_'+H;
try{var ca=JSON.parse(sessionStorage.getItem(ck)||'null');if(ca&&ca.k){injectCSS(ca.k,ca.i,ca.t);return;}}catch(e){}
(async function(){try{
var ct='';
try{var cr=await fetch(A+'/api/challenge').then(function(r){return r.json();});if(cr&&cr.success){var nonce=await sp(cr.challenge,cr.difficulty);if(nonce!==null){var tr=await fetch(A+'/api/challenge-token',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({challenge:cr.challenge,nonce:nonce})}).then(function(r){return r.json();});if(tr&&tr.success)ct=tr.token;}}}catch(e){}
var hd={'Content-Type':'application/json'};if(ct)hd['X-Challenge-Token']=ct;
var d=await fetch(A+'/api/fingerprint-key',{method:'POST',headers:hd,credentials:'omit',body:JSON.stringify({page_hash:H,fingerprint:fp()})}).then(function(r){return r.json();});
if(d.success){try{sessionStorage.setItem(ck,JSON.stringify({k:d.aes_key,i:d.iv,t:d.ciphertext}));}catch(e){}injectCSS(d.aes_key,d.iv,d.ciphertext);}
}catch(e){}})();
})();"""


def _allowed_origin(skip: bool) -> bool:
    """Return True if request Origin/Referer is from an allowed domain.

    Always True when skip=True (screenshot bypass).
    Always True for requests from localhost (internal calls).
    """
    if skip:
        return True
    # Internal Playwright / deploy scripts call the API directly on localhost
    remote = request.environ.get("REMOTE_ADDR", "")
    if remote in ("127.0.0.1", "::1"):
        return True
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin:
        return any(origin == o for o in ALLOWED_ORIGINS)
    referer = request.headers.get("Referer") or ""
    return any(referer.startswith(o) for o in ALLOWED_ORIGINS)


@app.route('/api/fingerprint-key', methods=['POST'])
@limiter.limit("20 per minute")
def fingerprint_key():
    """Validate browser fingerprint, return AES-GCM encrypted CSS bundle."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": {"code": "INVALID_JSON", "message": "JSON required"}}), 400

    page_hash = str(data.get("page_hash") or "").strip()
    fp = data.get("fingerprint") or {}

    if not page_hash or not re.match(r'^[a-zA-Z0-9_-]+$', page_hash) or not isinstance(fp, dict):
        return jsonify({"success": False, "error": {"code": "MISSING_FIELDS", "message": "page_hash and fingerprint required"}}), 400

    # Screenshot token bypass: skip headless/origin/challenge checks for internal Playwright
    skip_headless = False
    screenshot_token = request.headers.get("X-Screenshot-Token", "").strip()
    if screenshot_token:
        r_tok = _redis_client()
        if r_tok:
            try:
                consumed = r_tok.getdel(f"screenshot_token:{screenshot_token}")
            except Exception:
                # Fallback for Redis < 6.2 without getdel
                consumed = r_tok.get(f"screenshot_token:{screenshot_token}")
                if consumed:
                    r_tok.delete(f"screenshot_token:{screenshot_token}")
            if consumed:
                skip_headless = True
            else:
                app.logger.warning(f"Invalid/expired screenshot token ip={request.remote_addr}")

    # Origin/Referer validation: block requests not coming from our domain
    if not _allowed_origin(skip_headless):
        app.logger.info(f"Fingerprint blocked (bad origin) page={page_hash} ip={request.remote_addr} "
                        f"origin={request.headers.get('Origin')} referer={request.headers.get('Referer')}")
        return jsonify({"success": False, "error": {"code": "BLOCKED", "message": "Access denied"}}), 403

    # PoW challenge token validation (skip for screenshot bypass)
    if not skip_headless and CHALLENGE_SECRET:
        challenge_token = request.headers.get("X-Challenge-Token", "").strip()
        if not challenge_token:
            return jsonify({"success": False, "error": {"code": "CHALLENGE_REQUIRED", "message": "Challenge token required"}}), 403
        try:
            payload = pyjwt.decode(challenge_token, CHALLENGE_SECRET, algorithms=["HS256"])
            if payload.get("sub") != "antibot":
                raise pyjwt.InvalidTokenError("invalid sub")
        except pyjwt.ExpiredSignatureError:
            return jsonify({"success": False, "error": {"code": "CHALLENGE_EXPIRED", "message": "Challenge token expired"}}), 403
        except pyjwt.InvalidTokenError:
            return jsonify({"success": False, "error": {"code": "CHALLENGE_INVALID", "message": "Invalid challenge token"}}), 403

    if not skip_headless:
        bot_score = score_headless(fp)
        if bot_score >= HEADLESS_SCORE_THRESHOLD:
            app.logger.info(f"Fingerprint blocked (score={bot_score}) page={page_hash} ip={request.remote_addr}")
            return jsonify({"success": False, "error": {"code": "BLOCKED", "message": "Access denied"}}), 403

    r = _redis_client()
    if not r:
        return jsonify({"success": False, "error": {"code": "SERVICE_UNAVAILABLE", "message": "Service unavailable"}}), 503

    css_data = r.get(f"css_bundle:{page_hash}")
    if not css_data:
        return jsonify({"success": False, "error": {"code": "CSS_NOT_FOUND", "message": "CSS bundle not available"}}), 404

    css_bytes = css_data.encode("utf-8") if isinstance(css_data, str) else css_data
    encrypted = encrypt_css(css_bytes)
    return jsonify({"success": True, **encrypted})


@app.route('/api/preview-js', methods=['GET'])
@limiter.limit("60 per minute")
def preview_js():
    """Return minified fingerprint collector + CSS decryptor JS for a preview page.

    Canary tokens are fetched from Redis and embedded directly in the JS response
    so they never appear in the static HTML (invisible to curl scrapers).
    Cache-Control: no-store because canary tokens rotate on every deploy.
    """
    page_hash = (request.args.get('h') or '').strip()
    if not page_hash or not re.match(r'^[a-zA-Z0-9_-]+$', page_hash):
        return '', 400

    canary_tokens = '[]'
    r = _redis_client()
    if r:
        try:
            raw = r.get(f"canary:page:{page_hash}")
            if raw:
                canary_tokens = raw
        except Exception:
            pass

    js = _PREVIEW_JS.replace('{{page_hash}}', page_hash).replace('{{canary_tokens}}', canary_tokens)
    response = app.make_response(js)
    response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store'
    return response


# ============================================================
# Anti-Scraping: One-time screenshot token (localhost only)
# ============================================================

@app.route('/api/internal/screenshot-token', methods=['POST'])
@limiter.limit("30 per minute")
def create_screenshot_token():
    """Issue a one-time bypass token for Playwright screenshot service.

    Token is stored in Redis with TTL and consumed atomically on first use.
    Localhost-only (enforced by before_request → check_local_only).
    """
    r = _redis_client()
    if not r:
        return jsonify({"success": False, "error": {"code": "SERVICE_UNAVAILABLE", "message": "Redis unavailable"}}), 503

    token = secrets.token_urlsafe(32)
    r.setex(f"screenshot_token:{token}", SCREENSHOT_TOKEN_TTL, "1")
    return jsonify({"success": True, "token": token, "ttl": SCREENSHOT_TOKEN_TTL})


# ============================================================
# Anti-Scraping: CSS bundle storage (localhost only)
# ============================================================

@app.route('/api/css-bundle', methods=['POST'])
@require_api_key
def store_css_bundle():
    """Store obfuscated CSS bundle in Redis for a page hash.

    Called by deploy_single.sh after Docker build.
    Localhost-only (enforced by before_request).
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": {"code": "INVALID_JSON", "message": "JSON required"}}), 400

    page_hash = str(data.get("page_hash") or "").strip()
    css_data = data.get("css_data") or ""

    if not page_hash or not re.match(r'^[a-zA-Z0-9_-]+$', page_hash) or not css_data:
        return jsonify({"success": False, "error": {"code": "MISSING_FIELDS", "message": "page_hash and css_data required"}}), 400

    r = _redis_client()
    if not r:
        return jsonify({"success": False, "error": {"code": "SERVICE_UNAVAILABLE", "message": "Redis unavailable"}}), 503

    ttl = 30 * 24 * 3600  # 30 days
    r.setex(f"css_bundle:{page_hash}", ttl, css_data)
    return jsonify({"success": True})


@app.route("/api/app-state.js", methods=["GET"])
def get_analytics_js():
    response = app.make_response(_ANALYTICS_JS)
    response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response

@app.route("/api/app-state/sync", methods=["POST", "OPTIONS"])
def analytics_event():
    if request.method == 'OPTIONS':
        resp = app.make_default_options_response()
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp

    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"success": False}), 400

    site_id = str(data.get("site_id", "")).strip()
    if not site_id:
        return jsonify({"success": False}), 400

    event_type = str(data.get("event_type", "pageview"))
    path = str(data.get("path", ""))
    session_id = str(data.get("session_id", ""))
    referrer = str(data.get("referrer", ""))
    target_data = str(data.get("target_data", ""))
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO analytics_events (site_id, event_type, path, session_id, referrer, target_data, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (site_id, event_type, path, session_id, referrer, target_data, request.remote_addr, request.headers.get("User-Agent", ""))
        )
    
    resp = jsonify({"success": True})
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

if __name__ == '__main__':
    app.run(
        host=API_HOST,
        port=API_PORT,
        debug=API_DEBUG
    )
