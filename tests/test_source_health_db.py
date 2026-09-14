from test_database import db
from test_official_pagination import adapter,page
from radar.adapters.base import AcquiredDetail
from radar.models import Program
from radar.ingestion import ingest


def test_partial_scan_persists_coverage_and_does_not_advance_full_scan(db,monkeypatch):
    source=db.upsert_source('coverage-fixture','Coverage','KSTARTUP',{})
    def run(cap):
        instance,_=adapter('kstartup',[page('kstartup',[1,2],3),page('kstartup',[3],3)],monkeypatch,max_pages=cap)
        instance.fetch_detail=lambda row:AcquiredDetail(row.official_detail_url,'Official body',row.title)
        instance.fetch_documents=lambda detail:[]
        instance.normalize=lambda row,detail,docs:Program(title=row.title,organization='Fixture',official_url=detail.url)
        class Extractor:
            def extract(self,program,*args):return program
        return ingest(db,[source],adapter_factory=lambda source:instance,extractor=Extractor())
    partial=run(1)
    assert partial['status']=='PARTIAL_SUCCESS'
    with db.transaction() as c:
        health=c.execute('select * from startup_radar.sources where id=%s',(source['id'],)).fetchone()
        report=c.execute('select coverage from startup_radar.source_run_results where run_id=%s',(partial['id'],)).fetchone()['coverage']
    assert health['last_successful_full_scan_at'] is None
    assert health['last_persisted_at'] and health['last_source_observation_at']
    assert health['last_failure_reason']=='PAGE_LIMIT'
    assert report['persisted_records']==2 and report['advertised_records']==3 and not report['pagination_complete']
    full=run(3)
    assert full['status']=='SUCCESS'
    with db.transaction() as c:
        health=c.execute('select * from startup_radar.sources where id=%s',(source['id'],)).fetchone()
        report=c.execute('select coverage from startup_radar.source_run_results where run_id=%s',(full['id'],)).fetchone()['coverage']
    assert health['last_successful_full_scan_at'] and report['pagination_complete']
    assert report['persisted_records']==report['unique_source_ids']==3 and report['failed_records']==0
    assert health['last_failure_reason']=='PAGE_LIMIT'  # Recovery must retain failure history.
