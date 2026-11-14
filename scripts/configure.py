"""Create local-only configuration without printing or overwriting secrets."""
import base64,json,os,secrets
from pathlib import Path
p=Path('.env')
values={'POSTGRES_PASSWORD':secrets.token_hex(24),'HOUNDSCRAPER_API_KEYS':json.dumps({'local':secrets.token_urlsafe(32)},separators=(',',':')),'HOUNDSCRAPER_ENCRYPTION_KEY':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),'HOUNDSCRAPER_WEBHOOK_KEY':secrets.token_urlsafe(32),'HOUNDBROWSER_SERVICE_KEY':secrets.token_urlsafe(32),'HOUNDSCRAPER_PARSER_KEY':secrets.token_urlsafe(32)}
fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:
    for k,v in values.items():f.write(k+"='"+v+"'\n")
print('Created .env with mode 0600. Secrets were not printed. Keep this file private.')
