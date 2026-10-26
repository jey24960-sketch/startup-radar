"""Planner persistence/idempotency tests against an explicitly isolated DB."""
import os
from datetime import timedelta
from unittest.mock import Mock

import pytest
from psycopg.types.json import Jsonb
from radar.models import Program
from radar.weekly import snapshot
from radar.early_announcements import plan_early_notices, announce_early, next_weekly_at
from test_database import db

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit isolated test database required')


@pytest.fixture
def early_db(db):
    with db.transaction() as c:
        c.execute('truncate startup_radar.early_notices cascade')
        now=c.execute('select now() as at').fetchone()['at']
        c.execute("update startup_radar.runtime_settings set value=%s where key='early_announcements'",
                  (Jsonb({'enabled':True,'active_from':(now-timedelta(hours=1)).isoformat(),'max_items':3}),))
    return db


def candidates(db,count=1):
    source=db.upsert_source('early-fixture-api','Official API','KSTARTUP',{})
    with db.transaction() as c:
        at=c.execute('select now() as at').fetchone()['at']
    # Between now+7d and next Tuesday+7d: the current opportunity has enough
    # runway, but next week's digest would be too late under the same policy.
    end=at+timedelta(days=7)+(next_weekly_at(at)-at)/2
    result=[]
    for i in range(count):
        program=Program(title=f'예비창업팀 MVP 제작 및 액셀러레이팅 프로그램 {i}',
            organization='공식 창업 지원기관',official_url=f'https://example.org/early/{i}',
            applicant_summary='예비창업자와 초기 창업팀이 신청할 수 있습니다.',
            support_summary='MVP 제품 개발, 고객 검증과 시제품 제작을 지원하는 액셀러레이팅 프로그램입니다.',
            application_start_at=at+timedelta(hours=1),application_end_at=end,
            application_start_precision='DATETIME',application_end_precision='DATETIME',deadline_type='FIXED_DATE')
        saved=db.save_program(program,source['id'],str(i),program.official_url,{},'Verified structured fields',
                              extraction_metadata={'provider':'structured_api_weekly','status':'SUCCESS'})
        result.append({**saved,'snapshot':snapshot(program,{})})
    return result


def test_plan_is_one_small_bundle_per_week_and_each_program_is_preserved(early_db):
    acquired=candidates(early_db,5)
    first=plan_early_notices(early_db,candidates=acquired)
    assert first['state']=='PUBLISHED' and first['planned']==3
    second=plan_early_notices(early_db,candidates=acquired)
    assert second['state']=='WEEKLY_EXCEPTION_LIMIT'
    assert second['notice_id']==first['notice_id']
    with early_db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.early_notices').fetchone()['n']==1
        assert c.execute('select count(*) n from startup_radar.early_notice_items').fetchone()['n']==3
        assert c.execute("select count(*) n from startup_radar.admin_audit where action='EARLY_NOTICE_PUBLISHED'").fetchone()['n']==1


def test_pre_activation_discoveries_never_backfill_an_exception(early_db):
    acquired=candidates(early_db)
    with early_db.transaction() as c:
        c.execute("update startup_radar.program_sources set discovered_at=now()-interval '2 days'")
    assert plan_early_notices(early_db,candidates=acquired)['state']=='NO_EARLY_OPPORTUNITIES'
    with early_db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.early_notices').fetchone()['n']==0


def test_short_runway_does_not_publish(early_db):
    acquired=candidates(early_db)
    with early_db.transaction() as c:
        now=c.execute('select now() as at').fetchone()['at']
    acquired[0]['snapshot']['application_end_at']=(now+timedelta(days=6)).isoformat()
    assert plan_early_notices(early_db,candidates=acquired)['state']=='NO_EARLY_OPPORTUNITIES'


def test_official_delivery_is_once_with_receipt_and_cannot_be_repeated(early_db):
    first=plan_early_notices(early_db,candidates=candidates(early_db))
    with early_db.transaction() as c:
        c.execute("update startup_radar.runtime_settings set value=%s where key='weekly_telegram_channel'",
            (Jsonb({'enabled':True,'chat_id':'synthetic-fixture-only','name':'GFC StartupRadar'}),))
    transport=Mock();transport.send.return_value={'state':'DELIVERED','receipt':{'message_id':42}}
    sent=announce_early(early_db,first['notice_id'],transport)
    again=announce_early(early_db,first['notice_id'],transport)
    assert sent['state']==again['state']=='DELIVERED' and transport.send.call_count==1
    with early_db.transaction() as c:
        row=c.execute('select delivery_state,receipt from startup_radar.early_notices where id=%s',(first['notice_id'],)).fetchone()
        assert row['delivery_state']=='DELIVERED' and row['receipt']['message_id']==42
        assert c.execute('select count(*) n from startup_radar.weekly_announcements').fetchone()['n']==0


def test_visible_publication_can_be_created_without_delivery(early_db):
    first=plan_early_notices(early_db,candidates=candidates(early_db))
    with early_db.transaction() as c:
        c.execute("update startup_radar.runtime_settings set value=%s where key='weekly_telegram_channel'",
            (Jsonb({'enabled':True,'chat_id':'synthetic-fixture-only','name':'GFC StartupRadar'}),))
    assert announce_early(early_db,first['notice_id'])['state']=='DELIVERY_DISABLED'
    with early_db.transaction() as c:
        row=c.execute('select delivery_state,attempted_at from startup_radar.early_notices where id=%s',(first['notice_id'],)).fetchone()
        assert row['delivery_state']=='PENDING' and row['attempted_at'] is None


def test_deadline_shortened_after_planning_is_not_sent(early_db):
    acquired=candidates(early_db)
    first=plan_early_notices(early_db,candidates=acquired)
    with early_db.transaction() as c:
        now=c.execute('select now() as at').fetchone()['at']
        version=c.execute('select normalized from startup_radar.program_versions where id=%s',(acquired[0]['version_id'],)).fetchone()
        source=c.execute("select id from startup_radar.sources where slug='early-fixture-api'").fetchone()
        c.execute("update startup_radar.runtime_settings set value=%s where key='weekly_telegram_channel'",
            (Jsonb({'enabled':True,'chat_id':'synthetic-fixture-only','name':'GFC StartupRadar'}),))
    changed=Program.model_validate(version['normalized'])
    changed.application_end_at=now+timedelta(days=6)
    early_db.save_program(changed,source['id'],'0',changed.official_url,{},'Verified deadline shortened',
                          extraction_metadata={'provider':'structured_api_weekly','status':'SUCCESS'})
    transport=Mock()
    assert announce_early(early_db,first['notice_id'],transport)['state']=='EXPIRED'
    transport.send.assert_not_called()
    with early_db.transaction() as c:
        row=c.execute('select delivery_state,failure_reason,attempted_at from startup_radar.early_notices where id=%s',(first['notice_id'],)).fetchone()
        assert row['delivery_state']=='EXPIRED' and row['failure_reason']=='SOURCE_CHANGED_OR_UNVERIFIED'
        assert row['attempted_at'] is None
