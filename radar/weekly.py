"""One official-source briefing per Seoul week, independent of team calculations."""
import html
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID
from psycopg.types.json import Jsonb
from core.clock import now, SEOUL
from radar.adapters.base import AcquiredDetail
from radar.documents import html_text
from radar.identity import digest
from radar.notifications import safe_link

FALLBACK = '\uacf5\uc2dd \uacf5\uace0 \ud655\uc778 \ud544\uc694'
MATERIAL = ('title','organization','support_summary','applicant_summary','application_start_at',
            'application_end_at','application_start_precision','application_end_precision',
            'deadline_type','official_url','application_url','attachments','category','participation','cohort','year',
            'fee','investment_terms','benefit_kind','cancelled','event_start_at','event_end_at')


def material_hash(facts):
    # Keep hashes of pre-discovery weekly snapshots stable when extra fields
    # are absent. Schema expansion alone is not an official programme update.
    return digest({key:facts.get(key) for index,key in enumerate(MATERIAL) if index<12 or facts.get(key) is not None})


def weekly_detail(candidate):
    row = candidate.raw_metadata
    text = html_text(row.get('pbanc_ctnt') or row.get('bsnsSumryCn') or row.get('description') or '')
    return AcquiredDetail(candidate.official_detail_url,text,candidate.title,raw_metadata=row)


def snapshot(program, raw):
    facts = program.model_dump(mode='json')
    result = {key:facts.get(key) for key in MATERIAL if key!='attachments'}
    for key in ('title','organization','support_summary','applicant_summary'):
        result[key] = html_text(str(result.get(key) or '')).strip() or FALLBACK
    for key in ('official_url','application_url'):
        if not safe_link(result.get(key)):result[key] = None
    # API attachment identities detect advertised replacements without downloading/OCR.
    result['attachments'] = sorted({url.strip() for key in ('flpthNm','printFlpthNm')
        for url in str(raw.get(key) or '').split('@') if safe_link(url.strip())})
    return result


def week_window(at):
    if at.tzinfo is None:raise ValueError('Timezone-aware weekly clock required')
    day = at.astimezone(SEOUL).date()
    start = day-timedelta(days=day.weekday())
    return start,start+timedelta(days=6)


