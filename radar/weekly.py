"""One official-source briefing per Seoul week, independent of team calculations."""
from datetime import timedelta
from psycopg.types.json import Jsonb
from core.clock import now, SEOUL
from radar.actionability import actionability
from radar.adapters.base import AcquiredDetail
from radar.documents import html_text
from radar.identity import digest,deduplicate_publication
from radar.notifications import safe_link
from radar.broadcast import SETTING_KEY,announcement_text,briefing_url,official_channel as official_channel_config
from radar.operation import visibility_mode
from radar.relevance import classify,PUBLISHABLE_STATUSES,RELEVANCE_VERSION
from radar.stage import classify_stage,STAGE_VERSION
from radar.weekly_scope import weekly_sources,collection_completed

FALLBACK = '\uacf5\uc2dd \uacf5\uace0 \ud655\uc778 \ud544\uc694'
# Relevance is deliberately NOT part of MATERIAL. MATERIAL drives the NEW/UPDATE
# fingerprint, so folding an editorial judgement into it would make every stored
# program look materially changed the moment the classifier version moves.
MATERIAL = ('title','organization','support_summary','applicant_summary','application_start_at',
            'application_end_at','application_start_precision','application_end_precision',
            'deadline_type','official_url','application_url','attachments')
# GFC_RELEVANT is presented before CONDITIONAL; the member view renders the two
# as separate sections and relies on this ordering.
SECTION_RANK = {'GFC_RELEVANT':0,'CONDITIONAL':1}


def record_relevance(c, version_id, decision):
    """Persist the classification for audit, including hidden outcomes."""
    c.execute('insert into startup_radar.program_relevance(program_version_id,relevance_version,'
        'relevance_status,startup_leverage,applicability,startup_leverage_reason,restriction_summary,'
        'classification_method,evidence) values(%s,%s,%s,%s,%s,%s,%s,%s,%s) '
        'on conflict(program_version_id,relevance_version) do update set '
        'relevance_status=excluded.relevance_status,startup_leverage=excluded.startup_leverage,'
        'applicability=excluded.applicability,startup_leverage_reason=excluded.startup_leverage_reason,'
        'restriction_summary=excluded.restriction_summary,classification_method=excluded.classification_method,'
        'evidence=excluded.evidence,classified_at=now()',
        (version_id,decision['relevance_version'],decision['relevance_status'],decision['startup_leverage'],
         decision['applicability'],decision['startup_leverage_reason'],decision['restriction_summary'],
         decision['classification_method'],Jsonb(decision['evidence'])))


def record_stage(c, version_id, decision):
    """Persist stage fit for audit. Editorial metadata only; never a gate."""
    c.execute('insert into startup_radar.program_stage_fit(program_version_id,stage_version,method,stage_codes,reason,evidence) '
        'values(%s,%s,%s,%s,%s,%s) on conflict(program_version_id,stage_version) do update set '
        'method=excluded.method,stage_codes=excluded.stage_codes,reason=excluded.reason,evidence=excluded.evidence,classified_at=now()',
        (version_id,decision['stage_version'],decision['method'],decision['stage_codes'],decision['reason'],Jsonb(decision['evidence'])))


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


def published_result(c, briefing):
    status=briefing['collection_status']
    result={'status':status,'collection_status':status,'briefing_id':str(briefing['id']),
            'published':True,'unchanged':True}
    if status=='PARTIAL_SUCCESS':
        recorded=c.execute('select summary from startup_radar.ingestion_runs where id=%s',
            (briefing['ingestion_run_id'],)).fetchone()
        sources=(recorded['summary'] or {}).get('sources',[]) if recorded else []
        if collection_completed(sources,legacy=True):
            result.update(status='SUCCESS',coverage_warning='PUBLISHED_BOUNDED_COLLECTION')
    return result


