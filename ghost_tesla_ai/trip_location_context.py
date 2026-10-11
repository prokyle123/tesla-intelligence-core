#!/usr/bin/env python3
"""GHOST location-context v2: stable place IDs and nearby-context evidence.

Shadow only. Reads v1 private latest.json, keeps private registry, and writes
private location-context.json plus share-safe TXT with no coordinates.
Does not modify the Tesla AI SQLite DB, production departure engine or neural models.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import time

VERSION = 'location-context-shadow-v2.0.0'
RADIUS_KM = 0.85
NEARBY_KM = 2.5
REGISTRY_NAME = 'stable-zones.json'


def num(x):
    try:
        n = float(x)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError, OverflowError):
        return None


def distance_km(a, b):
    a0, a1 = math.radians(a[0]), math.radians(a[1])
    b0, b1 = math.radians(b[0]), math.radians(b[1])
    h = math.sin((b0-a0)/2)**2 + math.cos(a0)*math.cos(b0)*math.sin((b1-a1)/2)**2
    return 12742 * math.asin(min(1, math.sqrt(max(0, h))))


def safe_write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.ghost-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def safe_write_text(path, s):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix='.ghost-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(s)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def center(z):
    x, y = num(z.get('centroid_lat')), num(z.get('centroid_lon'))
    return (x, y) if x is not None and y is not None and -90 < x < 90 and -180 < y < 180 else None


def normalized_registry(old):
    if not isinstance(old, dict):
        old = {}
    return {
        'version': VERSION,
        'next_id': max(1, int(old.get('next_id') or 1)),
        'places': {k: v for k, v in (old.get('places') or {}).items()
                   if isinstance(k, str) and isinstance(v, dict) and center(v)},
    }


def associate_sites(zones, registry, ts):
    """One-to-one nearest matches; never merge different physical sites.

    For mapping stability, known sites retain their IDs even if their ranks and
    labels in the source's size-ranked ZONE_N listing change.
    """
    registry = normalized_registry(registry)
    live = []
    for z in zones:
        if not isinstance(z, dict) or not z.get('id') or center(z) is None:
            continue
        live.append(z)
    known = registry['places']
    candidates = []
    for z in live:
        for stable, ref in known.items():
            d = distance_km(center(z), center(ref))
            if d <= RADIUS_KM:
                candidates.append((d, z['id'], stable))
    mapping = {}
    used = set()
    for d, transient, stable in sorted(candidates):
        if transient not in mapping and stable not in used:
            mapping[transient] = stable
            used.add(stable)
    for z in live:
        transient = z['id']
        if transient not in mapping:
            while f'SITE_{registry["next_id"]:03d}' in known:
                registry['next_id'] += 1
            stable = f'SITE_{registry["next_id"]:03d}'
            registry['next_id'] += 1
            mapping[transient] = stable
            known[stable] = {
                'centroid_lat': center(z)[0], 'centroid_lon': center(z)[1],
                'created_at': ts, 'seen_count': 0,
            }
        stable = mapping[transient]
        rec = known[stable]
        # Light centroid smoothing allows small GPS drift without ID churn.
        # Existing stable sites are NOT merged with nearby independent sites.
        alpha = 0.15 if rec.get('seen_count', 0) else 1.0
        rec['centroid_lat'] = round((1-alpha) * float(rec['centroid_lat']) + alpha * center(z)[0], 7)
        rec['centroid_lon'] = round((1-alpha) * float(rec['centroid_lon']) + alpha * center(z)[1], 7)
        rec['seen_count'] = int(rec.get('seen_count', 0)) + 1
        rec['last_seen_at'] = ts
        rec['latest_observations'] = int(z.get('visits') or 0)
        rec['latest_observed_days'] = int(z.get('observed_days') or 0)
        rec['source_label'] = transient
    return mapping, registry


def build_context(v1, registry, now):
    if not isinstance(v1, dict) or not isinstance(v1.get('anonymous_zones'), list):
        raise ValueError('v1 sequence report missing anonymous_zones')
    mapping, registry = associate_sites(v1['anonymous_zones'], registry, now)
    actual_sites = sorted(set(mapping.values()))
    pairs = []
    for i, a in enumerate(actual_sites):
        for b in actual_sites[i+1:]:
            km = distance_km(center(registry['places'][a]), center(registry['places'][b]))
            if km <= NEARBY_KM:
                pairs.append({'site_a': a, 'site_b': b, 'distance_km': round(km, 2),
                              'relationship': 'NEARBY_ONLY_NOT_MERGED'})
    pairs.sort(key=lambda x: x['distance_km'])
    transitions = []
    for t in v1.get('zone_transitions') or []:
        start, end = mapping.get(t.get('from')), mapping.get(t.get('to'))
        if start and end and start != end:
            transitions.append({**{k: t.get(k) for k in (
                'group', 'support_days', 'typical_departure', 'median_soc_drop',
                'time_mad_minutes', 'median_distance_mi', 'energy_samples')},
                'from_site': start, 'to_site': end})
    raw_current = v1.get('current_location') or {}
    current = {
        'site': mapping.get(raw_current.get('zone')),
        'observation_age_minutes': num(raw_current.get('observation_age_minutes')),
    }
    original_pred = v1.get('location_next_trip_prediction') or {}
    prediction = None
    if original_pred:
        origin = mapping.get(original_pred.get('origin_zone'))
        dest = mapping.get(original_pred.get('destination_zone'))
        if origin and dest:
            prediction = {'departure_local': original_pred.get('departure_local'),
                          'departure_ts': num(original_pred.get('departure_ts')),
                          'origin_site': origin, 'destination_site': dest,
                          'support_days': int(original_pred.get('support_days') or 0),
                          'median_soc_drop': num(original_pred.get('median_soc_drop')),
                          'time_mad_minutes': num(original_pred.get('mad_minutes')),
                          'basis': 'DIRECT_OBSERVED_ROUTE', 'status': 'SHADOW_ONLY'}
    possible_nearby = []
    if not prediction and current['site']:
        # Clearly mark these as hypotheses, never convert them to a confirmed route
        # from the actual parked site. They are NOT production predictions.
        near_ids = {p['site_b'] if p['site_a'] == current['site'] else p['site_a']
                    for p in pairs if current['site'] in (p['site_a'], p['site_b'])}
        for t in transitions:
            if t['from_site'] in near_ids and int(t.get('support_days') or 0) >= 3:
                possible_nearby.append({
                    'observed_origin_site': t['from_site'],
                    'observed_destination_site': t['to_site'],
                    'typical_departure': t['typical_departure'],
                    'support_days': t['support_days'],
                    'status': 'POSSIBLE_NEARBY_CONTEXT_NOT_CONFIRMED',
                })
    return {
        'version': VERSION, 'generated_at': now,
        'shadow_mode': True, 'production_predictions_unchanged': True,
        'source_model_version': v1.get('model_version'),
        'source_training_at': num(v1.get('trained_at')),
        'source_zone_mapping': mapping,
        'stable_sites': actual_sites, 'nearby_not_merged': pairs,
        'transitions': transitions, 'trip_chains': [
            {'sequence': ' -> '.join(mapping.get(p.strip(), 'UNKNOWN') for p in c.get('sequence','').split('->')),
             'support_days': c.get('support_days'), 'typical_park_hours': c.get('typical_park_hours')}
            for c in v1.get('trip_chains') or [] if isinstance(c, dict)],
        'current_site': current, 'direct_shadow_prediction': prediction,
        'nearby_hypotheses': possible_nearby,
        'notes': ['Nearby is not equal to same parking location.',
                  'Stable SITE identifiers persist across changes in observation ranking.',
                  'No labels such as home/work are inferred from proximity alone.',
                  'Private site centers are kept only in stable-zones.json on the Pi.',
                  'No calibrated probability/accuracy claim is made.'],
    }, registry


def report(m):
    generated = datetime.fromtimestamp(m['generated_at']).isoformat(timespec='seconds')
    lines = [f'GHOST LOCATION CONTEXT {VERSION}', f'Generated: {generated}',
             'SHADOW ONLY — production departure predictions and neural models unchanged.', '',
             'STABLE PLACE IDs (source labels can change):']
    for transient, stable in sorted(m['source_zone_mapping'].items()):
        lines.append(f'  {transient} -> {stable}')
    lines.extend(['', 'NEARBY LOCATIONS (NOT automatically the same parking place):'])
    if not m['nearby_not_merged']:
        lines.append('  No currently distinct sites within 2.5 km.')
    for item in m['nearby_not_merged'][:15]:
        lines.append(f'  {item["site_a"]} <-> {item["site_b"]}: {item["distance_km"]} km (kept separate)')
    lines.extend(['', 'OBSERVED ROUTE LINKS:'])
    for tr in m['transitions'][:15]:
        lines.append(f'  {tr["from_site"]} -> {tr["to_site"]} | {tr["group"]} {tr["typical_departure"]} | {tr["support_days"]} days | SOC {tr["median_soc_drop"]}%')
    if not m['transitions']:
        lines.append('  No reliable zone-to-zone transitions detected.')
    lines.extend(['', 'OBSERVED CHAINS:'])
    for ch in m['trip_chains'][:12]:
        lines.append(f'  {ch["sequence"]} | {ch["support_days"]} days | parked {ch["typical_park_hours"]} h')
    if not m['trip_chains']:
        lines.append('  No recurring trip chains identified.')
    lines.extend(['', 'CURRENT SITE CONTEXT:'])
    c = m['current_site']
    lines.append(f'  {c["site"] or "UNKNOWN"} | last verified GPS {c["observation_age_minutes"]} min ago')
    lines.append('NEXT DIRECT SHADOW PREDICTION:')
    p = m['direct_shadow_prediction']
    if p:
        lines.append(f'  {p["departure_local"]} | {p["origin_site"]} -> {p["destination_site"]} | {p["support_days"]} independent days')
    else:
        lines.append('  NONE. Not inventing an unobserved route.')
    if m['nearby_hypotheses']:
        lines.append('POSSIBLE NEARBY CONTEXT (not confirmed from current site):')
        for h in m['nearby_hypotheses'][:5]:
            lines.append(f'  {h["observed_origin_site"]} -> {h["observed_destination_site"]} {h["typical_departure"]} | {h["support_days"]} days')
    lines.extend(['', 'DATA PRIVACY: No GPS coordinates or address labels in this text report.',
                  'Do not upload stable-zones.json (contains private coordinates).',
                  'Location matching remains SHADOW ONLY until evaluated.'])
    return '\n'.join(lines) + '\n'


def self_test():
    def zone(z, lat, lon):
        return {'id':z, 'centroid_lat':lat, 'centroid_lon':lon,
                'visits':8, 'observed_days':5}
    sample = {'model_version':'test', 'trained_at':time.time(),
              'anonymous_zones': [zone('ZONE_1', 41.600, -87.300),
                                  zone('ZONE_2', 41.620, -87.310),
                                  zone('ZONE_3', 41.636, -87.310)],
              'zone_transitions':[{'from':'ZONE_1','to':'ZONE_2','group':'weekday',
                                    'support_days':6,'typical_departure':'06:15',
                                    'median_soc_drop':13}],
              'trip_chains':[], 'current_location':{'zone':'ZONE_1','observation_age_minutes':2.3},
              'location_next_trip_prediction':{'origin_zone':'ZONE_1','destination_zone':'ZONE_2',
                                                'departure_local':'2026-10-08T14:41','support_days':6}}
    state, reg = build_context(sample, {}, 12345)
    assert state['direct_shadow_prediction']['origin_site'] == 'SITE_001'
    assert len(state['stable_sites']) == 3
    # Swapping source ranks must not alter stable ids.
    shifted = {**sample, 'anonymous_zones': [zone('ZONE_3',41.6001,-87.3001),
                                            zone('ZONE_1',41.6361,-87.3101),
                                            zone('ZONE_2',41.6201,-87.3101)]}
    newer, _ = build_context(shifted, reg, 12355)
    assert newer['source_zone_mapping']['ZONE_3'] == state['source_zone_mapping']['ZONE_1']
    assert newer['source_zone_mapping']['ZONE_1'] == state['source_zone_mapping']['ZONE_3']
    # Nearby but separate sites remain separate; no coordinate leaked into TXT.
    assert len(newer['stable_sites']) == 3
    assert 'centroid_lat' not in report(newer)
    assert '41.6' not in report(newer)
    print('SELF-TEST PASS: stable IDs, changed ranks, nearby-not-merged, no GPS in text')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--self-test', action='store_true')
    ap.add_argument('--root', default='/home/ghost/ghost-trip-sequence')
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    v1file = root / 'latest.json'
    if not v1file.is_file():
        raise SystemExit(f'Missing v1 private report: {v1file}')
    v1 = json.loads(v1file.read_text())
    registry_file = root / REGISTRY_NAME
    reg = json.loads(registry_file.read_text()) if registry_file.is_file() else {}
    output, updated = build_context(v1, reg, time.time())
    # Write the private persistent registry last, so a failed report run doesn't
    # partially change site identities. All writes are atomic.
    safe_write_json(root / 'latest-location-context.json', output)
    safe_write_text(root / 'latest-location-context.txt', report(output))
    safe_write_json(registry_file, updated)
    print(report(output))


if __name__ == '__main__':
    main()
