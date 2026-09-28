from __future__ import annotations
import argparse, json, sqlite3, time
from . import db, config
from .tessie_source import TessieClient, parse_state

RICH_FIELDS = [
    'pack_power_kw','charge_input_kw','module_temp_spread_c','pack_ambient_delta_c',
    'state','battery_level','usable_battery_level','rated_range_km','ideal_range_km','est_range_km',
    'outside_temp_c','inside_temp_c','battery_temp_c','power_kw','speed_kmh','odometer_km','plugged_in',
    'charging_state','charge_energy_added_kwh','charger_power_kw','charger_voltage','charger_actual_current',
    'climate_on','preconditioning','shift_state','battery_heater_on','lifetime_energy_used_kwh',
    'energy_remaining_kwh','pack_current_a','pack_voltage_v','module_temp_min_c','module_temp_max_c','raw_json'
]
BATCH_SIZE = 200


def _results(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ('results','states','data','response'):
            v = payload.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                nested = _results(v)
                if nested:
                    return nested
    return []


def _locked(exc: BaseException) -> bool:
    s = str(exc).lower()
    return isinstance(exc, sqlite3.OperationalError) and ('locked' in s or 'busy' in s)


def _merge_batch(batch: list[dict], fallback_car: str, attempts: int = 8):
    """Merge one short, atomic batch. A failed transaction is rolled back and retried."""
    delay = 0.15
    for attempt in range(attempts):
        inserted = updated = 0
        try:
            with db.connect() as con:
                for s0 in batch:
                    s = db.enrich_sample(s0)
                    ts = float(s.get('ts') or 0)
                    car = str(s.get('car_id') or fallback_car)
                    old = con.execute(
                        'SELECT * FROM telemetry WHERE car_id=? AND ABS(ts-?) < 0.5 ORDER BY id LIMIT 1',
                        (car, ts)
                    ).fetchone()
                    if old:
                        sets=[]; vals=[]
                        for f in RICH_FIELDS:
                            v=s.get(f)
                            if v is not None and (old[f] is None or f == 'raw_json'):
                                sets.append(f'{f}=?'); vals.append(v)
                        if sets:
                            vals.append(int(old['id']))
                            con.execute(f"UPDATE telemetry SET {','.join(sets)} WHERE id=?", vals)
                            updated += 1
                    else:
                        vals=[s.get(f) for f in db.TELEMETRY_FIELDS]
                        con.execute(
                            f"INSERT INTO telemetry({','.join(db.TELEMETRY_FIELDS)}) VALUES({','.join('?' for _ in db.TELEMETRY_FIELDS)})",
                            vals
                        )
                        inserted += 1
            return inserted, updated
        except Exception as exc:
            if not _locked(exc) or attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2.0, 3.0)
    raise RuntimeError('unreachable')


def import_history(days: int = 30, interval: int = 300, train_after: bool = False):
    db.init_db()
    days = max(1, min(int(days), 3650))
    interval = max(60, min(int(interval), 86400))
    end = time.time()
    start = end - days * 86400
    state = {
        'status':'running','phase':'fetching','started_at':time.time(),
        'days':days,'interval':interval,'inserted':0,'updated':0,'seen':0,
        'processed':0,'batch_size':BATCH_SIZE
    }
    db.set_state('backfill', state)
    try:
        client = TessieClient()
        client.discover_vehicle()
        payload = client.history(start, end, interval)
        rows = _results(payload)
        state['seen'] = len(rows)
        state['vin_tail'] = client.vin[-6:] if client.vin else None
        state['phase'] = 'normalizing'
        db.set_state('backfill', state)

        samples=[]
        parse_errors=0
        for item in rows:
            if not isinstance(item, dict):
                continue
            try:
                s=db.enrich_sample(parse_state(item, None, client.vin or 'tessie'))
                s['source']='tessie_history'
                samples.append(s)
            except Exception:
                parse_errors += 1
        samples.sort(key=lambda x: float(x.get('ts') or 0))
        state.update({'phase':'merging','total':len(samples),'parse_errors':parse_errors})
        db.set_state('backfill', state)

        inserted=updated=processed=0
        fallback = client.vin or 'tessie'
        for off in range(0, len(samples), BATCH_SIZE):
            batch = samples[off:off+BATCH_SIZE]
            ins, upd = _merge_batch(batch, fallback)
            inserted += ins; updated += upd; processed += len(batch)
            # IMPORTANT: this progress write occurs only after the telemetry batch has
            # committed and released its writer lock. v0.2.1 tried this from a second
            # connection while one giant transaction was still open, self-deadlocking
            # at exactly row 500.
            state.update({
                'inserted':inserted,'updated':updated,'processed':processed,
                'total':len(samples),'progress_pct':round(processed/max(1,len(samples))*100,1),
                'last_progress_at':time.time()
            })
            db.set_state('backfill', state)

        if train_after:
            # Build the event memory before training so regime-specific models can
            # immediately benefit from the newly imported history.
            try:
                from .event_engine import rebuild_events
                state['event_engine']=rebuild_events(min(days, config.EVENT_LOOKBACK_DAYS) if hasattr(config,'EVENT_LOOKBACK_DAYS') else days)
            except Exception as ee:
                state['event_engine']={'status':'error','error':f'{type(ee).__name__}: {ee}'}
            from .trainer import train_all
            state.update({'status':'running','phase':'training','training':'started'})
            db.set_state('backfill', state)
            results=train_all()
            state['training']='complete'
            state['training_results']=results

        state.update({
            'status':'complete','phase':'complete','finished_at':time.time(),
            'inserted':inserted,'updated':updated,'processed':processed,'total':len(samples),
            'progress_pct':100.0
        })
        db.set_state('backfill', state)
        return state
    except Exception as e:
        state.update({'status':'error','phase':'error','finished_at':time.time(),'error':f'{type(e).__name__}: {e}'})
        try:
            db.set_state('backfill', state)
        except Exception:
            pass
        return state


if __name__=='__main__':
    p=argparse.ArgumentParser(description='Backfill local GHOST training data from Tessie historical states')
    p.add_argument('--days',type=int,default=30)
    p.add_argument('--interval',type=int,default=300)
    p.add_argument('--train-after',action='store_true')
    a=p.parse_args()
    out=import_history(a.days,a.interval,a.train_after)
    print(json.dumps(out,indent=2,default=str))
    raise SystemExit(0 if out.get('status')=='complete' else 1)