def build_briefing(db, collection, at=None, publish=True, revision_note=None):
    at = at or now()
    if revision_note is not None and (not publish or not 5<=len(revision_note.strip())<=500):
        raise ValueError('Published revision requires publication and a 5..500 character operator note')
    start,end = week_window(at)
    sources = collection.get('sources',[])
    useful = [s for s in sources if s['status']=='SUCCESS' or s.get('parsed',0)>0]
    complete = collection_completed(sources)
    collection_status = 'SUCCESS' if len(sources)>=2 and all(s['status']=='SUCCESS' for s in sources) else 'PARTIAL_SUCCESS'
    if not useful:return {'status':'FAILED','reason':'ALL_SOURCES_FAILED','published':False}
    with db.transaction() as c:
        c.execute('select pg_advisory_xact_lock(782394203)')
        old = c.execute("select * from startup_radar.weekly_briefings where week_start=%s and publication_kind='WEEKLY' for update",(start,)).fetchone()
        if old and old['status']=='PUBLISHED' and not revision_note:return published_result(c,old)
        previous = c.execute("select distinct on(i.program_id) i.program_id,i.material_hash from startup_radar.weekly_briefing_items i "
            "join startup_radar.weekly_briefings b on b.id=i.briefing_id where b.status='PUBLISHED' "
            "and (b.week_start<%s or b.publication_kind='INITIAL_BASELINE') "
            "order by i.program_id,b.week_start desc,b.publication_kind desc",(start,)).fetchall()
        known = {str(row['program_id']):row['material_hash'] for row in previous}
        # Order is deliberate: dedup -> material change -> actionability -> relevance.
        collected,duplicates = deduplicate_publication(collection.get('weekly_programs',[]))
        items = {}
        withheld = {'DUPLICATE':len(duplicates)}
        for row in collected:
            pid = str(row['program_id']); facts = row['snapshot']
            if not facts.get('official_url'):continue
            fingerprint = digest({key:facts.get(key) for key in MATERIAL})
            if known.get(pid)==fingerprint:continue
            # Classified and retained even when withheld, so an operator can audit
            # why a stored opportunity never reached members.
            decision = classify(facts)
            record_relevance(c,row['version_id'],decision)
            stage = classify_stage(facts)
            record_stage(c,row['version_id'],stage)
            publishable,reason = actionability(facts,at)
            if not publishable:
                withheld[reason] = withheld.get(reason,0)+1;continue
            if decision['relevance_status'] not in PUBLISHABLE_STATUSES:
                withheld[decision['relevance_status']] = withheld.get(decision['relevance_status'],0)+1;continue
            items.setdefault(pid,{**row,'material_hash':fingerprint,
                'change_type':'UPDATE' if pid in known else 'NEW',
                'relevance_status':decision['relevance_status'],
                'restriction_summary':decision['restriction_summary'],
                'stage_codes':stage['stage_codes']})
        if not items and not complete:
            return {'status':'FAILED','reason':'INCOMPLETE_EMPTY_COLLECTION','published':False}
        if old and old['status']=='PUBLISHED':
            before=c.execute('select to_jsonb(i) item from startup_radar.weekly_briefing_items i where briefing_id=%s order by display_order',(old['id'],)).fetchall()
            c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('WEEKLY_BRIEFING_REVISION',%s,%s)",
                (str(old['id']),Jsonb({'reason':revision_note.strip(),'previous_revision':old['revision'],
                    'previous_ingestion_run_id':str(old['ingestion_run_id']),'items':[row['item'] for row in before],
                    'replacement_ingestion_run_id':collection['id'],'actor':'PRIVILEGED_WEEKLY_OPERATOR'})))
        ordered = sorted(items.values(),key=lambda row:(SECTION_RANK[row['relevance_status']],
            row['snapshot'].get('application_end_at') or '9999',row['snapshot']['title'],str(row['program_id'])))
        new_count = sum(row['change_type']=='NEW' for row in ordered)
        display_start = (old or {}).get('display_start') or start
        display_end = (old or {}).get('display_end') or end
        title = f'{display_start:%m.%d} ~ {display_end:%m.%d} \uc8fc\uac04 \uc9c0\uc6d0\uc0ac\uc5c5 \uacf5\uc9c0'
        # "\uc0c8\ub85c \ud655\uc778" states what is actually known: StartupRadar saw it for the
        # first time. It does not claim the institution posted it this week.
        summary = f'\uc0c8\ub85c \ud655\uc778 {new_count}\uac74 \u00b7 \ubcc0\uacbd {len(ordered)-new_count}\uac74\uc785\ub2c8\ub2e4.' if ordered else '\uc774\ubc88 \uc8fc \uc0c8\ub85c \ud655\uc778\u00b7\ubcc0\uacbd\ub41c \uc9c0\uc6d0\uc0ac\uc5c5 \uc5c6\uc74c'
        row = c.execute("insert into startup_radar.weekly_briefings(week_start,week_end,title,status,item_count,new_count,updated_count,summary,collection_status,ingestion_run_id) "
            "values(%s,%s,%s,'DRAFT',%s,%s,%s,%s,%s,%s) on conflict(week_start,publication_kind) do update set "
            "title=excluded.title,item_count=excluded.item_count,new_count=excluded.new_count,updated_count=excluded.updated_count,summary=excluded.summary,"
            "collection_status=excluded.collection_status,ingestion_run_id=excluded.ingestion_run_id,revision=weekly_briefings.revision+1,generated_at=now(),updated_at=now() returning id",
            (start,end,title,len(ordered),new_count,len(ordered)-new_count,summary,collection_status,collection['id'])).fetchone()
        bid = row['id']
        c.execute('delete from startup_radar.weekly_briefing_items where briefing_id=%s',(bid,))
        for index,item in enumerate(ordered):
            c.execute('insert into startup_radar.weekly_briefing_items(briefing_id,program_id,program_version_id,change_type,display_order,snapshot,material_hash,relevance_status,restriction_summary,relevance_version,stage_codes,stage_version) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (bid,item['program_id'],item['version_id'],item['change_type'],index,Jsonb(item['snapshot']),item['material_hash'],
                 item['relevance_status'],item['restriction_summary'],RELEVANCE_VERSION,item['stage_codes'],STAGE_VERSION))
        if publish:c.execute("update startup_radar.weekly_briefings set status='PUBLISHED',published_at=coalesce(published_at,now()),updated_at=now() where id=%s",(bid,))
    return {'status':'SUCCESS' if complete else 'PARTIAL_SUCCESS','collection_status':collection_status,
            'briefing_id':str(bid),'published':publish,'item_count':len(ordered),'new_count':new_count,'updated_count':len(ordered)-new_count,
            'withheld':{reason:count for reason,count in withheld.items() if count}}


