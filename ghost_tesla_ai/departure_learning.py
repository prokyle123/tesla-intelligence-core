from __future__ import annotations

import math
import statistics
import time
from collections import defaultdict

from . import config, db

STATE_KEY = 'departure_learning'
MODEL_VERSION = 'schedule-kernel-v1'


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, float(v)))


def _day_key(ts: float) -> str:
    return time.strftime('%Y-%m-%d', time.localtime(float(ts)))


def _minute_of_day(ts: float) -> int:
    lt = time.localtime(float(ts))
    return lt.tm_hour * 60 + lt.tm_min


def _minute_delta(a: float, b: float) -> float:
    d = abs(float(a) - float(b)) % 1440.0
    return min(d, 1440.0 - d)


def _parse_anchor_minute():
    raw = (config.EXPECTED_DEPARTURE or '').strip()
    if ':' not in raw:
        return None
    try:
        h, m = (int(x) for x in raw.split(':', 1))
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    except Exception:
        pass
    return None


def _kernel(delta_min: float, sigma_min: float) -> float:
    sigma = max(10.0, float(sigma_min))
    return math.exp(-0.5 * (float(delta_min) / sigma) ** 2)


def _empty_grid(bin_minutes: int):
    return [0.0] * int(1440 // bin_minutes)


def _grid_index(minute: float, bin_minutes: int) -> int:
    bins = max(1, int(1440 // bin_minutes))
    return int(round((float(minute) % 1440) / bin_minutes)) % bins


def _event_daily_grid(events, bin_minutes: int, sigma_min: float):
    grid = _empty_grid(bin_minutes)
    for ev in events:
        minute = float(ev['minute'])
        amp = 1.0 if ev.get('first_drive') else float(config.DEPARTURE_SECONDARY_TRIP_WEIGHT)
        for i in range(len(grid)):
            center = i * bin_minutes
            k = amp * _kernel(_minute_delta(center, minute), sigma_min)
            if k > grid[i]:
                grid[i] = k
    return grid


def _mean_grids(grids, bin_minutes: int):
    if not grids:
        return _empty_grid(bin_minutes)
    n = len(grids)
    return [sum(g[i] for g in grids) / n for i in range(len(grids[0]))]


def _blend_grids(a, b, wa: float, wb: float):
    n = min(len(a), len(b))
    return [_clamp(a[i] * wa + b[i] * wb) for i in range(n)]


def _apply_anchor_prior(grid, anchor_minute, strength: float, bin_minutes: int, sigma_min: float):
    if anchor_minute is None or strength <= 0:
        return list(grid)
    out = list(grid)
    for i in range(len(out)):
        prior = strength * _kernel(_minute_delta(i * bin_minutes, anchor_minute), sigma_min)
        # Union-like blend: the prior can help sparse data, but cannot erase evidence.
        out[i] = _clamp(1.0 - (1.0 - out[i]) * (1.0 - prior))
    return out


def _observed_days(cutoff: float, car_id: str):
    with db.connect() as con:
        rows = con.execute('SELECT ts FROM telemetry WHERE car_id=? AND ts>=? ORDER BY ts', (car_id, cutoff)).fetchall()
    days = {}
    for r in rows:
        ts = float(r['ts'])
        key = _day_key(ts)
        rec = days.setdefault(key, {'first_ts': ts, 'last_ts': ts, 'samples': 0, 'dow': time.localtime(ts).tm_wday})
        rec['first_ts'] = min(rec['first_ts'], ts)
        rec['last_ts'] = max(rec['last_ts'], ts)
        rec['samples'] += 1
    # A few samples are enough to know the car was observed that day; avoid treating
    # one isolated stale record as a complete no-trip day.
    return {k: v for k, v in days.items() if v['samples'] >= 3 or (v['last_ts'] - v['first_ts']) >= 3600}


def _drive_events(cutoff: float, car_id: str):
    with db.connect() as con:
        rows = con.execute(
            """SELECT start_ts,end_ts,distance_km,duration_min,start_soc,end_soc
                 FROM vehicle_events
                WHERE car_id=? AND event_type='drive' AND start_ts>=?
                ORDER BY start_ts""",
            (car_id, cutoff),
        ).fetchall()
    by_day = defaultdict(list)
    for r in rows:
        dist = _f(r['distance_km']) or 0.0
        dur = _f(r['duration_min']) or 0.0
        if dist < float(config.DEPARTURE_MIN_DRIVE_KM) and dur < 2.0:
            continue
        ts = float(r['start_ts'])
        by_day[_day_key(ts)].append(r)
    out = []
    for key in sorted(by_day):
        day_rows = sorted(by_day[key], key=lambda x: float(x['start_ts']))
        for i, r in enumerate(day_rows):
            ts = float(r['start_ts'])
            out.append({
                'ts': ts,
                'day': key,
                'dow': time.localtime(ts).tm_wday,
                'minute': _minute_of_day(ts),
                'first_drive': i == 0,
                'distance_km': _f(r['distance_km']),
                'duration_min': _f(r['duration_min']),
            })
    return out


def _first_workday_peak(events, anchor_minute, bin_minutes, sigma_min, prior_strength):
    first = [e for e in events if e['first_drive'] and e['dow'] < 5]
    if not first:
        return anchor_minute, 0, None
    grid = _empty_grid(bin_minutes)
    for e in first:
        for i in range(len(grid)):
            grid[i] += _kernel(_minute_delta(i * bin_minutes, e['minute']), sigma_min)
    n = max(1, len(first))
    grid = [x / n for x in grid]
    grid = _apply_anchor_prior(grid, anchor_minute, prior_strength, bin_minutes, sigma_min)
    # Prefer the strongest morning cluster. This prevents the predictable drive home
    # from becoming the work-departure routine while still allowing the morning time
    # itself to move as observations accumulate.
    morning_bins = [i for i in range(len(grid)) if 2 * 60 <= i * bin_minutes <= 11 * 60]
    pool = morning_bins or list(range(len(grid)))
    peak_i = max(pool, key=lambda i: grid[i])
    peak = peak_i * bin_minutes
    near = [e['minute'] for e in first if _minute_delta(e['minute'], peak) <= max(75, sigma_min * 1.8)]
    learned = int(round(statistics.median(near))) if near else int(peak)
    mad = statistics.median([_minute_delta(x, learned) for x in near]) if near else None
    return learned % 1440, len(near), mad


def learn_schedule(days: int | None = None, force: bool = False):
    db.init_db()
    days = int(days or config.DEPARTURE_LOOKBACK_DAYS)
    now = time.time()
    car_id = db.latest_car_id() or str(config.CAR_ID)
    cutoff = now - days * 86400
    events = _drive_events(cutoff, car_id)
    latest_event_ts = max((e['ts'] for e in events), default=0.0)
    old = db.get_state(STATE_KEY, {}) or {}
    if (
        not force
        and old.get('model_version') == MODEL_VERSION
        and int(old.get('event_count') or 0) == len(events)
        and abs(float(old.get('latest_event_ts') or 0.0) - latest_event_ts) < 1.0
        and now - float(old.get('trained_at') or 0.0) < 12 * 3600
    ):
        return old

    observed = _observed_days(cutoff, car_id)
    by_day_events = defaultdict(list)
    for e in events:
        by_day_events[e['day']].append(e)

    bin_minutes = int(config.DEPARTURE_BIN_MINUTES)
    sigma_min = float(config.DEPARTURE_KERNEL_MINUTES)
    daily_grids = {}
    for day, rec in observed.items():
        daily_grids[day] = _event_daily_grid(by_day_events.get(day, []), bin_minutes, sigma_min)

    dow_grids = {}
    group_grids = {}
    for dow in range(7):
        grids = [g for d, g in daily_grids.items() if observed[d]['dow'] == dow]
        dow_grids[str(dow)] = _mean_grids(grids, bin_minutes)
    work = [g for d, g in daily_grids.items() if observed[d]['dow'] < 5]
    weekend = [g for d, g in daily_grids.items() if observed[d]['dow'] >= 5]
    group_grids['workday'] = _mean_grids(work, bin_minutes)
    group_grids['weekend'] = _mean_grids(weekend, bin_minutes)

    first_work_days = len({e['day'] for e in events if e['first_drive'] and e['dow'] < 5})
    anchor_minute = _parse_anchor_minute()
    # The 06:00 value is a seed, not an override. Its influence fades to zero as
    # actual first-drive mornings accumulate.
    prior_strength = 0.0
    if anchor_minute is not None:
        prior_strength = float(config.DEPARTURE_PRIOR_STRENGTH) * max(0.0, 1.0 - first_work_days / float(config.DEPARTURE_PRIOR_FADE_DAYS))

    final_grids = {}
    for dow in range(7):
        group = group_grids['workday' if dow < 5 else 'weekend']
        grid = _blend_grids(dow_grids[str(dow)], group, 0.68, 0.32)
        if dow < 5:
            grid = _apply_anchor_prior(grid, anchor_minute, prior_strength, bin_minutes, sigma_min)
        final_grids[str(dow)] = [round(_clamp(x), 5) for x in grid]

    routine_minute, routine_samples, routine_mad = _first_workday_peak(
        events, anchor_minute, bin_minutes, sigma_min, prior_strength
    )

    observed_days = len(observed)
    event_days = len({e['day'] for e in events})
    evidence = _clamp(observed_days / 28.0)
    confidence = int(round(100 * (0.25 + 0.75 * evidence))) if events else int(round(prior_strength * 60))
    confidence = max(5 if anchor_minute is not None else 0, min(100, confidence))

    state = {
        'status': 'learned' if len(events) >= 3 else 'learning',
        'model_version': MODEL_VERSION,
        'trained_at': now,
        'lookback_days': days,
        'bin_minutes': bin_minutes,
        'kernel_minutes': sigma_min,
        'car_tail': str(car_id)[-6:],
        'event_count': len(events),
        'event_days': event_days,
        'observed_days': observed_days,
        'latest_event_ts': latest_event_ts,
        'anchor_text': config.EXPECTED_DEPARTURE or None,
        'anchor_minute': anchor_minute,
        'anchor_weight': round(prior_strength, 4),
        'routine_minute': routine_minute,
        'routine_text': None if routine_minute is None else f'{routine_minute // 60:02d}:{routine_minute % 60:02d}',
        'routine_samples': routine_samples,
        'routine_mad_min': None if routine_mad is None else round(float(routine_mad), 1),
        'confidence': confidence,
        'grids': final_grids,
    }
    db.set_state(STATE_KEY, state)
    return state


def model_state(refresh: bool = True):
    state = db.get_state(STATE_KEY, {}) or {}
    if refresh and (not state or time.time() - float(state.get('trained_at') or 0) > 12 * 3600):
        try:
            state = learn_schedule()
        except Exception:
            pass
    return state


def probability_at(ts: float, state=None) -> float:
    state = state or model_state(refresh=False)
    grids = state.get('grids') or {}
    bin_minutes = int(state.get('bin_minutes') or config.DEPARTURE_BIN_MINUTES)
    grid = grids.get(str(time.localtime(float(ts)).tm_wday))
    if not grid:
        return 0.0
    minute = _minute_of_day(ts)
    pos = (minute % 1440) / bin_minutes
    i0 = int(math.floor(pos)) % len(grid)
    i1 = (i0 + 1) % len(grid)
    frac = pos - math.floor(pos)
    return _clamp(float(grid[i0]) * (1 - frac) + float(grid[i1]) * frac)


def _candidate_peaks(now: float, state, horizon_hours=36):
    step = int(state.get('bin_minutes') or config.DEPARTURE_BIN_MINUTES) * 60
    start = math.ceil((now + 5 * 60) / step) * step
    end = now + horizon_hours * 3600
    samples = []
    t = start
    while t <= end:
        samples.append((t, probability_at(t, state)))
        t += step
    peaks = []
    for i, (ts, p) in enumerate(samples):
        left = samples[i - 1][1] if i else -1.0
        right = samples[i + 1][1] if i + 1 < len(samples) else -1.0
        if p >= left and p >= right:
            peaks.append((ts, p))
    return peaks or samples


def next_departure(now: float | None = None, state=None):
    now = float(now or time.time())
    state = state or model_state(refresh=True)
    anchor = state.get('anchor_minute')
    if not state.get('grids'):
        if anchor is None:
            return {'departure_ts': None, 'probability': 0.0, 'confidence': 0, 'source': 'learning', 'class': 'LEARNING'}
        lt = time.localtime(now)
        midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))
        dep = midnight + float(anchor) * 60
        if dep <= now + 5 * 60:
            dep += 86400
        return {'departure_ts': dep, 'probability': 0.25, 'confidence': 20, 'source': 'anchor_prior', 'class': 'ANCHOR'}

    peaks = _candidate_peaks(now, state)
    threshold = float(config.DEPARTURE_PREDICTION_THRESHOLD)
    qualifying = [(ts, p) for ts, p in peaks if p >= threshold]
    if qualifying:
        ts, p = min(qualifying, key=lambda x: x[0])
    else:
        ts, p = max(peaks, key=lambda x: x[1])
    evidence = _clamp(float(state.get('observed_days') or 0) / 28.0)
    conf = int(round(100 * _clamp((0.25 + 0.75 * evidence) * (0.45 + 0.55 * p))))
    cls = 'ROUTINE' if p >= 0.55 else 'LIKELY' if p >= 0.30 else 'LOW-CONFIDENCE'
    source = 'learned_schedule' if int(state.get('event_count') or 0) >= 3 else 'anchor_prior'
    return {
        'departure_ts': float(ts),
        'probability': round(float(p), 3),
        'confidence': conf,
        'source': source,
        'class': cls,
    }


def _recent_classifications(state, limit=12):
    car_id = db.latest_car_id() or str(config.CAR_ID)
    cutoff = time.time() - int(config.DEPARTURE_LOOKBACK_DAYS) * 86400
    events = _drive_events(cutoff, car_id)
    out = []
    for e in events[-max(1, int(limit)):][::-1]:
        p = probability_at(e['ts'], state)
        if e['first_drive'] and p >= 0.35:
            cls = 'ROUTINE'
        elif p >= 0.25:
            cls = 'RECURRING'
        else:
            cls = 'AD-HOC'
        out.append({
            'ts': e['ts'],
            'minute': e['minute'],
            'first_drive': bool(e['first_drive']),
            'probability': round(p, 3),
            'class': cls,
            'distance_mi': None if e['distance_km'] is None else round(e['distance_km'] * 0.621371, 1),
        })
    return out


def schedule_status(now: float | None = None, refresh: bool = True):
    now = float(now or time.time())
    state = model_state(refresh=refresh)
    nxt = next_departure(now, state)
    recent = _recent_classifications(state, 12) if state else []
    adhoc = sum(1 for x in recent if x['class'] == 'AD-HOC')
    result = dict(state)
    result['next'] = nxt
    result['recent_departures'] = recent
    result['recent_ad_hoc_count'] = adhoc
    result['seed_is_override'] = False
    result['message'] = (
        'Observed trips are driving the schedule; the configured departure is only a fading prior.'
        if float(state.get('anchor_weight') or 0) < 0.15
        else 'Schedule learning is active; the configured departure is being used only as a temporary prior.'
    ) if state else 'Waiting for departure evidence.'
    # Keep the browser payload compact.
    result.pop('grids', None)
    return result


def features_at(ts: float, state=None):
    state = state or model_state(refresh=False)
    p = probability_at(ts, state)
    nxt = next_departure(ts, state)
    dep = nxt.get('departure_ts')
    minutes = None if dep is None else max(0.0, (float(dep) - float(ts)) / 60.0)
    # Normalize at 12 hours and clip so a far-future routine cannot dominate the GRU.
    norm = 1.0 if minutes is None else min(1.0, minutes / 720.0)
    return {
        'departure_probability': float(p),
        'minutes_to_departure_norm': float(norm),
        'minutes_to_departure': minutes,
    }
