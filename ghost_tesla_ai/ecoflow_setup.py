from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

from . import config
from .ecoflow_mqtt import _private_cert


def main():
    print('============================================================')
    print(' GHOST EcoFlow RIVER 3 - PRIVATE MQTT SETUP')
    print('============================================================')
    print('Credentials stay on this Pi and are never sent to the dashboard browser.')
    print()
    email=input('EcoFlow app email: ').strip()
    password=getpass.getpass('EcoFlow app password: ')
    if not email or not password:
        raise SystemExit('Email/password cannot be blank.')
    print('Testing EcoFlow login + MQTT certification...')
    cert=_private_cert(email,password)
    p=Path(config.ECOFLOW_APP_CREDENTIALS_FILE)
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps({'email':email,'password':password},separators=(',',':')))
    os.chmod(tmp,0o600)
    tmp.replace(p)
    os.chmod(p,0o600)
    account=str(cert.get('username') or '')
    masked=('...'+account[-6:]) if len(account)>6 else account
    print()
    print('EcoFlow private MQTT: PASS')
    print('Broker :',cert.get('host'))
    print('Port   :',cert.get('port'))
    print('Account:',masked)
    print('Device :',config.ECOFLOW_RIVER3_SN or 'SERIAL NOT SET')
    print('Saved  :',p)
    print('Mode   : 0600')
    print()
    print('Restart the dashboard with:')
    print('  sudo systemctl restart ghost-tesla-ai-web.service')

if __name__=='__main__':
    main()
