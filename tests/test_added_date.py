from datetime import datetime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.models import Base, Lead
from app.main import lead_sorts


def test_added_date_sort_uses_creation_not_latest_activity():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            Lead(id=1, sales_nav_id='old', created_at=datetime(2026, 9, 1), last_followup_at=datetime(2026, 9, 15)),
            Lead(id=2, sales_nav_id='new', created_at=datetime(2026, 9, 14)),
            Lead(id=3, sales_nav_id='tie', created_at=datetime(2026, 9, 14)),
        ])
        db.commit()
        for key, expected in [('created', [1, 2, 3]), ('created_desc', [3, 2, 1])]:
            assert list(db.scalars(select(Lead.id).order_by(*lead_sorts()[key]))) == expected
    engine.dispose()
