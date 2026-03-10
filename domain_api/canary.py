"""
Canary link system for detecting preview HTML theft.

Deploy generates 5 hidden links per page pointing to /r/<token>.
When a link is followed, this module logs the referer (detects stolen HTML).
"""
import json
import time
from typing import Optional

CANARY_TOKEN_PREFIX = "canary:token:"
CANARY_HITS_KEY = "canary:hits"
CANARY_HITS_MAX = 10000
CANARY_TOKEN_TTL = 365 * 24 * 3600  # 1 year


def resolve_canary_token(redis_client, token: str) -> Optional[dict]:
    """Look up a canary token. Returns metadata dict or None if not found."""
    raw = redis_client.get(f"{CANARY_TOKEN_PREFIX}{token}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def log_canary_hit(
    redis_client,
    token: str,
    page_hash: str,
    referer: str,
    ip: str,
    ua: str,
) -> None:
    """Log a canary link hit — someone loaded our HTML from another domain."""
    entry = json.dumps({
        "token": token,
        "page_hash": page_hash,
        "referer": referer,
        "ip": ip,
        "ua": ua,
        "ts": int(time.time()),
    })
    redis_client.lpush(CANARY_HITS_KEY, entry)
    redis_client.ltrim(CANARY_HITS_KEY, 0, CANARY_HITS_MAX - 1)
