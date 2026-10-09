"""Engine + session factory. SQLite by default (OCC_DB_URL can point at
Postgres, e.g. postgresql+psycopg://user:pass@host/occ)."""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .config import APP_DATA_DIR

APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_URL = os.environ.get('OCC_DB_URL', f"sqlite:///{APP_DATA_DIR / 'app_data.db'}")

connect_args = {'check_same_thread': False} if DB_URL.startswith('sqlite') else {}
engine = create_engine(DB_URL, connect_args=connect_args, future=True)

if DB_URL.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def _set_sqlite_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute('PRAGMA foreign_keys=ON')
        cur.execute('PRAGMA journal_mode=WAL')
        cur.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def migrate_lead_identity_index(bind=None):
    """Allow missing IDs while retaining uniqueness for identified leads.

    Build the replacement before dropping the old index. No lead rows change.
    An explicit engine lets migrations be rehearsed on a database copy.
    """
    from sqlalchemy import text
    with (bind or engine).begin() as connection:
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_lead_snid_campaign_present "
                                "ON leads (sales_nav_id, campaign_id) WHERE sales_nav_id <> ''"))
        connection.execute(text('DROP INDEX IF EXISTS uq_lead_snid_campaign'))


def init_db():
    from .models import Base  # noqa: circular-safe
    Base.metadata.create_all(engine)
    migrate_lead_identity_index()
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    if 'schedule_id' not in {c['name'] for c in insp.get_columns('run_logs')}:
        with engine.begin() as connection:
            connection.execute(text('ALTER TABLE run_logs ADD COLUMN schedule_id INTEGER'))

    # Lightweight in-place migrations (SQLite-compatible ALTER ADD COLUMN).
    _ensure_columns('run_logs', {
        'owner_user_id': 'INTEGER REFERENCES users(id) ON DELETE SET NULL',
        'execution_id': 'VARCHAR(32)',
    })
    with engine.begin() as connection:
        connection.execute(text('CREATE INDEX IF NOT EXISTS ix_run_logs_owner ON run_logs (owner_user_id)'))
        connection.execute(text('CREATE INDEX IF NOT EXISTS ix_run_logs_execution ON run_logs (execution_id)'))
    _ensure_columns('accounts', {
        'daily_invite_cap': 'INTEGER DEFAULT 30',
        'weekly_invite_cap': 'INTEGER DEFAULT 100',
        'daily_inmail_cap': 'INTEGER DEFAULT 10',
        'daily_message_cap': 'INTEGER DEFAULT 60',
        'total_runs': 'INTEGER DEFAULT 0',
    })
    _ensure_columns('campaigns', {
        'invite_fu_days': "JSON DEFAULT '[3, 5, 7]'",
        'inmail_fu_days': "JSON DEFAULT '[3, 5, 7]'",
    })
    _ensure_columns('leads', {
        'status_before_error': 'VARCHAR(40)',
        'stage_time_before_error': 'DATETIME',
        'first_contacted_at': 'DATETIME',
        'contact_channel': "VARCHAR(20) DEFAULT ''",
        'last_followup_at': 'DATETIME',
        'last_followup_stage': "VARCHAR(40) DEFAULT ''",
        'reply_category': "VARCHAR(30) DEFAULT ''",
        'reply_category_source': "VARCHAR(10) DEFAULT ''",
        'reply_category_at': 'DATETIME',
        'review_status': "VARCHAR(20) DEFAULT ''",
        'reply_reviewed_at': 'DATETIME',
        'import_fp': "VARCHAR(64) DEFAULT ''",
        'sales_nav_urn': "VARCHAR(255) DEFAULT ''",
        'last_error': "VARCHAR(255) DEFAULT ''",
    })
    # Users table (added after first release): older DBs have the table
    # without the scope columns — ALTER TABLE ... ADD COLUMN fills them in
    # (empty JSON list = access to everything, matching previous behaviour).
    _ensure_columns('users', {
        'allowed_campaign_ids': "JSON DEFAULT '[]' NOT NULL",
        'allowed_account_ids': "JSON DEFAULT '[]' NOT NULL",
        'can_manage_licenses': "BOOLEAN DEFAULT 0 NOT NULL",
    })

    # Sort-column indexes for the leads table: CREATE TABLE-time indexes only
    # get created with the table — existing databases keep running without
    # them, so every sort click did a full scan + filesort. CREATE INDEX IF
    # NOT EXISTS is idempotent and instant when they already exist.
    with engine.begin() as connection:
        _idx_cols = {
            'ix_leads_last_followup': 'last_followup_at', 'ix_leads_first_contacted': 'first_contacted_at',
            'ix_leads_created_at': 'created_at', 'ix_leads_company': 'company',
            'ix_leads_full_name': 'full_name', 'ix_leads_associate_account': 'associate_account_id',
        }
        for idx, col in _idx_cols.items():
            connection.execute(text(f'CREATE INDEX IF NOT EXISTS {idx} ON leads ({col})'))

    # Backfill contact dates from existing audit events: the first 'outbound'
    # event is the first touch, channel inferred from the lead's status prefix.
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE leads
            SET first_contacted_at = (
                SELECT MIN(le.created_at) FROM lead_events le
                WHERE le.lead_id = leads.id AND le.kind = 'outbound'
            ),
            contact_channel = CASE
                WHEN leads.status LIKE 'INMAIL%' THEN 'inmail'
                WHEN leads.status LIKE 'INVITE%' THEN 'invite'
                ELSE leads.contact_channel
            END
            WHERE first_contacted_at IS NULL
        """))


    # Classify historical replies once (rule-based; leaves ambiguous as unclassified).
    _backfill_reply_categories()
    from .invite_limits import backfill_weekly_invites
    with SessionLocal() as db:
        backfill_weekly_invites(db)


def _backfill_reply_categories():
    from sqlalchemy import text
    from .classify import suggest_category
    with engine.begin() as connection:
        rows = connection.execute(text(
            "SELECT id, reply_message FROM leads "
            "WHERE received_replies = 1 AND reply_category = '' AND reply_category_source = ''"
        )).all()
    if not rows:
        return
    with engine.begin() as connection:
        for lead_id, message in rows:
            cat, source = suggest_category(message or '')
            connection.execute(text(
                'UPDATE leads SET reply_category = :c, reply_category_source = :s, '
                'reply_category_at = CURRENT_TIMESTAMP, review_status = CASE WHEN review_status = \'\' THEN \'needs_review\' ELSE review_status END '
                'WHERE id = :i'
            ), {'c': cat, 's': source, 'i': lead_id})
    print(f'[migrate] auto-classified {len(rows)} historical reply(ies)')


def _ensure_columns(table: str, columns: dict):
    from sqlalchemy import inspect, text
    existing = {c['name'] for c in inspect(engine).get_columns(table)}
    with engine.begin() as connection:
        for name, ddl in columns.items():
            if name not in existing:
                connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))


def get_db():
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
