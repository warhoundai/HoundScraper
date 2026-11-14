import time
import uuid
from urllib.parse import urlsplit
import httpx
class APIError(RuntimeError):
    def __init__(self,status,value):
        error=value.get('error',{});super().__init__(error.get('message','HoundScraper request failed'));self.status=status;self.code=error.get('code')
class Client:
    def __init__(self,endpoint='http://127.0.0.1:8081',*,api_key,timeout=200,transport=None):
        u=urlsplit(endpoint)
        if u.username or u.password or u.query or u.fragment or (u.scheme!='https' and not(u.scheme=='http' and u.hostname in ('127.0.0.1','localhost','::1'))):raise ValueError('Use HTTPS or loopback HTTP')
        self.http=httpx.Client(base_url=endpoint.rstrip('/'),headers={'Authorization':'Bearer '+api_key},timeout=timeout,transport=transport,trust_env=False)
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def close(self):self.http.close()
    def request(self,method,path,**kwargs):
        r=self.http.request(method,path,**kwargs)
        if r.status_code>=400:raise APIError(r.status_code,r.json())
        return r.json() if r.content else None
    def scrape(self,url,**options):return self.request('POST','/v1/scrape',json={'url':url,'options':options})
    def submit(self,kind,urls,*,idempotency_key=None,**kwargs):return self.request('POST','/v1/jobs',json={'kind':kind,'urls':urls,**kwargs},headers={'Idempotency-Key':idempotency_key or uuid.uuid4().hex})
    def job(self,jid):return self.request('GET','/v1/jobs/'+jid)
    def wait(self,jid,timeout=900):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            result=self.job(jid)
            if result['status'] in ('completed','partial','cancelled','paused'):return result
            time.sleep(.3)
        raise TimeoutError('Job remains resumable; poll its original ID')
    def results(self,jid):
        cursor=0
        while True:
            page=self.request('GET',f'/v1/jobs/{jid}/results',params={'cursor':cursor})
            yield from (row['result'] for row in page['data'])
            if not page['next_cursor']:break
            cursor=page['next_cursor']
    def transition(self,jid,action,**budgets):return self.request('POST',f'/v1/jobs/{jid}/{action}',**({'json':budgets} if action=='resume' else {}))
