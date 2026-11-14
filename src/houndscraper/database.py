"""PostgreSQL leases, atomic budgets, tenant isolation and transactional events."""
import hashlib
import json
import time
import uuid
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from .errors import ScrapeError

SCHEMA='''
CREATE TABLE IF NOT EXISTS hs_jobs (
 id text PRIMARY KEY, tenant text NOT NULL, kind text NOT NULL, request jsonb NOT NULL,
 status text NOT NULL DEFAULT 'queued', reason text, created double precision NOT NULL,
 updated double precision NOT NULL, processed integer NOT NULL DEFAULT 0,
 inflight integer NOT NULL DEFAULT 0, errors integer NOT NULL DEFAULT 0,
 bytes bigint NOT NULL DEFAULT 0, spent_ms bigint NOT NULL DEFAULT 0,
 idempotency text, request_hash text NOT NULL, UNIQUE(tenant,idempotency));
CREATE TABLE IF NOT EXISTS hs_frontier (
 job text REFERENCES hs_jobs(id) ON DELETE CASCADE, url text NOT NULL, depth integer NOT NULL,
 state text NOT NULL DEFAULT 'queued', attempts integer NOT NULL DEFAULT 0,
 lease text, lease_until double precision, retry_at double precision NOT NULL DEFAULT 0,
 PRIMARY KEY(job,url));
ALTER TABLE hs_jobs ADD COLUMN IF NOT EXISTS reserved_bytes bigint NOT NULL DEFAULT 0;
ALTER TABLE hs_frontier ADD COLUMN IF NOT EXISTS allowed_bytes bigint NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS hs_frontier_claim ON hs_frontier(state,retry_at);
CREATE TABLE IF NOT EXISTS hs_results (
 id bigserial PRIMARY KEY, job text REFERENCES hs_jobs(id) ON DELETE CASCADE,
 url text NOT NULL, result jsonb NOT NULL, hash text, UNIQUE(job,url));
CREATE TABLE IF NOT EXISTS hs_events (
 id bigserial PRIMARY KEY, job text REFERENCES hs_jobs(id) ON DELETE CASCADE,
 kind text NOT NULL, value jsonb NOT NULL, created double precision NOT NULL);
CREATE TABLE IF NOT EXISTS hs_network_slots (slot integer PRIMARY KEY, owner text, lease_until double precision NOT NULL DEFAULT 0);
INSERT INTO hs_network_slots(slot) SELECT generate_series(1,64) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS hs_origin_slots (origin text PRIMARY KEY, owner text, lease_until double precision NOT NULL DEFAULT 0, retry_at double precision NOT NULL DEFAULT 0, last_start double precision NOT NULL DEFAULT 0, delay double precision NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS hs_notification_profiles (tenant text NOT NULL,name text NOT NULL,ciphertext text NOT NULL,PRIMARY KEY(tenant,name));
CREATE TABLE IF NOT EXISTS hs_model_calls (
 id text PRIMARY KEY, job text NOT NULL REFERENCES hs_jobs(id) ON DELETE CASCADE,
 tokens bigint NOT NULL, cost_nano bigint NOT NULL, settled boolean NOT NULL DEFAULT false,
 usage jsonb, created double precision NOT NULL);
CREATE INDEX IF NOT EXISTS hs_model_calls_job ON hs_model_calls(job);
CREATE TABLE IF NOT EXISTS hs_agent_state (job text PRIMARY KEY REFERENCES hs_jobs(id) ON DELETE CASCADE, state jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS hs_cache (
 tenant text NOT NULL, key text NOT NULL, value jsonb NOT NULL,
 created double precision NOT NULL, PRIMARY KEY(tenant,key));
CREATE TABLE IF NOT EXISTS hs_artifacts (
 id text PRIMARY KEY, tenant text NOT NULL, key text NOT NULL, mime text NOT NULL,
 sha256 text NOT NULL, bytes bigint NOT NULL, created double precision NOT NULL);
CREATE TABLE IF NOT EXISTS hs_credentials (
 tenant text NOT NULL, name text NOT NULL, origin text NOT NULL, ciphertext text NOT NULL,
 PRIMARY KEY(tenant,name));
CREATE TABLE IF NOT EXISTS hs_monitors (
 id text PRIMARY KEY, tenant text NOT NULL, request jsonb NOT NULL,
 cron text NOT NULL, next_run double precision NOT NULL, active boolean NOT NULL DEFAULT true,
 previous jsonb NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS hs_outbox (
 id bigserial PRIMARY KEY, tenant text NOT NULL, url text NOT NULL, payload jsonb NOT NULL,
 state text NOT NULL DEFAULT 'queued', attempts integer NOT NULL DEFAULT 0,
 retry_at double precision NOT NULL DEFAULT 0, lease_until double precision);
'''

