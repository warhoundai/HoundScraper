"""Encrypted notification profiles and operator-configured TLS email transport."""
import asyncio
import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from .errors import ScrapeError
from .network import normalize_url
class Notifications:
    def __init__(self,engine):self.engine=engine;self.store=engine.store;self.cipher=engine.credentials.cipher
    def put(self,tenant,name,value):
        if not self.cipher:raise ScrapeError('ENCRYPTION_NOT_CONFIGURED','Configure credential encryption before notification profiles',503)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',name):raise ScrapeError('INVALID_PROFILE','Invalid notification profile name')
        if value.get('kind')=='email':
            if set(value)!={'kind','recipients'} or not isinstance(value['recipients'],list) or not 1<=len(value['recipients'])<=20 or any(not isinstance(v,str) or len(v)>254 or not re.fullmatch(r'[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+',v) for v in value['recipients']):raise ScrapeError('INVALID_RECIPIENT','Provide 1–20 mailbox addresses without display names')
        elif value.get('kind')=='slack':
            if set(value)!={'kind','webhook_url'}:raise ScrapeError('INVALID_PROFILE','Slack requires a webhook URL')
            url=normalize_url(value['webhook_url'])
            if not url.startswith('https://hooks.slack.com/services/'):raise ScrapeError('INVALID_PROFILE','Use an official Slack incoming webhook')
        else:raise ScrapeError('INVALID_PROFILE','Choose email or slack')
        token=self.cipher.encrypt(json.dumps(value).encode()).decode()
        with self.store.pool.connection() as c:c.execute('INSERT INTO hs_notification_profiles VALUES(%s,%s,%s) ON CONFLICT(tenant,name) DO UPDATE SET ciphertext=excluded.ciphertext',(tenant,name,token))
    def get(self,tenant,name):
        with self.store.pool.connection() as c:row=c.execute('SELECT ciphertext FROM hs_notification_profiles WHERE tenant=%s AND name=%s',(tenant,name)).fetchone()
        if not row or not self.cipher:raise ScrapeError('NOT_FOUND','Notification profile not found',404)
        return json.loads(self.cipher.decrypt(row['ciphertext'].encode()))
    async def send(self,tenant,name,payload):
        profile=self.get(tenant,name)
        if profile['kind']=='slack':
            body=json.dumps({'text':'HoundScraper monitor update\n'+json.dumps(payload,ensure_ascii=False)[:25000]}).encode()
            r=await self.engine.network.fetch(profile['webhook_url'],method='POST',body=body,headers={'Content-Type':'application/json'},max_bytes=65536,timeout=15)
            if not 200<=r.status<300:raise ScrapeError('NOTIFICATION_FAILED','Slack delivery failed',502,True)
        else:await asyncio.to_thread(self.email,profile['recipients'],payload)
    def email(self,recipients,payload):
        host=os.environ.get('HOUNDSCRAPER_SMTP_HOST');sender=os.environ.get('HOUNDSCRAPER_SMTP_FROM')
        if not host or not sender:raise ScrapeError('CAPABILITY_UNAVAILABLE','Configure the SMTP host and sender',503)
        message=EmailMessage();message['Subject']='HoundScraper monitor update';message['From']=sender;message['To']=', '.join(recipients);message.set_content(json.dumps(payload,indent=2,ensure_ascii=False))
        context=ssl.create_default_context();port=int(os.environ.get('HOUNDSCRAPER_SMTP_PORT','587'));use_ssl=os.environ.get('HOUNDSCRAPER_SMTP_SSL','false')=='true'
        connection=smtplib.SMTP_SSL(host,port,timeout=15,context=context) if use_ssl else smtplib.SMTP(host,port,timeout=15)
        with connection as smtp:
            if not use_ssl:smtp.starttls(context=context)
            if os.environ.get('HOUNDSCRAPER_SMTP_USER'):smtp.login(os.environ['HOUNDSCRAPER_SMTP_USER'],os.environ.get('HOUNDSCRAPER_SMTP_PASSWORD',''))
            smtp.send_message(message)
