"""
Auth: password hashing (PBKDF2-HMAC-SHA256) + signed bearer tokens (HMAC-SHA256).

No external dependencies (no bcrypt/jose/JWT libraries) so this runs anywhere
with plain Python 3 - useful in network-restricted environments, and there's
nothing here that needs a security update from a third-party package.

For production: set GRANTPASS_SECRET to a long random value via environment
variable. The default below is ONLY for local development.
"""
import hashlib
import hmac
import os
import base64
import time

SERVER_SECRET = os.environ.get("GRANTPASS_SECRET", "dev-secret-change-me-in-production")
PBKDF2_ITERATIONS = 100_000
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


def hash_password(password: str, salt: bytes = None):
    if salt is None:
        salt = os.urandom(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return base64.b64encode(salt).decode(), base64.b64encode(pwd_hash).decode()


def verify_password(password: str, salt_b64: str, hash_b64: str) -> bool:
    try:
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return hmac.compare_digest(expected, actual)


def make_token(user_id: int, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    expiry = int(time.time()) + ttl_seconds
    payload = f"{user_id}:{expiry}"
    sig = hmac.new(SERVER_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_token(token: str):
    """Returns user_id (int) if valid and unexpired, else None."""
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        user_id, expiry, sig = raw.split(":")
        payload = f"{user_id}:{expiry}"
        expected_sig = hmac.new(SERVER_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, sig):
            return None
        if int(expiry) < time.time():
            return None
        return int(user_id)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# score_ref: signed handoff token from a completed free scorecard (this
# service) to the consulting site's contact form (frankly-inspired-backend,
# a separate Node service). This is the integration piece from the August
# 2026 wealth-transfer research brief ("the three touchpoints don't share
# state") - a visitor's stage/score/band now follows them into the contact
# form instead of them re-explaining their diagnostic from scratch.
#
# Token format: "<base64url(JSON payload, no padding)>.<hex HMAC-SHA256 sig>".
# frankly-inspired-backend verifies this independently in Node
# (scoreRef.js) using the SAME SCORE_REF_SECRET value - set it identically
# on both services' environment variables, or every token will fail
# verification on the receiving end.
SCORE_REF_SECRET = os.environ.get("SCORE_REF_SECRET", "dev-score-ref-secret-change-me-in-production")
SCORE_REF_TTL_SECONDS = 60 * 60 * 24 * 14  # 14 days - long enough for a visitor to come back later


def make_score_ref(stage: str, score, band: str, source: str = "demo", ttl_seconds: int = SCORE_REF_TTL_SECONDS) -> str:
    import json
    payload = {
        "stage": stage,
        "score": round(score) if isinstance(score, (int, float)) else None,
        "band": band,
        "src": source,
        "exp": int(time.time()) + ttl_seconds,
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).rstrip(b"=").decode()
    sig = hmac.new(SCORE_REF_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_score_ref(token: str):
    """Returns the decoded {stage, score, band, src, exp} dict if the token
    is validly signed and unexpired, else None."""
    import json
    try:
        payload_b64, sig = token.rsplit(".", 1)
        expected_sig = hmac.new(SCORE_REF_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, sig):
            return None
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None
