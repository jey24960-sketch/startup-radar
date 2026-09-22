"""Publication labels use the first persisted Seoul day, not the weekly identity."""
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock

import pytest
from radar.weekly import publication_title, build_briefing, run_weekly, announce
from test_database import db
from test_weekly import collection, configure_official_channel, AT

DB = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Explicit test database required')


@pytest.mark.parametrize('stamp,kind,title', [
    ('2026-09-21T14:59:59+00:00','WEEKLY','9월 21일자 주간 지원사업 공지'),
    ('2026-09-21T15:00:00+00:00','WEEKLY','9월 22일자 주간 지원사업 공지'),
    ('2026-12-31T15:00:00+00:00','WEEKLY','1월 1일자 주간 지원사업 공지'),
    ('2026-09-15T08:35:11+00:00','INITIAL_BASELINE','9월 15일자 최초 지원사업 목록'),
])
def test_publication_date_uses_seoul(stamp,kind,title):
    assert publication_title(datetime.fromisoformat(stamp),kind)==title


def test_missing_date_is_not_guessed_and_naive_clock_is_rejected():
    assert publication_title(None)=='발행 전 주간 지원사업 공지'
    with pytest.raises(ValueError):publication_title(datetime(2026,9,22))


@DB
def test_new_publication_uses_database_day_and_announcement_reuses_stored_title(db):
    # The operational reference intentionally differs from today's database
    # clock: an issue date must not come from the week_window argument.
    result=build_briefing(db,collection(db,1),AT)
    with db.transaction() as c:
        row=c.execute('select * from startup_radar.weekly_briefings where id=%s',(result['briefing_id'],)).fetchone()
        assert row['title']==publication_title(row['published_at'])
        assert row['week_start']==AT.date()
    configure_official_channel(db)
    transport=Mock();transport.send.return_value={'state':'DELIVERED','receipt':{'message_id':123}}
    announce(db,result['briefing_id'],transport)
    assert row['title'] in transport.send.call_args.args[1]
    assert ' ~ ' not in transport.send.call_args.args[1]


@DB
def test_draft_has_no_invented_date_then_uses_first_publication_day(db):
    acquired=collection(db,1)
    draft=build_briefing(db,acquired,AT,publish=False)
    with db.transaction() as c:
        row=c.execute('select title,published_at from startup_radar.weekly_briefings').fetchone()
        assert row=={'title':'발행 전 주간 지원사업 공지','published_at':None}
    published=build_briefing(db,acquired,AT)
    assert published['briefing_id']==draft['briefing_id']
    with db.transaction() as c:
        row=c.execute('select title,published_at from startup_radar.weekly_briefings').fetchone()
        assert row['title']==publication_title(row['published_at'])


@DB
def test_rerun_and_explicit_revision_preserve_original_title_date_and_delivery(db):
    acquired=collection(db,1)
    first=build_briefing(db,acquired,AT)
    # The synthetic first publication is before Seoul midnight, the revision
    # reference is a different day. The stored first date stays authoritative.
    original=datetime(2026,9,14,14,59,59,tzinfo=timezone.utc)
    with db.transaction() as c:
        c.execute('update startup_radar.weekly_briefings set published_at=%s where id=%s',(original,first['briefing_id']))
        before=c.execute('select * from startup_radar.weekly_briefings').fetchone()
    configure_official_channel(db)
    transport=Mock();transport.send.return_value={'state':'DELIVERED','receipt':{'message_id':456}}
    announce(db,first['briefing_id'],transport)
    with db.transaction() as c:
        delivery=c.execute('select to_jsonb(a) row from startup_radar.weekly_announcements a').fetchone()['row']
    rerun=run_weekly(db,transport,at=AT+timedelta(days=1),collector=Mock(side_effect=AssertionError('No recollection')))
    assert rerun['unchanged'] and transport.send.call_count==1
    acquired['weekly_programs'][0]['snapshot']['support_summary']='Verified corrected official benefit'
    revised=build_briefing(db,acquired,AT+timedelta(days=1),revision_note='Verified source correction')
    announce(db,revised['briefing_id'],transport)
    with db.transaction() as c:
        after=c.execute('select * from startup_radar.weekly_briefings').fetchone()
        assert after['title']==before['title']=='9월 14일자 주간 지원사업 공지'
        assert after['published_at']==original
        assert after['revision']==before['revision']+1
        assert after['week_start']==before['week_start']
        assert after['id']==before['id']
        assert c.execute('select to_jsonb(a) row from startup_radar.weekly_announcements a').fetchone()['row']==delivery
        assert transport.send.call_count==1