def build_briefing(db, collection, at=None, publish=True, revision_note=None):
    at = at or now()
    if revision_note is not None and (not publish or not 5<=len(revision_note.strip())<=500):
        raise ValueError('Published revision requires publication and a 5..500 character operator note')
    start,end = week_window(at)
    sources = collection.get('sources',[])
    useful = [s for s in sources if s['status']=='SUCCESS' or s.get('parsed',0)>0]
    complete = bool(sources) and all(s['status']=='SUCCESS' and s.get('coverage',{}).get('pagination_complete') for s in sources)
    if not useful:return {'status':'FAILED','reason':'ALL_SOURCES_FAILED','published':False}
    with db.transaction() as c:
        c.execute('select pg_advisory_xact_lock(782394203)')
        old = c.execute('select * from startup_radar.weekly_briefings where week_start=%s for update',(start,)).fetchone()
        if old and old['status']=='PUBLISHED' and not revision_note:return {'status':old['collection_status'],'briefing_id':str(old['id']),'published':True,'unchanged':True}
        previous = c.execute("select distinct on(i.program_id) i.program_id,i.material_hash from startup_radar.weekly_briefing_items i "
            "join startup_radar.weekly_briefings b on b.id=i.briefing_id where b.status='PUBLISHED' and b.week_start<%s "
            "order by i.program_id,b.week_start desc",(start,)).fetchall()
        known = {str(row['program_id']):row['material_hash'] for row in previous}
        items = {}
        for row in collection.get('weekly_programs',[]):
            pid = str(row['program_id']); facts = row['snapshot']
            if row['status'] in ('CLOSED','ROLLING') or (row['status']=='CANCELLED' and pid not in known) or facts.get('deadline_type') in ('ROLLING','UNTIL_BUDGET_EXHAUSTED') or not facts.get('official_url'):continue
            fingerprint = material_hash(facts)
            if known.get(pid)==fingerprint:continue
            items.setdefault(pid,{**row,'material_hash':fingerprint,'change_type':'UPDATE' if pid in known else 'NEW'})
        if not items and not complete:
            return {'status':'FAILED','reason':'INCOMPLETE_EMPTY_COLLECTION','published':False}
        if old and old['status']=='PUBLISHED':
            before=c.execute('select to_jsonb(i) item from startup_radar.weekly_briefing_items i where briefing_id=%s order by display_order',(old['id'],)).fetchall()
            c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('WEEKLY_BRIEFING_REVISION',%s,%s)",
                (str(old['id']),Jsonb({'reason':revision_note.strip(),'previous_revision':old['revision'],
                    'previous_ingestion_run_id':str(old['ingestion_run_id']),'items':[row['item'] for row in before],
                    'replacement_ingestion_run_id':collection['id'],'actor':'PRIVILEGED_WEEKLY_OPERATOR'})))
        ordered = sorted(items.values(),key=lambda row:(row['snapshot'].get('application_end_at') or '9999',row['snapshot']['title'],str(row['program_id'])))
        new_count = sum(row['change_type']=='NEW' for row in ordered)
        title = f'{start:%m.%d} ~ {end:%m.%d} \uc8fc\uac04 \uc9c0\uc6d0\uc0ac\uc5c5 \uacf5\uc9c0'
        summary = f'\uc774\ubc88 \uc8fc \ud655\uc778\ub41c \uc2e0\uaddc {new_count}\uac74 \u00b7 \ubcc0\uacbd {len(ordered)-new_count}\uac74\uc785\ub2c8\ub2e4.' if ordered else '\uc774\ubc88 \uc8fc \uc2e0\uaddc\u00b7\ubcc0\uacbd \uc9c0\uc6d0\uc0ac\uc5c5 \uc5c6\uc74c'
        row = c.execute("insert into startup_radar.weekly_briefings(week_start,week_end,title,status,item_count,new_count,updated_count,summary,collection_status,ingestion_run_id) "
            "values(%s,%s,%s,'DRAFT',%s,%s,%s,%s,%s,%s) on conflict(week_start) do update set "
            "title=excluded.title,item_count=excluded.item_count,new_count=excluded.new_count,updated_count=excluded.updated_count,summary=excluded.summary,"
            "collection_status=excluded.collection_status,ingestion_run_id=excluded.ingestion_run_id,revision=weekly_briefings.revision+1,generated_at=now(),updated_at=now() returning id",
            (start,end,title,len(ordered),new_count,len(ordered)-new_count,summary,'SUCCESS' if complete else 'PARTIAL_SUCCESS',collection['id'])).fetchone()
        bid = row['id']
        c.execute('delete from startup_radar.weekly_briefing_items where briefing_id=%s',(bid,))
        for index,item in enumerate(ordered):
            c.execute('insert into startup_radar.weekly_briefing_items(briefing_id,program_id,program_version_id,change_type,display_order,snapshot,material_hash) values(%s,%s,%s,%s,%s,%s,%s)',
                (bid,item['program_id'],item['version_id'],item['change_type'],index,Jsonb(item['snapshot']),item['material_hash']))
        if publish:c.execute("update startup_radar.weekly_briefings set status='PUBLISHED',published_at=coalesce(published_at,now()),updated_at=now() where id=%s",(bid,))
    return {'status':'SUCCESS' if complete else 'PARTIAL_SUCCESS','briefing_id':str(bid),'published':publish,'item_count':len(ordered),'new_count':new_count,'updated_count':len(ordered)-new_count}


