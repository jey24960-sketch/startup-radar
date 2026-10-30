"""Rare early notices, preserving the member's once-weekly reading routine.

These are not daily digests. A verified important opportunity may be announced
once, with seven full days remaining, only when waiting for Tuesday would lose
that preparation window. The first post-rollout baseline never broadcasts.
"""
from datetime import datetime, timedelta
import html
import re
from uuid import UUID

from psycopg.types.json import Jsonb
from core.clock import SEOUL
from radar.broadcast import SETTING_KEY, official_channel, safe_link
from radar.identity import cross_source_key, deduplicate_publication
from radar.operation import operation_state, visibility_mode
from radar.relevance import classify
from radar.stage import classify_stage, telegram_tag
from radar.opportunity_facts import explicit_closure

SETTING = 'early_announcements'
MINIMUM_LEAD = timedelta(days=7)
SEND_MARGIN = timedelta(minutes=1)
MAX_ITEMS = 3
IMPORTANT = re.compile(
    r'액셀러레이[팅터]|accelerat|인큐베이[팅션]|창업\s*보육|입주\s*(기업|팀|모집)|'
    r'사업화\s*(지원|자금)|예비\s*창업\s*패키지|초기\s*창업\s*패키지|'
    r'시제품\s*(제작|개발|지원)|\bMVP\b|\bPoC\b|실증\s*(지원|기업|사업)|'
    r'창업\s*(지원금|지원\s*사업|경진대회)', re.I)
NOT_IMPORTANT = re.compile(r'참관객|참관\s*신청|관람객|청중|세미나|장비\s*교육|특강|설명회|투자\s*교류회')


def aware(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        try: parsed = datetime.fromisoformat(str(value))
        except (ValueError, TypeError): return None
    return parsed if parsed.tzinfo is not None else None


def next_weekly_at(at):
    """The next scheduled Tuesday 09:00 Seoul, strictly after the reference."""
    if at is None or at.tzinfo is None: raise ValueError('Aware reference timestamp required')
    local = at.astimezone(SEOUL)
    due = local.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=(1-local.weekday()) % 7)
    return due + timedelta(days=7) if due <= local else due


def candidate_decision(facts, at):
    """Return an auditable narrow exception decision without touching the DB."""
    if at is None or at.tzinfo is None: raise ValueError('Aware reference timestamp required')
    if facts.get('review_note'):
        return False, 'SOURCE_CONFIRMATION_REQUIRED'
    if facts.get('recruitment_closed') is True or explicit_closure(facts.get('title') or ''):
        return False, 'CLOSED_SOURCE_STATUS'
    end, start = aware(facts.get('application_end_at')), aware(facts.get('application_start_at'))
    if (facts.get('deadline_type') != 'FIXED_DATE' or end is None
            or facts.get('application_end_precision') not in ('DATE', 'DATETIME')):
        return False, 'FIXED_VERIFIED_DEADLINE_REQUIRED'
    if (facts.get('application_start_at') and start is None) or (start and start > end):
        return False, 'INVALID_PERIOD'
    if end-at < MINIMUM_LEAD: return False, 'UNDER_SEVEN_DAYS'
    if end-next_weekly_at(at) >= MINIMUM_LEAD: return False, 'CAN_WAIT_FOR_WEEKLY'
    if not safe_link(facts.get('official_url')): return False, 'OFFICIAL_URL_REQUIRED'
    decision = classify(facts)
    if decision['relevance_status'] != 'GFC_RELEVANT': return False, 'BROAD_GFC_RELEVANCE_REQUIRED'
    stages = classify_stage(facts)['stage_codes']
    if not set(stages).intersection(('STAGE_0','STAGE_1','STAGE_2','STAGE_3')):
        return False, 'EARLY_FOUNDER_FIT_REQUIRED'
    text = '\n'.join(str(facts.get(k) or '') for k in ('title','support_summary'))
    if NOT_IMPORTANT.search(text) or not IMPORTANT.search(text): return False, 'NOT_EXCEPTIONAL_OPPORTUNITY'
    return True, 'SEVEN_DAY_WINDOW_LOST_IF_WAITING'


def _settings(c):
    row = c.execute('select value from startup_radar.runtime_settings where key=%s', (SETTING,)).fetchone()
    value = row['value'] if row and isinstance(row['value'],dict) else {}
    active = aware(value.get('active_from'))
    return value, active


def _cross_key(facts):
    return cross_source_key(facts.get('title'),facts.get('application_start_at'),facts.get('application_end_at'))


def _clock(c, at):
    server = c.execute('select now() as reference_at').fetchone()['reference_at']
    if at is not None and (at.tzinfo is None or abs((at-server).total_seconds()) > 120):
        raise ValueError('Early notice clock must match the database clock')
    return server


