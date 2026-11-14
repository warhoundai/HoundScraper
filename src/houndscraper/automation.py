"""Durable schedules and signed, retryable, public-destination webhook delivery."""
import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from croniter import croniter
from psycopg.types.json import Jsonb
from .errors import ScrapeError

class Automation:
    def __init__(self,engine):self.engine=engine;self.store=engine.store;self.key=os.environ.get('HOUNDSCRAPER_WEBHOOK_KEY','')
    def create_monitor(self,tenant,job,schedule,zone='UTC',notifications=None):
        try:
            tz=ZoneInfo(zone);base=datetime.now(tz);it=croniter(schedule,base);first=it.get_next(datetime);second=it.get_next(datetime)
            if (second-first).total_seconds()<60:raise ValueError()
        except Exception:raise ScrapeError('INVALID_SCHEDULE','Use a valid cron schedule, IANA timezone and an interval of at least one minute')
        if job.webhook and len(self.key)<32:raise ScrapeError('WEBHOOK_NOT_CONFIGURED','Configure an independent webhook signing key',503)
        if notifications is not None and (not isinstance(notifications,list) or len(notifications)>20 or not all(isinstance(n,str) for n in notifications)):raise ScrapeError('INVALID_PROFILE','Provide at most 20 notification profile names')
        mid=uuid.uuid4().hex;body=job.model_dump();body['monitor_timezone']=zone;body['notification_profiles']=notifications or []
        from .notifications import Notifications
        for name in body['notification_profiles']:Notifications(self.engine).get(tenant,name)
        with self.store.pool.connection() as c:c.execute('INSERT INTO hs_monitors(id,tenant,request,cron,next_run) VALUES(%s,%s,%s,%s,%s)',(mid,tenant,Jsonb(body),schedule,first.timestamp()))
        return {'id':mid,'schedule':schedule,'timezone':zone,'next_run':first.timestamp()}
    def reconcile(self):
        with self.store.pool.connection() as c:
            monitors=c.execute("SELECT * FROM hs_monitors WHERE previous ? 'active_job' FOR UPDATE SKIP LOCKED").fetchall()
            for monitor in monitors:
                previous=monitor['previous'];jid=previous['active_job'];job=c.execute('SELECT * FROM hs_jobs WHERE id=%s',(jid,)).fetchone()
                if not job or job['status'] not in ('completed','partial','cancelled'):continue
                rows=c.execute('SELECT result,url FROM hs_results WHERE job=%s',(jid,)).fetchall()
                old=previous.get('snapshot',{});snapshot={};changes=[]
                for row in rows:
                    result=row['result'];url=row['url']
                    if result.get('error'):changes.append({'url':url,'status':'error','error':result['error']});continue
                    digest=result.get('content_sha256') or result.get('sha256');snapshot[url]=digest
                    status='new' if url not in old else 'changed' if old[url]!=digest else 'same'
                    if status!='same':changes.append({'url':url,'status':status,'sha256':digest})
                # Failed/incomplete checks never establish removal or replace missing evidence.
                if job['status']=='completed':
                    for url in set(old)-set(snapshot):changes.append({'url':url,'status':'missing_from_complete_crawl'})
                else:snapshot={**old,**snapshot}
                current={'snapshot':snapshot,'last_job':jid,'changes':changes,'checked_at':time.time()}
                c.execute('UPDATE hs_monitors SET previous=%s WHERE id=%s',(Jsonb(current),monitor['id']))
                if changes:
                    for name in monitor['request'].get('notification_profiles',[]):
                        c.execute('INSERT INTO hs_outbox(tenant,url,payload) VALUES(%s,%s,%s)',(monitor['tenant'],'notification:'+name,Jsonb({'event':'monitor_changed','monitor_id':monitor['id'],'job_id':jid,'changes':changes})))
                if changes and monitor['request'].get('webhook'):
                    c.execute('INSERT INTO hs_outbox(tenant,url,payload) VALUES(%s,%s,%s)',(monitor['tenant'],monitor['request']['webhook'],Jsonb({'event':'monitor_changed','monitor_id':monitor['id'],'job_id':jid,'changes':changes})))
    async def tick(self):
        self.reconcile()
        with self.store.pool.connection() as c:
            rows=c.execute('SELECT * FROM hs_monitors WHERE active=true AND next_run<=%s FOR UPDATE SKIP LOCKED',(time.time(),)).fetchall()
            due=[]
            for row in rows:
                active=row['previous'].get('active_job')
                if active:
                    job=c.execute('SELECT status FROM hs_jobs WHERE id=%s',(active,)).fetchone()
                    if job and job['status'] in ('running','queued','paused'):continue
                tz=ZoneInfo(row['request'].get('monitor_timezone','UTC'));next_run=croniter(row['cron'],datetime.now(tz)).get_next(datetime).timestamp()
                body={k:v for k,v in row['request'].items() if k not in ('monitor_timezone','notification_profiles')};body['webhook']=None
                if body['kind']=='search':
                    due.append((row,body));c.execute('UPDATE hs_monitors SET next_run=%s WHERE id=%s',(next_run,row['id']));continue
                job=self.store.create(row['tenant'],body,'monitor:'+row['id']+':'+str(row['next_run']))
                previous=row['previous'];previous['active_job']=job['id']
                c.execute('UPDATE hs_monitors SET previous=%s,next_run=%s WHERE id=%s',(Jsonb(previous),next_run,row['id']))
        for row,body in due:
            try:
                found=await self.engine.providers.search(body['query'],min(body['max_pages'],100));body['urls']=[r['url'] for r in found['results']]
                if not body['urls']:continue
                job=self.store.create(row['tenant'],body,'monitor:'+row['id']+':'+str(row['next_run']))
                previous=row['previous'];previous['active_job']=job['id']
                with self.store.pool.connection() as c:c.execute('UPDATE hs_monitors SET previous=%s WHERE id=%s',(Jsonb(previous),row['id']))
            except ScrapeError:pass
    async def deliver(self):
        with self.store.pool.connection() as c:
            row=c.execute("SELECT * FROM hs_outbox WHERE (state='queued' OR state='sending' AND lease_until<%s) AND retry_at<=%s AND (url LIKE 'notification:%%' OR %s) ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1",(time.time(),time.time(),len(self.key)>=32)).fetchone()
            if not row:return
            c.execute("UPDATE hs_outbox SET state='sending',attempts=attempts+1,lease_until=%s WHERE id=%s",(time.time()+30,row['id']))
        body=json.dumps(row['payload'],sort_keys=True,separators=(',',':')).encode();timestamp=str(int(time.time()));eid=str(row['id'])
        signature=hmac.new(self.key.encode(),timestamp.encode()+b'.'+eid.encode()+b'.'+body,hashlib.sha256).hexdigest()
        try:
            if row['url'].startswith('notification:'):
                from .notifications import Notifications
                await Notifications(self.engine).send(row['tenant'],row['url'].split(':',1)[1],row['payload'])
                response=type('Delivery',(),{'status':204})()
            else:response=await self.engine.network.fetch(row['url'],method='POST',body=body,headers={'content-type':'application/json','X-Hound-Timestamp':timestamp,'X-Hound-Event':eid,'X-Hound-Signature':'sha256='+signature},max_bytes=65536,timeout=15)
            if not 200<=response.status<300:raise ValueError()
            state='delivered'
        except Exception:state='failed' if row['attempts']>=4 else 'queued'
        with self.store.pool.connection() as c:c.execute('UPDATE hs_outbox SET state=%s,retry_at=%s,lease_until=NULL WHERE id=%s',(state,time.time()+min(3600,2**(row['attempts']+1)),row['id']))
