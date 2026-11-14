import hashlib
import os
import time
import uuid
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from .errors import ScrapeError

class Artifacts:
    def __init__(self,store,root):
        self.store=store
        from .storage_backends import LocalBackend,S3Backend
        self.backend=S3Backend(root) if root.startswith('s3://') else LocalBackend(root)
    def put(self,tenant,body,mime):
        aid=uuid.uuid4().hex;key=hashlib.sha256(tenant.encode()).hexdigest()+'/'+aid
        self.backend.put(key,body,mime)
        sha=hashlib.sha256(body).hexdigest()
        with self.store.pool.connection() as c:c.execute('INSERT INTO hs_artifacts VALUES(%s,%s,%s,%s,%s,%s,%s)',(aid,tenant,key,mime,sha,len(body),time.time()))
        return {'id':aid,'url':'/v1/artifacts/'+aid,'sha256':sha,'bytes':len(body),'content_type':mime}
    def get(self,tenant,aid):
        with self.store.pool.connection() as c:row=c.execute('SELECT * FROM hs_artifacts WHERE tenant=%s AND id=%s',(tenant,aid)).fetchone()
        if not row:raise ScrapeError('NOT_FOUND','Artifact not found',404)
        body=self.backend.get(row['key'],row['bytes'])
        if hashlib.sha256(body).hexdigest()!=row['sha256']:raise ScrapeError('INTEGRITY_ERROR','Artifact integrity check failed',500)
        return body,row
    def expire(self,days):
        # Delete storage first. A failed deletion keeps metadata for the next cleanup.
        with self.store.pool.connection() as c:
            rows=c.execute('SELECT id,key FROM hs_artifacts WHERE created<%s',(time.time()-days*86400,)).fetchall()
            for row in rows:
                self.backend.delete(row['key'])
                c.execute('DELETE FROM hs_artifacts WHERE id=%s',(row['id'],))

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
