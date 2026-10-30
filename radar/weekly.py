"""One official-source briefing per Seoul week, independent of team calculations."""
from datetime import datetime,timedelta
from contextlib import nullcontext
from uuid import UUID
from psycopg.types.json import Jsonb
from core.clock import now, SEOUL
from radar.actionability import actionability
from radar.adapters.base import AcquiredDetail
from radar.documents import html_text
from radar.identity import digest,deduplicate_publication,normalize_url
from radar.notifications import safe_link
from radar.broadcast import SETTING_KEY,announcement_text,briefing_url,official_channel as official_channel_config
from radar.operation import visibility_mode
from radar.relevance import classify,PUBLISHABLE_STATUSES,RELEVANCE_VERSION,REVIEW_REQUIRED
from radar.stage import classify_stage,STAGE_VERSION
from radar.weekly_scope import weekly_sources,collection_completed
from radar.models import Program

FALLBACK = '\uacf5\uc2dd \uacf5\uace0 \ud655\uc778 \ud544\uc694'
# Relevance is deliberately NOT part of MATERIAL. MATERIAL drives the NEW/UPDATE
# fingerprint, so folding an editorial judgement into it would make every stored
# program look materially changed the moment the classifier version moves.
MATERIAL = ('title','organization','support_summary','applicant_summary','application_start_at',
            'application_end_at','application_start_precision','application_end_precision',
            'deadline_type','official_url','application_url','attachments')
# Confirmed opportunities precede the clearly labelled uncertainty appendix.
# The broader weekly contract does not change advanced recommendations or the
# rare early-notice contract, which still use confirmed relevance statuses only.
WEEKLY_PUBLISHABLE_STATUSES = (*PUBLISHABLE_STATUSES, REVIEW_REQUIRED)
SECTION_RANK = {'GFC_RELEVANT':0,'CONDITIONAL':1,REVIEW_REQUIRED:2}


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
    from radar.official_facts import clean_legacy_snapshot
    facts = clean_legacy_snapshot(program.model_dump(mode='json'))
    result = {key:facts.get(key) for key in MATERIAL if key!='attachments'}
    # An official support category is classification evidence, not a material
    # change: classifier/metadata updates must not republish an unchanged notice.
    result['program_types'] = list(facts.get('program_types') or [])
    official_detail = raw.get('_official_detail') or {}
    if official_detail.get('status') == 'SUCCESS' and official_detail.get('recruitment_closed') is True:
        result['recruitment_closed'] = True
    for key in ('title','organization','support_summary','applicant_summary'):
        result[key] = html_text(str(result.get(key) or '')).strip() or FALLBACK
    for key in ('official_url','application_url'):
        if not safe_link(result.get(key)):result[key] = None
    if result.get('official_url'):
        result['official_url'] = normalize_url(result['official_url'])
    # API attachment identities detect advertised replacements without downloading/OCR.
    result['attachments'] = sorted({url.strip() for key in ('flpthNm','printFlpthNm')
        for url in str(raw.get(key) or '').split('@') if safe_link(url.strip())})
    return result


def publication_fingerprint(facts):
    # Removing the historical full-page append is an editorial repair, not a
    # changed opportunity. Compare both old and new public facts the same way.
    from radar.official_facts import clean_legacy_snapshot
    facts = clean_legacy_snapshot(facts)
    if facts.get('official_url'):
        facts['official_url'] = normalize_url(facts['official_url'])
    return digest({key: facts.get(key) for key in MATERIAL})


def stored_candidates(rows, at):
    """Build candidates from current versions with approved, recent provenance.

    The input has one latest observation per program/source. An excluded direct
    observation or identity conflict blocks the program rather than reviving an
    older accepted observation from another source.
    """
    candidates = {}
    blocked = set()
    for row in rows:
        pid = str(row['program_id'])
        if (row.get('extraction_metadata') or {}).get('provider') not in (
            'structured_api_weekly', 'official_html_weekly'
        ):
            continue
        raw = row['raw_metadata'] or {}
        if raw.get('weekly_duplicate_conflict'):
            blocked.add(pid)
            continue
        direct = row['source_config'].get('weekly_direct') is True
        from radar.opportunity_facts import publication_review_note
        metadata = row.get('extraction_metadata') or {}
        source_note = publication_review_note(raw.get('weekly_decision'),
                                              raw.get('weekly_reason') or metadata.get('weekly_reason')) if direct else None
        if direct and raw.get('weekly_decision') != 'ACCEPTED' and not source_note:
            blocked.add(pid)
            continue
        if str(row['observation_version_id']) != str(row['version_id']):
            continue
        try:
            program = Program.model_validate(row['normalized'])
        except (ValueError, TypeError):
            continue
        if direct:
            from radar.opportunity_facts import weekly_decision
            decision, reason = weekly_decision(program, raw.get('weekly_direct_facts') or {}, at)
            source_note = publication_review_note(decision, reason)
            if decision != 'ACCEPTED' and not source_note:
                blocked.add(pid)
                continue
        # Query order prefers the freshest source-specific observation. Its
        # attachment URLs belong to the same current version as the facts.
        candidates.setdefault(pid, {
            'program_id': row['program_id'], 'version_id': row['version_id'],
            'snapshot': snapshot(program, raw),
        })
        if source_note:
            candidates[pid]['snapshot']['review_note'] = source_note
    return [row for pid, row in candidates.items() if pid not in blocked]


