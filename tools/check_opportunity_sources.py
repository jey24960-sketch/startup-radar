"""Bounded real-source check in an explicitly marked, disposable local database.

No credentials are read from .env.worker; no Telegram transport is constructed.
Run only after the database regression suite, since this resets local fixtures.
"""
import argparse,json,os
from pathlib import Path
from uuid import uuid4
from radar.database import Database
from radar.institutions import seed_institutions
from radar.discovery import run_discovery
from radar.weekly import run_weekly
from psycopg.types.json import Jsonb


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='work/opportunity-source-check.json');args=parser.parse_args()
    db=Database(os.environ['TEST_DATABASE_URL'])
    with db.transaction() as c:
        if c.info.host not in ('127.0.0.1','localhost','::1') or c.info.dbname!='radar_test':raise ValueError('Loopback radar_test required')
        if c.execute('select value from public.radar_test_marker').fetchone()['value']!='ephemeral-test-only':raise ValueError('Disposable test marker required')
        c.execute('truncate auth.users,startup_radar.sources,startup_radar.programs,startup_radar.ingestion_runs,startup_radar.worker_executions,startup_radar.institutions cascade')
    seed_institutions(db)
    with db.transaction() as c:
        # Intentionally small, explicit samples of the three listing channels.
        for slug,selector in [('snu-home','a[href*="bo_table=sub4_1"][href*="wr_id=129"]'),('kaist-home','a[href*="/boards/view/board_event/2191"]'),('asan-notices','a[href*="/notice/2026-anf-maru-open-h2/"]')]:
            c.execute("update startup_radar.sources set config=config||%s where slug=%s",(Jsonb({'link_selector':selector,'max_records':2,'sample_only':True}),slug))
        c.execute("update startup_radar.sources set enabled=true where config->>'policy_status'='APPROVED' and config->>'method'<>'REQUEST'")
    result=run_discovery(db)
    with db.transaction() as c:
        records=c.execute('select program_id id,facts,confirmed,review_reasons,last_verified_at,startup_radar.opportunity_status(facts) status from startup_radar.opportunity_records order by facts->>\'title\'').fetchall()
        sources=c.execute('select s.slug,s.name,r.status,r.parsed_count,r.failures,r.coverage from startup_radar.source_run_results r join startup_radar.sources s on s.id=r.source_id where r.run_id=%s order by s.slug',(result.get('id'),)).fetchall()
        user=uuid4();c.execute('insert into auth.users values(%s)',(user,));c.execute("insert into public.test_gfc_roles values(%s,'member')",(user,))
    with db.transaction(user) as c:
        feed=c.execute('select public.gfc_opportunities() value').fetchone()['value']
        detail=c.execute('select public.gfc_opportunity(%s) value',(feed['items'][0]['id'],)).fetchone()['value'] if feed['items'] else None
    weekly=run_weekly(db,from_catalog=True)
    with db.transaction() as c:messages=c.execute('select count(*) n from startup_radar.weekly_announcements').fetchone()['n']
    report={'scope':'LOCAL_PUBLIC_SOURCE_SAMPLE_NOT_NATIONWIDE','status':result['status'],'sources':sources,'records':records,
        'member_count':feed['total'],'member_detail_verified':bool(detail),'weekly':weekly,'telegram_announcement_rows':messages,
        'expected_recruitment_sample':9,'scope_note':'SNU 129; KAIST 2191; MARU 2026 H2; D2SF 5 distinct cards; Antler individual residency. SparkLabs introduction is an additional negative control. No API credentials or production database used.'}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True);Path(args.output).write_text(json.dumps(report,ensure_ascii=False,default=str,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':result['status'],'stored':len(records),'confirmed':feed['total'],'weekly':weekly,'telegram_rows':messages,'report':args.output},ensure_ascii=False,default=str))


if __name__=='__main__':main()
