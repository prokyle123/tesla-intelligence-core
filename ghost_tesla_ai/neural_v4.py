from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import time
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from . import config, db
from . import departure_learning
from .backends.sklearn_histgb import SklearnHistGBBackend
from .backends.torch_gru import TorchGRUBackend
from .features import V3_FEATURES, feature_map, row_to_features

MODEL_NAME = 'winter_multitask_gru'
FEATURE_VERSION = 'v4-sequence-3-departure-6h'
LOCK = config.DATA_DIR / 'neural-v4.lock'

# One network learns the related winter tasks together. Targets stay in their
# native units in storage: SOC percentage points and temperature in C.
TARGETS = [
    {'name': 'soc_60m', 'field': 'battery_level', 'horizon_min': 60, 'unit': '%', 'label': 'SOC +60 min'},
    {'name': 'pack_60m', 'field': 'battery_temp_c', 'horizon_min': 60, 'unit': 'C', 'label': 'Pack +60 min'},
    {'name': 'cabin_60m', 'field': 'inside_temp_c', 'horizon_min': 60, 'unit': 'C', 'label': 'Cabin +60 min'},
    {'name': 'soc_180m', 'field': 'battery_level', 'horizon_min': 180, 'unit': '%', 'label': 'SOC +3 hr'},
    {'name': 'pack_180m', 'field': 'battery_temp_c', 'horizon_min': 180, 'unit': 'C', 'label': 'Pack +3 hr'},
    {'name': 'pack_360m', 'field': 'battery_temp_c', 'horizon_min': 360, 'unit': 'C', 'label': 'Pack +6 hr'},
]
BASELINE_MODELS = {
    'soc_60m': 'soc_60m',
    'pack_60m': 'pack_temp_60m',
    'cabin_60m': 'cabin_temp_60m',
    'soc_180m': 'soc_180m',
    'pack_180m': 'pack_temp_180m',
    'pack_360m': 'pack_temp_360m',
}

# The v4 model sees the same rich contextual values used by v3, but as a
# sequence instead of a single row. sample_age_min tells the GRU when a step is
# based on held/stale telemetry (important while a sleeping Tesla is cached).
DEPARTURE_FEATURES = ['departure_probability','minutes_to_departure_norm']
INPUT_FEATURES = list(V3_FEATURES) + DEPARTURE_FEATURES + ['sample_age_min']


FEATURE_GROUPS = {
    'battery': ['battery_level','usable_battery_level','energy_remaining_kwh','module_temp_spread_c','pack_ambient_delta_c','soc_delta_15m'],
    'thermal': ['outside_temp_c','inside_temp_c','battery_temp_c','pack_temp_delta_15m','cabin_temp_delta_15m','outside_temp_delta_15m'],
    'charging': ['plugged_in','charger_power_kw','charge_input_kw','avg_charge_power_15m','battery_heater_on'],
    'vehicle': ['pack_power_kw','speed_kmh','avg_pack_power_15m','active_fraction_15m','state_asleep','state_online','state_charging','state_driving'],
    'climate_time': ['climate_on','preconditioning','hour_sin','hour_cos','dow_sin','dow_cos','sample_age_min'],
    'schedule': ['departure_probability','minutes_to_departure_norm'],
}


def _feature_group_summary(input_features=None):
    input_features = list(input_features or INPUT_FEATURES)
    items = []
    for key, fields in FEATURE_GROUPS.items():
        active = [f for f in input_features if f in fields]
        if not active:
            continue
        items.append({
            'name': key,
            'label': {
                'battery': 'Battery state',
                'thermal': 'Thermal context',
                'charging': 'Charging path',
                'vehicle': 'Drive / power state',
                'climate_time': 'Climate + time',
                'schedule': 'Learned departure schedule',
            }.get(key, key.title()),
            'count': len(active),
            'fields': active,
        })
    return items


