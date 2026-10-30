import os

import psycopg
import pytest
from psycopg.types.json import Jsonb

from test_database import db, source, program

pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Explicit test database required')


def test_weekly_selection_applies_reviews_and_does_not_republish_parser_only_edits(db):
    from datetime import timedelta
    from radar.models import Program
    from radar.weekly import build_briefing, snapshot
    from test_weekly import collection, AT

    collected = collection(db, 4)
    original = collected['weekly_programs'][0]
    with db.transaction() as c:
        version = c.execute('select normalized,raw_text from startup_radar.program_versions where id=%s', (original['version_id'],)).fetchone()
        provenance = c.execute('select source_id,source_program_id,discovery_url from startup_radar.program_sources where program_id=%s', (original['program_id'],)).fetchone()
        for index, disposition in enumerate(('RETAIN', 'DUPLICATE', 'EXCLUDE', 'HOLD')):
            row = collected['weekly_programs'][index]
            c.execute("insert into startup_radar.publication_reviews(program_id,reviewed_version_id,disposition,representative_program_id,snapshot_patch,relevance_status,restriction_summary,reason,evidence) values(%s,%s,%s,%s,%s,%s,%s,'공식 원문 검토에 따른 게시 결정','{}')",
                      (row['program_id'],row['version_id'],disposition,
                       original['program_id'] if disposition=='DUPLICATE' else None,
                       Jsonb({'support_summary':'검토한 시제품 제작비 지원'} if index==0 else {}),
                       'CONDITIONAL' if index==0 else None,'서울 소재' if index==0 else None))
    first = build_briefing(db, collected, AT)
    assert first['item_count'] == 1
    assert first['withheld']['REVIEWED_HOLD'] == first['withheld']['REVIEWED_EXCLUDE'] == first['withheld']['REVIEWED_DUPLICATE'] == 1
    parsed = Program.model_validate(version['normalized']).model_copy(update={'support_summary':'파서가 새로 추출한 같은 원문의 지원내용'})
    saved = db.save_program(parsed, provenance['source_id'], provenance['source_program_id'], provenance['discovery_url'], {}, version['raw_text'])
    assert saved['version_id'] != original['version_id']
    collected['weekly_programs'][0] = {**saved,'snapshot':snapshot(parsed,{})}
    second = build_briefing(db, collected, AT+timedelta(days=7))
    assert second['item_count'] == 0
    with db.transaction() as c:
        assert c.execute('select normalized from startup_radar.program_versions where id=%s',(original['version_id'],)).fetchone()['normalized'] == version['normalized']
        item = c.execute('select snapshot,relevance_status from startup_radar.weekly_briefing_items where briefing_id=%s',(first['briefing_id'],)).fetchone()
        assert item['snapshot']['support_summary'] == '검토한 시제품 제작비 지원'
        assert item['relevance_status'] == 'CONDITIONAL'


def test_private_reviews_are_audited_and_bound_to_source_version(db):
    p = program()
    row = db.save_program(p, source(db), 'reviewed', p.official_url, {}, 'immutable original')
    with db.transaction() as c:
        c.execute("insert into startup_radar.publication_reviews(program_id,reviewed_version_id,disposition,reason,evidence) values(%s,%s,'HOLD','공식 신청기한 상충으로 보류','{}')",
                  (row['program_id'], row['version_id']))
        assert c.execute("select count(*) n from startup_radar.admin_audit where action='PUBLICATION_REVIEW_INSERT'").fetchone()['n'] == 1
        c.execute("update startup_radar.publication_reviews set active=false where program_id=%s", (row['program_id'],))
        audit = c.execute("select detail from startup_radar.admin_audit where action='PUBLICATION_REVIEW_UPDATE'").fetchone()['detail']
        assert audit['before']['active'] is True and audit['after']['active'] is False
        with pytest.raises(psycopg.Error, match='permission'):
            with c.transaction():
                c.execute('set local role authenticated')
                c.execute('select * from startup_radar.publication_reviews')
        with pytest.raises(psycopg.Error):
            with c.transaction():
                c.execute("update startup_radar.publication_reviews set snapshot_patch=%s", (Jsonb({'application_end_at': '2099-01-01'}),))
    other = db.save_program(program(), source(db), 'other', 'https://example.org/other', {}, 'other')
    with db.transaction() as c:
        with pytest.raises(psycopg.Error, match='must belong'):
            with c.transaction():
                c.execute('update startup_radar.publication_reviews set reviewed_version_id=%s where program_id=%s',
                          (other['version_id'], row['program_id']))


