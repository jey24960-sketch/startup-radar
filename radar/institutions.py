"""Reviewed catalogue installation. Existing operator settings always win."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from psycopg.types.json import Jsonb


def seed_institutions(db,path='institutions.json',update_reviewed=False):
    catalogue=json.loads(Path(path).read_text(encoding='utf-8'))
    added=channels=0;updated=[];conflicts=[]
    with db.transaction() as c:
        for org in catalogue['institutions']:
            row=c.execute('insert into startup_radar.institutions(slug,name,kind,homepage,approved_hosts,policy_status,policy_note,checked_at) values(%s,%s,%s,%s,%s,%s,%s,%s) on conflict(slug) do nothing returning id',
                (org['slug'],org['name'],org['kind'],org['homepage'],org.get('approved_hosts',[]),org.get('policy_status','REVIEW_REQUIRED'),org['note'],catalogue['checked_at'])).fetchone()
            added+=bool(row)
            institution=c.execute('select * from startup_radar.institutions where slug=%s',(org['slug'],)).fetchone()
            previous=org.get('previous_review')
            if previous and update_reviewed and institution['policy_status']!=org['policy_status']:
                # Explicit operator opt-in; only replace the exact shipped review
                # that was examined. A concurrent/custom review must never vanish.
                changed=c.execute('update startup_radar.institutions set approved_hosts=%s,policy_status=%s,policy_note=%s,checked_at=%s where id=%s and policy_status=%s and approved_hosts=%s and policy_note=%s returning *',
                    (org['approved_hosts'],org['policy_status'],org['note'],catalogue['checked_at'],institution['id'],previous['policy_status'],previous['approved_hosts'],previous['note'])).fetchone()
                if changed:
                    c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('INSTITUTION_CATALOGUE_REVIEW',%s,%s)",
                        (str(institution['id']),Jsonb({'before':previous,'after':{k:org[k] for k in ('approved_hosts','policy_status','note')},'reason':'Explicit --update-reviewed catalogue installation'})))
                    institution=changed;updated.append(org['slug'])
                else:conflicts.append(org['slug'])
            if previous and update_reviewed and institution['policy_status']==org['policy_status'] and institution['approved_hosts']==org['approved_hosts']:
                c.execute("update startup_radar.sources s set config=config||%s from startup_radar.source_channels ch where ch.source_id=s.id and ch.institution_id=%s and ch.revision=1 and not s.enabled and s.last_attempted_at is null and s.config->>'policy_status'=%s and s.config->'allowed_hosts'=%s and s.config->>'method'<>'REQUEST'",
                    (Jsonb({'allowed_hosts':institution['approved_hosts'],'policy_status':institution['policy_status']}),institution['id'],previous['policy_status'],Jsonb(previous['approved_hosts'])))
            for channel in org.get('channels',[]):
                config={**channel['config'],'opportunity_channel':True,'organization':org['name'],'organization_type':org['kind'],
                    'allowed_hosts':institution['approved_hosts'],'policy_status':institution['policy_status'] if urlsplit(channel['config']['url']).hostname in institution['approved_hosts'] else 'REVIEW_REQUIRED'}
                row=c.execute("insert into startup_radar.sources(slug,name,adapter,config,enabled) values(%s,%s,'HTML',%s,false) on conflict(slug) do nothing returning id",
                    (channel['slug'],channel['name'],Jsonb(config))).fetchone()
                if row:
                    channels+=1
                    c.execute('insert into startup_radar.source_channels(source_id,institution_id,last_reason) values(%s,%s,%s)',(row['id'],institution['id'],channel.get('reason','AWAITING_FIRST_LOCAL_OR_DEPLOYED_RUN')))
    return {'status':'SUCCESS','institutions_added':added,'channels_added':channels,'new_channels_enabled':False,
            'reviews_updated':updated,'review_conflicts':conflicts}
