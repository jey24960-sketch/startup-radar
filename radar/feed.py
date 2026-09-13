"""Persist deterministic results; filter and paginate in PostgreSQL, never in the browser.

Cold/changed scopes are refreshed in bounded batches without any LLM call. The
same cache can be warmed by the scheduled worker; page reads reuse explanations.
"""
from psycopg.types.json import Jsonb
from core.clock import now
from radar.identity import digest
from radar.recommendations import configured_weights,Ranking
from radar.models import EligibilityResult


def cached_browse(db, user_id, profile, team_id=None, q='', program_type=None,
                  status=None, eligibility=None, history=False, recommended=False,
                  limit=30, offset=0, date_from=None, date_to=None):
    from radar.services import public_program,profile_for
    weights = configured_weights(db)
    scope = str(team_id) if team_id else f'preset:{profile.preset or 0}'
    key = digest({'profile': profile.model_dump(mode='json'), 'weights': weights,
                  'day': now().date().isoformat(), 'engine': 'feed-2.1.0',
                  'eligibility':EligibilityResult.model_fields['engine_version'].default,
                  'ranking':Ranking.prompt_version})
    # RLS restricts candidate reads. Privileged writes contain server-derived
    # data only; clients never submit eligibility, scores or scope identities.
    while True:
        # A membership revocation during a cold refresh must stop the batch,
        # even though member-level program rows remain independently readable.
        profile_for(db,user_id,team_id,None if team_id else profile.preset or 0)
        with db.transaction(user_id) as c:
            rows = c.execute('select v.* from startup_radar.programs p '
                'join startup_radar.program_versions v on v.id=p.current_version_id '
                'left join startup_radar.feed_snapshots f on f.program_id=p.id and f.scope_key=%s and f.cache_key=%s '
                'where f.program_version_id is distinct from v.id '
                'order by p.id limit 100', (scope,key)).fetchall()
        if not rows: break
        with db.transaction() as c:
            for row in rows:
                item=public_program(row,profile,weights)
                item['updated_at']=row['created_at'].isoformat()
                c.execute('insert into startup_radar.feed_snapshots(scope_key,program_id,program_version_id,team_id,preset,cache_key,payload,eligibility_status,program_status,score) '
                    'values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(scope_key,program_id,cache_key) do update set '
                    'program_version_id=excluded.program_version_id,cache_key=excluded.cache_key,payload=excluded.payload,'
                    'eligibility_status=excluded.eligibility_status,program_status=excluded.program_status,score=excluded.score,refreshed_at=now()',
                    (scope,row['program_id'],row['id'],team_id,None if team_id else profile.preset or 0,key,Jsonb(item),
                     item['eligibility']['status'],item['status'],item['recommendation']['score'] if item['recommendation'] else None))
    # Time-sensitive open/closed state is derived at read time, including an
    # intra-day deadline. Cached eligibility is independent of wall-clock hours.
    sql = '''with feed as (
      select f.*,v.created_at, p.title,p.organization,p.program_types,p.application_end_at,
      case when p.application_end_at<now() then 'CLOSED'
           when p.application_start_at>now() then 'UPCOMING'
           when p.deadline_type in ('ROLLING','UNTIL_BUDGET_EXHAUSTED') or p.application_end_at is not null then 'OPEN'
           else 'UNKNOWN' end as live_status
      from startup_radar.feed_snapshots f
      join startup_radar.programs p on p.id=f.program_id and p.current_version_id=f.program_version_id
      join startup_radar.program_versions v on v.id=f.program_version_id
      where f.scope_key=%s and f.cache_key=%s
    ), filtered as (select * from feed where
      (%s='' or title ilike %s or organization ilike %s)
      and (%s::text is null or %s=any(program_types))
      and (%s or live_status<>'CLOSED')
      and (%s::text is null or live_status=%s)
      and (%s::text is null or eligibility_status=%s)
      and (not %s or (score is not null and eligibility_status<>'INELIGIBLE' and live_status in ('OPEN','UPCOMING')))
      and (%s::date is null or application_end_at >= %s::date)
      and (%s::date is null or application_end_at < %s::date+interval '1 day'))
    select (select count(*) from filtered) total,
      coalesce((select jsonb_agg(x.item order by x.rank_score desc nulls last,x.created_at desc,x.program_id)
        from (select payload || jsonb_build_object('status',live_status,
              'recommendation',case when live_status in ('OPEN','UPCOMING') then payload->'recommendation' else 'null'::jsonb end) as item,
              case when %s then score end rank_score,created_at,program_id
              from filtered order by rank_score desc nulls last,created_at desc,program_id limit %s offset %s) x),'[]'::jsonb) items'''
    with db.transaction(user_id) as c:
        result=c.execute(sql,(scope,key,q,'%'+q+'%','%'+q+'%',program_type,program_type,history,status,status,
                eligibility,eligibility,recommended,date_from,date_from,date_to,date_to,recommended,limit,offset)).fetchone()
    return {**result,'profile':profile.model_dump(mode='json'),'offset':offset,'limit':limit}
