from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import secrets
from pathlib import Path

PIN_FILE = Path(os.environ.get("GHOST_FUNNEL_PIN_FILE", "/var/lib/ghost-tesla-ai/funnel_pin.json"))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def main() -> int:
    print("GHOST Funnel PIN setup")
    print("This protects ONLY the public Tailscale Funnel gateway.")
    print("Direct Tailscale/LAN access to port 8766 stays unchanged.")
    print()

    p1 = getpass.getpass("Choose a 6-10 digit PIN: ").strip()
    if not p1.isdigit() or not 6 <= len(p1) <= 10:
        raise SystemExit("ERROR: PIN must contain 6-10 digits only.")
    p2 = getpass.getpass("Confirm PIN: ").strip()
    if p1 != p2:
        raise SystemExit("ERROR: PINs did not match.")

    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(p1.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    record = {
        "version": 1,
        "salt": _b64(salt),
        "pin_hash": _b64(digest),
        "session_secret": _b64(secrets.token_bytes(32)),
        "cookie_days": 30,
    }

    PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PIN_FILE.with_suffix(PIN_FILE.suffix + ".tmp")
    old_umask = os.umask(0o077)
    try:
        tmp.write_text(json.dumps(record, separators=(",", ":")) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, PIN_FILE)
        os.chmod(PIN_FILE, 0o600)
    finally:
        os.umask(old_umask)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    print()
    print("PASS - Funnel PIN configured.")
    print("File :", PIN_FILE)
    print("Mode : 0600")
    print("Login: use the HTTPS URL shown by: tailscale funnel status")
    print("The PIN is not stored in plaintext.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
