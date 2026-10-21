#!/usr/bin/env python3
"""Prepare a PRIVATE, source-only review ZIP from a running GHOST Pi.

No services stopped or restarted. No network requests. No runtime DB, model
weights, credentials, logs, telemetry, trip history, or config files included.
The ZIP is for private review; do NOT upload it directly to a public repository.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ALLOWED_EXT = {".py", ".html", ".js", ".css", ".in"}
MAX_FILE_BYTES = 1_500_000
MAX_TOTAL_BYTES = 25_000_000
HOME_COMPONENTS = (
    "ghost-v62-memory-status",
    "ghost-v64-evidence-shadow",
    "ghost-v65-ambient-thermal-lab",
    "ghost-v651-thermal-model-lab",
    "ghost-v66-safe-production",
    "ghost-forecast-calibration",
)
UNITS = (
    "ghost-intelligence-collector.service",
    "ghost-intelligence-collector.timer",
    "ghost-intelligence-web.service",
    "ghost-intelligence-llm.service",
    "ghost-intelligence-v3-briefing.service",
    "ghost-intelligence-v3-briefing.timer",
    "ghost-v62-memory.service",
    "ghost-v62-memory.timer",
    "ghost-v66-watchdog.service",
    "ghost-v66-watchdog.timer",
    "ghost-thermal-range-recorder.service",
    "ghost-thermal-range-recorder.timer",
)
BLOCKED_FILE_WORDS = (
    "token", "password", "credential", "secret", "private", "telemetry",
    "sqlite", ".env", ".gguf", ".pem", ".key", "history", "journal",
    "snapshot", "snapshot", "backup", "model", "trip", "route",
)
# Only the extensions above are archived. The blocklist applies to file
# basenames, not parent names or source package names such as model_engine.py.
ALLOWED_SPECIAL_BASENAMES = {"trip_history.py", "trip_outcome.py"}
SENSITIVE = (
    ("credential literal", re.compile(
        r"(?i)\b(?:password|api[_-]?key|access[_-]?token|refresh[_-]?token|"
        r"secret)\s*=\s*['\"](?![\"'])([^'\"\r\n]{8,})['\"]")),
    ("access token", re.compile(
        r"(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{20,}|"
        r"sk-[A-Za-z0-9]{24,}|AKIA[0-9A-Z]{16})")),
    ("Bearer credential", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_./-]{24,}")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("private network address", re.compile(
        r"\b(?:192\.168\.|10\.(?:[0-9]{1,3})\.|100\.(?:6[4-9]|[789][0-9]|1[01][0-9]|12[0-7])\.)\d{1,3}\.\d{1,3}\b")),
)
UNIT_INLINE_CREDENTIAL = re.compile(
    r"(?im)^\s*Environment\s*=\s*.*(?:PASSWORD|TOKEN|SECRET|API_KEY)\s*=")

def possible_secrets(data: bytes, unit: bool = False) -> list[str]:
    try:
        txt = data.decode("utf-8")
    except UnicodeDecodeError:
        return ["non-UTF8 source"]
    findings = [label for label, rx in SENSITIVE if rx.search(txt)]
    if unit and UNIT_INLINE_CREDENTIAL.search(txt):
        findings.append("systemd inline credential")
    return findings

def source_roots(home: Path):
    result = [
        ("core/python", Path("/opt/ghost-tesla-ai/ghost_tesla_ai")),
        ("core/web", Path("/opt/ghost-tesla-ai/web")),
        ("intel/app", Path("/opt/ghost-intelligence/app")),
    ]
    for name in HOME_COMPONENTS:
        result.append(("research/" + name, home / name))
    return result

def safe_candidate(path: Path) -> bool:
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in ALLOWED_EXT:
        return False
    if any(piece.startswith(".") or piece == "__pycache__" for piece in path.parts):
        return False
    base = path.name.lower()
    if base not in ALLOWED_SPECIAL_BASENAMES and any(s in base for s in
            (".env", "token", "password", "secret", "credential", ".db")):
        return False
    return 0 < path.stat().st_size <= MAX_FILE_BYTES

def scan(home: Path):
    found = {}
    blocked = {}
    skipped = {}
    for label, root in source_roots(home):
        if not root.is_dir():
            skipped[label] = "directory absent"
            continue
        for path in sorted(root.rglob("*")):
            if not safe_candidate(path):
                continue
            rel = path.relative_to(root)
            member = (Path(label) / rel).as_posix()
            raw = path.read_bytes()
            flags = possible_secrets(raw)
            if flags:
                blocked[member] = sorted(set(flags))
            else:
                found[member] = raw
    for unit in UNITS:
        cmd = ["systemctl", "cat", unit]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=7, check=False)
        except (subprocess.TimeoutExpired, OSError):
            continue
        if proc.returncode != 0 or not proc.stdout:
            continue
        member = "units/" + unit + ".txt"
        flags = possible_secrets(proc.stdout, unit=True)
        if flags:
            blocked[member] = sorted(set(flags))
        elif len(proc.stdout) <= MAX_FILE_BYTES:
            found[member] = proc.stdout
    return found, blocked, skipped

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Explicit ZIP destination")
    parser.add_argument("--check", action="store_true", help="Scan only; do not write ZIP")
    args = parser.parse_args()
    files, blocked, skipped = scan(Path.home())
    total = sum(len(blob) for blob in files.values())
    print("=== PRIVATE GHOST V2 SOURCE-ONLY REVIEW ===")
    print(f"Eligible source/unit files: {len(files)}; bytes: {total}")
    print(f"Files blocked for possible secrets: {len(blocked)}")
    for name, labels in blocked.items():
        print(f"REVIEW / NOT COPIED: {name} ({', '.join(labels)})")
    for name in skipped:
        print(f"MISSING OPTIONAL SOURCE: {name}")
    if blocked:
        print("STOP: source files flagged; nothing archived. Do not publish flagged files.")
        return 2
    if not files or total > MAX_TOTAL_BYTES:
        print("STOP: source absent or archive exceeds size limit.")
        return 2
    if args.check:
        print("CHECK PASS: no source exported, all operations read-only")
        return 0
    output = args.output or (Path.home() / ("ghost-v2-source-review-" +
             dt.datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip"))
    if output.exists():
        print("STOP: output already exists; refusing overwrite")
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "kind": "GHOST V2 PRIVATE SOURCE REVIEW, NOT PUBLIC RELEASE",
        "file_count": len(files),
        "files": {name: hashlib.sha256(blob).hexdigest()
                  for name, blob in sorted(files.items())},
        "omitted_optional_roots": list(skipped),
        "excluded": "telemetry, databases, history, credentials, model weights, logs",
    }
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=7) as z:
        for name, blob in sorted(files.items()):
            z.writestr(name, blob)
        z.writestr("SOURCE_MANIFEST.json", json.dumps(manifest, indent=2))
    print(f"CREATED PRIVATE SOURCE ARCHIVE: {output}")
    print("Upload this ZIP in the ChatGPT conversation for review. DO NOT push it to public GitHub.")
    print("No services, telemetry databases or model weights were modified.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
