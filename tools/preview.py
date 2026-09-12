"""Loopback-only fixture demo. Never use as a production entry point."""
import os
from uuid import uuid4
from datetime import timedelta
import uvicorn
from fastapi.responses import JSONResponse
from radar.database import Database
from radar.models import Program,TeamProfile,Requirement,Evidence,apply_preset
from radar.web import create_app
from radar.auth import authenticated_user
from radar.recommendations import refresh_recommendations
from core.clock import now


def main():
    db=Database(os.environ['TEST_DATABASE_URL'])
    with db.transaction() as c:
        marker=c.execute('select value from public.radar_test_marker').fetchone()
        if not marker or marker['value']!='ephemeral-test-only':raise ValueError('Preview requires the ephemeral test database')
        c.execute('truncate auth.users,radar.teams,radar.sources,radar.programs,radar.ingestion_runs,radar.notification_runs cascade')
        owner=uuid4();c.execute('insert into auth.users values(%s)',(owner,));c.execute('insert into radar.admin_users values(%s)',(owner,))
    team=db.create_team('GFC · 아이디어 팀',owner,apply_preset(TeamProfile(),0))
    db.create_team('GFC · 법인 팀',owner,TeamProfile(business_status='CORPORATION',product_stage='MVP'))
    source=db.upsert_source('preview-only','로컬 검증용 소스','HTML',{})
    def rule(key,operator,value,quote):return Requirement(key=key,operator=operator,value=value,certain=True,
        evidence=[Evidence(source_id=str(source['id']),text=quote,method='MANUAL',location='신청 자격 (테스트)',confidence=1,verified=True)])
    notices=[('아이디어를 검증하는 예비창업 캠프',14,True,[rule('business_status','EQ','PRE_BUSINESS','예비창업자만 신청할 수 있습니다.')]),
             ('서울 청년 창업 아이디어 경진대회',7,True,[rule('founder_age','LTE',39,'대표자 만 39세 이하'),rule('region','EQ','서울','서울 소재 예비창업자')]),
             ('법인 전용 글로벌 시장 진출 지원',21,True,[rule('business_status','EQ','CORPORATION','법인사업자만 신청할 수 있습니다.')]),
             ('첨부문서 확인이 필요한 보육 프로그램',10,False,[]),
             ('지난달 마감된 테스트 창업학교',-3,True,[])]
    for index,(title,days,complete,rules) in enumerate(notices):
        p=Program(title='[테스트] '+title,organization='검증용 가상 기관',official_url=f'https://example.org/fixture/{index}',
            program_types=['GLOBAL' if index==2 else 'EDUCATION'],application_end_at=now()+timedelta(days=days),deadline_type='FIXED_DATE',
            benefit_summary='테스트 데이터: 전문가 멘토링과 실험 설계 워크숍',support_summary='화면과 판정 엔진 검증을 위한 가상 공고입니다. 실제 지원사업이 아닙니다.',
            evidence_complete=complete,requirements=rules,product_stages=['IDEA','LANDING'])
        docs=[{'original_url':'https://example.org/fixture/broken.hwp','filename':'테스트 공고문.hwp','fetch_status':'SUCCESS','extraction_status':'FAILED','error_kind':'DOCUMENT_PARSE','error_message':'테스트: 손상된 문서'}] if index==3 else []
        db.save_program(p,source['id'],str(index),p.official_url,{'fixture':True},'Explicit fixture evidence',docs)
    refresh_recommendations(db)
    app=create_app(db,preview=True);app.dependency_overrides[authenticated_user]=lambda:owner
    @app.middleware('http')
    async def no_external_actions(request,call_next):
        if request.url.path in ('/api/admin/jobs','/telegram/webhook'):
            return JSONResponse({'detail':'로컬 검증 화면에서는 외부 작업 실행·발송을 하지 않습니다.'},status_code=403)
        return await call_next(request)
    uvicorn.run(app,host='127.0.0.1',port=8765)


if __name__=='__main__':main()