def plan_early_notices(db, at=None, candidates=None):
    """Publish at most one small exception bundle per Seoul week; never send here.

    Set active_from only AFTER an initial non-delivering discovery has completed.
    This prevents newly imported historical records from becoming rollout alerts.
    Parent discovery owns the durable worker execution; this lock serializes the
    final publication against the weekly publication and other planners.
    """
    from radar.weekly import load_stored_candidates, week_window
    with db.transaction() as c:
        c.execute('select pg_advisory_xact_lock(782394203)')
        reference = _clock(c, at)
        config, active_from = _settings(c)
        if not operation_state(c)['enabled']: return {'state':'PAUSED','planned':0}
        if not config.get('enabled') or active_from is None or reference < active_from:
            return {'state':'EARLY_NOTICES_DISABLED','planned':0}
        if visibility_mode(c) == 'PRIVATE': return {'state':'VISIBILITY_PRIVATE','planned':0}
        start, _ = week_window(reference)
        existing = c.execute('select id from startup_radar.early_notices where week_start=%s', (start,)).fetchone()
        if existing: return {'state':'WEEKLY_EXCEPTION_LIMIT','planned':0,'notice_id':str(existing['id'])}
        rows = candidates if candidates is not None else load_stored_candidates(db, reference, connection=c)
        from radar.publication_reviews import load_reviews
        rows, _ = load_reviews(c, rows)
        rows, _ = deduplicate_publication(rows)
        known = c.execute('select i.program_id,i.snapshot from startup_radar.weekly_briefing_items i '
            "join startup_radar.weekly_briefings b on b.id=i.briefing_id where b.status='PUBLISHED' "
            'union all select program_id,snapshot from startup_radar.early_notice_items').fetchall()
        known_ids = {str(row['program_id']) for row in known}
        known_cross = {key for row in known if (key := _cross_key(row['snapshot']))}
        selected = []
        for row in rows:
            pid, facts = str(row['program_id']), row['snapshot']
            if pid in known_ids or _cross_key(facts) in known_cross: continue
            if (row.get('publication_review') or {}).get('relevance_status', 'GFC_RELEVANT') != 'GFC_RELEVANT': continue
            if not candidate_decision(facts, reference)[0]: continue
            first = c.execute('select min(discovered_at) as first_observed from startup_radar.program_sources '
                'where program_id=%s', (pid,)).fetchone()['first_observed']
            if first is None or first < active_from or first > reference: continue
            selected.append({**row, 'stage_codes':classify_stage(facts)['stage_codes']})
        selected.sort(key=lambda row:(aware(row['snapshot']['application_end_at']),row['snapshot']['title'],str(row['program_id'])))
        limit = config.get('max_items', MAX_ITEMS)
        limit = limit if type(limit) is int and 1 <= limit <= MAX_ITEMS else MAX_ITEMS
        selected = selected[:limit]
        if not selected: return {'state':'NO_EARLY_OPPORTUNITIES','planned':0}
        # The database clock, not the caller clock, anchors all published facts.
        published = c.execute('select clock_timestamp() as reference_at').fetchone()['reference_at']
        selected = [row for row in selected if candidate_decision(row['snapshot'],published)[0]]
        if not selected: return {'state':'PREPARATION_WINDOW_EXPIRED','planned':0}
        day = published.astimezone(SEOUL).date()
        title = f'{day.month}월 {day.day}일자 중요 모집 사전 안내'
        summary = f'다음 주 공지까지 기다리면 준비기간이 짧아지는 중요 모집 {len(selected)}건입니다.'
        notice = c.execute('insert into startup_radar.early_notices(week_start,title,summary,published_at,item_count) '
            'values(%s,%s,%s,%s,%s) returning id', (start,title,summary,published,len(selected))).fetchone()
        for index, row in enumerate(selected):
            c.execute('insert into startup_radar.early_notice_items(notice_id,program_id,program_version_id,display_order,snapshot,stage_codes) '
                'values(%s,%s,%s,%s,%s,%s)', (notice['id'],row['program_id'],row['version_id'],index,Jsonb(row['snapshot']),row['stage_codes']))
        c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('EARLY_NOTICE_PUBLISHED',%s,%s)",
            (str(notice['id']),Jsonb({'reason':'SEVEN_DAY_PREPARATION_WINDOW','item_count':len(selected),'policy_version':'gfc-early-v1'})))
    return {'state':'PUBLISHED','planned':len(selected),'notice_id':str(notice['id'])}


def early_notice_url(notice_id):
    from radar.broadcast import briefing_url
    return briefing_url(notice_id).replace('/weekly/', '/early/')


def announcement_text(notice, items):
    lines = ['[GFC StartupRadar · 중요 모집 사전 안내]', '', html.escape(notice['title']),
             '다음 주 공지까지 기다리면 준비기간이 짧아져 미리 안내드립니다.', '']
    for item in items:
        facts = item['snapshot']
        tag = telegram_tag(item.get('stage_codes'))
        end = aware(facts['application_end_at']).astimezone(SEOUL)
        lines.append(html.escape(f"• {tag + ' ' if tag else ''}{str(facts.get('title') or '')[:100]} / 마감: {end:%Y-%m-%d}"))
    link = html.escape(early_notice_url(notice['id']), quote=True)
    lines += ['', '모든 사업은 안내 시점에 마감까지 최소 7일이 남아 있습니다.', f'<a href="{link}">모집 내용 확인</a>']
    return '\n'.join(lines)


