from __future__ import annotations

import base64
import json
import math
import random
import struct
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import config

try:
    import paho.mqtt.client as mqtt
except Exception:  # surfaced through status instead of breaking GHOST startup
    mqtt = None

PRIVATE_LOGIN_URL = "https://api.ecoflow.com/auth/login"
PRIVATE_CERT_URL = "https://api.ecoflow.com/iot-auth/app/certification"


# ---- River 3 / R651 Gen-3 protobuf helpers -------------------------------
# River 3 private APP MQTT frames are protobuf.  Only the small subset of
# fields needed by the GHOST header is decoded here.

def _pb_varint(n: int) -> bytes:
    n=int(n)
    if n < 0: n &= (1 << 64) - 1
    out=bytearray()
    while True:
        b=n & 0x7f; n >>= 7
        if n: out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _pb_key(field: int, wire: int) -> bytes:
    return _pb_varint((int(field)<<3)|int(wire))


def _pb_u32(field: int, value: int) -> bytes:
    return _pb_key(field,0)+_pb_varint(value)


def _pb_bytes(field: int, value: bytes) -> bytes:
    value=bytes(value)
    return _pb_key(field,2)+_pb_varint(len(value))+value


def _pb_string(field: int, value: str) -> bytes:
    return _pb_bytes(field,value.encode('utf-8'))


def _river3_latest_quotas_packet() -> bytes:
    # Captured River 3/3 Plus latestQuotas action:
    # setMessage.header { src:32, dest:32, seq:<ms>, from:"ios" }
    seq=int(time.time()*1000) & 0x7fffffff
    header=b''.join((_pb_u32(2,32),_pb_u32(3,32),_pb_u32(14,seq),_pb_string(23,'ios')))
    return _pb_bytes(1,header)


def _pb_read_varint(buf: bytes, pos: int):
    value=0; shift=0
    while pos < len(buf) and shift < 70:
        b=buf[pos]; pos+=1
        value |= (b & 0x7f) << shift
        if not (b & 0x80): return value,pos
        shift += 7
    raise ValueError('invalid protobuf varint')


def _pb_fields(buf: bytes):
    pos=0
    while pos < len(buf):
        tag,pos=_pb_read_varint(buf,pos)
        field=tag>>3; wire=tag&7
        if field <= 0: raise ValueError('invalid protobuf field')
        if wire==0:
            value,pos=_pb_read_varint(buf,pos)
        elif wire==1:
            if pos+8>len(buf): raise ValueError('truncated fixed64')
            value=buf[pos:pos+8]; pos+=8
        elif wire==2:
            ln,pos=_pb_read_varint(buf,pos)
            if pos+ln>len(buf): raise ValueError('truncated bytes')
            value=buf[pos:pos+ln]; pos+=ln
        elif wire==5:
            if pos+4>len(buf): raise ValueError('truncated fixed32')
            value=buf[pos:pos+4]; pos+=4
        else:
            raise ValueError(f'unsupported protobuf wire type {wire}')
        yield field,wire,value


def _pb_first(buf: bytes, field_no: int, wire=None):
    for f,w,v in _pb_fields(buf):
        if f==field_no and (wire is None or w==wire): return v
    return None


def _pb_uint(buf: bytes, field_no: int):
    v=_pb_first(buf,field_no,0)
    return None if v is None else int(v)


def _pb_int32(buf: bytes, field_no: int):
    v=_pb_uint(buf,field_no)
    if v is None: return None
    v &= 0xffffffff
    return v-0x100000000 if v & 0x80000000 else v


def _pb_float(buf: bytes, field_no: int):
    raw=_pb_first(buf,field_no,5)
    if raw is None: return None
    x=struct.unpack('<f',raw)[0]
    return x if math.isfinite(x) else None