def official_channel(c):
    row = c.execute('select value from startup_radar.runtime_settings where key=%s',(SETTING_KEY,)).fetchone()
    return official_channel_config(row['value'] if row else None)


def announce(db, briefing_id, transport=None):
    """Post one summary of a published WEEKLY briefing to the official GFC channel.

    Recipients are no longer selected from team subscriptions or notification
    preferences: there is exactly one target, configured by the operator in
    runtime_settings. The ledger row is keyed by (briefing_id, chat_id), so a
    retry can never post the same issue twice, and FAILED/UNCERTAIN/SENDING rows
    are never picked up again without explicit operator recovery.
    """
    with db.transaction() as c:
        briefing=c.execute("select * from startup_radar.weekly_briefings where id=%s and status='PUBLISHED'",(briefing_id,)).fetchone()
        if not briefing:raise ValueError('Weekly announcement requires a published briefing')
        if briefing['publication_kind']=='INITIAL_BASELINE':
            return {'state':'BASELINE_ARCHIVE','planned':0,'delivered':0}
        # A withdrawn issue is hidden from members, so it is never (newly) announced.
        # An already delivered message stays in Telegram history untouched.
        if briefing.get('withdrawn_at') is not None:return {'state':'WITHDRAWN','planned':0,'delivered':0}
        channel=official_channel(c)
        if channel is None:return {'state':'NO_BROADCAST_CHANNEL','planned':0,'delivered':0}
        # PRIVATE web visibility suppresses the public channel; the channel's own
        # privacy is never changed from here.
        if visibility_mode(c)=='PRIVATE':return {'state':'VISIBILITY_PRIVATE','planned':0,'delivered':0,'channel':channel['name']}
        if transport is None:return {'state':'DELIVERY_DISABLED','planned':0,'delivered':0,'channel':channel['name']}
        items=c.execute('select snapshot,stage_codes from startup_radar.weekly_briefing_items where briefing_id=%s order by display_order',(briefing_id,)).fetchall()
        text=announcement_text(briefing,items)
        c.execute("insert into startup_radar.weekly_announcements(briefing_id,subscription_id,chat_id,payload,target_kind) "
            "values(%s,null,%s,%s,'OFFICIAL_CHANNEL') on conflict(briefing_id,chat_id) do nothing",
            (briefing_id,channel['chat_id'],text))
        ids=c.execute("select id from startup_radar.weekly_announcements where briefing_id=%s and chat_id=%s and state='PENDING' order by id",
            (briefing_id,channel['chat_id'])).fetchall()
    delivered=0
    for item in ids:
        with db.transaction() as c:
            row=c.execute("select * from startup_radar.weekly_announcements where id=%s and state='PENDING' for update skip locked",(item['id'],)).fetchone()
            if not row:continue
            c.execute("update startup_radar.weekly_announcements set state='SENDING',attempted_at=now() where id=%s",(row['id'],))
        try:result=transport.send(row['chat_id'],row['payload'])
        except Exception:result={'state':'UNCERTAIN'}
        state=result.get('state') if result.get('state') in ('DELIVERED','FAILED','UNCERTAIN') else 'UNCERTAIN'
        with db.transaction() as c:
            c.execute("update startup_radar.weekly_announcements set state=%s,receipt=%s,failure_reason=%s,delivered_at=case when %s='DELIVERED' then now() end where id=%s and state='SENDING'",
                (state,Jsonb(result.get('receipt')),None if state=='DELIVERED' else 'TELEGRAM_'+state+(': '+str(result.get('error'))[:160] if result.get('error') else ''),state,row['id']))
        delivered+=state=='DELIVERED'
    with db.transaction() as c:
        states=c.execute('select state,count(*) count from startup_radar.weekly_announcements where briefing_id=%s and chat_id=%s group by state',
            (briefing_id,channel['chat_id'])).fetchall()
    return {'state':'RECORDED','planned':len(ids),'delivered':delivered,'channel':channel['name'],'states':{row['state']:row['count'] for row in states}}