@pytest.mark.skipif(not os.environ.get('TEST_NATIVE_POSTGRES'), reason='Native PostgreSQL savepoint protocol; embedded DB guard covered by Node suite')
def test_reviewed_plain_description_repair_requires_exact_same_transaction_authorization(db):
    p = program()
    row = db.save_program(p, source(db), 'description', p.official_url, {}, 'immutable original')
    with db.transaction() as c:
        clock = c.execute("select now()-interval '14 days' published_at, now()-interval '1 day' deadline").fetchone()
        run = c.execute("insert into startup_radar.ingestion_runs(status,trigger_type) values('SUCCESS','test') returning id").fetchone()['id']
        bid = c.execute("insert into startup_radar.weekly_briefings(week_start,week_end,title,summary,status,collection_status,ingestion_run_id) values('2026-10-26','2026-11-01','review','review','DRAFT','SUCCESS',%s) returning id", (run,)).fetchone()['id']
        before = {'title': '공식 제목', 'support_summary': '등록일 조회수 등 전체 페이지',
                  'applicant_summary': '중소기업', 'organization': '감독부처',
                  'application_end_at': clock['deadline'].isoformat()}
        after = {**before, 'support_summary': '시제품 제작비 최대 500만원',
                 'applicant_summary': '청주 소재 7년 미만 기업', 'organization': '수행기관'}
        c.execute("insert into startup_radar.weekly_briefing_items(briefing_id,program_id,program_version_id,change_type,display_order,snapshot,material_hash,relevance_status) values(%s,%s,%s,'NEW',0,%s,'m','GFC_RELEVANT')", (bid,row['program_id'],row['version_id'],Jsonb(before)))
        c.execute("update startup_radar.runtime_settings set value=jsonb_set(value,'{enabled}','true') where key='notice_policy'")
        c.execute("update startup_radar.weekly_briefings set status='PUBLISHED',published_at=%s where id=%s", (clock['published_at'],bid))

        def change(facts):
            c.execute('update startup_radar.weekly_briefing_items set snapshot=%s where briefing_id=%s', (Jsonb(facts),bid))

        with pytest.raises(psycopg.Error, match='seven days'):
            with c.transaction():
                change(after)
        c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('WEEKLY_EDITORIAL_REPAIR_AUTHORIZATION',%s,jsonb_build_object('actor','PRIVILEGED_PUBLICATION_OPERATOR','reason','공식 원문 대조에 따른 표시 정정','transaction_id',txid_current(),'patches',%s::jsonb))",
                  (str(bid), Jsonb([{'program_id': str(row['program_id']), 'program_version_id': str(row['version_id']), 'before_snapshot':before, 'after_snapshot':after}])))
        for forbidden in ({**after, 'title':'다른 사업'}, {**after, 'application_end_at':before['application_end_at']+'x'}, {**after,'support_summary':'다른 지원금'}):
            with pytest.raises(psycopg.Error, match='seven days'):
                with c.transaction():
                    change(forbidden)
        change(after)
        actual = c.execute('select snapshot from startup_radar.weekly_briefing_items where briefing_id=%s', (bid,)).fetchone()['snapshot']
        assert actual == after
        assert c.execute('select raw_text from startup_radar.program_versions where id=%s', (row['version_id'],)).fetchone()['raw_text'] == 'immutable original'
        assert c.execute('select published_at from startup_radar.weekly_briefings where id=%s', (bid,)).fetchone()['published_at'] == clock['published_at']