def _river3_proto_decode(raw: bytes):
    # sentDisplayPropertyUpload / sentRuntimePropertyUpload / sentBMS... all
    # have header in field 1.  Be tolerant of a bare header for diagnostics.
    top=list(_pb_fields(raw))
    header=next((v for f,w,v in top if f==1 and w==2),None) or raw
    cmd_func=_pb_uint(header,8)
    cmd_id=_pb_uint(header,9)
    pdata=_pb_first(header,1,2)
    meta={'cmd_func':cmd_func,'cmd_id':cmd_id,'kind':f'{cmd_func}/{cmd_id}'}
    if pdata is None:
        meta['kind']='no_pdata'
        return {},meta

    vals={}
    if cmd_func==254 and cmd_id==21:              # DisplayPropertyUpload
        meta['kind']='DisplayPropertyUpload'
        vals={
            'input_w':_pb_float(pdata,3),
            'output_w':_pb_float(pdata,4),
            'soc':_pb_float(pdata,262),
            'soh':_pb_float(pdata,263),
            'dsg_min':_pb_uint(pdata,268),
            'chg_min':_pb_uint(pdata,269),
            'state':_pb_uint(pdata,282),
            'temp_min_c':_pb_int32(pdata,258),
            'temp_c':_pb_int32(pdata,259),
            'ac_input_w':_pb_float(pdata,54),
            'ac_output_w':_pb_float(pdata,368),
        }
        if vals['soc'] is None: vals['soc']=_pb_float(pdata,242)
        if vals['soh'] is None: vals['soh']=_pb_float(pdata,243)
        if vals['dsg_min'] is None: vals['dsg_min']=_pb_uint(pdata,254)
        if vals['chg_min'] is None: vals['chg_min']=_pb_uint(pdata,255)
        if vals['state'] is None: vals['state']=_pb_uint(pdata,281)
    elif cmd_func==32 and cmd_id==50:             # BMSHeartBeatReport
        meta['kind']='BMSHeartBeatReport'
        vals={
            'soc':_pb_float(pdata,25),
            'soh':_pb_float(pdata,52),
            'temp_c':_pb_int32(pdata,18),
            'temp_min_c':_pb_int32(pdata,19),
            'input_w':_pb_uint(pdata,26),
            'output_w':_pb_uint(pdata,27),
            'dsg_min':_pb_uint(pdata,28),
            'cycles':_pb_uint(pdata,14),
            'state':_pb_uint(pdata,47),
        }
        if vals['soc'] is None: vals['soc']=_pb_uint(pdata,6)
        if vals['soh'] is None: vals['soh']=_pb_uint(pdata,15)
        if vals['temp_c'] is None: vals['temp_c']=_pb_int32(pdata,9)
    elif cmd_func==254 and cmd_id==22:
        meta['kind']='RuntimePropertyUpload'
    else:
        return {},meta
    return {k:v for k,v in vals.items() if v is not None},meta


