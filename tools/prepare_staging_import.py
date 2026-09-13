"""Prepare a reviewable SQL import of the bounded acquisition check.

This does not execute SQL. Only an empty staging catalog is accepted by the
generated transaction. Normal ingestion continues to use radar.database.
"""
import json
from pathlib import Path
from psycopg.sql import Literal
from radar.models import Program
from radar.identity import digest


def main():
    report=json.loads(Path('work/live-shared-source-check.json').read_text(encoding='utf-8'))
    assert len(report['sources'])==3
    assert {r['slug']:r['status'] for r in report['sources']}=={
        'kstartup':'FAILED','bizinfo':'FAILED','korea-startup-html':'ACQUIRED_WITHOUT_AI'}
    assert all(r.get('error_kind')=='MISSING_CREDENTIAL' for r in report['sources'] if r['status']=='FAILED')
    for row in report['sources']:
        if row['status']=='ACQUIRED_WITHOUT_AI':
            p=Program.model_validate(row['program'])
            assert not p.evidence_complete and not p.requirements
            assert p.application_end_at is None
            row['content_hash']=digest({'normalized':p.model_dump(mode='json'),'raw':row['detail_text']})
            row['detail_hash']=digest(row['detail_text'])
            row['observation_hash']=digest({'candidate':row['candidate'],'checked_at':report['checked_at']})
    payload=Literal(json.dumps(report,ensure_ascii=False)).as_string()
    template=Path('tools/sql/import_bounded_acquisition.sql.in').read_text(encoding='utf-8')
    Path('work/import-bounded-acquisition.sql').write_text(template.replace('__REVIEWED_JSON_PAYLOAD__',payload),encoding='utf-8')
    print('Prepared work/import-bounded-acquisition.sql; no SQL executed')


if __name__=='__main__':main()
