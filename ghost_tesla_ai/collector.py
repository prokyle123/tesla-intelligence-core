from __future__ import annotations
import json
import signal
import threading
import time
from . import config, db
from .mqtt_collector import Collector as MQTTCollector
from .tessie_source import TessieClient, TessieError, parse_state
from .prediction_audit import on_new_sample

class UnifiedCollector:
    def __init__(self):
        self.stop = threading.Event()
        self.token = config.tessie_token()
        self.mode = config.SOURCE_MODE
        self.tessie = None
        self.mqtt = None


    def _insert_if_new(self, sample):
        ts=float(sample.get('ts') or 0)
        with db.connect() as con:
            row=con.execute("SELECT id FROM telemetry WHERE car_id=? AND ABS(ts-?) < 0.5 LIMIT 1", (str(sample.get('car_id') or 'tessie'), ts)).fetchone()
        if row:
            return None
        return db.insert_telemetry(sample)

    def _choose(self):
        if self.mode not in {'auto','tessie','mqtt'}:
            raise RuntimeError(f'Invalid SOURCE_MODE={self.mode!r}; use auto, tessie, or mqtt')
        if self.mode == 'tessie' or (self.mode == 'auto' and self.token):
            return 'tessie'
        return 'mqtt'

    def run_tessie(self):
        self.tessie = TessieClient(self.token)
        selected = self.tessie.discover_vehicle()
        db.set_state('source', {'active':'tessie_api','status':'connected','vin_tail':self.tessie.vin[-6:] if self.tessie.vin else None,'at':time.time()})
        # Prefer last_state from /vehicles for the very first sample when available.
        initial = selected.get('last_state') if isinstance(selected, dict) else None
        if isinstance(initial, dict):
            try:
                s = parse_state(initial, None, self.tessie.vin or 'tessie')
                rid = self._insert_if_new(s)
                if rid is not None:
                    db.set_state('collector', {'status':'collecting','source':'tessie_api','last_row_id':rid,'last_sample_at':s['ts']})
                    on_new_sample(rid)
            except Exception:
                pass
        while not self.stop.is_set():
            started = time.time()
            try:
                state = self.tessie.state()
                normalized_state = str((state or {}).get('state') or (state or {}).get('status') or '').lower() if isinstance(state, dict) else ''
                battery = None
                if config.TESSIE_FETCH_BATTERY_WHEN_ACTIVE and normalized_state in {'online','awake','driving','charging'}:
                    try:
                        battery = self.tessie.battery()
                    except Exception as e:
                        db.set_state('tessie_battery', {'status':'error','error':f'{type(e).__name__}: {e}','at':time.time()})
                sample = parse_state(state, battery, self.tessie.vin or 'tessie')
                rid = self._insert_if_new(sample)
                if rid is not None:
                    db.set_state('collector', {'status':'collecting','source':'tessie_api','last_row_id':rid,'last_sample_at':sample['ts'],'fields':[k for k,v in sample.items() if v is not None and not k.startswith('_')]})
                    on_new_sample(rid)
                else:
                    db.set_state('collector', {'status':'cached-no-change','source':'tessie_api','last_sample_at':sample['ts']})
                db.set_state('source', {'active':'tessie_api','status':'connected','vin_tail':self.tessie.vin[-6:] if self.tessie.vin else None,'at':time.time(),'cached':bool(config.TESSIE_USE_CACHE)})
                db.set_state('tessie', {'connected':True,'vin_tail':self.tessie.vin[-6:] if self.tessie.vin else None,'last_ok':time.time(),'cached':bool(config.TESSIE_USE_CACHE)})
            except Exception as e:
                err = f'{type(e).__name__}: {e}'
                db.set_state('source', {'active':'tessie_api','status':'error','error':err,'at':time.time()})
                db.set_state('tessie', {'connected':False,'error':err,'at':time.time()})
                db.set_state('collector_error', {'at':time.time(),'error':err})
            elapsed = time.time() - started
            self.stop.wait(max(1, config.TESSIE_POLL_SECONDS - elapsed))

    def run_mqtt(self):
        db.set_state('source', {'active':'teslamate_mqtt','status':'starting','at':time.time()})
        self.mqtt = MQTTCollector()
        # Share stop so systemd SIGTERM stops the old collector too.
        self.mqtt.stop = self.stop
        self.mqtt.run()

    def run(self):
        db.init_db()
        chosen = self._choose()
        db.set_state('collector', {'status':'starting','source':chosen,'started_at':time.time()})
        if chosen == 'tessie':
            try:
                self.run_tessie()
            except Exception as e:
                err = f'{type(e).__name__}: {e}'
                db.set_state('source', {'active':'tessie_api','status':'error','error':err,'at':time.time()})
                db.set_state('collector_error', {'at':time.time(),'error':err})
                # In AUTO, fall back to MQTT after a hard Tessie startup failure.
                if self.mode == 'auto':
                    db.set_state('source', {'active':'teslamate_mqtt','status':'fallback','reason':err,'at':time.time()})
                    self.run_mqtt()
                else:
                    raise
        else:
            self.run_mqtt()

if __name__ == '__main__':
    c = UnifiedCollector()
    signal.signal(signal.SIGTERM, lambda *a: c.stop.set())
    signal.signal(signal.SIGINT, lambda *a: c.stop.set())
    c.run()