def _latest_candidates(db, connection, reference, items):
    from radar.weekly import load_stored_candidates
    wanted = {str(item['program_id']) for item in items}
    from radar.publication_reviews import load_reviews
    rows, _ = load_reviews(connection, load_stored_candidates(db, reference, connection=connection))
    return {str(row['program_id']):row for row in rows
            if str(row['program_id']) in wanted
            and (row.get('publication_review') or {}).get('relevance_status', 'GFC_RELEVANT') == 'GFC_RELEVANT'}


def announce_early(db, notice_id, transport=None, at=None):
    """Claim one channel send. Ambiguous sends are never automatically retried."""
    notice_id = UUID(str(notice_id))
    with db.transaction() as c:
        row = c.execute('select * from startup_radar.early_notices where id=%s for update', (notice_id,)).fetchone()
        if not row or row['status'] != 'PUBLISHED' or row.get('withdrawn_at') is not None:
            return {'state':'NOT_PUBLISHED','delivered':0}
        if not operation_state(c)['enabled']: return {'state':'PAUSED','delivered':0}
        if visibility_mode(c) == 'PRIVATE': return {'state':'VISIBILITY_PRIVATE','delivered':0}
        channel_row = c.execute('select value from startup_radar.runtime_settings where key=%s', (SETTING_KEY,)).fetchone()
        channel = official_channel(channel_row['value'] if channel_row else None)
        if channel is None: return {'state':'NO_BROADCAST_CHANNEL','delivered':0}
        if transport is None: return {'state':'DELIVERY_DISABLED','delivered':0}
        if row['delivery_state'] != 'PENDING': return {'state':row['delivery_state'],'delivered':0}
        reference = _clock(c, at)
        config, active_from = _settings(c)
        if not config.get('enabled') or active_from is None or reference < active_from:
            return {'state':'EARLY_NOTICES_DISABLED','delivered':0}
        current_week = (reference.astimezone(SEOUL)-timedelta(days=reference.astimezone(SEOUL).weekday())).date()
        if row['week_start'] != current_week or row['published_at'] < active_from:
            c.execute("update startup_radar.early_notices set delivery_state='EXPIRED',failure_reason='STALE_EARLY_NOTICE' where id=%s", (notice_id,))
            return {'state':'EXPIRED','delivered':0}
        items = c.execute('select program_id,program_version_id,snapshot,stage_codes from startup_radar.early_notice_items where notice_id=%s order by display_order', (notice_id,)).fetchall()
        current = _latest_candidates(db,c,reference,items)
        if any(str(item['program_id']) not in current or
                str(current[str(item['program_id'])]['version_id']) != str(item['program_version_id'])
                for item in items):
            c.execute("update startup_radar.early_notices set delivery_state='EXPIRED',failure_reason='SOURCE_CHANGED_OR_UNVERIFIED' where id=%s", (notice_id,))
            return {'state':'EXPIRED','delivered':0}
        if not items or any(aware(i['snapshot'].get('application_end_at')) is None or
                aware(i['snapshot']['application_end_at'])-reference < MINIMUM_LEAD+SEND_MARGIN for i in items):
            c.execute("update startup_radar.early_notices set delivery_state='EXPIRED',failure_reason='UNDER_SEVEN_DAYS_AT_SEND' where id=%s", (notice_id,))
            return {'state':'EXPIRED','delivered':0}
        payload = announcement_text(row, items)
        c.execute("update startup_radar.early_notices set delivery_state='SENDING',chat_id=%s,payload=%s,attempted_at=now() where id=%s and delivery_state='PENDING'",
            (channel['chat_id'],payload,notice_id))
    try: result = transport.send(channel['chat_id'], payload)
    except Exception: result = {'state':'UNCERTAIN'}
    if not isinstance(result,dict): result = {'state':'UNCERTAIN'}
    state = result.get('state')
    if state not in ('DELIVERED','FAILED','UNCERTAIN'): state = 'UNCERTAIN'
    if state == 'DELIVERED' and not (isinstance(result.get('receipt'),dict) and result['receipt'].get('message_id')):
        state = 'UNCERTAIN'
    with db.transaction() as c:
        c.execute("update startup_radar.early_notices set delivery_state=%s,receipt=%s,failure_reason=%s,delivered_at=case when %s='DELIVERED' then now() end where id=%s and delivery_state='SENDING'",
            (state,Jsonb(result.get('receipt')),None if state=='DELIVERED' else 'TELEGRAM_'+state,state,notice_id))
    return {'state':state,'delivered':int(state=='DELIVERED'),'notice_id':str(notice_id)}
