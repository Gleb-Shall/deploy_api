"""
Fingerprint-based AES-GCM CSS encryption.

Browser collects 20+ signals, server detects headless browser signals,
then encrypts CSS with a fresh AES-128-GCM key returned to the browser.
"""
import json
import os
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HEADLESS_SCORE_THRESHOLD = 5


def score_headless(fp: dict) -> int:
    """Score fingerprint for headless browser signals. >= 5 = likely bot.

    Returns an integer score; higher = more bot-like.
    """
    score = 0

    # navigator.webdriver = true → definitive headless indicator
    if fp.get("webdriver") is True:
        score += 5

    renderer = str(fp.get("webgl_renderer", "")).lower()
    if any(s in renderer for s in ("swiftshader", "llvmpipe", "softwarerasterizer")):
        score += 3

    vendor = str(fp.get("webgl_vendor", "")).lower()
    if "google" in vendor and "swiftshader" in vendor:
        score += 2

    plugins_count = fp.get("plugins_count")
    if isinstance(plugins_count, int) and plugins_count == 0:
        score += 2

    if fp.get("audio_error") is True:
        score += 1

    if fp.get("canvas_blank") is True:
        score += 2

    if fp.get("session_storage") is False:
        score += 1

    return score


def compute_fp_hash(fp: dict) -> str:
    """Stable SHA-256 hash of key fingerprint signals."""
    keys = [
        "canvas_hash", "webgl_renderer", "webgl_vendor", "timezone",
        "screen_width", "screen_height", "color_depth", "platform",
        "language", "cpu_cores", "memory_gb", "touch_points",
    ]
    stable = {k: fp.get(k) for k in keys}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def encrypt_css(css_bytes: bytes) -> dict:
    """Encrypt CSS with a fresh AES-128-GCM key.

    Returns dict with hex-encoded aes_key, iv, and ciphertext.
    """
    key = AESGCM.generate_key(bit_length=128)
    iv = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(iv, css_bytes, None)
    return {
        "aes_key": key.hex(),
        "iv": iv.hex(),
        "ciphertext": ciphertext.hex(),
    }
