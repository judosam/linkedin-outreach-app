"""Isolated tests for the new schedule_store.py."""
import os
import tempfile
import unittest
import json
from datetime import datetime, timezone, timedelta

_temp = tempfile.TemporaryDirectory()
os.environ.setdefault('OCC_APP_DATA_DIR', _temp.name
)
os.environ.setdefault('OCC_DB_URL', 'sqlite:///' + _temp.name.replace('\\', '/') + '/test.db'
)
os.environ.setdefault('OCC_DISABLE_SCHEDULER', '1'
)
os.environ.setdefault('OCC_ADMIN_PASSWORD', 'test-password-only'
)
os.environ.setdefault('OCC_ADMIN_USERNAME', 'test-admin'
)
os.environ.setdefault('NOTIFY_SENDER_APP_PASSWORD', 'offline-test-only'
)

from app.database import engine, SessionLocal
from app.models import Base, Schedule, Campaign, Account, CampaignAccount, Setting
from app import schedule_store


class ScheduleStoreTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)

    def test_next_time_skips_dst_gap(self):
        s = Schedule(timezone='America/New_York', run_time='02:30', days_of_week=None, jitter_minutes=0)
        # 2026-03-08 02:30 does not exist in NY (spring forward)
        # So after 2026-03-07 02:30, it should skip to 2026-03-09 02:30
        after = datetime(2026, 3, 7, 7, 30, tzinfo=timezone.utc)  # Mar 7, 2:30 AM EST
        nt = schedule_store.next_time(s, after=after)
        # Should be Mar 9, 2:30 AM EDT = 6:30 AM UTC
        self.assertEqual(nt, datetime(2026, 3, 9, 6, 30))

    def test_validate_scope(self):
        with SessionLocal() as db:
            c = Campaign(name='c', campaign_key='c', search_url='u')
            a = Account(name='a', session_ref='f')
            db.add_all([c, a])
            db.commit()
            
            db.add(CampaignAccount(campaign_id=c.id, account_id=a.id)); db.commit()
            # valid specific
            schedule_store.validate_scope({'campaign_ids': [c.id], 'account_ids': [a.id]}, db)
            
            # valid 'all'
            schedule_store.validate_scope({'campaign_ids': None, 'account_ids': None}, db)
            
            # invalid specific (empty list)
            with self.assertRaises(ValueError):
                schedule_store.validate_scope({'campaign_ids': []}, db)
                
            # invalid specific (non-existent)
            with self.assertRaises(ValueError):
                schedule_store.validate_scope({'campaign_ids': [999]}, db)

    def test_save_and_serialize(self):
        with SessionLocal() as db:
            c = Campaign(name='c', campaign_key='c', search_url='u')
            db.add(c)
            db.commit()
            cid = c.id
            
        data = {
            'name': 'Test',
            'run_time': '09:00',
            'timezone': 'Asia/Kolkata',
            'days_of_week': ['mon', 'tue'],
            'job_keys': ['send_connections'],
            'scopes': {'send_connections': {'campaign_ids': [cid]}},
            'active': True,
            'jitter_minutes': 5,
            'window_end': None,
        }
        res = schedule_store.save(data)
        self.assertEqual(res['name'], 'Test')
        self.assertEqual(res['days_of_week'], ['mon', 'tue'])
        self.assertIsNotNone(res['next_run_at'])

        items = schedule_store.listing()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['id'], res['id'])

    def test_fixed_india_default_and_reject_other_timezones(self):
        data = dict(name='India schedule', run_time='09:00', days_of_week=['mon'],
                    job_keys=['check_replies'], active=False)
        saved = schedule_store.save(data)
        self.assertEqual(saved['timezone'], 'Asia/Kolkata')
        for zone in ['UTC', 'America/New_York', None, '']:
            with self.assertRaisesRegex(ValueError, 'India Standard Time'):
                schedule_store.save({**data, 'timezone': zone})
            with self.assertRaisesRegex(ValueError, 'India Standard Time'):
                schedule_store.save({'timezone': zone}, saved['id'])
        self.assertEqual(len(schedule_store.listing()), 1)
        self.assertEqual(schedule_store.save({'name':'Renamed'}, saved['id'])['timezone'], 'Asia/Kolkata')

    def test_india_weekday_uses_local_midnight(self):
        row = Schedule(timezone='Asia/Kolkata', run_time='00:15', days_of_week=['mon'], jitter_minutes=0)
        # Monday 00:15 IST falls on Sunday 18:45 UTC.
        self.assertEqual(schedule_store.next_time(row, datetime(2026, 9, 13, 18, 31)),
                         datetime(2026, 9, 13, 18, 45))
        # Once that occurrence has passed, the next Monday is selected.
        self.assertEqual(schedule_store.next_time(row, datetime(2026, 9, 13, 18, 46)),
                         datetime(2026, 9, 20, 18, 45))

    def test_existing_rows_migrate_once_preserving_clock_and_history(self):
        history = datetime(2026, 9, 1, 8, 0)
        with SessionLocal() as db:
            db.add(Setting(key='schedule_rows_migrated', value_json='true'))
            for active in [True, False]:
                db.add(Schedule(name=str(active), run_time='09:00', timezone='UTC',
                                days_of_week=['mon'], job_keys=['check_replies'], scopes={},
                                active=active, jitter_minutes=0, last_run_at=history,
                                next_run_at=datetime(2030, 1, 1, 9)))
            db.commit()
        rows = schedule_store.listing()
        for row in rows:
            self.assertEqual(row['timezone'], 'Asia/Kolkata')
            self.assertEqual(row['run_time'], '09:00')
            self.assertEqual(row['days_of_week'], ['mon'])
            self.assertEqual(row['last_run_at'], history.isoformat()+'Z')
            if row['active']:
                next_run = datetime.fromisoformat(row['next_run_at'].replace('Z','+00:00'))
                self.assertEqual((next_run.weekday(), next_run.hour, next_run.minute), (0,3,30))
            else:
                self.assertIsNone(row['next_run_at'])
        self.assertEqual(schedule_store.listing(), rows)

    def test_legacy_settings_import_uses_india(self):
        with SessionLocal() as db:
            db.add(Setting(key='named_jobs_schedule', value_json=json.dumps([
                dict(name='Legacy', job='check_replies', time='09:00', timezone='UTC', enabled=False)
            ])))
            db.commit()
        row = schedule_store.listing()[0]
        self.assertEqual((row['timezone'], row['run_time']), ('Asia/Kolkata','09:00'))

    def test_partial_edit_normalizes_old_zone_without_listing(self):
        with SessionLocal() as db:
            row = Schedule(name='Old', run_time='09:00', timezone='UTC', days_of_week=['mon'],
                           job_keys=['check_replies'], scopes={}, active=True, jitter_minutes=0,
                           next_run_at=datetime(2030, 1, 1, 9))
            db.add(row); db.commit(); row_id = row.id
        edited = schedule_store.save({'name':'Updated'}, row_id)
        self.assertEqual(edited['timezone'], 'Asia/Kolkata')
        self.assertIn('T03:30:00', edited['next_run_at'])


if __name__ == '__main__':
    unittest.main()