def load_stored_candidates(db, at=None, connection=None, max_age_days=14):
    """Re-evaluate stored daily discoveries without depending on today's page.

    This privileged worker query never exposes unpublished rows to members.
    It deliberately loads current versions only, and uses the latest immutable
    observation for each source rather than any historical accepted snapshot.
    """
    at = at or now()
    if at.tzinfo is None:
        raise ValueError('Aware reference timestamp required for stored candidates')
    if type(max_age_days) is not int or not 1 <= max_age_days <= 30:
        raise ValueError('Stored candidate freshness must be 1..30 days')
    with (db.transaction() if connection is None else nullcontext(connection)) as c:
        rows = c.execute(
            'select p.id program_id,p.current_version_id version_id,v.normalized,'
            's.adapter source_adapter,s.config source_config,ps.last_seen_at,'
            'ob.program_version_id observation_version_id,ob.raw_metadata,ob.extraction_metadata '
            'from startup_radar.programs p '
            'join startup_radar.program_versions v on v.id=p.current_version_id '
            'join startup_radar.program_sources ps on ps.program_id=p.id '
            'join startup_radar.sources s on s.id=ps.source_id '
            'join lateral (select ss.program_version_id,ss.raw_metadata,ss.extraction_metadata '
            ' from startup_radar.program_source_snapshots ss '
            ' where ss.program_id=p.id and ss.source_id=s.id '
            ' order by ss.observed_at desc,ss.id desc limit 1) ob on true '
            'where s.enabled and ps.last_seen_at >= %s '
            "and (s.adapter in ('KSTARTUP','BIZINFO') or "
            " (s.config->'weekly_direct'='true'::jsonb and s.config->>'policy_status'='APPROVED')) "
            'order by ps.last_seen_at desc,p.id,s.id',
            (at-timedelta(days=max_age_days),)).fetchall()
    return stored_candidates(rows, at)


def merge_candidates(stored, collected):
    """Current collection wins while retaining earlier daily discoveries."""
    merged = {str(row['program_id']): row for row in stored}
    merged.update({str(row['program_id']): row for row in collected})
    return list(merged.values())


def week_window(at):
    if at.tzinfo is None:raise ValueError('Timezone-aware weekly clock required')
    day = at.astimezone(SEOUL).date()
    start = day-timedelta(days=day.weekday())
    return start,start+timedelta(days=6)


def publication_title(published_at, publication_kind='WEEKLY'):
    """Label the first publication day, never the collection or operational week."""
    label = '최초 지원사업 목록' if publication_kind=='INITIAL_BASELINE' else '주간 지원사업 공지'
    if published_at is None:return f'발행 전 {label}'
    if published_at.tzinfo is None:raise ValueError('Timezone-aware publication timestamp required')
    day=published_at.astimezone(SEOUL).date()
    return f'{day.month}월 {day.day}일자 {label}'


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


