"""Private artifact backends. Target content cannot select a backend or object key."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from .errors import ScrapeError
class LocalBackend:
    def __init__(self,root):self.root=Path(root).resolve();self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
    def put(self,key,body,mime):
        path=self.root/key;path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as f:f.write(body)
    def get(self,key,maximum):
        with (self.root/key).open('rb') as f:return f.read(maximum+1)
    def delete(self,key):(self.root/key).unlink(missing_ok=True)
class S3Backend:
    def __init__(self,url,client=None):
        parsed=urlsplit(url)
        if parsed.scheme!='s3' or not parsed.netloc or parsed.query or parsed.fragment or '..' in parsed.path.split('/'):raise ValueError('Use s3://bucket/optional-prefix')
        self.bucket=parsed.netloc;self.prefix=parsed.path.strip('/')
        if client is None:
            try:import boto3
            except ImportError:raise ScrapeError('CAPABILITY_UNAVAILABLE','Install the s3 extra for S3-compatible storage',503)
            from botocore.config import Config
            client=boto3.client('s3',endpoint_url=os.environ.get('HOUNDSCRAPER_S3_ENDPOINT'),config=Config(connect_timeout=10,read_timeout=30,retries={'max_attempts':2}))
        self.client=client
    def key(self,key):return (self.prefix+'/' if self.prefix else '')+key
    def put(self,key,body,mime):self.client.put_object(Bucket=self.bucket,Key=self.key(key),Body=body,ContentType=mime,ServerSideEncryption='AES256')
    def get(self,key,maximum):
        response=self.client.get_object(Bucket=self.bucket,Key=self.key(key))
        try:return response['Body'].read(maximum+1)
        finally:response['Body'].close()
    def delete(self,key):self.client.delete_object(Bucket=self.bucket,Key=self.key(key))
