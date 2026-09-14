"""Replay just-fetched public samples through an isolated local DB and weekly job.

This avoids fetching institutions again. It is not a production collection run.
Requires explicit loopback radar_test with its disposable marker; never loads .env.
"""
import argparse,json,os
from pathlib import Path
from uuid import uuid4
from radar.database import Database
from radar.institutions import seed_institutions
from radar.ingestion import ingest
from radar.discovery import run_discovery
from radar.weekly import run_weekly
from radar.adapters.base import Candidate,AcquiredDetail,SourceFailure
from radar.adapters.opportunities import OfficialChannelAdapter,ChannelCoverage

def main():
    parser=argparse.ArgumentParser();parser.add_argument('samples',nargs='+');parser.add_argument('--output',default='work/expansion-pipeline.json');args=parser.parse_args()
    samples={}
    for file in args.samples:
        data=json.loads(Path(file).read_text(encoding='utf8'))
        if data['scope']!='BOUNDED_PUBLIC_SOURCE_SAMPLE':raise ValueError('Expected public read-check output')
        for row in data['results']:samples[row['channel']]=row
    db=Database(os.environ['TEST_DATABASE_URL'])
    with db.transaction() as c:
        if c.info.host not in ('127.0.0.1','localhost','::1') or c.info.dbname!='radar_test':raise ValueError('Only loopback radar_test is permitted')
        if c.execute('select value from public.radar_test_marker').fetchone()['value']!='ephemeral-test-only':raise ValueError('Disposable marker required')
        c.execute('truncate auth.users,startup_radar.sources,startup_radar.programs,startup_radar.ingestion_runs,startup_radar.worker_executions,startup_radar.institutions cascade')
    seed_institutions(db)
    with db.transaction() as c:c.execute('update startup_radar.sources set enabled=true where slug=any(%s)',(list(samples),))
    class Replay:
        def __init__(self,source):
            self.row=samples[source['slug']];self.source=source;self.pagination=ChannelCoverage(source['config'])
            self.normalizer=OfficialChannelAdapter(source,None)
        def discover(self):
            self.pagination.pages=self.row['coverage']['pages_requested'];self.pagination.discovered=len(self.row['records'])
            self.pagination.complete=not self.row['failures']
            for record in self.row['records']:yield Candidate(**record['candidate'])
            if self.row['failures']:raise SourceFailure('SAMPLE_PARTIAL','The live sample contained an unreadable notice; retained successful records')
        def fetch_detail(self,candidate):
            return AcquiredDetail(**next(x['detail'] for x in self.row['records'] if x['candidate']['source_program_id']==candidate.source_program_id))
        def normalize(self,*args):return self.normalizer.normalize(*args)
    result=run_discovery(db,collector=lambda db,sources,**kwargs:ingest(db,sources,adapter_factory=Replay,**kwargs))
    with db.transaction() as c:
        user=uuid4();c.execute('insert into auth.users(id) values(%s)',(user,));c.execute("insert into public.test_gfc_roles values(%s,'member')",(user,))
        stored=c.execute("select o.program_id,o.confirmed,o.review_reasons,o.facts,startup_radar.opportunity_status(o.facts) status from startup_radar.opportunity_records o order by o.facts->>'title'").fetchall()
    with db.transaction(user) as c:
        feed=c.execute('select public.gfc_opportunities() value').fetchone()['value']
        details=[c.execute('select public.gfc_opportunity(%s) value',(r['id'],)).fetchone()['value'] for r in feed['items'][:3]]
    first=run_weekly(db,from_catalog=True);second=run_weekly(db,from_catalog=True)
    with db.transaction() as c:messages=c.execute('select count(*) n from startup_radar.weekly_announcements').fetchone()['n']
    report={'scope':'LOCAL_DB_REPLAY_OF_REAL_PUBLIC_READS','collection':result,'records':stored,'member_total':feed['total'],'member_details_verified':len([d for d in details if d]),'first_weekly':first,'repeat_weekly':second,'telegram_rows':messages}
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,default=str,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('records','collection')},ensure_ascii=False,default=str))

if __name__=='__main__':main()
