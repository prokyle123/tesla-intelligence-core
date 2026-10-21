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
import subprocess

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

# Read unit *source definitions*, not private /etc/ghost-tesla-ai config.
# systemctl cat includes drop-in overrides required to replicate the service.
SAFE_UNIT_NAMES = (
    'ghost-tesla-ai-web.service',
    'ghost-tesla-ai-collector.service',
    'ghost-intelligence-web.service',
    'ghost-intelligence-collector.service',
    'ghost-intelligence-collector.timer',
    'ghost-intelligence-llm.service',
    'ghost-intelligence-v3-briefing.service',
    'ghost-intelligence-v3-briefing.timer',
    'ghost-v62-memory.service',
    'ghost-v62-memory.timer',
    'ghost-v66-watchdog.service',
    'ghost-v66-watchdog.timer',
    'ghost-thermal-range-recorder.service',
    'ghost-thermal-range-recorder.timer',
)
INLINE_SECRET = re.compile(
    r'(?im)^\s*Environment\s*=\s*.*(?:PASSWORD|TOKEN|API_KEY|SECRET)\s*=')

def installed_service_sources():
    for unit in SAFE_UNIT_NAMES:
        try:
            proc = subprocess.run(
                ['systemctl', 'cat', unit], capture_output=True,
                text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0 and proc.stdout:
            yield 'systemd-live/' + unit + '.txt', proc.stdout.encode('utf-8')


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

def blocked_diagnostics(home: Path):
    """Only report match categories and line numbers, never private match text."""
    categories = (
        'possible_hardcoded_credential',
        'bearer_token',
        'possible_vehicle_identifier',
        'private_network_address',
    )
    report = []

    def inspect(name, raw, unit=False):
        try:
            decoded = raw.decode('utf-8')
        except UnicodeDecodeError:
            report.append({'path': name, 'matches': [{'category': 'non_utf8'}]})
            return
        details = []
        for label, pattern in zip(categories, SENSITIVE):
            line_numbers = [decoded.count('\n', 0, hit.start()) + 1
                            for hit in pattern.finditer(decoded)]
            if line_numbers:
                details.append({'category': label, 'count': len(line_numbers),
                                'first_line_numbers': line_numbers[:15]})
        if unit:
            line_numbers = [decoded.count('\n', 0, hit.start()) + 1
                            for hit in INLINE_SECRET.finditer(decoded)]
            if line_numbers:
                details.append({'category': 'inline_systemd_secret',
                                'count': len(line_numbers),
                                'first_line_numbers': line_numbers[:15]})
        if details:
            report.append({'path': name, 'matches': details})

    for name, path in safe_candidates(home):
        try:
            if 0 < path.stat().st_size <= MAX_FILE_BYTES:
                inspect(name, path.read_bytes())
        except OSError:
            continue
    for name, raw in installed_service_sources():
        inspect(name, raw, unit=True)
    return report


def build(home: Path, output: Path, allow_incomplete: bool = False):
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
    # Exact installed unit definitions, with the same private-secret veto as
    # application source. Never inspect the EnvironmentFile target itself.
    for name, contents in installed_service_sources():
        if len(contents) > MAX_FILE_BYTES:
            blocked.append({'path': name, 'reason': 'unit_exceeds_size_limit'})
            continue
        data = contents.decode('utf-8')
        if INLINE_SECRET.search(data) or any(p.search(data) for p in SENSITIVE):
            blocked.append({'path': name, 'reason': 'unit_sensitive_pattern_for_review'})
        else:
            accepted.append((name, contents))
            total_bytes += len(contents)
            if total_bytes > MAX_ARCHIVE_BYTES:
                raise ValueError('Source bundle exceeds size limit; aborting')
    if not accepted:
        raise ValueError('No permitted source files found')
    if blocked and not allow_incomplete:
        # Fail closed by default. With explicit opt-in, archive ONLY the
        # accepted subset; blocked bytes are never copied into the ZIP.
        return {'created': False, 'files': len(accepted), 'blocked': blocked}
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        'format': 'ghost-v2-private-source-export-v1',
        'source_files': [{'path': name, 'sha256': hashlib.sha256(body).hexdigest(), 'bytes':len(body)}
                         for name,body in accepted],
        'source_only_no_runtime_data': True,
        'not_an_install_package': True,
        'incomplete_due_to_blocked_files': bool(blocked),
        'blocked_paths_not_included': blocked,
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
            'output': str(output), 'private_review_required': True,
            'incomplete_due_to_blocked_files': bool(blocked),
            'blocked_paths_not_included': blocked}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--home',type=Path,default=Path.home())
    p.add_argument('--output',type=Path,default=Path.home() / 'ghost-v2-source-review.zip')
    p.add_argument('--export-safe-subset', action='store_true',
                   help='Explicitly archive only unflagged files; mark ZIP INCOMPLETE')
    p.add_argument('--diagnose', action='store_true',
                   help='Only print match categories and line numbers, never private values')
    args=p.parse_args(argv)
    try:
        if args.diagnose:
            print(json.dumps({'safe_read_only_diagnostics': blocked_diagnostics(args.home)}, indent=2))
            print('No source contents or matched strings printed.')
            return 0
        result=build(args.home,args.output,allow_incomplete=args.export_safe_subset)
        print(json.dumps(result,indent=2))
        if not result['created']:
            print('STOP: flagged paths require private inspection; no ZIP was created.')
            return 2
        if result['incomplete_due_to_blocked_files']:
            print('INCOMPLETE PRIVATE SOURCE ZIP: flagged files EXCLUDED.')
            print('Use --diagnose to inspect the match categories and line numbers.')
        else:
            print('Private source ZIP created, pending additional review.')
        print('Upload this ZIP privately to ChatGPT for reconciliation only.')
        print('Do NOT publish this ZIP or commit it to GitHub as-is.')
        return 0
    except (OSError, ValueError) as e:
        print('STOP: '+str(e),file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
