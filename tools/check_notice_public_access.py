"""Read-only anonymous REST verification. Prints statuses, never credentials."""
import json
from pathlib import Path
import requests

def main():
    env={}
    for line in Path('.env.staging').read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.startswith('#'):
            key,value=line.split('=',1);env[key]=value.strip().strip('"').strip("'")
    base=env['SUPABASE_URL'];headers={'apikey':env['SUPABASE_PUBLISHABLE_KEY']}
    notices=requests.get(base+'/rest/v1/gfc_notices',params={'select':'id,title,visibility','limit':1},headers=headers,timeout=20)
    radar=requests.get(base+'/rest/v1/programs',params={'select':'id,title','limit':1},headers={**headers,'Accept-Profile':'startup_radar'},timeout=20)
    context=requests.post(base+'/rest/v1/rpc/gfc_radar_me',json={},headers=headers,timeout=20)
    programs=requests.post(base+'/rest/v1/rpc/gfc_radar_programs',json={},headers=headers,timeout=20)
    detail=requests.post(base+'/rest/v1/rpc/gfc_radar_program_detail',json={'p_program_id':'00000000-0000-0000-0000-000000000000'},headers=headers,timeout=20)
    create=requests.post(base+'/rest/v1/rpc/gfc_radar_create_team',json={'p_name':'Anonymous rejection probe','p_preset':0,'p_request_id':'00000000-0000-0000-0000-000000000000'},headers=headers,timeout=20)
    update=requests.post(base+'/rest/v1/rpc/gfc_radar_update_profile',json={'p_team_id':'00000000-0000-0000-0000-000000000000','p_expected_version':1},headers=headers,timeout=20)
    settings_checks={}
    for name,payload in [('gfc_radar_preferences',{'p_team_id':'00000000-0000-0000-0000-000000000000'}),
                         ('gfc_radar_save_preferences',{'p_team_id':'00000000-0000-0000-0000-000000000000','p_preferences':{'enabled':False,'digest_enabled':False,'alerts_enabled':False,'reminders_enabled':False}}),
                         ('gfc_radar_health',{})]:
        response=requests.post(base+'/rest/v1/rpc/'+name,json=payload,headers=headers,timeout=20)
        settings_checks[name]=response.status_code
    report={'anonymous_notice_http':notices.status_code,'anonymous_notice_rows':len(notices.json()) if notices.ok else None,
            'anonymous_radar_http':radar.status_code,'anonymous_radar_denied':not radar.ok,
            'anonymous_radar_context_http':context.status_code,'anonymous_radar_context_denied':not context.ok,
            'anonymous_radar_programs_http':programs.status_code,'anonymous_radar_programs_denied':not programs.ok,
            'anonymous_radar_detail_http':detail.status_code,'anonymous_radar_detail_denied':not detail.ok,
            'anonymous_radar_create_http':create.status_code,'anonymous_radar_create_denied':not create.ok,
            'anonymous_radar_update_http':update.status_code,'anonymous_radar_update_denied':not update.ok,
            'anonymous_settings_rpc_http':settings_checks,
            'real_member_jwt_browser_test':'NOT_RUN: dedicated test login unavailable'}
    assert notices.ok and not radar.ok and all(r.status_code in (401,403) for r in (context,programs,detail,create,update)), report
    assert all(status in (401,403) for status in settings_checks.values()),report
    Path('docs/GFC-NOTICE-PUBLIC-REST.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