def _finite(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _diag_bins(values, bins=16):
    """Compress a real tensor/vector into stable display groups.

    Each bin reports signed mean plus RMS strength so the browser can visualize
    direction and activity without receiving a large tensor.
    """
    try:
        arr = np.asarray(values, dtype=np.float64).reshape(-1)
    except Exception:
        return []
    if arr.size == 0:
        return []
    parts = np.array_split(arr, min(int(bins), int(arr.size)))
    out = []
    for part in parts:
        if part.size == 0:
            continue
        mean = float(np.mean(part))
        rms = float(np.sqrt(np.mean(np.square(part))))
        mx = float(np.max(np.abs(part)))
        out.append({'mean': round(mean, 6), 'rms': round(rms, 6), 'max_abs': round(mx, 6)})
    return out


def _norm(values):
    try:
        arr = np.asarray(values, dtype=np.float64)
        return round(float(np.linalg.norm(arr)), 6)
    except Exception:
        return None


def _diagnostic_summary(diag, Xn):
    """JSON-safe observability data from the exact live PyTorch inference pass."""
    try:
        hidden = diag['hidden_final'].detach().cpu().numpy()[:, 0, :]
        temporal = diag['gru_output'].detach().cpu().numpy()[0]
        latent = diag['latent'].detach().cpu().numpy()[0]
        dense = diag['dense_activation'].detach().cpu().numpy()[0]
        input_steps = np.asarray(Xn, dtype=np.float64)[0]
        input_activity = np.mean(np.abs(input_steps), axis=1)
        max_input = max(float(np.max(input_activity)), 1e-9)
        temporal_norms = np.linalg.norm(temporal, axis=1)
        max_temporal = max(float(np.max(temporal_norms)), 1e-9)
        temporal_delta = np.zeros_like(temporal_norms)
        if len(temporal_norms) > 1:
            temporal_delta[1:] = np.linalg.norm(np.diff(temporal, axis=0), axis=1)
        max_delta = max(float(np.max(temporal_delta)), 1e-9)
        layers = []
        for i, layer in enumerate(hidden):
            layers.append({
                'layer': i + 1,
                'norm': _norm(layer),
                'mean': round(float(np.mean(layer)), 6),
                'max_abs': round(float(np.max(np.abs(layer))), 6),
                'bins': _diag_bins(layer, 16),
            })
        return {
            'source': 'exact_live_inference',
            'hidden_layers': layers,
            'temporal_norms': [round(float(x), 6) for x in temporal_norms],
            'temporal_activity_rel': [round(float(x / max_temporal), 6) for x in temporal_norms],
            'temporal_delta_rel': [round(float(x / max_delta), 6) for x in temporal_delta],
            'input_step_activity': [round(float(x), 6) for x in input_activity],
            'input_step_activity_rel': [round(float(x / max_input), 6) for x in input_activity],
            'latent': {
                'norm': _norm(latent),
                'mean': round(float(np.mean(latent)), 6),
                'max_abs': round(float(np.max(np.abs(latent))), 6),
                'bins': _diag_bins(latent, 16),
            },
            'dense': {
                'norm': _norm(dense),
                'mean': round(float(np.mean(dense)), 6),
                'max_abs': round(float(np.max(np.abs(dense))), 6),
                'bins': _diag_bins(dense, 12),
            },
        }
    except Exception as e:
        return {'source': 'diagnostic_error', 'error': f'{type(e).__name__}: {e}'}


def _get(row, key, default=None):
    try:
        return row[key]
    except Exception:
        try:
            return row.get(key, default)
        except Exception:
            return default


def _next_generation() -> int:
    with db.connect() as con:
        r = con.execute('SELECT MAX(generation) g FROM neural_v4_runs').fetchone()
    return int((r['g'] or 0) + 1)


def _window_steps() -> int:
    return max(3, int(config.NEURAL_V4_WINDOW_MINUTES // config.NEURAL_V4_STEP_MINUTES) + 1)


def _day_split(source_ts, n):
    days = [time.strftime('%Y-%m-%d', time.localtime(t)) for t in source_ts]
    uniq = []
    for d in days:
        if not uniq or uniq[-1] != d:
            uniq.append(d)
    if len(uniq) >= 5:
        test_days = max(1, int(math.ceil(len(uniq) * .20)))
        cutoff = uniq[-test_days]
        split = next((i for i, d in enumerate(days) if d >= cutoff), int(n * .8))
        if split >= 100 and n - split >= 100:
            return split, f'day-blocked chronological holdout ({test_days} whole days)'
    split = max(100, min(n - 100, int(n * .8)))
    return split, 'row-ordered fallback'


def _history_for_index(rows, times, i, seconds=3600):
    h0 = bisect.bisect_left(times, times[i] - seconds, 0, i + 1)
    return rows[h0:i + 1]


def _step_vector(row, history, age_min: float, input_features=None, schedule_state=None, schedule_cache=None):
    input_features = list(input_features or INPUT_FEATURES)
    fm = feature_map(row, history)
    ts = _finite(_get(row, 'ts')) or time.time()
    dep = {}
    if any(k in input_features for k in DEPARTURE_FEATURES):
        key = int(ts // max(60, int((schedule_state or {}).get('bin_minutes') or config.DEPARTURE_BIN_MINUTES) * 60))
        if schedule_cache is not None and key in schedule_cache:
            dep = schedule_cache[key]
        else:
            dep = departure_learning.features_at(ts, state=schedule_state)
            if schedule_cache is not None:
                schedule_cache[key] = dep
    merged = dict(fm)
    merged.update(dep)
    merged['sample_age_min'] = float(age_min)
    return [float(merged.get(k, float('nan'))) for k in input_features]


def _sequence_at(rows, times, i, max_hold_minutes=90, input_features=None, schedule_state=None, schedule_cache=None):
    input_features = list(input_features or INPUT_FEATURES)
    anchor = times[i]
    step_sec = config.NEURAL_V4_STEP_MINUTES * 60
    nsteps = _window_steps()
    seq = []
    max_age = 0.0
    # Oldest -> newest, using the latest observation available at each grid time.
    # input_features is artifact-specific so pre-v0.8.27 GRUs keep their original
    # input width while new generations gain the departure-schedule context.
    for back in range(nsteps - 1, -1, -1):
        wanted = anchor - back * step_sec
        j = bisect.bisect_right(times, wanted, 0, i + 1) - 1
        if j < 0:
            return None, None
        age_min = max(0.0, (wanted - times[j]) / 60.0)
        if age_min > max_hold_minutes:
            return None, None
        max_age = max(max_age, age_min)
        history = _history_for_index(rows, times, j, 3600)
        seq.append(_step_vector(rows[j], history, age_min, input_features=input_features, schedule_state=schedule_state, schedule_cache=schedule_cache))
    return seq, max_age




def _sequence_debug(rows, times, i, max_hold_minutes=120, schedule_state=None):
    anchor = times[i]
    step_sec = config.NEURAL_V4_STEP_MINUTES * 60
    nsteps = _window_steps()
    out = []
    for back in range(nsteps - 1, -1, -1):
        wanted = anchor - back * step_sec
        j = bisect.bisect_right(times, wanted, 0, i + 1) - 1
        if j < 0:
            return []
        age_min = max(0.0, (wanted - times[j]) / 60.0)
        if age_min > max_hold_minutes:
            return []
        row = rows[j]
        dep = departure_learning.features_at(float(times[j]), state=schedule_state)
        out.append({
            'offset_min': int(back * config.NEURAL_V4_STEP_MINUTES),
            'label': 'NOW' if back == 0 else f'-{back * config.NEURAL_V4_STEP_MINUTES}m',
            'ts': float(times[j]),
            'sample_age_min': round(float(age_min), 1),
            'battery_level': _finite(_get(row, 'battery_level')),
            'outside_temp_c': _finite(_get(row, 'outside_temp_c')),
            'inside_temp_c': _finite(_get(row, 'inside_temp_c')),
            'battery_temp_c': _finite(_get(row, 'battery_temp_c')),
            'pack_power_kw': _finite(_get(row, 'pack_power_kw')),
            'charge_input_kw': _finite(_get(row, 'charge_input_kw')),
            'charger_power_kw': _finite(_get(row, 'charger_power_kw')),
            'climate_on': bool(_get(row, 'climate_on')),
            'preconditioning': bool(_get(row, 'preconditioning')),
            'battery_heater_on': bool(_get(row, 'battery_heater_on')),
            'state': str(_get(row, 'state') or ''),
            'departure_probability': round(float(dep.get('departure_probability') or 0.0), 3),
            'minutes_to_departure': None if dep.get('minutes_to_departure') is None else round(float(dep['minutes_to_departure']), 1),
        })
    return out

def _target_index(times, i, horizon_min):
    want = times[i] + horizon_min * 60
    j = bisect.bisect_left(times, want, i + 1)
    if j >= len(times):
        return None
    tolerance = max(12 * 60, horizon_min * 60 * .18)
    if times[j] - want > tolerance:
        return None
    return j


def build_sequence_dataset():
    cutoff = time.time() - config.TRAIN_LOOKBACK_DAYS * 86400
    car_id = db.latest_car_id() or str(config.CAR_ID)
    with db.connect() as con:
        rows = con.execute('SELECT * FROM telemetry WHERE car_id=? AND ts>=? ORDER BY ts', (car_id, cutoff)).fetchall()
    if not rows:
        return None
    times = [float(r['ts']) for r in rows]
    schedule_state = departure_learning.model_state(refresh=True)
    schedule_cache = {}
    X, Y, source_ids, source_ts, source_indices, max_ages = [], [], [], [], [], []
    warmup = config.NEURAL_V4_WINDOW_MINUTES * 60
    for i, row in enumerate(rows):
        if times[i] - times[0] < warmup:
            continue
        seq, max_age = _sequence_at(rows, times, i, max_hold_minutes=20, input_features=INPUT_FEATURES, schedule_state=schedule_state, schedule_cache=schedule_cache)
        if seq is None:
            continue
        yy = []
        valid = True
        for target in TARGETS:
            j = _target_index(times, i, target['horizon_min'])
            if j is None or _get(rows[j], target['field']) is None:
                valid = False
                break
            v = _finite(_get(rows[j], target['field']))
            if v is None:
                valid = False
                break
            yy.append(v)
        if not valid:
            continue
        X.append(seq)
        Y.append(yy)
        source_ids.append(int(row['id']))
        source_ts.append(times[i])
        source_indices.append(i)
        max_ages.append(max_age)
    return {
        'X': np.asarray(X, dtype=np.float32),
        'Y': np.asarray(Y, dtype=np.float32),
        'source_ids': source_ids,
        'source_ts': source_ts,
        'source_indices': source_indices,
        'rows': rows,
        'times': times,
        'max_ages': max_ages,
        'schedule_state': schedule_state,
        'schedule_cache': schedule_cache,
    }


def _scalers(Xtr, Ytr):
    flat = Xtr.reshape(-1, Xtr.shape[-1]).astype(np.float64)
    med = np.nanmedian(flat, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    filled = np.where(np.isnan(flat), med[None, :], flat)
    mean = np.mean(filled, axis=0)
    std = np.std(filled, axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    ymean = np.mean(Ytr, axis=0)
    ystd = np.std(Ytr, axis=0)
    ystd = np.where(ystd < 1e-6, 1.0, ystd)
    return med.astype(np.float32), mean.astype(np.float32), std.astype(np.float32), ymean.astype(np.float32), ystd.astype(np.float32)


def _transform_x(X, med, mean, std):
    z = np.where(np.isnan(X), med[None, None, :], X)
    z = (z - mean[None, None, :]) / std[None, None, :]
    return np.clip(z, -8.0, 8.0).astype(np.float32)


def _metrics(y, p):
    out = {}
    for j, target in enumerate(TARGETS):
        yy, pp = y[:, j], p[:, j]
        out[target['name']] = {
            'label': target['label'],
            'unit': target['unit'],
            'mae': float(mean_absolute_error(yy, pp)),
            'rmse': float(math.sqrt(mean_squared_error(yy, pp))),
            'r2': float(r2_score(yy, pp)) if len(yy) > 1 else None,
        }
    return out


def _baseline_same_holdout(data, split):
    out = {}
    rows, times = data['rows'], data['times']
    indices = data['source_indices'][split:]
    yte = data['Y'][split:]
    for t_idx, target in enumerate(TARGETS):
        model_name = BASELINE_MODELS[target['name']]
        with db.connect() as con:
            run = con.execute('SELECT * FROM model_runs WHERE model_name=? AND promoted=1 ORDER BY generation DESC LIMIT 1', (model_name,)).fetchone()
        if not run or not run['artifact_path'] or not Path(run['artifact_path']).exists():
            out[target['name']] = {'available': False}
            continue
        try:
            feats = json.loads(run['features_json'] or '[]') or V3_FEATURES
            model = SklearnHistGBBackend.load(run['artifact_path'])
            bx = []
            for i in indices:
                history = _history_for_index(rows, times, i, 3600)
                bx.append(row_to_features(rows[i], feats, history))
            bp = model.predict(np.asarray(bx, dtype=float))
            mae = float(mean_absolute_error(yte[:, t_idx], bp))
            out[target['name']] = {
                'available': True,
                'generation': int(run['generation']),
                'backend': run['backend'],
                'mae': mae,
            }
        except Exception as e:
            out[target['name']] = {'available': False, 'error': f'{type(e).__name__}: {e}'}
    return out


def _torch_version():
    return getattr(torch, '__version__', 'unknown')


def _served_neural_generation():
    try:
        with db.connect() as con:
            r=con.execute("SELECT generation FROM neural_v4_governor WHERE stage='PRODUCTION' ORDER BY production_started_at DESC,generation DESC LIMIT 1").fetchone()
        return None if not r else int(r['generation'])
    except Exception:
        return None


def _neural_baseline_same_holdout(data, split, generation):
    if generation is None:return {}
    try:
        with db.connect() as con:
            run=con.execute('SELECT * FROM neural_v4_runs WHERE generation=? ORDER BY id DESC LIMIT 1',(int(generation),)).fetchone()
        if not run or not run['artifact_path'] or not Path(run['artifact_path']).exists():return {}
        payload=TorchGRUBackend.load(run['artifact_path'])
        payload_targets=list(payload.get('targets') or [])
        backend=TorchGRUBackend(input_size=len(payload['input_features']),output_size=len(payload_targets),hidden_size=int(payload['hidden_size']),layers=int(payload['layers']),dropout=float(payload['dropout']))
        model=backend.create();model.load_state_dict(payload['state_dict']);model.eval()
        old_features=list(payload.get('input_features') or [])
        if old_features == list(INPUT_FEATURES):
            Xte=data['X'][split:]
        else:
            # Rebuild identical holdout timestamps with the served artifact's own
            # feature contract. A five-head production GRU can therefore remain
            # the baseline while a challenger adds the new six-hour head.
            seqs=[]
            for idx in data['source_indices'][split:]:
                seq,_=_sequence_at(data['rows'],data['times'],idx,max_hold_minutes=20,input_features=old_features,schedule_state=data.get('schedule_state'),schedule_cache=data.get('schedule_cache'))
                if seq is None:
                    return {'_error':'could not rebuild legacy production holdout sequences'}
                seqs.append(seq)
            Xte=np.asarray(seqs,dtype=np.float32)
        med=np.asarray(payload['x_median'],dtype=np.float32);mean=np.asarray(payload['x_mean'],dtype=np.float32);std=np.asarray(payload['x_std'],dtype=np.float32)
        Xn=_transform_x(Xte,med,mean,std)
        with torch.no_grad():pn=model(torch.from_numpy(Xn)).cpu().numpy()
        ymean=np.asarray(payload['y_mean'],dtype=np.float32);ystd=np.asarray(payload['y_std'],dtype=np.float32)
        pp=pn*ystd[None,:]+ymean[None,:]
        current_index={t['name']:i for i,t in enumerate(TARGETS)}
        out={}
        for old_i,target in enumerate(payload_targets):
            name=target.get('name')
            cur_i=current_index.get(name)
            if cur_i is None or old_i>=pp.shape[1]:continue
            out[name]={'available':True,'generation':int(generation),'backend':'pytorch_gru','mae':float(mean_absolute_error(data['Y'][split:,cur_i],pp[:,old_i])),'source':'neural_production'}
        return out
    except Exception as e:
        return {'_error':f'{type(e).__name__}: {e}'}


def _publish_training_state(**extra):
    state = {
        'status': 'training',
        'backend': 'pytorch',
        'torch': _torch_version(),
        'last_update': time.time(),
    }
    state.update(extra)
    db.set_state('neural_v4', state)
    return state


def _parameter_count(model):
    return int(sum(p.numel() for p in model.parameters()))


def train():
    db.init_db()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 4 * 3600:
        return {'status': 'busy'}
    LOCK.write_text(str(os.getpid()))
    started = time.time()
    _publish_training_state(phase='building_dataset', started_at=started, rows=0, epoch=0,
                            max_epochs=int(config.NEURAL_V4_EPOCHS), progress_pct=0.0,
                            message='Building 60-minute Tesla telemetry sequences…', history=[])
    print('[neural-v4] building 60-minute sequence dataset...', flush=True)
    try:
        data = build_sequence_dataset()
        if not data:
            return {'status': 'waiting', 'rows': 0}
        X, Y = data['X'], data['Y']
        n = len(Y)
        if n < config.NEURAL_V4_MIN_ROWS:
            state = {'status': 'waiting', 'phase': 'evidence_gate', 'rows': n, 'need': config.NEURAL_V4_MIN_ROWS,
                     'finished_at': time.time(), 'torch': _torch_version(),
                     'message': f'Need {config.NEURAL_V4_MIN_ROWS-n:,} more eligible sequence rows.'}
            db.set_state('neural_v4', state)
            print(f'[neural-v4] waiting: {n:,}/{config.NEURAL_V4_MIN_ROWS:,} eligible rows', flush=True)
            return state
        split, strategy = _day_split(data['source_ts'], n)
        Xtr, Xte = X[:split], X[split:]
        Ytr, Yte = Y[:split], Y[split:]
        med, xmean, xstd, ymean, ystd = _scalers(Xtr, Ytr)
        Xtrn = _transform_x(Xtr, med, xmean, xstd)
        Xten = _transform_x(Xte, med, xmean, xstd)
        Ytrn = ((Ytr - ymean[None, :]) / ystd[None, :]).astype(np.float32)
        Yten = ((Yte - ymean[None, :]) / ystd[None, :]).astype(np.float32)

        torch.manual_seed(42)
        np.random.seed(42)
        backend = TorchGRUBackend(
            input_size=X.shape[-1],
            output_size=Y.shape[-1],
            hidden_size=config.NEURAL_V4_HIDDEN,
            layers=config.NEURAL_V4_LAYERS,
            dropout=config.NEURAL_V4_DROPOUT,
        )
        model = backend.create()
        parameters = _parameter_count(model)
        _publish_training_state(
            phase='training', started_at=started, rows=n, train_rows=split, test_rows=n-split,
            validation=strategy, epoch=0, max_epochs=int(config.NEURAL_V4_EPOCHS), progress_pct=0.0,
            best_epoch=0, best_val_loss=None, train_loss=None, val_loss=None, patience=0,
            parameters=parameters, sequence_steps=int(X.shape[1]), input_features=int(X.shape[2]),
            outputs=int(Y.shape[1]), history=[], message='PyTorch GRU initialized; beginning epoch 1.'
        )
        print(f'[neural-v4] evidence={n:,} train={split:,} test={n-split:,} params={parameters:,} strategy={strategy}', flush=True)
        opt = torch.optim.AdamW(model.parameters(), lr=config.NEURAL_V4_LR, weight_decay=1e-4)
        loss_fn = nn.SmoothL1Loss(beta=.5)
        ds = TensorDataset(torch.from_numpy(Xtrn), torch.from_numpy(Ytrn))
        loader = DataLoader(ds, batch_size=config.NEURAL_V4_BATCH_SIZE, shuffle=True, num_workers=0)
        xval = torch.from_numpy(Xten)
        yval = torch.from_numpy(Yten)
        best_loss = float('inf')
        best_state = None
        best_epoch = 0
        patience = 0
        history = []
        for epoch in range(1, config.NEURAL_V4_EPOCHS + 1):
            epoch_started = time.monotonic()
            model.train()
            losses = []
            for xb, yb in loader:
                opt.zero_grad(set_to_none=True)
                pred = model(xb)
                loss = loss_fn(pred, yb)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 3.0)
                opt.step()
                losses.append(float(loss.detach()))
            model.eval()
            with torch.no_grad():
                vp = model(xval)
                vloss = float(loss_fn(vp, yval))
            epoch_seconds = max(1e-6, time.monotonic() - epoch_started)
            samples_per_sec = float(split) / epoch_seconds
            batches_per_sec = float(len(loader)) / epoch_seconds
            train_loss = float(sum(losses) / max(1, len(losses)))
            history.append({
                'epoch': epoch,
                'train_loss': round(train_loss, 6),
                'val_loss': round(vloss, 6),
                'epoch_seconds': round(epoch_seconds, 3),
                'samples_per_sec': round(samples_per_sec, 1),
                'batches_per_sec': round(batches_per_sec, 2),
                'batch_count': int(len(loader)),
            })
            if vloss < best_loss - 1e-5:
                best_loss = vloss
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                best_epoch = epoch
                patience = 0
            else:
                patience += 1
            pct = round(100.0 * epoch / max(1, int(config.NEURAL_V4_EPOCHS)), 1)
            _publish_training_state(
                phase='training', started_at=started, rows=n, train_rows=split, test_rows=n-split,
                validation=strategy, epoch=epoch, max_epochs=int(config.NEURAL_V4_EPOCHS), progress_pct=pct,
                train_loss=round(train_loss, 6), val_loss=round(vloss, 6),
                best_val_loss=None if not math.isfinite(best_loss) else round(best_loss, 6),
                best_epoch=best_epoch, patience=patience, patience_limit=int(config.NEURAL_V4_PATIENCE),
                parameters=parameters, sequence_steps=int(X.shape[1]), input_features=int(X.shape[2]),
                outputs=int(Y.shape[1]), history=history[-180:],
                epoch_seconds=round(epoch_seconds, 3), samples_per_sec=round(samples_per_sec, 1),
                batches_per_sec=round(batches_per_sec, 2), batch_count=int(len(loader)),
                message=f'Epoch {epoch}/{config.NEURAL_V4_EPOCHS} • validation loss {vloss:.5f} • {samples_per_sec:.0f} samples/s'
            )
            print(f'[neural-v4] epoch {epoch:03d}/{config.NEURAL_V4_EPOCHS} train={train_loss:.6f} val={vloss:.6f} best={best_loss:.6f}@{best_epoch} patience={patience}/{config.NEURAL_V4_PATIENCE}', flush=True)
            if patience >= config.NEURAL_V4_PATIENCE:
                print(f'[neural-v4] early stopping at epoch {epoch}; best epoch {best_epoch}', flush=True)
                break
        if best_state is not None:
            model.load_state_dict(best_state)
        model.eval()
        with torch.no_grad():
            predn = model(xval).cpu().numpy()
        pred = predn * ystd[None, :] + ymean[None, :]
        metrics = _metrics(Yte, pred)
        baseline = _baseline_same_holdout(data, split)
        served_neural=_served_neural_generation()
        if served_neural is not None:
            neural_baseline=_neural_baseline_same_holdout(data,split,served_neural)
            if neural_baseline and '_error' not in neural_baseline:
                # Overlay only heads the served generation actually owns. New
                # heads retain their tree champion as the safe comparison.
                baseline.update(neural_baseline)
        for target in TARGETS:
            name = target['name']
            b = baseline.get(name) or {}
            if b.get('available') and b.get('mae') is not None:
                bm = float(b['mae'])
                nm = float(metrics[name]['mae'])
                metrics[name]['baseline_mae'] = bm
                metrics[name]['baseline_generation'] = b.get('generation')
                metrics[name]['baseline_backend'] = b.get('backend')
                metrics[name]['baseline_source'] = b.get('source') or ('tree_production' if b.get('backend') else None)
                metrics[name]['improvement_pct'] = ((bm - nm) / bm * 100.0) if bm > 1e-9 else None
                metrics[name]['beats_champion_same_holdout'] = nm < bm
            else:
                metrics[name]['baseline_mae'] = None
                metrics[name]['improvement_pct'] = None
                metrics[name]['beats_champion_same_holdout'] = False

        generation = _next_generation()
        outdir = config.MODEL_DIR / 'neural_v4'
        artifact = outdir / f'gru-gen-{generation:04d}.pt'
        architecture = f'GRU({config.NEURAL_V4_HIDDEN}x{config.NEURAL_V4_LAYERS}) -> LayerNorm -> 48 -> {len(TARGETS)}'
        payload = {
            'model_name': MODEL_NAME,
            'architecture': architecture,
            'backend': backend.name,
            'generation': generation,
            'trained_at': time.time(),
            'torch_version': _torch_version(),
            'state_dict': model.state_dict(),
            'input_features': INPUT_FEATURES,
            'feature_version': FEATURE_VERSION,
            'departure_schedule': {k:v for k,v in (data.get('schedule_state') or {}).items() if k != 'grids'},
            'targets': TARGETS,
            'window_minutes': config.NEURAL_V4_WINDOW_MINUTES,
            'step_minutes': config.NEURAL_V4_STEP_MINUTES,
            'hidden_size': config.NEURAL_V4_HIDDEN,
            'layers': config.NEURAL_V4_LAYERS,
            'dropout': config.NEURAL_V4_DROPOUT,
            'x_median': med,
            'x_mean': xmean,
            'x_std': xstd,
            'y_mean': ymean,
            'y_std': ystd,
            'metrics': metrics,
            'baseline': baseline,
            'validation_strategy': strategy,
            'best_epoch': best_epoch,
            'parameters': parameters,
            'sequence_steps': int(X.shape[1]),
            'history_tail': history[-180:],
        }
        TorchGRUBackend.save(artifact, payload)
        with db.connect() as con:
            con.execute('''INSERT INTO neural_v4_runs(model_name,backend,generation,trained_at,rows_total,rows_train,rows_test,artifact_path,
                          architecture,window_minutes,step_minutes,input_features_json,targets_json,metrics_json,baseline_json,validation_strategy,best_epoch,torch_version,notes)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (MODEL_NAME, backend.name, generation, payload['trained_at'], n, split, n-split, str(artifact),
                         architecture,
                         config.NEURAL_V4_WINDOW_MINUTES, config.NEURAL_V4_STEP_MINUTES, json.dumps(INPUT_FEATURES), json.dumps(TARGETS),
                         json.dumps(metrics), json.dumps(baseline), strategy, best_epoch, _torch_version(),
                         'PyTorch multi-task temporal challenger with learned departure-schedule context; governed by shadow/truth/canary promotion pipeline'))
        state = {
            'status': 'trained', 'phase': 'complete', 'generation': generation, 'rows': n, 'train_rows': split, 'test_rows': n-split,
            'best_epoch': best_epoch, 'epochs_ran': len(history), 'max_epochs': int(config.NEURAL_V4_EPOCHS),
            'metrics': metrics, 'baseline': baseline, 'history': history[-180:],
            'artifact': str(artifact), 'validation': strategy, 'finished_at': time.time(), 'duration_s': round(time.time()-started, 2),
            'torch': _torch_version(), 'architecture': payload['architecture'], 'parameters': parameters,
            'sequence_steps': int(X.shape[1]), 'input_features': int(X.shape[2]), 'outputs': int(Y.shape[1]),
            'progress_pct': 100.0, 'message': f'Generation {generation} complete.'
        }
        db.set_state('neural_v4', state)
        try:
            from .neural_governor import cycle as governor_cycle
            state['governor']=governor_cycle()
            db.set_state('neural_v4', state)
        except Exception as e:
            state['governor_error']=f'{type(e).__name__}: {e}'
            db.set_state('neural_v4', state)
        print(f'[neural-v4] generation {generation} complete in {state["duration_s"]}s; best epoch {best_epoch}', flush=True)
        return state
    except Exception as e:
        state = {'status': 'error', 'phase': 'error', 'error': f'{type(e).__name__}: {e}', 'finished_at': time.time(),
                 'started_at': started, 'torch': _torch_version(), 'message': 'PyTorch training failed; see neural-v4-train.log.'}
        db.set_state('neural_v4', state)
        raise
    finally:
        try:
            LOCK.unlink()
        except FileNotFoundError:
            pass


def latest_run():
    db.init_db()
    with db.connect() as con:
        return con.execute('SELECT * FROM neural_v4_runs ORDER BY generation DESC LIMIT 1').fetchone()


def _load_run(run):
    if not run or not run['artifact_path'] or not Path(run['artifact_path']).exists():
        return None, None
    payload = TorchGRUBackend.load(run['artifact_path'])
    backend = TorchGRUBackend(
        input_size=len(payload['input_features']),
        output_size=len(payload['targets']),
        hidden_size=int(payload['hidden_size']),
        layers=int(payload['layers']),
        dropout=float(payload['dropout']),
    )
    model = backend.create()
    model.load_state_dict(payload['state_dict'])
    model.eval()
    return run, (payload, model)


def _load_latest():
    return _load_run(latest_run())


def _run_for_generation(generation):
    db.init_db()
    with db.connect() as con:
        return con.execute('SELECT * FROM neural_v4_runs WHERE generation=? ORDER BY id DESC LIMIT 1',(int(generation),)).fetchone()


def forecast_for_generation(generation):
    return _forecast_loaded(*_load_run(_run_for_generation(generation)))


def current_forecast():
    return _forecast_loaded(*_load_latest())


def _forecast_loaded(run, loaded):
    if not loaded:
        return {'status': 'waiting', 'message': 'No PyTorch generation has been trained yet.'}
    payload, model = loaded
    car_id = db.latest_car_id() or str(config.CAR_ID)
    with db.connect() as con:
        rows = con.execute('SELECT * FROM telemetry WHERE car_id=? ORDER BY ts DESC LIMIT 500', (car_id,)).fetchall()
    rows = list(reversed(rows))
    if not rows:
        return {'status': 'waiting', 'message': 'No telemetry.'}
    times = [float(r['ts']) for r in rows]
    artifact_features = list(payload.get('input_features') or INPUT_FEATURES)
    schedule_state = departure_learning.model_state(refresh=True)
    seq, max_age = _sequence_at(rows, times, len(rows)-1, max_hold_minutes=120, input_features=artifact_features, schedule_state=schedule_state, schedule_cache={})
    if seq is None:
        return {'status': 'waiting', 'message': 'Not enough recent sequence history.'}
    X = np.asarray([seq], dtype=np.float32)
    med = np.asarray(payload['x_median'], dtype=np.float32)
    mean = np.asarray(payload['x_mean'], dtype=np.float32)
    std = np.asarray(payload['x_std'], dtype=np.float32)
    Xn = _transform_x(X, med, mean, std)
    diagnostics = {}
    with torch.no_grad():
        xt = torch.from_numpy(Xn)
        if hasattr(model, 'forward_diagnostics'):
            pred_tensor, diag = model.forward_diagnostics(xt)
            pn = pred_tensor.cpu().numpy()[0]
            diagnostics = _diagnostic_summary(diag, Xn)
        else:
            pn = model(xt).cpu().numpy()[0]
    ymean = np.asarray(payload['y_mean'], dtype=np.float32)
    ystd = np.asarray(payload['y_std'], dtype=np.float32)
    pred = pn * ystd + ymean
    out = []
    for i, target in enumerate(payload['targets']):
        metric = (payload.get('metrics') or {}).get(target['name'], {})
        out.append({
            'name': target['name'], 'label': target['label'], 'field': target['field'], 'horizon_min': target['horizon_min'],
            'unit': target['unit'], 'value': float(pred[i]), 'holdout_mae': metric.get('mae'),
            'baseline_mae': metric.get('baseline_mae'), 'improvement_pct': metric.get('improvement_pct'),
        })
    seq_debug = _sequence_debug(rows, times, len(rows)-1, max_hold_minutes=120, schedule_state=schedule_state)
    departure_context = departure_learning.schedule_status(times[-1], refresh=False)
    return {
        'status': 'ready', 'generation': int(run['generation']), 'backend': run['backend'], 'predicted_at': times[-1],
        'source_telemetry_id': int(rows[-1]['id']), 'sequence_max_age_min': round(float(max_age or 0), 1), 'predictions': out,
        'sequence_debug': seq_debug,
        'feature_groups': _feature_group_summary(artifact_features),
        'departure_context': departure_context,
        'diagnostics': diagnostics,
        'latest_context': {
            'row_ts': float(times[-1]),
            'battery_level': _finite(_get(rows[-1], 'battery_level')),
            'outside_temp_c': _finite(_get(rows[-1], 'outside_temp_c')),
            'inside_temp_c': _finite(_get(rows[-1], 'inside_temp_c')),
            'battery_temp_c': _finite(_get(rows[-1], 'battery_temp_c')),
            'state': str(_get(rows[-1], 'state') or ''),
        },
    }


def status():
    run = latest_run()
    state = db.get_state('neural_v4', {}) or {}
    forecast = current_forecast()
    if not run:
        return {'engine': state, 'run': None, 'forecast': forecast, 'torch_version': _torch_version(),
                'feature_groups': _feature_group_summary(INPUT_FEATURES),
                'departure_learning': departure_learning.schedule_status(refresh=True)}
    def loads(v, default):
        try: return json.loads(v) if v else default
        except Exception: return default
    artifact_meta = {}
    try:
        if run['artifact_path'] and Path(run['artifact_path']).exists():
            ap = TorchGRUBackend.load(run['artifact_path'])
            artifact_meta = {
                'history': ap.get('history_tail') or [],
                'parameters': int(ap.get('parameters') or 0),
                'sequence_steps': int(ap.get('sequence_steps') or _window_steps()),
                'input_features_count': len(ap.get('input_features') or []),
                'input_features': list(ap.get('input_features') or []),
                'outputs': len(ap.get('targets') or []),
            }
    except Exception:
        artifact_meta = {}
    return {
        'engine': state,
        'torch_version': _torch_version(),
        'hyperparams': {
            'window_minutes': int(config.NEURAL_V4_WINDOW_MINUTES),
            'step_minutes': int(config.NEURAL_V4_STEP_MINUTES),
            'hidden_size': int(config.NEURAL_V4_HIDDEN),
            'layers': int(config.NEURAL_V4_LAYERS),
            'dropout': float(config.NEURAL_V4_DROPOUT),
            'batch_size': int(config.NEURAL_V4_BATCH_SIZE),
            'epochs': int(config.NEURAL_V4_EPOCHS),
            'patience': int(config.NEURAL_V4_PATIENCE),
            'lr': float(config.NEURAL_V4_LR),
        },
        'feature_groups': _feature_group_summary((artifact_meta.get('input_features') or INPUT_FEATURES)),
        'departure_learning': departure_learning.schedule_status(refresh=True),
        'run': {
            'generation': int(run['generation']), 'trained_at': float(run['trained_at']), 'rows': int(run['rows_total']),
            'train_rows': int(run['rows_train']), 'test_rows': int(run['rows_test']), 'backend': run['backend'],
            'architecture': run['architecture'], 'window_minutes': int(run['window_minutes']), 'step_minutes': int(run['step_minutes']),
            'metrics': loads(run['metrics_json'], {}), 'baseline': loads(run['baseline_json'], {}),
            'validation': run['validation_strategy'], 'best_epoch': int(run['best_epoch'] or 0), 'torch_version': run['torch_version'],
            **artifact_meta,
        },
        'forecast': forecast,
    }


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--train', action='store_true')
    p.add_argument('--status', action='store_true')
    a = p.parse_args()
    print(json.dumps(train() if a.train else status(), indent=2, default=str))
