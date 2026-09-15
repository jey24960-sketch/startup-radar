"""Stored-snapshot partition and subsequent weekly comparison regressions."""
import os
from datetime import datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from core.clock import SEOUL
from radar.weekly import build_briefing, run_weekly, announce
from test_database import db
from test_weekly import collection

pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Explicit test database required')
AT = datetime(2026, 9, 15, 17, 35, tzinfo=SEOUL)


def first_snapshot(db, count=206):
    acquired = collection(db, count)
    for index, row in enumerate(acquired['weekly_programs']):
        if index < 12:
            row['snapshot'].update(application_start_at='2026-09-08T00:00:00+09:00', application_start_precision='DATE')
        elif index < count - 1:
            row['snapshot'].update(application_start_at='2026-09-01T00:00:00+09:00', application_start_precision='DATE')
    first = build_briefing(db, acquired, AT)
    with db.transaction() as c:
        c.execute('update startup_radar.weekly_briefings set published_at=%s where id=%s', (AT, first['briefing_id']))
    return acquired, first


def split(db, bid, count=206):
    with db.transaction() as c:
        return c.execute("select startup_radar.split_initial_publication(%s,'Separate official recent dates from initial archive',%s) result",
                         (bid, count)).fetchone()['result']


def test_206_partition_once_and_future_new_update_unchanged(db):
    acquired, first = first_snapshot(db)
    result = split(db, first['briefing_id'])
    assert (result['weekly_count'], result['baseline_count'], result['total']) == (12, 194, 206)
    assert (result['window_start'], result['window_end'], result['snapshot_date']) == ('2026-09-08', '2026-09-14', '2026-09-15')
    assert result['weekly_id'] == first['briefing_id']
    assert split(db, first['briefing_id']) == {**result, 'unchanged': True}
    with db.transaction() as c:
        rows = c.execute('select briefing_id,program_id from startup_radar.weekly_briefing_items').fetchall()
        weekly = {str(x['program_id']) for x in rows if str(x['briefing_id']) == result['weekly_id']}
        baseline = {str(x['program_id']) for x in rows if str(x['briefing_id']) == result['baseline_id']}
        assert not weekly & baseline and len(weekly | baseline) == 206
        assert str(acquired['weekly_programs'][-1]['program_id']) in baseline  # Unknown official timing.
        assert c.execute('select published_at from startup_radar.weekly_briefings where id=%s', (first['briefing_id'],)).fetchone()['published_at'] == AT
        assert c.execute("select count(*) n from startup_radar.admin_audit where action='INITIAL_PUBLICATION_SPLIT'").fetchone()['n'] == 1
    collector = Mock(side_effect=AssertionError('Do not recollect this week'))
    same_week = run_weekly(db, at=AT, collector=collector)
    assert same_week['briefing_id'] == first['briefing_id'] and not collector.called
    assert build_briefing(db, acquired, AT + timedelta(days=7))['item_count'] == 0
    acquired['weekly_programs'][20]['snapshot']['support_summary'] = 'Verified material support change'
    # The next collection includes one genuinely new identity.
    added = collection(db, 207)['weekly_programs'][-1]
    acquired['weekly_programs'].append(added)
    acquired['weekly_programs'][30]['status'] = 'CLOSED'
    later = build_briefing(db, acquired, AT + timedelta(days=14))
    assert (later['item_count'], later['new_count'], later['updated_count']) == (2, 1, 1)
    with db.transaction() as c:
        assert c.execute("select count(*) n from startup_radar.weekly_briefings where publication_kind='INITIAL_BASELINE'").fetchone()['n'] == 1
        with pytest.raises(psycopg.errors.UniqueViolation):
            with c.transaction():
                c.execute("insert into startup_radar.weekly_briefings(week_start,week_end,title,status,summary,collection_status,ingestion_run_id,publication_kind,snapshot_date) values('2026-09-21','2026-09-27','Duplicate','DRAFT','No','SUCCESS',%s,'INITIAL_BASELINE','2026-09-15')", (acquired['id'],))
    transport = Mock()
    assert announce(db, result['baseline_id'], transport)['state'] == 'BASELINE_ARCHIVE'
    assert not transport.send.called


def test_official_publication_precedence_boundaries_and_invalid_dates(db):
    acquired = collection(db, 6)
    starts = ['2026-09-07', '2026-09-08', '2026-09-14', '2026-09-15', None, '2026-09-10']
    for row, start in zip(acquired['weekly_programs'], starts):
        row['snapshot'].update(application_start_at=start, application_start_precision='DATETIME' if start else 'UNKNOWN')
    first = build_briefing(db, acquired, AT)
    with db.transaction() as c:
        c.execute('update startup_radar.weekly_briefings set published_at=%s where id=%s', (AT, first['briefing_id']))
        c.execute("update startup_radar.sources set adapter='BIZINFO'")
        # An older official publication takes precedence over a recent start.
        c.execute("update startup_radar.program_source_snapshots set raw_metadata=%s,observed_at=%s where program_version_id=%s",
                  (Jsonb({'creatPnttm': '2026-09-01 10:00:00'}), AT-timedelta(hours=1), acquired['weekly_programs'][5]['version_id']))
        assert c.execute("select startup_radar.official_calendar_date('2026-02-30') d").fetchone()['d'] is None
        assert c.execute("select startup_radar.official_calendar_date('09.10') d").fetchone()['d'] is None
    result = split(db, first['briefing_id'], 6)
    assert (result['weekly_count'], result['baseline_count']) == (2, 4)


def test_split_and_both_articles_keep_member_authorization(db):
    _, first = first_snapshot(db, 14)
    result = split(db, first['briefing_id'], 14)
    member, external = uuid4(), uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users(id) values(%s),(%s)', (member, external))
        c.execute("insert into public.test_gfc_roles values(%s,'member'),(%s,'external')", (member, external))
    with db.transaction(member) as c:
        assert c.execute('select public.gfc_radar_weekly_briefings() data').fetchone()['data']['total'] == 2
        for bid in (result['weekly_id'], result['baseline_id']):
            assert c.execute('select public.gfc_radar_weekly_briefing(%s) data', (bid,)).fetchone()['data']
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction(member) as c:
            c.execute("select startup_radar.split_initial_publication(%s,'Unauthorized revision',14)", (first['briefing_id'],))
    for bid in (result['weekly_id'], result['baseline_id']):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction(external) as c:
                c.execute('select public.gfc_radar_weekly_briefing(%s)', (bid,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction() as c:
                c.execute('set local role anon')
                c.execute('select public.gfc_radar_weekly_briefing(%s)', (bid,))
