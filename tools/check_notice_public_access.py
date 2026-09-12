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
    report={'anonymous_notice_http':notices.status_code,'anonymous_notice_rows':len(notices.json()) if notices.ok else None,
            'anonymous_radar_http':radar.status_code,'anonymous_radar_denied':not radar.ok,
            'real_member_jwt_browser_test':'NOT_RUN: dedicated test login unavailable'}
    assert notices.ok and not radar.ok, report
    Path('docs/GFC-NOTICE-PUBLIC-REST.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