def build_briefing(db, collection, at=None, publish=True, revision_note=None, *, database_clock=False):
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
        # Production uses one transaction clock for both the seven-day gate and
        # first published_at. Collection can take minutes after a worker starts;
        # that elapsed time must never erode the promised preparation window.
        gate_at = c.execute('select now() reference_at').fetchone()['reference_at'] if database_clock else at
        previous = c.execute("select distinct on(i.program_id) i.program_id,i.material_hash,i.snapshot from startup_radar.weekly_briefing_items i "
            "join startup_radar.weekly_briefings b on b.id=i.briefing_id where b.status='PUBLISHED' "
            "and (b.week_start<%s or b.publication_kind='INITIAL_BASELINE') "
            "order by i.program_id,b.week_start desc,b.publication_kind desc",(start,)).fetchall()
        known = {str(row['program_id']):publication_fingerprint(row['snapshot']) for row in previous}
        # Order is deliberate: dedup -> material change -> actionability -> relevance.
        candidates = merge_candidates(load_stored_candidates(db,gate_at,connection=c),
                                      collection.get('weekly_programs',[]))
        collected,duplicates = deduplicate_publication(candidates)
        items = {}
        withheld = {'DUPLICATE':len(duplicates)}
        for row in collected:
            from radar.official_facts import clean_legacy_snapshot
            facts = clean_legacy_snapshot(row['snapshot'])
            row = {**row, 'snapshot': facts}
            pid = str(row['program_id'])
            if not facts.get('official_url'):continue
            fingerprint = publication_fingerprint(facts)
            if known.get(pid)==fingerprint:continue
            # Classified and retained even when withheld, so an operator can audit
            # why a stored opportunity never reached members.
            decision = classify(facts)
            if facts.get('review_note') and decision['relevance_status'] in WEEKLY_PUBLISHABLE_STATUSES:
                decision = {**decision, 'relevance_status':REVIEW_REQUIRED,
                            'startup_leverage':'UNKNOWN', 'applicability':'UNKNOWN',
                            'startup_leverage_reason':facts['review_note']}
            record_relevance(c,row['version_id'],decision)
            stage = classify_stage(facts)
            record_stage(c,row['version_id'],stage)
            publishable,reason = actionability(facts,gate_at)
            if not publishable:
                withheld[reason] = withheld.get(reason,0)+1;continue
            if decision['relevance_status'] not in WEEKLY_PUBLISHABLE_STATUSES:
                withheld[decision['relevance_status']] = withheld.get(decision['relevance_status'],0)+1;continue
            published_facts = dict(facts)
            if decision['relevance_status'] == REVIEW_REQUIRED:
                published_facts['review_note'] = (decision.get('startup_leverage_reason') or
                    '창업 관련 공고이나 지원 내용이나 신청 대상은 공식 공고 확인 필요')
            else:
                published_facts.pop('review_note', None)
            items.setdefault(pid,{**row,'snapshot':published_facts,'material_hash':fingerprint,
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
        # The database clock is authoritative for first publication. Explicit
        # revisions retain that first timestamp; drafts never invent a date.
        published_at = (old or {}).get('published_at')
        if publish and published_at is None:
            published_at = gate_at if database_clock else c.execute('select now() as published_at').fetchone()['published_at']
        title = publication_title(published_at)
        # "\uc0c8\ub85c \ud655\uc778" states what is actually known: StartupRadar saw it for the
        # first time. It does not claim the institution posted it this week.
        summary = f'\uc0c8\ub85c \ud655\uc778 {new_count}\uac74 \u00b7 \ubcc0\uacbd {len(ordered)-new_count}\uac74\uc785\ub2c8\ub2e4.' if ordered else '\uc774\ubc88 \uc8fc \uc0c8\ub85c \ud655\uc778\u00b7\ubcc0\uacbd\ub41c \uc9c0\uc6d0\uc0ac\uc5c5 \uc5c6\uc74c'
        review_count = sum(item['relevance_status'] == REVIEW_REQUIRED for item in ordered)
        if review_count:
            summary += f' 추가 확인이 필요한 공고 {review_count}건이 포함되어 있습니다.'
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
        if publish:c.execute("update startup_radar.weekly_briefings set status='PUBLISHED',published_at=coalesce(published_at,%s),updated_at=now() where id=%s",(published_at,bid))
    return {'status':'SUCCESS' if complete else 'PARTIAL_SUCCESS','collection_status':collection_status,
            'briefing_id':str(bid),'published':publish,'item_count':len(ordered),'new_count':new_count,'updated_count':len(ordered)-new_count,
            'review_count':review_count,
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
        if not isinstance(result,dict):result={'state':'UNCERTAIN'}
        if result.get('state')=='DELIVERED' and not (isinstance(result.get('receipt'),dict) and result['receipt'].get('message_id')):
            result={'state':'UNCERTAIN','error':'Invalid transport receipt'}
        state=result.get('state') if result.get('state') in ('DELIVERED','FAILED','UNCERTAIN') else 'UNCERTAIN'
        with db.transaction() as c:
            c.execute("update startup_radar.weekly_announcements set state=%s,receipt=%s,failure_reason=%s,delivered_at=case when %s='DELIVERED' then now() end where id=%s and state='SENDING'",
                (state,Jsonb(result.get('receipt')),None if state=='DELIVERED' else 'TELEGRAM_'+state+(': '+str(result.get('error'))[:160] if result.get('error') else ''),state,row['id']))
        delivered+=state=='DELIVERED'
    with db.transaction() as c:
        states=c.execute('select state,count(*) count from startup_radar.weekly_announcements where briefing_id=%s and chat_id=%s group by state',
            (briefing_id,channel['chat_id'])).fetchall()
    return {'state':'RECORDED','planned':len(ids),'delivered':delivered,'channel':channel['name'],'states':{row['state']:row['count'] for row in states}}


def recover_weekly_announcement(db,announcement_id,note,confirmed_not_delivered=False):
    """Authorize a retry only for a definitively failed send; never send here.

    Ambiguous/in-flight/delivered outcomes remain blocked. The original payload,
    publication and ledger identity stay intact; prior delivery evidence goes to
    the private audit before an explicitly confirmed FAILED row becomes PENDING.
    """
    from radar.executions import LOCK_KEY,owner_identity
    if not confirmed_not_delivered:raise ValueError('Confirm that the failed announcement was not delivered before recovery')
    if not isinstance(note,str) or not 5<=len(note.strip())<=500:raise ValueError('A recovery note of 5..500 characters is required')
    announcement_id=UUID(str(announcement_id))
    with db.transaction() as c:
        if not c.execute('select pg_try_advisory_xact_lock(%s) acquired',(LOCK_KEY,)).fetchone()['acquired']:
            raise ValueError('Another ownership operation is in progress')
        if c.execute('select 1 from startup_radar.worker_executions where finished_at is null').fetchone():
            raise ValueError('Verify and recover the active execution owner before authorizing a delivery retry')
        row=c.execute('select * from startup_radar.weekly_announcements where id=%s for update',(announcement_id,)).fetchone()
        if not row:raise LookupError('Weekly announcement not found')
        if row['state']!='FAILED' or row['receipt'] is not None or row['delivered_at'] is not None:
            raise ValueError('Only FAILED without delivery evidence can be recovered; uncertain or in-flight sends remain blocked')
        briefing=c.execute('select * from startup_radar.weekly_briefings where id=%s',(row['briefing_id'],)).fetchone()
        channel=official_channel(c)
        if row['target_kind']!='OFFICIAL_CHANNEL' or not briefing or briefing['status']!='PUBLISHED' or briefing['publication_kind']!='WEEKLY' or briefing.get('withdrawn_at') is not None:
            raise ValueError('Only a visible published weekly announcement can be recovered')
        if channel is None or channel['chat_id']!=row['chat_id'] or visibility_mode(c)=='PRIVATE':
            raise ValueError('The same official channel and an allowed visibility setting are required')
        previous={key:row[key] for key in ('state','attempted_at','delivered_at','receipt','failure_reason')}
        previous={key:value.isoformat() if isinstance(value,datetime) else value for key,value in previous.items()}
        c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('WEEKLY_ANNOUNCEMENT_RETRY_AUTHORIZED',%s,%s)",
                  (str(announcement_id),Jsonb({'reason':note.strip(),'briefing_id':str(row['briefing_id']),
                    'previous':previous,'operator':owner_identity(),'confirmed_not_delivered':True})))
        c.execute("update startup_radar.weekly_announcements set state='PENDING',attempted_at=null,delivered_at=null,receipt=null,failure_reason=null where id=%s",(announcement_id,))
    return {'status':'SUCCESS','state':'PENDING','announcement_id':str(announcement_id),
            'briefing_id':str(row['briefing_id']),'retry_dispatched':False,'delivered':False}


def run_weekly(db, transport=None, at=None, publish=True, collector=None, revision_note=None, check_sources=False,
               scheduler_request_id=None,expected_week_start=None):
    from radar.ingestion import ingest
    from radar.executions import claim_execution,finish_execution,weekly_schedule_arguments
    request_id,expected_week=weekly_schedule_arguments(scheduler_request_id,expected_week_start)
    if request_id and (not publish or revision_note is not None or check_sources):
        raise ValueError('Scheduled weekly requests cannot draft, revise, or run a source check')
    explicit_clock = at is not None
    at=at or now(); start,_=week_window(at)
    # claim_execution() returns {'status':'PAUSED'} while the operator pause is
    # on: no claim, collection, publication or send happens.
    try:
        claim=claim_execution(db,'WEEKLY',scheduler_request_id=request_id,expected_week_start=expected_week)
    except Exception as error:
        # A lost commit acknowledgement can leave a confirmed owner in the DB.
        # Do not recollect or dispatch another owner based only on this response.
        return {'status':'UNCERTAIN','reason':type(error).__name__,'executed':False,
                **({'scheduler_request_id':str(request_id)} if request_id else {}),
                'message':'Execution claim uncertain; inspect durable request and owner before retry'}
    if 'execution_id' not in claim:return claim
    schedule_metadata={key:claim[key] for key in ('scheduler_request_id','expected_week_start') if key in claim}
    if request_id:
        at=datetime.fromisoformat(claim['reference_at']);start,_=week_window(at)
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
            if result is None:result=build_briefing(db,collection,at,publish,revision_note,
                                                 database_clock=not explicit_clock)
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
    result={**result,**schedule_metadata}
    try:finish_execution(db,claim['execution_id'],result)
    except Exception as error:
        return {'status':'UNCERTAIN','execution_id':claim['execution_id'],**schedule_metadata,'reason':type(error).__name__,
                'message':'Execution finalization uncertain; inspect durable owner and partial effects before retry'}
    return {**result,'execution_id':claim['execution_id']}
