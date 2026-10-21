#!/usr/bin/env python3
"""Read-only V2 deployment inventory. Emits no raw telemetry or source contents.

Run on a Pi to compare an existing development install with a portable release.
Never runs sudo, changes systemd, opens a TCP connection, or copies user data.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

UNITS = (
    'ghost-tesla-ai-collector.service', 'ghost-tesla-ai-web.service',
    'ghost-intelligence-llm.service', 'ghost-intelligence-web.service',
    'ghost-intelligence-v3-briefing.timer', 'ghost-intelligence-collector.timer',
    'ghost-v62-memory.timer', 'ghost-v66-watchdog.timer',
)

def run_command(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                timeout=8, check=False)
        return result.stdout.strip() if result.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''

def sha_source(path: Path):
    # Only source files; never hashes private DBs, credentials, logs or GGUF weights.
    if path.suffix != '.py' or not path.is_file() or path.is_symlink():
        return None
    if path.stat().st_size > 2_000_000:
        return None
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()

def inventory(home: Path = None, systemd=run_command):
    home = home if home is not None else Path.home()
    sources = {
        'core_readiness': Path('/opt/ghost-tesla-ai/ghost_tesla_ai/readiness.py'),
        'core_dashboard': Path('/opt/ghost-tesla-ai/web/templates/index.html'),
        'intelligence_briefing': Path('/opt/ghost-intelligence/app/briefing_v3.py'),
        'intelligence_collector': Path('/opt/ghost-intelligence/app/worker.py'),
        'v62_memory': home / 'ghost-v62-memory-status/collector.py',
        'v644_guard': home / 'ghost-v64-evidence-shadow/engine.py',
        'v66_watchdog': home / 'ghost-v66-safe-production/watchdog.py',
        'v65_thermal_lab': home / 'ghost-v65-ambient-thermal-lab/v65.py',
    }
    fingerprints = {}
    for label, path in sources.items():
        if path.suffix == '.py':
            digest = sha_source(path)
            fingerprints[label] = {'present': digest is not None, 'sha256': digest}
        else:
            fingerprints[label] = {'present': path.is_file()}
    states = {unit: systemd(['systemctl','is-active',unit]) == 'active' for unit in UNITS}
    command = systemd(['systemctl','show','ghost-intelligence-llm.service',
                       '--property=ExecStart','--value'])
    model = ('qwen3.5-4b' if 'Qwen3.5-4B' in command else
             'qwen3-0.6b' if 'Qwen3-0.6B' in command else 'unknown')
    return {
        'format': 'ghost-v2-read-only-source-inventory-v1',
        'deployed_model_family': model,
        'systemd_active': states,
        'source_presence_and_code_hashes': fingerprints,
        'release_ready': False,  # Inventory never approves a release.
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Machine-readable metadata only')
    args = parser.parse_args()
    report = inventory()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print('GHOST V2 READ-ONLY RELEASE INVENTORY (not a release approval)')
        print('Language server:', report['deployed_model_family'])
        for name, active in report['systemd_active'].items():
            print(('ACTIVE  ' if active else 'INACTIVE'), name)
        for name, detail in report['source_presence_and_code_hashes'].items():
            print(('PRESENT ' if detail['present'] else 'MISSING '), name,
                  detail.get('sha256') or '')
        print('No files, services, credentials, model weights or databases modified.')

if __name__ == '__main__':
    main()
