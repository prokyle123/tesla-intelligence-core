#!/usr/bin/env python3
"""Fail-closed V2 *stable* release gate. Read-only and never touches vehicle data.

This is intentionally NOT satisfied by a screenshot or the preview tag. It checks
that the actual integrated source, optional runtime and an explicit offline/hardware
acceptance report exist at the commit proposed for the stable tag.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
REQUIRED_FILES=(
    'ghost_tesla_ai/server.py',
    'web/templates/index.html',
    'optional-intelligence/app/briefing_v3.py',
    'optional-intelligence/app/engine.py',
    'optional-intelligence/app/v61.py',
    'optional-intelligence/app/pilot.py',
    'optional-intelligence/app/v62_collector.py',
    'optional-intelligence/app/tessie_intelligence.py',
    'optional-intelligence/app/v2_watchdog.py',
    'scripts/install_optional_intelligence.py',
    'tests/test_v2_package.py',
    'docs/V2_RELEASE_NOTES.md',
)
MUST_VERIFY=(
    'clean_pi_fresh_install',
    'upgrade_v1_preserves_history_models_and_config',
    'rollback_restores_previous_services',
    'reboot_recovery',
    'real_4b_inference_and_fallback',
    'watchdog_restart_and_real_fallback',
    'browser_voice_and_readiness_operate_without_llm',
    'private_address_and_credential_review',
)

def check(root=ROOT):
    errors=[]
    version=(root/'VERSION').read_text().strip() if (root/'VERSION').is_file() else ''
    if version!='2.0.0':
        errors.append('VERSION is not 2.0.0 (the stable upgrade has not been approved).')
    for item in REQUIRED_FILES:
        if not (root/item).is_file():
            errors.append('Integrated source or regression file missing: '+item)
    ui=(root/'web/templates/index.html').read_text(errors='replace') if (root/'web/templates/index.html').is_file() else ''
    for marker in ('GHOST AI INSIGHT','GHOST-VOICE-ALERTS-V1'):
        if marker not in ui:errors.append('Current dashboard feature missing: '+marker)
    source=(root/'optional-intelligence/app/briefing_v3.py').read_text(errors='replace') if (root/'optional-intelligence/app/briefing_v3.py').is_file() else ''
    if 'v66_guard_' not in source:
        errors.append('V6.6 guarded 4B fallback is missing.')
    if 'REDACTED_PRIVATE_NETWORK_ADDRESS' in ui or 'REDACTED_PRIVATE_NETWORK_ADDRESS' in source:
        errors.append('Review-only network placeholder would ship to users.')
    if list(root.rglob('*.gguf')):
        errors.append('Do not commit model weights to source release.')
    report_file=root/'docs/V2_HARDWARE_ACCEPTANCE.json'
    if not report_file.is_file():
        errors.append('Independent clean-install / upgrade / rollback sign-off missing.')
    else:
        try:
            report=json.loads(report_file.read_text())
            for required in MUST_VERIFY:
                if report.get(required) is not True:
                    errors.append('Unverified hardware acceptance: '+required)
            if not str(report.get('reviewer','')).strip():
                errors.append('Hardware acceptance reviewer missing.')
            if not str(report.get('tested_commit','')).strip():
                errors.append('Hardware acceptance git SHA missing.')
            elif os.environ.get('GITHUB_SHA') and report['tested_commit']!=os.environ['GITHUB_SHA']:
                errors.append('Hardware acceptance was for a different commit.')
        except (ValueError,TypeError,KeyError) as exc:
            errors.append('Invalid V2 hardware acceptance report: '+str(exc))
    return errors

if __name__=='__main__':
    errors=check()
    if errors:
        print('V2 STABLE RELEASE BLOCKED:')
        for problem in errors:print('- '+problem)
        sys.exit(2)
    print('V2 stable source/hardware acceptance gates satisfied; run CI regression and privacy checks.')
