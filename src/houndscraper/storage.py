import hashlib
import os
import time
import uuid
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from .errors import ScrapeError

class Artifacts:
    def __init__(self,store,root):
        self.store=store;self.root=Path(root).resolve();self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
    def put(self,tenant,body,mime):
        aid=uuid.uuid4().hex;key=hashlib.sha256(tenant.encode()).hexdigest()+'/'+aid
        path=self.root/key;path.parent.mkdir(mode=0o700,exist_ok=True)
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as f:f.write(body)
        sha=hashlib.sha256(body).hexdigest()
        with self.store.pool.connection() as c:c.execute('INSERT INTO hs_artifacts VALUES(%s,%s,%s,%s,%s,%s,%s)',(aid,tenant,key,mime,sha,len(body),time.time()))
        return {'id':aid,'url':'/v1/artifacts/'+aid,'sha256':sha,'bytes':len(body),'content_type':mime}
    def get(self,tenant,aid):
        with self.store.pool.connection() as c:row=c.execute('SELECT * FROM hs_artifacts WHERE tenant=%s AND id=%s',(tenant,aid)).fetchone()
        if not row:raise ScrapeError('NOT_FOUND','Artifact not found',404)
        path=self.root/row['key'];body=path.read_bytes()
        if hashlib.sha256(body).hexdigest()!=row['sha256']:raise ScrapeError('INTEGRITY_ERROR','Artifact integrity check failed',500)
        return body,row
    def expire(self,days):
        with self.store.pool.connection() as c:
            rows=c.execute('DELETE FROM hs_artifacts WHERE created<%s RETURNING key',(time.time()-days*86400,)).fetchall()
        for row in rows:(self.root/row['key']).unlink(missing_ok=True)

class Credentials:
    def __init__(self,store,key):self.store=store;self.cipher=Fernet(key.encode()) if key else None
    def put(self,tenant,name,target,headers):
        import json
        if not self.cipher:raise ScrapeError('ENCRYPTION_NOT_CONFIGURED','Configure an external encryption key first',503)
        if not name or len(name)>100:raise ScrapeError('INVALID_PROFILE','Profile name must be 1–100 characters')
        allowed={'authorization','cookie','accept-language'}
        if not headers or any(k.lower() not in allowed or '\n' in v or '\r' in v for k,v in headers.items()):raise ScrapeError('INVALID_PROFILE','Only authorization, cookie and language headers are supported')
        token=self.cipher.encrypt(json.dumps(headers).encode()).decode()
        with self.store.pool.connection() as c:c.execute('INSERT INTO hs_credentials VALUES(%s,%s,%s,%s) ON CONFLICT(tenant,name) DO UPDATE SET origin=excluded.origin,ciphertext=excluded.ciphertext',(tenant,name,target,token))
    def get(self,tenant,name,target):
        import json
        if not self.cipher:raise ScrapeError('ENCRYPTION_NOT_CONFIGURED','Credential encryption is not configured',503)
        with self.store.pool.connection() as c:row=c.execute('SELECT * FROM hs_credentials WHERE tenant=%s AND name=%s',(tenant,name)).fetchone()
        if not row or row['origin']!=target:raise ScrapeError('PROFILE_SCOPE','Credential profile is missing or belongs to another origin',403)
        return json.loads(self.cipher.decrypt(row['ciphertext'].encode()))
