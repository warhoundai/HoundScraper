import os
import pytest
from houndscraper.database import Store
from houndscraper.config import Settings
from cryptography.fernet import Fernet

@pytest.fixture
def store():
    url=os.environ.get('HOUNDSCRAPER_TEST_DATABASE_URL')
    if not url:pytest.skip('Set HOUNDSCRAPER_TEST_DATABASE_URL to an isolated test database')
    if not url.split('?',1)[0].endswith('/houndscraper_test'):raise RuntimeError('Refusing to clear a database not named houndscraper_test')
    db=Store(url)
    with db.pool.connection() as c:c.execute('TRUNCATE hs_jobs,hs_frontier,hs_results,hs_events,hs_cache,hs_artifacts,hs_credentials,hs_monitors,hs_outbox,hs_agent_state,hs_notification_profiles,hs_origin_slots RESTART IDENTITY CASCADE')
    with db.pool.connection() as c:c.execute('UPDATE hs_network_slots SET owner=NULL,lease_until=0')
    yield db
    db.close()
@pytest.fixture
def settings(store,tmp_path):return Settings(database='test',keys={'alpha':'a'*40,'beta':'b'*40},storage=str(tmp_path),encryption_key=Fernet.generate_key().decode(),workers=2)