def briefing_url(briefing_id):
    import os
    base = os.environ.get('RADAR_MEMBER_NOTICE_URL','https://www.gfc-startup.com/notice')
    parts = urlsplit(base)
    if not safe_link(base) or parts.query or parts.fragment:raise ValueError('Invalid member notice base URL')
    return urlunsplit((parts.scheme,parts.netloc,parts.path.rstrip('/')+'/weekly/'+str(UUID(str(briefing_id))),'',''))


def announcement_text(briefing, items):
    lines = ['[GFC StartupRadar]',briefing['title']+'\uac00 \uac8c\uc2dc\ub418\uc5c8\uc2b5\ub2c8\ub2e4.',
             f"\uc774\ubc88 \uc8fc \uc2e0\uaddc\u00b7\ubcc0\uacbd \uc9c0\uc6d0\uc0ac\uc5c5: {briefing['item_count']}\uac74"]
    for item in items[:3]:
        facts=item['snapshot']; deadline=(facts.get('application_end_at') or FALLBACK)[:10]
        lines.append(f"\u2022 {facts['title'][:100]} / \ub9c8\uac10: {deadline}")
    text='\n\n'.join(html.escape(line) for line in lines)
    return text+'\n\n<a href="'+html.escape(briefing_url(briefing['id']),quote=True)+'">\uc8fc\uac04 \uc9c0\uc6d0\uc0ac\uc5c5 \uc804\uccb4 \ubcf4\uae30</a>'


def announce(db, briefing_id, transport=None):
    with db.transaction() as c:
        briefing=c.execute("select * from startup_radar.weekly_briefings where id=%s and status='PUBLISHED'",(briefing_id,)).fetchone()
        if not briefing:raise ValueError('Weekly announcement requires a published briefing')
        subscriptions=c.execute("select distinct on(s.chat_id) s.id,s.chat_id from startup_radar.telegram_subscriptions s "
            "left join startup_radar.team_notification_preferences p on p.team_id=s.team_id "
            "where s.enabled and s.digest_enabled and s.channel_health='HEALTHY' and coalesce(p.enabled,true) and coalesce(p.digest_enabled,true) order by s.chat_id,s.id").fetchall()
        if not subscriptions:return {'state':'NO_SUBSCRIBERS','planned':0,'delivered':0}
        if transport is None:return {'state':'DELIVERY_DISABLED','planned':0,'delivered':0,'subscribers':len(subscriptions)}
        items=c.execute('select snapshot from startup_radar.weekly_briefing_items where briefing_id=%s order by display_order',(briefing_id,)).fetchall()
        text=announcement_text(briefing,items)
        for sub in subscriptions:
            c.execute('insert into startup_radar.weekly_announcements(briefing_id,subscription_id,chat_id,payload) values(%s,%s,%s,%s) on conflict(briefing_id,chat_id) do nothing',
                (briefing_id,sub['id'],sub['chat_id'],text))
        ids=c.execute("select id from startup_radar.weekly_announcements where briefing_id=%s and state='PENDING' order by id",(briefing_id,)).fetchall()
    delivered=0
    for item in ids:
        with db.transaction() as c:
            # Serialize a correction with claiming a message. Pending messages
            # use current editorial text; already sent messages remain untouched.
            current=c.execute('select * from startup_radar.weekly_briefings where id=%s for update',(briefing_id,)).fetchone()
            current_items=c.execute('select snapshot from startup_radar.weekly_briefing_items where briefing_id=%s order by display_order',(briefing_id,)).fetchall()
            row=c.execute("select a.* from startup_radar.weekly_announcements a join startup_radar.telegram_subscriptions s on s.id=a.subscription_id "
                "left join startup_radar.team_notification_preferences p on p.team_id=s.team_id where a.id=%s and a.state='PENDING' "
                "and s.chat_id=a.chat_id and s.enabled and s.digest_enabled and s.channel_health='HEALTHY' and coalesce(p.enabled,true) and coalesce(p.digest_enabled,true) for update of a skip locked",(item['id'],)).fetchone()
            if not row:continue
            row['payload']=announcement_text(current,current_items)
            c.execute("update startup_radar.weekly_announcements set state='SENDING',attempted_at=now(),payload=%s where id=%s",(row['payload'],row['id']))
        try:result=transport.send(row['chat_id'],row['payload'])
        except Exception:result={'state':'UNCERTAIN'}
        state=result.get('state') if result.get('state') in ('DELIVERED','FAILED','UNCERTAIN') else 'UNCERTAIN'
        with db.transaction() as c:
            c.execute("update startup_radar.weekly_announcements set state=%s,receipt=%s,failure_reason=%s,delivered_at=case when %s='DELIVERED' then now() end where id=%s and state='SENDING'",
                (state,Jsonb(result.get('receipt')),None if state=='DELIVERED' else 'TELEGRAM_'+state,state,row['id']))
            if result.get('channel_health')=='BLOCKED':c.execute("update startup_radar.telegram_subscriptions set channel_health='BLOCKED',health_checked_at=now(),health_reason='WEEKLY_DELIVERY_REJECTED' where id=%s",(row['subscription_id'],))
        delivered+=state=='DELIVERED'
    with db.transaction() as c:
        states=c.execute('select state,count(*) count from startup_radar.weekly_announcements where briefing_id=%s group by state',(briefing_id,)).fetchall()
    return {'state':'RECORDED','planned':len(ids),'delivered':delivered,'states':{row['state']:row['count'] for row in states}}