def _finite(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _flatten(obj: Any, prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    out = out if out is not None else {}
    if isinstance(obj, dict):
        for k,v in obj.items():
            key=f"{prefix}.{k}" if prefix else str(k)
            _flatten(v,key,out)
    elif isinstance(obj, list):
        for i,v in enumerate(obj):
            _flatten(v,f"{prefix}[{i}]",out)
    else:
        out[prefix]=obj
    return out


def _pick(flat: dict[str, Any], candidates: list[str]):
    items=list(flat.items())
    for cand in candidates:
        cl=cand.lower()
        for k,v in items:
            leaf=k.rsplit('.',1)[-1].lower()
            if leaf==cl:
                x=_finite(v)
                if x is not None: return x
    for cand in candidates:
        cl=cand.lower()
        for k,v in items:
            if k.lower().endswith(cl):
                x=_finite(v)
                if x is not None: return x
    return None


def _read_app_credentials() -> tuple[str,str]:
    p=Path(config.ECOFLOW_APP_CREDENTIALS_FILE)
    try:
        data=json.loads(p.read_text())
        return str(data.get('email') or '').strip(), str(data.get('password') or '')
    except Exception:
        return '', ''


def _private_cert(email: str, password: str) -> dict[str, Any]:
    b64=base64.b64encode(password.encode('utf-8')).decode('ascii')
    body=json.dumps({
        'email':email,
        'password':b64,
        'scene':'IOT_APP',
        'userType':'ECOFLOW',
        'appVersion':'4.1.2.02',
        'os':'android',
        'osVersion':'30',
    }).encode()
    req=urllib.request.Request(PRIVATE_LOGIN_URL,data=body,method='POST',headers={
        'Content-Type':'application/json','lang':'en-us','platform':'android',
        'sysversion':'11','version':'4.1.2.02','phonemodel':'SM-G998B',
        'User-Agent':'okhttp/3.14.9',
    })
    with urllib.request.urlopen(req,timeout=config.ECOFLOW_TIMEOUT_SECONDS) as r:
        login=json.loads(r.read().decode('utf-8','replace'))
    if str(login.get('code'))!='0':
        raise RuntimeError(f"EcoFlow login {login.get('code')}: {login.get('message') or 'failed'}")
    data=login.get('data') or {}
    token=str(data.get('token') or '')
    user=data.get('user') or data
    uid=str(user.get('userId') or user.get('id') or '')
    if not token or not uid:
        raise RuntimeError('EcoFlow login did not return token/userId')
    url=PRIVATE_CERT_URL+'?'+urllib.parse.urlencode({'userId':uid})
    req=urllib.request.Request(url,method='GET',headers={
        'Authorization':'Bearer '+token,'Accept':'application/json','lang':'en-us',
        'User-Agent':'okhttp/3.14.9',
    })
    with urllib.request.urlopen(req,timeout=config.ECOFLOW_TIMEOUT_SECONDS) as r:
        cert=json.loads(r.read().decode('utf-8','replace'))
    if str(cert.get('code'))!='0':
        raise RuntimeError(f"EcoFlow cert {cert.get('code')}: {cert.get('message') or 'failed'}")
    c=cert.get('data') or {}
    if not c.get('certificateAccount') or not c.get('certificatePassword'):
        raise RuntimeError('EcoFlow certificate response missing MQTT credentials')
    return {
        'user_id':uid,
        'host':str(c.get('url') or 'mqtt.ecoflow.com'),
        'port':int(c.get('port') or 8883),
        'username':str(c.get('certificateAccount')),
        'password':str(c.get('certificatePassword')),
        'protocol':str(c.get('protocol') or 'mqtts'),
    }


class EcoFlowPrivateMqtt:
    def __init__(self):
        self.lock=threading.RLock()
        self.started=False
        self.stop_evt=threading.Event()
        self.thread=None
        self.client=None
        self.user_id=''
        self.connected=False
        self.last_message_at=0.0
        self.last_cert_at=0.0
        self.last_keepalive_at=0.0
        self.last_error=''
        self.values={}
        self.message_count=0
        self.protobuf_message_count=0
        self.json_message_count=0
        self.last_packet_kind=''
        self.last_cmd_func=None
        self.last_cmd_id=None

    def configured(self) -> bool:
        email,password=_read_app_credentials()
        return bool(config.ECOFLOW_RIVER3_SN and email and password)

    def start(self):
        with self.lock:
            if self.started: return
            self.started=True
            self.thread=threading.Thread(target=self._supervisor,name='ghost-ecoflow-private-mqtt',daemon=True)
            self.thread.start()

    def _client_id(self,uid: str) -> str:
        return f"ANDROID_{str(int(time.time()))[-8:]}_{uid}"

    def _disconnect(self):
        c=None
        with self.lock:
            c=self.client
            self.client=None
            self.connected=False
        if c is not None:
            try: c.loop_stop()
            except Exception: pass
            try: c.disconnect()
            except Exception: pass

    def _make_client(self,cert: dict[str,Any]):
        if mqtt is None:
            raise RuntimeError('paho-mqtt is not installed')
        cid=self._client_id(cert['user_id'])
        c=mqtt.Client(client_id=cid,clean_session=True,protocol=mqtt.MQTTv311)
        c.username_pw_set(cert['username'],cert['password'])
        c.tls_set()
        c.reconnect_delay_set(min_delay=5,max_delay=60)
        c.on_connect=self._on_connect
        c.on_disconnect=self._on_disconnect
        c.on_message=self._on_message
        return c

    def _on_connect(self,c,userdata,flags,rc,*extra):
        ok=int(rc)==0
        with self.lock:
            self.connected=ok
            if ok: self.last_error=''
            else: self.last_error=f'MQTT connect rc={rc}'
        if not ok: return
        sn=config.ECOFLOW_RIVER3_SN
        c.subscribe(f'/app/device/property/{sn}',qos=1)
        if self.user_id:
            c.subscribe(f'/app/{self.user_id}/{sn}/thing/property/get_reply',qos=1)
        threading.Timer(1.5,self._send_get,args=(c,'connect')).start()

    def _on_disconnect(self,c,userdata,rc,*extra):
        with self.lock:
            self.connected=False
            if int(rc)!=0: self.last_error=f'MQTT disconnected rc={rc}'

    def _send_get(self,c=None,label='keepalive'):
        with self.lock:
            c=c or self.client
            uid=self.user_id
        if c is None or not uid: return
        sn=config.ECOFLOW_RIVER3_SN
        topic=f'/app/{uid}/{sn}/thing/property/get'
        payload=_river3_latest_quotas_packet()
        try:
            info=c.publish(topic,payload,qos=1)
            if getattr(info,'rc',0) not in (0,None):
                raise RuntimeError(f'publish rc={info.rc}')
            with self.lock: self.last_keepalive_at=time.time()
        except Exception as e:
            with self.lock: self.last_error=f'protobuf latestQuotas: {type(e).__name__}: {e}'

    def _on_message(self,c,userdata,msg):
        raw=bytes(msg.payload or b'')
        if not raw: return
        vals={}; packet_kind=''
        if raw[:1] in (b'{',b'['):
            try:
                payload=json.loads(raw.decode('utf-8'))
                flat=_flatten(payload)
                vals={
                    'soc':_pick(flat,['cmsBattSoc','bmsBattSoc','f32ShowSoc','soc']),
                    'soh':_pick(flat,['cmsBattSoh','bmsBattSoh','realSoh','soh']),
                    'temp_c':_pick(flat,['bmsMaxCellTemp','maxCellTemp','temp','bmsMinCellTemp','minCellTemp']),
                    'input_w':_pick(flat,['powInSumW','inputWatts','powGetAcIn']),
                    'output_w':_pick(flat,['powOutSumW','outputWatts','powGetAcOut','powGetAc']),
                    'dsg_min':_pick(flat,['cmsDsgRemTime','bmsDsgRemTime','remainTime']),
                    'chg_min':_pick(flat,['cmsChgRemTime','bmsChgRemTime']),
                    'cycles':_pick(flat,['cycles']),
                    'state':_pick(flat,['cmsChgDsgState','bmsChgDsgState','chgDsgState']),
                }
                vals={k:v for k,v in vals.items() if v is not None}
                packet_kind='json'
                with self.lock: self.json_message_count+=1
            except Exception as e:
                with self.lock: self.last_error=f'JSON decode: {type(e).__name__}: {e}'
                return
        else:
            try:
                vals,meta=_river3_proto_decode(raw)
                packet_kind=str(meta.get('kind') or 'protobuf')
                with self.lock:
                    self.protobuf_message_count+=1
                    self.last_cmd_func=meta.get('cmd_func')
                    self.last_cmd_id=meta.get('cmd_id')
            except Exception as e:
                with self.lock: self.last_error=f'protobuf decode: {type(e).__name__}: {e}'
                return
        # A valid envelope counts as live MQTT traffic; incremental packets only
        # replace measurements actually present in the frame.
        with self.lock:
            for k,v in vals.items():
                if v is not None: self.values[k]=v
            self.last_message_at=time.time()
            self.message_count+=1
            self.last_packet_kind=packet_kind
            self.last_error=''

    def _supervisor(self):
        retry=5
        while not self.stop_evt.is_set():
            if not self.configured():
                with self.lock: self.last_error='EcoFlow app credentials not configured'
                self.stop_evt.wait(5)
                continue
            try:
                email,password=_read_app_credentials()
                cert=_private_cert(email,password)
                c=self._make_client(cert)
                self._disconnect()
                with self.lock:
                    self.user_id=cert['user_id']
                    self.client=c
                    self.last_cert_at=time.time()
                    self.last_error=''
                c.connect_async(cert['host'],cert['port'],keepalive=45)
                c.loop_start()
                retry=5
                recert_at=time.time()+config.ECOFLOW_MQTT_RECERT_SECONDS
                while not self.stop_evt.is_set() and time.time()<recert_at:
                    now=time.time()
                    with self.lock:
                        connected=self.connected
                        last_msg=self.last_message_at
                        last_keep=self.last_keepalive_at
                    if connected and now-last_keep>=config.ECOFLOW_MQTT_KEEPALIVE_SECONDS:
                        self._send_get(label='periodic')
                    # Refresh a connected-but-silent River session quickly; after
                    # telemetry starts, use the normal five-minute stale guard.
                    if connected and not last_msg and now-self.last_cert_at>90:
                        with self.lock: self.last_error='MQTT connected but no River 3 telemetry; refreshing certificate'
                        break
                    if connected and last_msg and now-last_msg>300:
                        with self.lock: self.last_error='MQTT telemetry stale; refreshing certificate'
                        break
                    self.stop_evt.wait(2)
            except Exception as e:
                with self.lock:
                    self.connected=False
                    self.last_error=f'{type(e).__name__}: {e}'
                self.stop_evt.wait(retry)
                retry=min(60,retry*2)
            finally:
                self._disconnect()

    def status(self) -> dict[str,Any]:
        self.start()
        now=time.time()
        configured=self.configured()
        with self.lock:
            v=dict(self.values)
            connected=self.connected
            last=self.last_message_at
            err=self.last_error
            cert_at=self.last_cert_at
            count=self.message_count
            proto_count=self.protobuf_message_count
            json_count=self.json_message_count
            packet_kind=self.last_packet_kind
            cmd_func=self.last_cmd_func
            cmd_id=self.last_cmd_id
        age=None if not last else max(0.0,now-last)
        online=bool(last and age<120)
        soc=v.get('soc'); temp_c=v.get('temp_c')
        state=v.get('state')
        dsg=v.get('dsg_min'); chg=v.get('chg_min')
        rem=chg if state==2 and chg is not None else dsg
        if rem is not None and rem>10080: rem=None
        return {
            'configured':configured,
            'source':'private_mqtt',
            'status':'online' if online else ('connected' if connected else ('connecting' if configured else 'unconfigured')),
            'online':online,
            'mqtt_connected':connected,
            'device':'RIVER 3',
            'serial_tail':config.ECOFLOW_RIVER3_SN[-6:] if config.ECOFLOW_RIVER3_SN else '',
            'soc':None if soc is None else round(float(soc),1),
            'battery_temp_c':None if temp_c is None else round(float(temp_c),1),
            'battery_temp_f':None if temp_c is None else round(float(temp_c)*9/5+32,1),
            'input_w':None if v.get('input_w') is None else round(float(v['input_w']),1),
            'output_w':None if v.get('output_w') is None else round(float(v['output_w']),1),
            'remaining_min':None if rem is None else int(round(rem)),
            'charge_remaining_min':None if chg is None else int(round(chg)),
            'soh':None if v.get('soh') is None else round(float(v['soh']),1),
            'cycles':None if v.get('cycles') is None else int(round(v['cycles'])),
            'charge_state':None if state is None else int(round(state)),
            'updated_at':last or None,
            'telemetry_age_s':None if age is None else round(age,1),
            'mqtt_messages':count,
            'protobuf_messages':proto_count,
            'json_messages':json_count,
            'last_packet_kind':packet_kind or None,
            'last_cmd_func':cmd_func,
            'last_cmd_id':cmd_id,
            'certificate_age_s':None if not cert_at else round(now-cert_at,1),
            'error':err or None,
        }


_MANAGER=EcoFlowPrivateMqtt()

def status() -> dict[str,Any]:
    return _MANAGER.status()