def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class Store:
    def __init__(self,url):
        self.pool=ConnectionPool(url,min_size=1,max_size=16,open=True,kwargs={'row_factory':dict_row})
        self.pool.wait(timeout=15)
        with self.pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(6741453456134)')
            c.execute(SCHEMA)
    def close(self):self.pool.close()
    def event(self,c,job,kind,value):
        c.execute('INSERT INTO hs_events(job,kind,value,created) VALUES(%s,%s,%s,%s)',(job,kind,Jsonb(value),time.time()))
    def create(self,tenant,request,idempotency=None):
        body=request.model_dump() if hasattr(request,'model_dump') else request
        rh=fingerprint(body);jid=uuid.uuid4().hex;now=time.time()
        with self.pool.connection() as c:
            row=c.execute('INSERT INTO hs_jobs(id,tenant,kind,request,created,updated,idempotency,request_hash) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant,idempotency) DO NOTHING RETURNING *',(jid,tenant,body['kind'],Jsonb(body),now,now,idempotency,rh)).fetchone()
            if not row:
                row=c.execute('SELECT * FROM hs_jobs WHERE tenant=%s AND idempotency=%s',(tenant,idempotency)).fetchone()
                if row['request_hash']!=rh:raise ScrapeError('IDEMPOTENCY_CONFLICT','The key was already used with another request',409)
                return row
            seeds=['urn:houndscraper:agent:'+jid] if body['kind']=='agent' else body.get('urls',[])
            for url in seeds:c.execute('INSERT INTO hs_frontier(job,url,depth) VALUES(%s,%s,0) ON CONFLICT DO NOTHING',(jid,url))
            self.event(c,jid,'created',{'kind':body['kind']})
            return row
    def get(self,tenant,jid):
        with self.pool.connection() as c:row=c.execute('SELECT * FROM hs_jobs WHERE tenant=%s AND id=%s',(tenant,jid)).fetchone()
        if not row:raise ScrapeError('NOT_FOUND','Job not found',404)
        return row
    def list(self,tenant,cursor='',limit=30):
        with self.pool.connection() as c:return c.execute('SELECT * FROM hs_jobs WHERE tenant=%s AND id>%s ORDER BY id LIMIT %s',(tenant,cursor,limit)).fetchall()
    def claim(self,lease_seconds=120):
        now=time.time();lease=uuid.uuid4().hex
        with self.pool.connection() as c:
            row=c.execute("SELECT f.*,j.tenant,j.request,j.kind,j.bytes,j.spent_ms,j.reserved_bytes FROM hs_frontier f JOIN hs_jobs j ON j.id=f.job WHERE f.state='queued' AND f.retry_at<=%s AND j.status IN ('queued','running') AND j.processed+j.inflight<(j.request->>'max_pages')::int ORDER BY j.created,f.depth,f.url FOR UPDATE OF j,f SKIP LOCKED LIMIT 1",(now,)).fetchone()
            if not row:return None
            if row['bytes']>=row['request']['max_download_bytes'] or row['spent_ms']>=row['request']['max_seconds']*1000:
                c.execute("UPDATE hs_jobs SET status='partial',reason='BUDGET_EXHAUSTED',updated=%s WHERE id=%s",(now,row['job']));return None
            allowance=min(row['request']['max_download_bytes'] if row['kind']=='agent' else row['request']['options']['max_bytes'],row['request']['max_download_bytes']-row['bytes']-row['reserved_bytes'])
            if allowance<=0:return None
            c.execute("UPDATE hs_frontier SET state='leased',lease=%s,lease_until=%s,attempts=attempts+1,allowed_bytes=%s WHERE job=%s AND url=%s",(lease,now+lease_seconds,allowance,row['job'],row['url']))
            c.execute("UPDATE hs_jobs SET status='running',inflight=inflight+1,reserved_bytes=reserved_bytes+%s,updated=%s WHERE id=%s",(allowance,now,row['job']))
            row.update(lease=lease,allowed_bytes=allowance,attempts=row['attempts']+1)
            self.event(c,row['job'],'page_started',{'url':row['url'],'attempt':row['attempts']})
            return row
    def heartbeat(self,item,lease_seconds):
        with self.pool.connection() as c:
            row=c.execute('UPDATE hs_frontier SET lease_until=%s WHERE job=%s AND url=%s AND lease=%s AND state=\'leased\' RETURNING job',(time.time()+lease_seconds,item['job'],item['url'],item['lease'])).fetchone()
            job=c.execute('SELECT status FROM hs_jobs WHERE id=%s',(item['job'],)).fetchone()
            return bool(row and job and job['status']=='running')
    def finish(self,item,result,links=(),error=False,elapsed_ms=0):
        with self.pool.connection() as c:
            row=c.execute("SELECT f.state,j.status FROM hs_frontier f JOIN hs_jobs j ON j.id=f.job WHERE f.job=%s AND f.url=%s AND f.lease=%s FOR UPDATE OF j,f",(item['job'],item['url'],item['lease'])).fetchone()
            if not row or row['state']!='leased':return False
            if row['status'] in ('paused','cancelled'):
                c.execute("UPDATE hs_frontier SET state='queued',lease=NULL,lease_until=NULL WHERE job=%s AND url=%s",(item['job'],item['url']))
                c.execute('UPDATE hs_jobs SET inflight=GREATEST(0,inflight-1),reserved_bytes=GREATEST(0,reserved_bytes-%s) WHERE id=%s',(item['allowed_bytes'],item['job']));return False
            c.execute("UPDATE hs_frontier SET state='done',lease=NULL,lease_until=NULL WHERE job=%s AND url=%s",(item['job'],item['url']))
            c.execute('INSERT INTO hs_results(job,url,result,hash) VALUES(%s,%s,%s,%s) ON CONFLICT(job,url) DO NOTHING',(item['job'],item['url'],Jsonb(result),result.get('sha256')))
            for url,depth in links:c.execute('INSERT INTO hs_frontier(job,url,depth) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(item['job'],url,depth))
            c.execute('UPDATE hs_jobs SET processed=processed+1,inflight=GREATEST(0,inflight-1),reserved_bytes=GREATEST(0,reserved_bytes-%s),errors=errors+%s,bytes=bytes+%s,spent_ms=spent_ms+%s,updated=%s WHERE id=%s',(item['allowed_bytes'],int(error),result.get('usage',{}).get('budget_download_bytes',result.get('usage',{}).get('download_bytes',0)),elapsed_ms,time.time(),item['job']))
            self.event(c,item['job'],'page_failed' if error else 'page_completed',{'url':item['url'],'error':result.get('error')})
            return True
    def pause_for_budget(self,item,reason):
        with self.pool.connection() as c:
            job=c.execute('SELECT status FROM hs_jobs WHERE id=%s FOR UPDATE',(item['job'],)).fetchone()
            row=c.execute("UPDATE hs_frontier SET state='queued',lease=NULL,lease_until=NULL WHERE job=%s AND url=%s AND lease=%s AND state='leased' RETURNING job",(item['job'],item['url'],item['lease'])).fetchone()
            if not row:return
            c.execute('UPDATE hs_jobs SET inflight=GREATEST(0,inflight-1),reserved_bytes=GREATEST(0,reserved_bytes-%s) WHERE id=%s',(item['allowed_bytes'],item['job']))
            if job['status']!='cancelled':
                c.execute("UPDATE hs_jobs SET status='paused',reason=%s,updated=%s WHERE id=%s",(reason,time.time(),item['job']))
                self.event(c,item['job'],'paused',{'reason':reason})

    def retry(self,item,delay):
        with self.pool.connection() as c:
            row=c.execute("UPDATE hs_frontier SET state='queued',lease=NULL,lease_until=NULL,retry_at=%s WHERE job=%s AND url=%s AND lease=%s AND state='leased' RETURNING job",(time.time()+delay,item['job'],item['url'],item['lease'])).fetchone()
            if row:c.execute('UPDATE hs_jobs SET inflight=GREATEST(0,inflight-1),reserved_bytes=GREATEST(0,reserved_bytes-%s) WHERE id=%s',(item['allowed_bytes'],item['job']))
    def settle(self):
        with self.pool.connection() as c:
            rows=c.execute("SELECT * FROM hs_jobs WHERE status IN ('queued','running') AND inflight=0 FOR UPDATE SKIP LOCKED").fetchall()
            for row in rows:
                pending=c.execute("SELECT count(*) n FROM hs_frontier WHERE job=%s AND state='queued'",(row['id'],)).fetchone()['n']
                # Search-only jobs acquire seed URLs before entering the queue.
                if pending and row['processed']<row['request']['max_pages'] and row['bytes']<row['request']['max_download_bytes'] and row['spent_ms']<row['request']['max_seconds']*1000:continue
                status='partial' if pending or row['errors'] else 'completed'
                reason='BUDGET_EXHAUSTED' if pending else ('PAGE_ERRORS' if row['errors'] else None)
                c.execute('UPDATE hs_jobs SET status=%s,reason=%s,updated=%s WHERE id=%s',(status,reason,time.time(),row['id']))
                self.event(c,row['id'],status,{'reason':reason})
                if row['request'].get('webhook'):
                    c.execute('INSERT INTO hs_outbox(tenant,url,payload) VALUES(%s,%s,%s)',(row['tenant'],row['request']['webhook'],Jsonb({'event':status,'job_id':row['id']})))
    def recover(self):
        with self.pool.connection() as c:
            expired=c.execute("UPDATE hs_frontier SET state='queued',lease=NULL,lease_until=NULL WHERE state='leased' AND lease_until<%s RETURNING job,allowed_bytes",(time.time(),)).fetchall()
            for item in expired:
                c.execute('UPDATE hs_jobs SET inflight=GREATEST(0,inflight-1),reserved_bytes=GREATEST(0,reserved_bytes-%s) WHERE id=%s',(item['allowed_bytes'],item['job']))
                self.event(c,item['job'],'lease_recovered',{})
            return len(expired)
    def transition(self,tenant,jid,action,updates=None):
        with self.pool.connection() as c:
            row=c.execute('SELECT * FROM hs_jobs WHERE id=%s AND tenant=%s FOR UPDATE',(jid,tenant)).fetchone()
            if not row:raise ScrapeError('NOT_FOUND','Job not found',404)
            if action=='resume':
                if row['status'] not in ('paused','partial','cancelled'):raise ScrapeError('INVALID_STATE','This job cannot be resumed',409)
                request=row['request'];request.update(updates or {})
                from .models import JobRequest
                request=JobRequest.model_validate(request).model_dump()
                if row['kind']=='agent':
                    control='urn:houndscraper:agent:'+jid
                    previous=c.execute('DELETE FROM hs_results WHERE job=%s AND url=%s RETURNING result',(jid,control)).fetchone()
                    c.execute("UPDATE hs_frontier SET state='queued',lease=NULL,lease_until=NULL WHERE job=%s AND url=%s",(jid,control))
                    if previous:c.execute('UPDATE hs_jobs SET processed=GREATEST(0,processed-1),errors=GREATEST(0,errors-1) WHERE id=%s',(jid,))
                c.execute("UPDATE hs_jobs SET status='queued',reason=NULL,request=%s,updated=%s WHERE id=%s",(Jsonb(request),time.time(),jid))
            else:
                if row['status'] not in ('queued','running','paused'):raise ScrapeError('INVALID_STATE','This job is already terminal',409)
                c.execute('UPDATE hs_jobs SET status=%s,updated=%s WHERE id=%s',('paused' if action=='pause' else 'cancelled',time.time(),jid))
            self.event(c,jid,action,{'budget_changes':updates or {}})
        return self.get(tenant,jid)
    def results(self,tenant,jid,after=0,limit=100):
        self.get(tenant,jid)
        with self.pool.connection() as c:return c.execute('SELECT id,url,result FROM hs_results WHERE job=%s AND id>%s ORDER BY id LIMIT %s',(jid,after,limit)).fetchall()
    def events(self,tenant,jid,after=0):
        self.get(tenant,jid)
        with self.pool.connection() as c:return c.execute('SELECT * FROM hs_events WHERE job=%s AND id>%s ORDER BY id LIMIT 100',(jid,after)).fetchall()
    def cache_get(self,tenant,key,max_age):
        with self.pool.connection() as c:row=c.execute('SELECT value FROM hs_cache WHERE tenant=%s AND key=%s AND created>%s',(tenant,key,time.time()-max_age)).fetchone()
        return row['value'] if row else None
    def cache_put(self,tenant,key,value):
        with self.pool.connection() as c:c.execute('INSERT INTO hs_cache VALUES(%s,%s,%s,%s) ON CONFLICT(tenant,key) DO UPDATE SET value=excluded.value,created=excluded.created',(tenant,key,Jsonb(value),time.time()))
    def expire(self,days):
        before=time.time()-days*86400
        with self.pool.connection() as c:
            c.execute("DELETE FROM hs_jobs WHERE updated<%s AND status IN ('completed','cancelled','partial')",(before,))
            c.execute('DELETE FROM hs_cache WHERE created<%s',(before,))

    def acquire_network(self,target,maximum,seconds):
        now=time.time();owner=uuid.uuid4().hex
        with self.pool.connection() as c:
            c.execute('INSERT INTO hs_origin_slots(origin) VALUES(%s) ON CONFLICT DO NOTHING',(target,))
            host=c.execute('SELECT * FROM hs_origin_slots WHERE origin=%s FOR UPDATE SKIP LOCKED',(target,)).fetchone()
            if not host or host['lease_until']>now or max(host['retry_at'],host['last_start']+host['delay'])>now:return None
            slot=c.execute('SELECT slot FROM hs_network_slots WHERE slot<=%s AND lease_until<=%s ORDER BY slot FOR UPDATE SKIP LOCKED LIMIT 1',(maximum,now)).fetchone()
            if not slot:return None
            c.execute('UPDATE hs_network_slots SET owner=%s,lease_until=%s WHERE slot=%s',(owner,now+seconds,slot['slot']))
            c.execute('UPDATE hs_origin_slots SET owner=%s,lease_until=%s,last_start=%s WHERE origin=%s',(owner,now+seconds,now,target))
            return {'owner':owner,'slot':slot['slot'],'origin':target}
    def release_network(self,lease,retry_after=0):
        with self.pool.connection() as c:
            c.execute('UPDATE hs_network_slots SET owner=NULL,lease_until=0 WHERE slot=%s AND owner=%s',(lease['slot'],lease['owner']))
            c.execute('UPDATE hs_origin_slots SET owner=NULL,lease_until=0,retry_at=GREATEST(retry_at,%s) WHERE origin=%s AND owner=%s',(time.time()+retry_after,lease['origin'],lease['owner']))
    def origin_delay(self,target,delay):
        with self.pool.connection() as c:c.execute('INSERT INTO hs_origin_slots(origin,delay) VALUES(%s,%s) ON CONFLICT(origin) DO UPDATE SET delay=excluded.delay',(target,max(0,delay)))
