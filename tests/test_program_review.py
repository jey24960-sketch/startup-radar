import copy
import os
from types import SimpleNamespace
import pytest
from radar.models import Program,Evidence,Requirement
from radar.adapters.base import AcquiredDetail
from radar.program_review import evidence_input_hash,validate_decision,apply_review,resolve_review,revoke_review,source_packet
from test_database import db,source


def case(source_id='source'):
    detail=AcquiredDetail('https://example.org/notice','Attendance is required','Fixture')
    docs=[{'original_url':'https://example.org/image.png','filename':'image.png','content_hash':'a'*64,'fetch_status':'SUCCESS','extraction_status':'FAILED'},
          {'original_url':'https://example.org/text.txt','filename':'text.txt','content_hash':'b'*64,'fetch_status':'SUCCESS','extraction_status':'SUCCESS','extracted_text':'Attendance is required'}]
    program=Program(title='Fixture',organization='Fixture',official_url=detail.url,document_hashes=['a'*64,'b'*64],evidence_complete=True,
        requirements=[Requirement(key='program_response',response_id='attend',question='Can your team attend?',operator='EQ',value=True,certain=True,
            evidence=[Evidence(document_id='b'*64,text='Attendance is required',method='MANUAL',confidence=1,verified=True)])])
    decision={'primary_input_hash':evidence_input_hash(source_id,detail,docs,{}),'reviewed_program':program.model_dump(mode='json'),
        'coverage':[{'original_url':docs[0]['original_url'],'original_hash':'a'*64,'text_document_hash':'b'*64,'page_count':1,
          'pages':[{'page':1,'text_quote':'Attendance is required','review_note':'Compared the entire fixture image'}],
          'exclusions':'Decorative marks only; no eligibility or material terms omitted'}],
        'reviewer_kind':'AGENT_VISUAL_REVIEW','reviewer_label':'Synthetic test reviewer','rationale':'Fixture review compared all conditions and every document page.'}
    return detail,docs,decision


def test_complete_review_keeps_failed_parser_status_and_requires_answer():
    from radar.eligibility import evaluate
    from radar.models import TeamProfile
    detail,docs,decision=case()
    reviewed,kept=validate_decision(decision,'source',detail,docs,{})
    assert kept[0]['extraction_status']=='FAILED' and reviewed.document_coverage
    assert evaluate(TeamProfile(),reviewed.requirements,reviewed.evidence_complete).status=='NEEDS_INFO'
    assert evaluate(TeamProfile(),reviewed.requirements,reviewed.evidence_complete,program_responses={'attend':True}).status=='ELIGIBLE'


@pytest.mark.parametrize('mutation',['source','attachment','missing_page','quote','unread','reviewer','circular'])
def test_review_rejects_changed_or_unaccounted_evidence(mutation):
    detail,docs,decision=case()
    if mutation=='source':detail.text+=' A new restriction'
    if mutation=='attachment':docs[0]['content_hash']='c'*64
    if mutation=='missing_page':decision['coverage'][0]['page_count']=2
    if mutation=='quote':decision['reviewed_program']['requirements'][0]['evidence'][0]['text']='Invented permission'
    if mutation=='unread':decision['coverage']=[]
    if mutation=='reviewer':decision['reviewer_kind']='AUTOMATIC_CONFIDENCE'
    if mutation=='circular':decision['coverage'][0]['text_document_hash']='a'*64
    with pytest.raises(ValueError):validate_decision(decision,'source',detail,docs,{})


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')
def test_review_registry_reuse_drift_and_withdrawal(db):
    source_id=source(db);detail,docs,decision=case(str(source_id))
    original=Program.model_validate(decision['reviewed_program']);original.evidence_complete=False;original.requirements=[]
    saved=db.save_program(original,source_id,'review-case',detail.url,{},detail.text,docs)
    applied=apply_review(db,saved['program_id'],saved['version_id'],decision)
    assert applied['status']=='SUCCESS' and applied['version_id']!=str(saved['version_id'])
    reused=resolve_review(db,source_id,original,detail,docs,{})
    assert reused[0].evidence_complete and reused[2]['provider']=='source_review'
    changed=AcquiredDetail(detail.url,detail.text+' changed',detail.title)
    assert resolve_review(db,source_id,original,changed,docs,{}) is None
    revoked=revoke_review(db,applied['review_id'],applied['version_id'],'Fixture decision withdrawn')
    assert revoked['status']=='SUCCESS'
    assert resolve_review(db,source_id,original,detail,docs,{}) is None
    version,_,preserved=source_packet(db,saved['program_id'])
    assert not version['normalized']['evidence_complete'] and len(preserved)==2
    assert all(not r['certain'] for r in version['normalized']['requirements'])


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')
def test_registry_failure_rolls_back_reviewed_version(db,monkeypatch):
    from contextlib import contextmanager
    source_id=source(db);detail,docs,decision=case(str(source_id))
    program=Program.model_validate(decision['reviewed_program']);program.evidence_complete=False
    saved=db.save_program(program,source_id,'atomic-review',detail.url,{},detail.text,docs)
    transaction=db.transaction
    class FailingConnection:
        def __init__(self,c):self.connection=c
        def execute(self,sql,params=None):
            if sql.startswith('insert into startup_radar.program_reviews'):raise RuntimeError('Fixture registry failure')
            return self.connection.execute(sql,params)
    @contextmanager
    def wrapped(*args,**kwargs):
        with transaction(*args,**kwargs) as c:yield FailingConnection(c)
    monkeypatch.setattr(db,'transaction',wrapped)
    assert apply_review(db,saved['program_id'],saved['version_id'],decision)['status']=='FAILED'
    with transaction() as c:
        assert c.execute('select current_version_id from startup_radar.programs where id=%s',(saved['program_id'],)).fetchone()['current_version_id']==saved['version_id']
        assert c.execute('select count(*) n from startup_radar.program_reviews').fetchone()['n']==0
