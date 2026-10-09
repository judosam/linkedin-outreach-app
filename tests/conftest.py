"""One isolated database and credential configuration for the entire pytest run."""
import os
import tempfile
import pytest
from unittest.mock import patch

_data = tempfile.TemporaryDirectory()
os.environ.update(OCC_APP_DATA_DIR=_data.name,
                  OCC_DB_URL='sqlite:///' + _data.name.replace('\\', '/') + '/test.db',
                  OCC_DISABLE_SCHEDULER='1', OCC_ADMIN_USERNAME='test-admin',
                  OCC_ADMIN_PASSWORD='test-password-only', NOTIFY_SENDER_APP_PASSWORD='offline-test-only',
                  GCHAT_WEBHOOK_URL='')


@pytest.fixture(autouse=True)
def offline_notifications():
    # Individual payload tests may replace these mocks; no test delivers mail
    # or Google Chat messages, even if notification settings are changed.
    with patch('app.notify.send_gchat', return_value=False), patch('app.notify.send_reply_digest', return_value=False):
        yield

@pytest.fixture(scope='session', autouse=True)
def isolated_database_lifetime():
    yield
    from app.database import engine
    engine.dispose()
    _data.cleanup()
