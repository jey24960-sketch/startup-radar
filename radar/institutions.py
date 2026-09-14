"""Reviewed catalogue installation. Existing operator settings always win."""
import json
from pathlib import Path
from psycopg.types.json import Jsonb


def seed_institutions(db,path='institutions.json'):
    catalogue=json.loads(Path(path).read_text(encoding='utf-8'))
    added=channels=0
    with db.transaction() as c:
        for org in catalogue['institutions']:
            row=c.execute('insert into startup_radar.institutions(slug,name,kind,homepage,approved_hosts,policy_status,policy_note,checked_at) values(%s,%s,%s,%s,%s,%s,%s,%s) on conflict(slug) do nothing returning id',
                (org['slug'],org['name'],org['kind'],org['homepage'],org.get('approved_hosts',[]),org.get('policy_status','REVIEW_REQUIRED'),org['note'],catalogue['checked_at'])).fetchone()
            added+=bool(row)
            institution=c.execute('select * from startup_radar.institutions where slug=%s',(org['slug'],)).fetchone()
            for channel in org.get('channels',[]):
                config={**channel['config'],'opportunity_channel':True,'organization':org['name'],'organization_type':org['kind'],
                    'allowed_hosts':institution['approved_hosts'],'policy_status':institution['policy_status']}
                row=c.execute("insert into startup_radar.sources(slug,name,adapter,config,enabled) values(%s,%s,'HTML',%s,false) on conflict(slug) do nothing returning id",
                    (channel['slug'],channel['name'],Jsonb(config))).fetchone()
                if row:
                    channels+=1
                    c.execute('insert into startup_radar.source_channels(source_id,institution_id,last_reason) values(%s,%s,%s)',(row['id'],institution['id'],channel.get('reason','AWAITING_FIRST_LOCAL_OR_DEPLOYED_RUN')))
    return {'status':'SUCCESS','institutions_added':added,'channels_added':channels,'new_channels_enabled':False}
