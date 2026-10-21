#!/usr/bin/env python3
"""Prepare a source-only, privately reviewed GHOST V2 reconciliation ZIP.

No service restarts, DB queries, vehicle commands, credentials or model weights.
The output stays on the local machine for review before any GitHub publication.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

# Strict file extensions; never include .env, .json data, logs, SQL, tokens,
# binaries, GGUF model weights, credentials or training artifacts.
ALLOWED_SUFFIXES = {'.py', '.html', '.js', '.css', '.in', '.sh'}
ALLOWED_SINGLE_FILES = (
    'requirements.txt', 'requirements-starlink.txt',
)
SENSITIVE = (
    re.compile(r'(?i)\b(?:api_?key|access_?token|bearer|password|client_secret|refresh_?token)\b\s*[:=]\s*["\x27][^"\x27\n]{8,}'),
    re.compile(r'(?i)\bBearer\s+[A-Za-z0-9_.~-]{16,}'),
    re.compile(r'\b[A-HJ-NPR-Z0-9]{17}\b'),  # VIN-shaped identifier
    re.compile(r'\b(?:192\.168|10\.(?:\d{1,3})|172\.(?:1[6-9]|2\d|3[01])|100\.\d{1,3})\.\d{1,3}\.\d{1,3}\b'),
)
MAX_FILE_BYTES = 1_500_000
MAX_ARCHIVE_BYTES = 20_000_000

def sources(home: Path):
    # Both app paths are intentionally *source only* and can be absent.
    return (
        ('core/ghost_tesla_ai', Path('/opt/ghost-tesla-ai/ghost_tesla_ai')),
        ('core/web', Path('/opt/ghost-tesla-ai/web')),
        ('core/release-sidecars', Path('/opt/ghost-tesla-ai/release-sidecars')),
        ('core/systemd', Path('/opt/ghost-tesla-ai/systemd')),
        ('intelligence', Path('/opt/ghost-intelligence/app')),
        ('v5_tessie', home / 'ghost-tessie-sensor-v5'),
        ('v62_memory', home / 'ghost-v62-memory-status'),
        ('v64_evidence', home / 'ghost-v64-evidence-shadow'),
        ('v65_thermal_research', home / 'ghost-v65-ambient-thermal-lab'),
        ('v651_thermal_research', home / 'ghost-v651-thermal-model-lab'),
        ('v66_guarded_4b', home / 'ghost-v66-safe-production'),
    )

def safe_candidates(home: Path):
    for prefix, root in sources(home):
        if root.is_symlink() or not root.is_dir():
            continue
        for path in sorted(root.rglob('*')):
            if path.is_symlink() or not path.is_file():
                continue
            if path.suffix not in ALLOWED_SUFFIXES and path.name not in ALLOWED_SINGLE_FILES:
                continue
            rel = path.relative_to(root)
            if any(part.startswith('.') or part == '__pycache__' for part in rel.parts):
                continue
            yield prefix + '/' + rel.as_posix(), path

def check_source(name: str, path: Path):
    size = path.stat().st_size
    if not size or size > MAX_FILE_BYTES:
        return None, 'empty_or_exceeds_size_limit'
    try:
        data = path.read_bytes()
        decoded = data.decode('utf-8')
    except (OSError, UnicodeError):
        return None, 'unreadable_or_non_utf8'
    if b'\x00' in data:
        return None, 'binary_data'
    if any(p.search(decoded) for p in SENSITIVE):
        return None, 'sensitive_pattern_for_review'
    return data, None

def build(home: Path, output: Path):
    if output.exists() or output.is_symlink():
        raise ValueError('Output already exists; choose a new output path (no overwrites)')
    accepted, blocked = [], []
    total_bytes = 0
    for name, path in safe_candidates(home):
        contents, reason = check_source(name, path)
        if reason:
            blocked.append({'path': name, 'reason': reason})
        else:
            accepted.append((name, contents))
            total_bytes += len(contents)
            if total_bytes > MAX_ARCHIVE_BYTES:
                raise ValueError('Source bundle exceeds size limit; aborting')
    if not accepted:
        raise ValueError('No permitted source files found')
    if blocked:
        # Never publish or upload an incomplete collection without inspecting exclusions.
        return {'created': False, 'files': len(accepted), 'blocked': blocked}
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        'format': 'ghost-v2-private-source-export-v1',
        'source_files': [{'path': name, 'sha256': hashlib.sha256(body).hexdigest(), 'bytes':len(body)}
                         for name,body in accepted],
        'source_only_no_runtime_data': True,
        'not_an_install_package': True,
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(output, flags, 0o600)
    try:
        with os.fdopen(fd, 'wb') as f:
            with zipfile.ZipFile(f, mode='w', compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=7) as z:
                for name, data in accepted:
                    z.writestr('sources/' + name, data)
                z.writestr('manifest.json', json.dumps(manifest, indent=2))
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {'created': True, 'files': len(accepted), 'bytes': output.stat().st_size,
            'output': str(output), 'private_review_required': True}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--home',type=Path,default=Path.home())
    p.add_argument('--output',type=Path,default=Path.home() / 'ghost-v2-source-review.zip')
    args=p.parse_args(argv)
    try:
        result=build(args.home,args.output)
        print(json.dumps(result,indent=2))
        if not result['created']:
            print('STOP: flagged paths require private inspection; no ZIP was created.')
            return 2
        print('PRIVATE SOURCE REVIEW ZIP CREATED. Upload privately to ChatGPT for reconciliation.')
        print('Do NOT publish this ZIP or commit it to GitHub as-is.')
        return 0
    except (OSError, ValueError) as e:
        print('STOP: '+str(e),file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
