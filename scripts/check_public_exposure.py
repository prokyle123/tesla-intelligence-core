#!/usr/bin/env python3
"""Fail CI on obvious private identifiers in tracked public text files.

This is a conservative supplement to secret scanning and human screenshot review.
It never prints the matched secret/value.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

PATTERNS = (
    ("Tailnet IPv4 device address", re.compile(r"(?<!\d)100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}(?!\d)")),
    ("Tailnet device hostname", re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.ts\.net\b", re.I)),
    ("Tesla VIN", re.compile(r"\b(?:5YJ|7SA|LRW|XP7)[A-HJ-NPR-Z0-9]{14}\b")),
    ("Likely bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}")),
    ("Likely API secret", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
)

# Tailscale's shared DNS resolver, not a personal device identity.
PUBLIC_INFRA_ADDRESSES = {"100.100.100.100"}
# Clearly labeled examples in the Android connection settings, not real Tailnet nodes.
PUBLIC_EXAMPLE_HOSTNAMES = {"your-hostname.ts.net"}


def main() -> int:
    tracked = subprocess.check_output(["git", "ls-files", "-z"]).split(b"\x00")
    checked = 0
    failures = 0
    for entry in tracked:
        if not entry:
            continue
        path = Path(entry.decode("utf-8", "surrogateescape"))
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
            if b"\x00" in raw or len(raw) > 5_000_000:
                continue
            lines = raw.decode("utf-8").splitlines()
        except UnicodeError:
            continue
        checked += 1
        for lineno, line in enumerate(lines, 1):
            for label, regex in PATTERNS:
                for match in regex.finditer(line):
                    if label == "Tailnet IPv4 device address" and match.group(0) in PUBLIC_INFRA_ADDRESSES:
                        continue
                    if label == "Tailnet device hostname" and match.group(0).lower() in PUBLIC_EXAMPLE_HOSTNAMES:
                        continue
                    print(f"FAIL {path}:{lineno}: {label} (value hidden)")
                    failures += 1
    print(f"Scanned {checked} tracked text files; findings: {failures}")
    if failures:
        print("Review or redact before merging. Old Git history is not scanned.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
