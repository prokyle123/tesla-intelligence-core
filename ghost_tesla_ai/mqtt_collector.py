from __future__ import annotations
import json, signal, threading, time
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
from . import config, db
from .prediction_audit import on_new_sample

TOPIC_MAP = {
 'state': ('state', str),
 'battery_level': ('battery_level', float),
 'usable_battery_level': ('usable_battery_level', float),
 'rated_battery_range_km': ('rated_range_km', float),
 'ideal_battery_range_km': ('ideal_range_km', float),
 'est_battery_range_km': ('est_range_km', float),
 'outside_temp': ('outside_temp_c', float),
 'inside_temp': ('inside_temp_c', float),
 'power': ('power_kw', float),
 'speed': ('speed_kmh', float),
 'odometer': ('odometer_km', float),
 'plugged_in': ('plugged_in', lambda x: 1 if x.lower() == 'true' else 0),
 'charging_state': ('charging_state', str),
 'charge_energy_added': ('charge_energy_added_kwh', float),
 'charger_power': ('charger_power_kw', float),
 'charger_voltage': ('charger_voltage', float),
 'charger_actual_current': ('charger_actual_current', float),
 'is_climate_on': ('climate_on', lambda x: 1 if x.lower() == 'true' else 0),
 'is_preconditioning': ('preconditioning', lambda x: 1 if x.lower() == 'true' else 0),
}

class Collector:
    def __init__(self):
        self.values: dict[str, object] = {'car_id': str(config.CAR_ID), 'source': 'teslamate_mqtt'}
        self.lock = threading.Lock(); self.stop = threading.Event(); self.connected = False
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='ghost-tesla-ai')
        except Exception:
            self.client = mqtt.Client(client_id='ghost-tesla-ai')
        if config.MQTT_USER:
            self.client.username_pw_set(config.MQTT_USER, config.MQTT_PASSWORD or None)
        if config.MQTT_TLS:
            self.client.tls_set()
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = True
        client.subscribe(f'teslamate/cars/{config.CAR_ID}/#')
        db.set_state('mqtt', {'connected': True, 'host': config.MQTT_HOST, 'port': config.MQTT_PORT, 'at': time.time()})

    def on_disconnect(self, client, userdata, *args):
        self.connected = False
        db.set_state('mqtt', {'connected': False, 'host': config.MQTT_HOST, 'port': config.MQTT_PORT, 'at': time.time()})

    def on_message(self, client, userdata, msg):
        leaf = msg.topic.rsplit('/', 1)[-1]
        if leaf not in TOPIC_MAP: return
        field, caster = TOPIC_MAP[leaf]
        try:
            raw = msg.payload.decode('utf-8', 'replace').strip()
            value = None if raw.lower() in {'nil','null',''} else caster(raw)
            with self.lock:
                self.values[field] = value
                self.values['_last_topic_at'] = time.time()
        except Exception as e:
            db.set_state('collector_error', {'at': time.time(), 'error': f'{type(e).__name__}: {e}', 'topic': msg.topic})

    def snapshot_loop(self):
        while not self.stop.wait(config.SNAPSHOT_SECONDS):
            with self.lock:
                s = dict(self.values)
            if len(s) <= 3:
                continue
            s['ts'] = time.time(); s['source'] = 'teslamate_mqtt'; s['car_id'] = str(config.CAR_ID)
            raw = {k:v for k,v in s.items() if not k.startswith('_')}
            s['raw_json'] = json.dumps(raw, separators=(',', ':'))
            try:
                row_id = db.insert_telemetry(s)
                db.set_state('collector', {'status':'collecting','last_row_id':row_id,'last_sample_at':s['ts'],'fields':sorted(raw.keys())})
                on_new_sample(row_id)
            except Exception as e:
                db.set_state('collector_error', {'at':time.time(),'error':f'{type(e).__name__}: {e}'})

    def run(self):
        db.init_db()
        db.set_state('collector', {'status':'starting','started_at':time.time()})
        threading.Thread(target=self.snapshot_loop, daemon=True).start()
        while not self.stop.is_set():
            try:
                self.client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
                self.client.loop_forever(retry_first_connection=True)
            except Exception as e:
                db.set_state('mqtt', {'connected':False,'host':config.MQTT_HOST,'port':config.MQTT_PORT,'at':time.time(),'error':f'{type(e).__name__}: {e}'})
                self.stop.wait(10)

if __name__ == '__main__':
    c = Collector()
    signal.signal(signal.SIGTERM, lambda *a: c.stop.set())
    signal.signal(signal.SIGINT, lambda *a: c.stop.set())
    c.run()