def run_weekly(db, transport=None, at=None, publish=True, collector=None, revision_note=None, check_sources=False):
    from radar.ingestion import ingest
    from radar.executions import claim_execution,finish_execution
    at=at or now(); start,_=week_window(at)
    # claim_execution() returns {'status':'PAUSED'} while the operator pause is
    # on: no claim, collection, publication or send happens.
    claim=claim_execution(db,'WEEKLY')
    if 'execution_id' not in claim:return claim
    try:
        with db.transaction() as c:
            existing=c.execute("select id,collection_status,ingestion_run_id from startup_radar.weekly_briefings where week_start=%s and publication_kind='WEEKLY' and status='PUBLISHED'",(start,)).fetchone()
            sources=c.execute("select * from startup_radar.sources where enabled and "
                "(adapter in ('KSTARTUP','BIZINFO') or config->'weekly_direct'='true'::jsonb) "
                "order by case when adapter in ('KSTARTUP','BIZINFO') then 0 else 1 end,slug").fetchall()
            result=published_result(c,existing) if existing and not revision_note else None
        if result is None or check_sources:
            if not {'KSTARTUP','BIZINFO'}<={s['adapter'] for s in sources}:raise ValueError('Both official sources must be configured')
            collection=(collector or ingest)(db,weekly_sources(sources),trigger='weekly',structured_only=True)
            if result is None:result=build_briefing(db,collection,at,publish,revision_note)
            else:
                # An operator health check never revises an already published issue.
                result.pop('coverage_warning',None)
                result.update(status='SUCCESS' if collection_completed(collection['sources']) else
                    'FAILED' if collection['status']=='FAILED' else 'PARTIAL_SUCCESS',
                    published_collection_status=existing['collection_status'],collection_status=collection['status'])
            result['ingestion_run_id']=collection['id']
            result['sources']=collection['sources']
            if collection_completed(collection['sources']) and collection['status']=='PARTIAL_SUCCESS':
                result['coverage_warning']='BOUNDED_WEEKLY_SCOPE'
        if result.get('published') and result['status']!='FAILED':
            result['announcement']=announce(db,result['briefing_id'],None if check_sources else transport)
            states=result['announcement'].get('states',{})
            if states.get('SENDING') or states.get('UNCERTAIN'):result['status']='UNCERTAIN'
            elif states.get('FAILED') or states.get('PENDING'):result['status']='PARTIAL_SUCCESS'
    except Exception as error:result={'status':'FAILED','reason':type(error).__name__}
    finish_execution(db,claim['execution_id'],result)
    return {**result,'execution_id':claim['execution_id']}
