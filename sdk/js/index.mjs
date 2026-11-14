export class HoundScraperError extends Error{constructor(status,body){super(body?.error?.message||'Request failed');this.status=status;this.code=body?.error?.code;}}
export class HoundScraper{
 constructor({baseUrl='http://127.0.0.1:8081',apiKey,fetch:fetcher=globalThis.fetch}){const u=new URL(baseUrl);if(u.username||u.password||u.search||u.hash||u.protocol!=='https:'&&!(u.protocol==='http:'&&['localhost','127.0.0.1','[::1]'].includes(u.hostname)))throw new Error('Use HTTPS or loopback HTTP');this.baseUrl=baseUrl.replace(/\/$/,'');this.apiKey=apiKey;this.fetcher=fetcher;}
 async request(method,path,body,options={}){const r=await this.fetcher(this.baseUrl+path,{method,headers:{Authorization:`Bearer ${this.apiKey}`,...(body?{'Content-Type':'application/json'}:{}),...options.headers},...(body?{body:JSON.stringify(body)}:{}),signal:options.signal});const result=r.status===204?null:await r.json();if(!r.ok)throw new HoundScraperError(r.status,result);return result;}
 scrape(url,options={},requestOptions={}){return this.request('POST','/v1/scrape',{url,options},requestOptions);}
 submit(kind,urls,options={},idempotencyKey=crypto.randomUUID()){return this.request('POST','/v1/jobs',{kind,urls,...options},{headers:{'Idempotency-Key':idempotencyKey}});}
 job(id){return this.request('GET',`/v1/jobs/${encodeURIComponent(id)}`);}
 async wait(id,{timeout=900000,signal}={}){const end=Date.now()+timeout;while(Date.now()<end){signal?.throwIfAborted();const job=await this.job(id);if(['completed','partial','cancelled','paused'].includes(job.status))return job;await new Promise(r=>setTimeout(r,300));}throw new Error('Job is still resumable; poll the original ID');}
 async *results(id){let cursor=0;do{const page=await this.request('GET',`/v1/jobs/${encodeURIComponent(id)}/results?cursor=${cursor}`);for(const row of page.data)yield row.result;cursor=page.next_cursor;}while(cursor);}
 transition(id,action,budgets={}){if(!['pause','resume','cancel'].includes(action))throw new Error('Invalid transition');return this.request('POST',`/v1/jobs/${encodeURIComponent(id)}/${action}`,action==='resume'?budgets:undefined);}
}
