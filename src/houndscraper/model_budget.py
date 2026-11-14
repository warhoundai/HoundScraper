"""Atomic execution-wide model reservations, including retries and lost responses."""
import json,time,uuid
from contextvars import ContextVar
from decimal import Decimal
from psycopg.types.json import Jsonb
from .errors import ScrapeError
from .pricing import reserve_cost,NANO
current_budget=ContextVar('houndscraper_model_budget',default=None)

class ModelBudget:
    def __init__(self,settings,store,item):self.settings=settings;self.store=store;self.item=item
    def reserve(self,messages,output):
        input_ceiling=len(json.dumps(messages,ensure_ascii=False).encode())+4096
        tokens=input_ceiling+output;request=self.item['request'];cap=request.get('max_cost_usd')
        cost=reserve_cost(self.settings,input_ceiling,output) if cap is not None else 0
        rid=uuid.uuid4().hex
        with self.store.pool.connection() as c:
            job=c.execute('SELECT status,request FROM hs_jobs WHERE id=%s FOR UPDATE',(self.item['job'],)).fetchone()
            lease=c.execute("SELECT job FROM hs_frontier WHERE job=%s AND url=%s AND lease=%s AND state='leased'",(self.item['job'],self.item['url'],self.item['lease'])).fetchone()
            if not lease or job['status'] not in ('queued','running'):raise ScrapeError('STALE_LEASE','Model execution lease is no longer active',409)
            request=job['request'];totals=c.execute('SELECT COALESCE(sum(tokens),0) AS tokens,COALESCE(sum(cost_nano),0) AS cost FROM hs_model_calls WHERE job=%s',(self.item['job'],)).fetchone()
            if totals['tokens']+tokens>request['max_provider_tokens']:raise ScrapeError('PROVIDER_TOKEN_BUDGET','Execution-wide model token budget exhausted',402)
            if cap is not None and totals['cost']+cost>int(Decimal(str(request['max_cost_usd']))*NANO):raise ScrapeError('PROVIDER_COST_BUDGET','Execution-wide model spending budget exhausted',402)
            c.execute('INSERT INTO hs_model_calls(id,job,tokens,cost_nano,created) VALUES(%s,%s,%s,%s,%s)',(rid,self.item['job'],tokens,cost,time.time()))
        return rid
    def settle(self,rid,usage):
        counters=usage.get('provider_tokens',{});values=[counters.get('input_tokens'),counters.get('output_tokens')]
        actual=sum(values) if all(type(v) is int and v>=0 for v in values) else None
        cost=usage.get('cost_nano_usd');violation=False
        with self.store.pool.connection() as c:
            c.execute('SELECT id FROM hs_jobs WHERE id=%s FOR UPDATE',(self.item['job'],))
            row=c.execute('SELECT * FROM hs_model_calls WHERE id=%s FOR UPDATE',(rid,)).fetchone()
            if not row or row['settled']:return
            violation=(actual is not None and actual>row['tokens']) or (row['cost_nano']>0 and cost is not None and cost>row['cost_nano'])
            c.execute('UPDATE hs_model_calls SET tokens=%s,cost_nano=%s,settled=true,usage=%s WHERE id=%s',(actual if actual is not None else row['tokens'],cost if row['cost_nano'] and cost is not None else row['cost_nano'],Jsonb(usage),rid))
            if violation:c.execute("UPDATE hs_jobs SET status='paused',reason='provider_limit_violation' WHERE id=%s",(self.item['job'],))
        if violation:raise ScrapeError('PROVIDER_LIMIT_VIOLATION','Provider exceeded its declared usage ceiling; execution paused',502)
