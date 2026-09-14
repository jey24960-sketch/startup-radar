from datetime import timedelta
from core.clock import now
from radar.quality import assess,refresh_quality,quality_report,REASONS
from test_database import db,source,program


def test_non_actionable_programs_always_have_structured_reasons():
    p=program();p.application_end_at=None;p.deadline_type='UNKNOWN'
    result=assess(p,[],{'error_kind':'AI_DATE_TIME_REQUIRED'},None)
    assert result['state']=='UNVERIFIABLE'
    assert set(result['reasons'])<=(REASONS)
    assert {'MISSING_DEADLINE_EVIDENCE','MISSING_ELIGIBILITY_EVIDENCE','MISSING_APPLICATION_URL','STALE_SOURCE','AI_DATE_PRECISION_FAILED'}<=set(result['reasons'])
    p.application_url=p.official_url;p.deadline_type='ROLLING';p.evidence_complete=True
    result=assess(p,[],{},now(),raw_text='Open authoritative evidence')
    assert result['state']=='ACTIONABLE' and result['reasons']==[]


def test_ocr_draft_is_visible_but_not_actionable_evidence():
    p=program();p.application_url=p.official_url
    doc={'content_hash':'scan','fetch_status':'SUCCESS','extraction_status':'FAILED','error_kind':'DOCUMENT_OCR_REQUIRED'}
    metadata={'document_ocr_reviews':[{'content_hash':'scan','draft':{'review_required':True}}]}
    result=assess(p,[doc],metadata,now(),raw_text='Official partial body')
    assert result['state']=='NEEDS_REVIEW' and 'OCR_REQUIRED' in result['reasons']
    assert result['metrics']['ocr_success']==result['metrics']['document_failures']==1
    assert result['metrics']['text_extraction_success']==0 and not p.evidence_complete


def test_changed_document_result_has_a_new_version_and_current_counts_exclude_history(db):
    p=program();sid=source(db);doc={'original_url':p.official_url+'/doc','filename':'doc.txt','content_hash':'same-original',
        'fetch_status':'SUCCESS','extraction_status':'FAILED','error_kind':'DOCUMENT_PARSE'}
    first=db.save_program(p,sid,'same',p.official_url,{},'Same source',[doc])
    doc.update(extraction_status='SUCCESS',error_kind=None,extracted_text='Verified parser text')
    second=db.save_program(p,sid,'same',p.official_url,{},'Same source',[doc])
    assert first['version_id']!=second['version_id']
    refresh_quality(db);report=quality_report(db)
    assert report['total']==report['current_documents']['documents']==1
    assert report['current_documents']['document_failures']==0 and report['current_documents']['text_extraction_success']==1
    with db.transaction() as c:
        assert c.execute("select count(*) n from startup_radar.documents where extraction_status='FAILED'").fetchone()['n']==1
        assert c.execute('select count(*) n from startup_radar.program_quality').fetchone()['n']==2


def test_review_queue_prioritizes_current_deadlines_and_reports_source_denominators(db):
    sid=source(db)
    for name,left in [('old',-5),('d7',7),('d3',3)]:
        p=program();p.title=name;p.application_end_at=now()+timedelta(days=left)
        db.save_program(p,sid,name,p.official_url,{},'Partial official evidence')
    report=quality_report(db)
    assert [r['title'] for r in report['review_queue']]==['d3','d7','old']
    assert report['review_backlog']=={'d7':2,'d3':1}
    assert report['counts']['NEEDS_REVIEW']==3 and report['open_upcoming']['NEEDS_REVIEW']==2
    assert next(iter(report['sources'].values()))['total']==3