def run_weekly(db, transport=None, at=None, publish=True, collector=None, revision_note=None, scheduled=False, from_catalog=False):
    from radar.ingestion import ingest
    from radar.executions import claim_execution,finish_execution
    from radar.weekly_schedule import scheduled_week
    at=at or now(); start,_=week_window(at)
    if scheduled and (not publish or revision_note):raise ValueError('Scheduled run cannot draft or revise')
    if scheduled and not scheduled_week(db,at):
        return {'status':'SUCCESS','state':'NOT_DUE','executed':False}
    claim=claim_execution(db,'WEEKLY')
    if 'execution_id' not in claim:return claim
    try:
        if scheduled and not scheduled_week(db,at,claim['execution_id']):
            result={'status':'SUCCESS','state':'NOT_DUE','executed':False}
            finish_execution(db,claim['execution_id'],result)
            return result
        with db.transaction() as c:
            existing=c.execute("select id,collection_status from startup_radar.weekly_briefings where week_start=%s and status='PUBLISHED'",(start,)).fetchone()
            sources=c.execute("select * from startup_radar.sources where enabled and adapter in ('KSTARTUP','BIZINFO') order by slug").fetchall()
        if existing and not revision_note:result={'status':existing['collection_status'],'briefing_id':str(existing['id']),'published':True,'unchanged':True}
        else:
            if from_catalog:
                from radar.opportunity_store import catalog_collection
                collection=catalog_collection(db)
            else:
                if {s['adapter'] for s in sources}!={'KSTARTUP','BIZINFO'}:raise ValueError('Both official sources must be configured')
                collection=(collector or ingest)(db,sources,trigger='weekly',structured_only=True)
            result=build_briefing(db,collection,at,publish,revision_note)
            result['ingestion_run_id']=collection['id']
            result['sources']=collection['sources']
        if result.get('published'):
            result['announcement']=announce(db,result['briefing_id'],transport)
            states=result['announcement'].get('states',{})
            if states.get('SENDING') or states.get('UNCERTAIN'):result['status']='UNCERTAIN'
            elif states.get('FAILED') or states.get('PENDING'):result['status']='PARTIAL_SUCCESS'
    except Exception as error:result={'status':'FAILED','reason':type(error).__name__}
    finish_execution(db,claim['execution_id'],result)
    return {**result,'execution_id':claim['execution_id']}
