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
    'energy_remaining_kwh','pack_current_a','pack_voltage_v','module_temp_min_c','module_temp_max_c',
    'charge_limit_soc','charger_pilot_current','charge_current_request','charge_current_request_max','minutes_to_full_charge',
    'not_enough_power_to_heat','charge_port_cold_weather_mode','phantom_drain','defrost_mode','hvac_auto_request',
    'climate_keeper_mode','driver_temp_setting_c','front_defroster_on','rear_defroster_on','side_mirror_heaters',
    'wiper_blade_heater','steering_wheel_heater','battery_heater_no_power','auto_conditioning_on','user_present','sentry_mode',
    'pack_current_abs_a','module_min_ambient_delta_c','module_max_ambient_delta_c','charge_request_gap_a','charge_utilization',
    'thermal_aux_load','raw_json'
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


def import_history(days: int = 2500, interval: int = 300, train_after: bool = False):
    db.init_db()

    days = max(1, min(int(days), 3650))
    interval = max(60, min(int(interval), 86400))

    end = time.time()
    start = end - days * 86400

    # Tessie limits a single JSON states request to 10,000 data points.
    # At our normal 300-second interval, 30 days is 8,640 points, so
    # retrieve the requested history in 30-day chunks and merge each
    # chunk immediately instead of holding the whole history in RAM.
    chunk_days = 30
    chunk_seconds = chunk_days * 86400
    chunks_total = max(
        1,
        int((end - start + chunk_seconds - 1) // chunk_seconds)
    )

    state = {
        'status': 'running',
        'phase': 'discovering',
        'started_at': time.time(),
        'days': days,
        'interval': interval,
        'chunk_days': chunk_days,
        'chunks_total': chunks_total,
        'chunks_done': 0,
        'inserted': 0,
        'updated': 0,
        'seen': 0,
        'processed': 0,
        'batch_size': BATCH_SIZE,
        'progress_pct': 0.0,
    }
    db.set_state('backfill', state)

    try:
        client = TessieClient()
        client.discover_vehicle()

        state['vin_tail'] = client.vin[-6:] if client.vin else None
        state['phase'] = 'fetching'
        db.set_state('backfill', state)

        inserted = 0
        updated = 0
        processed = 0
        seen_total = 0
        parse_errors = 0
        chunk_index = 0
        chunk_start = start
        fallback = client.vin or 'tessie'

        while chunk_start < end:
            chunk_index += 1
            chunk_end = min(chunk_start + chunk_seconds, end)

            state.update({
                'phase': 'fetching',
                'chunk': chunk_index,
                'chunks_done': chunk_index - 1,
                'chunk_from': chunk_start,
                'chunk_to': chunk_end,
                'chunk_retry': 0,
            })
            db.set_state('backfill', state)

            payload = None

            # Retry transient API/network failures without throwing away
            # progress from chunks that have already committed.
            for attempt in range(4):
                try:
                    payload = client.history(
                        chunk_start,
                        chunk_end,
                        interval
                    )
                    break
                except Exception as exc:
                    if attempt >= 3:
                        raise

                    wait_seconds = 2 ** (attempt + 1)

                    state.update({
                        'phase': 'retrying',
                        'chunk_retry': attempt + 1,
                        'last_retry_error': f'{type(exc).__name__}: {exc}',
                        'retry_wait_seconds': wait_seconds,
                    })
                    db.set_state('backfill', state)
                    time.sleep(wait_seconds)

            rows = _results(payload)
            seen_total += len(rows)

            state.update({
                'phase': 'normalizing',
                'seen': seen_total,
                'chunk_seen': len(rows),
            })
            db.set_state('backfill', state)

            samples = []

            for item in rows:
                if not isinstance(item, dict):
                    continue

                try:
                    sample = db.enrich_sample(
                        parse_state(item, None, client.vin or 'tessie')
                    )
                    sample['source'] = 'tessie_history'
                    samples.append(sample)
                except Exception:
                    parse_errors += 1

            samples.sort(key=lambda x: float(x.get('ts') or 0))

            state.update({
                'phase': 'merging',
                'chunk_samples': len(samples),
                'parse_errors': parse_errors,
            })
            db.set_state('backfill', state)

            for off in range(0, len(samples), BATCH_SIZE):
                batch = samples[off:off + BATCH_SIZE]

                ins, upd = _merge_batch(batch, fallback)

                inserted += ins
                updated += upd
                processed += len(batch)

                state.update({
                    'inserted': inserted,
                    'updated': updated,
                    'processed': processed,
                    'seen': seen_total,
                    'parse_errors': parse_errors,
                    'last_progress_at': time.time(),
                })
                db.set_state('backfill', state)

            progress = round(
                min(100.0, chunk_index / chunks_total * 100.0),
                1
            )

            state.update({
                'phase': 'fetching',
                'chunks_done': chunk_index,
                'chunk_rows': len(samples),
                'seen': seen_total,
                'inserted': inserted,
                'updated': updated,
                'processed': processed,
                'parse_errors': parse_errors,
                'progress_pct': progress,
                'last_progress_at': time.time(),
            })
            db.set_state('backfill', state)

            chunk_start = chunk_end

            # Small courtesy gap between Tessie requests.
            if chunk_start < end:
                time.sleep(0.25)

        if train_after:
            state.update({
                'status': 'running',
                'phase': 'event_rebuild',
                'progress_pct': 100.0,
            })
            db.set_state('backfill', state)

            try:
                from .event_engine import rebuild_events

                lookback = (
                    min(days, config.EVENT_LOOKBACK_DAYS)
                    if hasattr(config, 'EVENT_LOOKBACK_DAYS')
                    else days
                )

                state['event_engine'] = rebuild_events(lookback)

            except Exception as ee:
                state['event_engine'] = {
                    'status': 'error',
                    'error': f'{type(ee).__name__}: {ee}'
                }

            state.update({
                'status': 'running',
                'phase': 'training',
                'training': 'started'
            })
            db.set_state('backfill', state)

            from .trainer import train_all
            results = train_all()

            state['training'] = 'complete'
            state['training_results'] = results

        state.update({
            'status': 'complete',
            'phase': 'complete',
            'finished_at': time.time(),
            'inserted': inserted,
            'updated': updated,
            'seen': seen_total,
            'processed': processed,
            'parse_errors': parse_errors,
            'chunks_done': chunk_index,
            'chunks_total': chunks_total,
            'progress_pct': 100.0,
        })

        db.set_state('backfill', state)
        return state

    except Exception as e:
        state.update({
            'status': 'error',
            'phase': 'error',
            'finished_at': time.time(),
            'error': f'{type(e).__name__}: {e}'
        })

        try:
            db.set_state('backfill', state)
        except Exception:
            pass

        return state


if __name__=='__main__':
    p=argparse.ArgumentParser(description='Backfill local GHOST training data from Tessie historical states')
    p.add_argument('--days',type=int,default=2500)
    p.add_argument('--interval',type=int,default=300)
    p.add_argument('--train-after',action='store_true')
    a=p.parse_args()
    out=import_history(a.days,a.interval,a.train_after)
    print(json.dumps(out,indent=2,default=str))
    raise SystemExit(0 if out.get('status')=='complete' else 1)
