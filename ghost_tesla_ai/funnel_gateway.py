from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import os
import secrets
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, make_response, redirect, request

PIN_FILE = Path(os.environ.get("GHOST_FUNNEL_PIN_FILE", "/var/lib/ghost-tesla-ai/funnel_pin.json"))
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8766
COOKIE = "ghost_funnel_session"
FAIL_WINDOW_S = 300
FAIL_MAX = 8
_FAIL_LOCK = threading.Lock()
_FAILS: list[float] = []

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

LOGIN_HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>GHOST Access</title>
<style>
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;background:#05080d;color:#e8f5ff;font-family:Arial,Helvetica,sans-serif}
body{display:flex;align-items:center;justify-content:center;background:radial-gradient(circle at 50% 20%,#10273a 0,#081019 34%,#05080d 72%)}
.card{width:min(520px,90vw);border:1px solid #1d5a78;border-radius:24px;padding:34px;background:rgba(6,13,20,.96);box-shadow:0 0 50px rgba(0,174,255,.16)}
.eyebrow{font-size:13px;letter-spacing:.2em;color:#61d8ff;font-weight:700}.title{font-size:34px;margin:8px 0 5px;font-weight:800}.sub{color:#91a7b8;font-size:15px;line-height:1.45;margin-bottom:25px}
input{width:100%;font-size:34px;letter-spacing:.28em;text-align:center;padding:18px 14px;border-radius:15px;border:1px solid #2a6988;background:#07121b;color:#fff;outline:none}
input:focus{border-color:#54d7ff;box-shadow:0 0 0 3px rgba(84,215,255,.12)}button{width:100%;margin-top:16px;padding:17px;border:0;border-radius:14px;background:#30c9ff;color:#031019;font-weight:900;font-size:18px}
.err{margin-top:14px;border:1px solid #873e4a;background:#261015;color:#ff9aa8;border-radius:11px;padding:11px;text-align:center}.foot{margin-top:20px;color:#667d8c;font-size:12px;text-align:center}
</style></head><body><div class="card"><div class="eyebrow">GHOST // SECURE FUNNEL</div><div class="title">Tesla Access</div><div class="sub">Enter the GHOST PIN to open the Winter Readiness Board on this public HTTPS endpoint.</div>
<form method="post" action="/__ghost_auth/login"><input autofocus inputmode="numeric" autocomplete="off" pattern="[0-9]*" name="pin" type="password" maxlength="10" placeholder="••••••" required><button type="submit">UNLOCK GHOST</button>__ERROR__</form>
<div class="foot">Public Funnel gateway • session remembered on this browser for 30 days</div></div></body></html>'''

SETUP_HTML = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GHOST PIN Setup Required</title><style>body{background:#05080d;color:#e8f5ff;font-family:Arial;margin:0;display:grid;place-items:center;height:100vh}.c{max-width:720px;padding:32px;border:1px solid #22526d;border-radius:20px;background:#09121b}code{color:#63dcff;font-size:16px}</style></head><body><div class="c"><h1>GHOST Funnel is locked</h1><p>No public PIN has been configured yet.</p><p>SSH to GHOST and run:</p><code>cd /opt/ghost-tesla-ai<br>./venv/bin/python -m ghost_tesla_ai.funnel_pin_setup</code></div></body></html>'''


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))


def _load_auth():
    try:
        obj = json.loads(PIN_FILE.read_text())
        if not all(obj.get(k) for k in ("salt", "pin_hash", "session_secret")):
            return None
        return obj
    except Exception:
        return None


def _pin_ok(pin: str, obj: dict) -> bool:
    try:
        got = hashlib.scrypt(pin.encode("utf-8"), salt=_b64d(obj["salt"]), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got, _b64d(obj["pin_hash"]))
    except Exception:
        return False


def _session_token(obj: dict) -> str:
    exp = int(time.time()) + int(obj.get("cookie_days", 30)) * 86400
    nonce = secrets.token_hex(12)
    payload = f"{exp}.{nonce}"
    sig = hmac.new(_b64d(obj["session_secret"]), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _session_ok(obj: dict) -> bool:
    raw = request.cookies.get(COOKIE, "")
    try:
        exp_s, nonce, sig = raw.split(".", 2)
        if int(exp_s) < int(time.time()):
            return False
        payload = f"{exp_s}.{nonce}"
        want = hmac.new(_b64d(obj["session_secret"]), payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, want)
    except Exception:
        return False


def _rate_limited() -> bool:
    now = time.time()
    with _FAIL_LOCK:
        _FAILS[:] = [x for x in _FAILS if now - x < FAIL_WINDOW_S]
        return len(_FAILS) >= FAIL_MAX


def _record_fail() -> None:
    with _FAIL_LOCK:
        _FAILS.append(time.time())


def _clear_fails() -> None:
    with _FAIL_LOCK:
        _FAILS.clear()


def _login_page(message: str = ""):
    error_html = "" if not message else f'<div class="err">{message}</div>'
    out = make_response(LOGIN_HTML.replace("__ERROR__", error_html), 200)
    out.headers["Cache-Control"] = "no-store"
    out.headers["X-Frame-Options"] = "DENY"
    out.headers["X-Content-Type-Options"] = "nosniff"
    return out


@app.get("/__ghost_auth/login")
def login_get():
    obj = _load_auth()
    if obj is None:
        return Response(SETUP_HTML, status=503, mimetype="text/html")
    if _session_ok(obj):
        return redirect("/")
    return _login_page()


@app.post("/__ghost_auth/login")
def login_post():
    obj = _load_auth()
    if obj is None:
        return Response(SETUP_HTML, status=503, mimetype="text/html")
    if _rate_limited():
        out = _login_page("Too many failed attempts. Try again in a few minutes.")
        out.status_code = 429
        out.headers["Retry-After"] = str(FAIL_WINDOW_S)
        return out
    pin = (request.form.get("pin") or "").strip()
    if not _pin_ok(pin, obj):
        _record_fail()
        time.sleep(0.7)
        return _login_page("Incorrect PIN")
    _clear_fails()
    out = redirect("/")
    out.set_cookie(
        COOKIE,
        _session_token(obj),
        max_age=int(obj.get("cookie_days", 30)) * 86400,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    out.headers["Cache-Control"] = "no-store"
    return out


@app.get("/__ghost_auth/logout")
def logout():
    out = redirect("/__ghost_auth/login")
    out.delete_cookie(COOKIE, path="/")
    return out


def _proxy(path: str):
    obj = _load_auth()
    if obj is None:
        return Response(SETUP_HTML, status=503, mimetype="text/html")
    if not _session_ok(obj):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "PIN authentication required"}), 401
        return _login_page()

    target = "/" + path
    if request.query_string:
        target += "?" + request.query_string.decode("latin1")
    body = request.get_data(cache=False)
    headers = {}
    for key, value in request.headers.items():
        if key.lower() in {"host", "connection", "content-length", "cookie", "transfer-encoding", "upgrade", "proxy-connection"}:
            continue
        headers[key] = value
    headers["Host"] = f"{BACKEND_HOST}:{BACKEND_PORT}"
    headers["X-GHOST-Funnel-Authenticated"] = "1"

    conn = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=35)
    try:
        conn.request(request.method, target, body=body, headers=headers)
        upstream = conn.getresponse()
        data = upstream.read()
        out = Response(data, status=upstream.status)
        safe = {"content-type", "cache-control", "expires", "last-modified", "etag", "content-disposition", "location"}
        for key, value in upstream.getheaders():
            if key.lower() in safe:
                if key.lower() == "location" and value.startswith(f"http://{BACKEND_HOST}:{BACKEND_PORT}"):
                    value = value.replace(f"http://{BACKEND_HOST}:{BACKEND_PORT}", "", 1) or "/"
                out.headers[key] = value
        out.headers["X-GHOST-Gateway"] = "PIN"
        return out
    except Exception as exc:
        return Response(f"GHOST backend unavailable: {type(exc).__name__}", status=502, mimetype="text/plain")
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.route("/", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def proxy_root():
    return _proxy("")


@app.route("/<path:path>", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def proxy_any(path):
    return _proxy(path)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8777, threaded=True)
