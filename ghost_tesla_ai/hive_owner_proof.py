"""Signed localhost attestation for PIN-authenticated Hive owner actions.

Only the GHOST PIN gateway holds the session and emits signed proofs over its
loopback backend connection. Untrusted X-GHOST-Funnel-Authenticated headers are
never authorization. Bound to method, path, Origin, body, timestamp and nonce.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

OWNER_PIN_FILE = Path(os.environ.get(
    "GHOST_FUNNEL_PIN_FILE", "/var/lib/ghost-tesla-ai/funnel_pin.json"))
MAX_SKEW_SECONDS = 30
MAX_NONCES = 2048
_NONCE_RE = re.compile(r"^[a-f0-9]{32}$")
_AUTH_LOCK = threading.Lock()
_SEEN: dict[str, float] = {}
HEADER_PREFIX = "X-Ghost-Owner-"

def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value+"="*((-len(value)) % 4))

def _key():
    try:
        path = OWNER_PIN_FILE
        if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
            return None
        if path.stat().st_size > 8192:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        key = _decode(data["session_secret"])
        return key if len(key)>=32 else None
    except (OSError,TypeError,ValueError,KeyError,OverflowError):
        return None

def allowed_browser_origin(origin: str, host: str) -> bool:
    # Gateway gets HTTPS from a TLS-terminating Tailscale Serve/Funnel proxy.
    # A plain HTTP backend Origin is not sufficient for remote cookie actions.
    if not origin or not host or len(origin)>512 or len(host)>255:
        return False
    try:
        u = urlsplit(origin)
        return (u.scheme=="https" and u.netloc==host
                and not u.path and not u.query and not u.fragment
                and u.username is None and u.password is None)
    except ValueError:
        return False

def _message(method: str, path: str, origin: str, body: bytes,
             timestamp: str, nonce: str) -> bytes:
    # Fixed-size body digest prevents boundary confusion in signatures.
    return ("\n".join((method,path,origin,timestamp,nonce,
                      hashlib.sha256(body).hexdigest()))).encode("utf-8")

def sign(method: str, path: str, origin: str, body: bytes, *,
         now: float | None=None) -> dict[str,str]:
    key=_key()
    if key is None:
        raise ValueError("Private GHOST owner PIN setup is required")
    if (method!="POST" or not path.startswith("/api/hive/control/")
        or not body or len(body)>1024 or not origin):
        raise ValueError("Only bounded Hive owner POST actions may be signed")
    timestamp=str(int(time.time() if now is None else now))
    nonce=secrets.token_hex(16)
    signature=hmac.new(key,_message(method,path,origin,body,timestamp,nonce),
                       hashlib.sha256).hexdigest()
    return {HEADER_PREFIX+"Timestamp":timestamp,
            HEADER_PREFIX+"Nonce":nonce,
            HEADER_PREFIX+"Signature":signature}

def verify(method: str,path: str,origin: str,body: bytes,headers,
           *,peer: str, now: float | None=None) -> bool:
    # Proxies are explicitly untrusted. Proofs are meaningful only when
    # delivered by a loopback process sharing the protected session key.
    if peer not in ("127.0.0.1","::1") or method!="POST" or len(body)>1024:
        return False
    if not path.startswith("/api/hive/control/"):
        return False
    key=_key()
    if key is None:return False
    timestamp=headers.get(HEADER_PREFIX+"Timestamp","")
    nonce=headers.get(HEADER_PREFIX+"Nonce","")
    signature=headers.get(HEADER_PREFIX+"Signature","")
    if (not timestamp.isascii() or not timestamp.isdigit() or
        not _NONCE_RE.fullmatch(nonce) or
        not re.fullmatch("[a-f0-9]{64}",signature)):
        return False
    clock=time.time() if now is None else now
    when=int(timestamp)
    if abs(clock-when)>MAX_SKEW_SECONDS:
        return False
    expected=hmac.new(key,_message(method,path,origin,body,timestamp,nonce),
                      hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature,expected):
        return False
    with _AUTH_LOCK:
        for n,seen in list(_SEEN.items()):
            if clock-seen > MAX_SKEW_SECONDS+2:del _SEEN[n]
        if nonce in _SEEN or len(_SEEN)>=MAX_NONCES:
            return False
        _SEEN[nonce]=clock
    return True
