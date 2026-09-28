from __future__ import annotations
import argparse,json,time
from pathlib import Path
from . import db,config

def _version():
    try:return Path('/opt/ghost-tesla-ai/VERSION').read_text().strip() or '0.4.1'
    except Exception:return '0.4.1'

def status():
    db.init_db()
    with db.connect() as con:
        n=con.execute('SELECT COUNT(*) n FROM telemetry').fetchone()['n']
        last=con.execute('''SELECT ts,source,state,battery_level,outside_temp_c,inside_temp_c,battery_temp_c,module_temp_min_c,module_temp_max_c,
                            pack_voltage_v,pack_current_a,pack_power_kw,charge_input_kw,battery_heater_on FROM telemetry ORDER BY ts DESC LIMIT 1''').fetchone()
        audits=con.execute("SELECT status,COUNT(*) n FROM prediction_audit GROUP BY status").fetchall()
        ev=con.execute("SELECT event_type,COUNT(*) n FROM vehicle_events GROUP BY event_type").fetchall()
        prod=con.execute("SELECT model_name,generation,mae,backend FROM model_runs WHERE promoted=1 ORDER BY model_name").fetchall()
        trip=con.execute("SELECT model_name,generation,mae FROM event_model_runs WHERE promoted=1 ORDER BY model_name").fetchall()
    from .readiness import current_readiness
    try:
        from .neural_v4 import status as neural_status
        neural=neural_status()
    except Exception as e:
        neural={'status':'unavailable','error':f'{type(e).__name__}: {e}'}
    try:
        from .neural_governor import status as governor_status
        governor=governor_status()
    except Exception as e:
        governor={'enabled':False,'error':f'{type(e).__name__}: {e}'}
    print(json.dumps({'version':_version(),'rows':n,'last':dict(last) if last else None,
        'source':db.get_state('source',{}),'collector':db.get_state('collector',{}),'training':db.get_state('training',{}),'backfill':db.get_state('backfill',{}),
        'truth_engine':db.get_state('truth_engine',{}),'prediction_audit':{r['status']:r['n'] for r in audits},
        'events':{r['event_type']:r['n'] for r in ev},'production_models':[dict(r) for r in prod],'trip_models':[dict(r) for r in trip],
        'neural_v4':neural,'neural_governor':governor,'morning_readiness':current_readiness()},indent=2,default=str))

def tessie_test():
    from .tessie_source import TessieClient,parse_state
    c=TessieClient();c.discover_vehicle();state=c.state();sample=parse_state(state,None,c.vin or 'tessie');safe={k:v for k,v in sample.items() if k not in {'raw_json','car_id'}};safe['vin_tail']=(c.vin or '')[-6:]
    print(json.dumps({'ok':True,'sample':safe},indent=2))

def intelligence():
    from .event_engine import rebuild_events
    from .readiness import snapshot_readiness
    from .departure_learning import learn_schedule
    from .prediction_audit import resolve_due_predictions
    derived=db.backfill_derived();events=rebuild_events(config.EVENT_LOOKBACK_DAYS);departure=learn_schedule();truth=resolve_due_predictions();readiness=snapshot_readiness()
    neural_truth={}
    try:
        from .neural_audit import cycle as neural_cycle
        neural_truth=neural_cycle()
    except Exception as e:
        neural_truth={'status':'error','error':f'{type(e).__name__}: {e}'}
    governor={}
    try:
        from .neural_governor import cycle as governor_cycle
        governor=governor_cycle()
    except Exception as e:
        governor={'status':'error','error':f'{type(e).__name__}: {e}'}
    out={'status':'complete','at':time.time(),'derived':derived,'events':events,'departure_learning':departure,'truth':truth,'neural_truth':neural_truth,'neural_governor':governor,'readiness':readiness};db.set_state('intelligence_cycle',out);print(json.dumps(out,indent=2,default=str))

def main():
    p=argparse.ArgumentParser(prog='ghost-ai');sp=p.add_subparsers(dest='cmd',required=True)
    for c in ('status','init-db','train','tessie-test','audit','events','readiness','departure','intelligence','neural','neural-v4','neural-status','neural-governor'):sp.add_parser(c)
    bp=sp.add_parser('backfill');bp.add_argument('--days',type=int,default=30);bp.add_argument('--interval',type=int,default=300);bp.add_argument('--train-after',action='store_true')
    a=p.parse_args()
    if a.cmd=='status':status()
    elif a.cmd=='init-db':db.init_db();print(config.DB_PATH)
    elif a.cmd=='tessie-test':tessie_test()
    elif a.cmd=='train':
        from .trainer import train_all;print(json.dumps(train_all(),indent=2))
    elif a.cmd=='backfill':
        from .backfill import import_history;print(json.dumps(import_history(a.days,a.interval,a.train_after),indent=2))
    elif a.cmd=='audit':
        from .prediction_audit import resolve_due_predictions;print(json.dumps(resolve_due_predictions(),indent=2))
    elif a.cmd=='events':
        from .event_engine import rebuild_events,recent_events;print(json.dumps({'build':rebuild_events(config.EVENT_LOOKBACK_DAYS),'recent':recent_events(20)},indent=2,default=str))
    elif a.cmd=='readiness':
        from .readiness import current_readiness;print(json.dumps(current_readiness(),indent=2,default=str))
    elif a.cmd=='departure':
        from .departure_learning import learn_schedule,schedule_status
        learn_schedule(force=True);print(json.dumps(schedule_status(refresh=False),indent=2,default=str))
    elif a.cmd=='intelligence':intelligence()
    elif a.cmd=='neural':
        from .neural_challenger import train_challengers;print(json.dumps(train_challengers(),indent=2))
    elif a.cmd=='neural-v4':
        from .neural_v4 import train;print(json.dumps(train(),indent=2,default=str))
    elif a.cmd=='neural-status':
        from .neural_v4 import status as neural_status
        from .neural_audit import metrics
        from .neural_governor import status as governor_status
        print(json.dumps({'engine':neural_status(),'truth':metrics(),'governor':governor_status()},indent=2,default=str))
    elif a.cmd=='neural-governor':
        from .neural_governor import cycle as governor_cycle
        print(json.dumps(governor_cycle(),indent=2,default=str))
if __name__=='__main__':main()
