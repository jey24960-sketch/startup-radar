"""Batch-owned GFC presentation results. Reads never run AI or the Python engine."""
from dataclasses import asdict
from psycopg.types.json import Jsonb
from core.clock import now, SEOUL
from radar.models import TeamProfile, Program, EligibilityResult, PRESETS, apply_preset
from radar.eligibility import evaluate
from radar.recommendations import configured_weights, rank, Ranking
from radar.identity import digest


def refresh_member_results(db):
    weights = configured_weights(db)
    generation = digest({'contract': 'member-read-1', 'weights': weights, 'presets': PRESETS,
                         'eligibility': EligibilityResult.model_fields['engine_version'].default,
                         'ranking': Ranking.prompt_version})
    computed = 0
    with db.transaction() as c:
        c.execute("update startup_radar.member_read_state set generation=%s,state='RUNNING',started_at=now(),finished_at=null,error_kind=null where singleton", (generation,))
        scopes = c.execute('select team_id,profile,version from startup_radar.team_profiles order by team_id').fetchall()
        c.execute("update startup_radar.profile_calculation_requests r set state='SUPERSEDED',finished_at=now() "
                  "from startup_radar.team_profiles p where r.team_id=p.team_id and r.profile_version<p.version and r.state in ('PENDING','RUNNING','FAILED')")
    scopes += [{'team_id': None, 'preset': i, 'profile': apply_preset(TeamProfile(), i).model_dump(mode='json'), 'version': None} for i in range(5)]
    try:
        for scope in scopes:
            team_id = scope['team_id']
            preset = scope.get('preset')
            key = str(team_id) if team_id else f'preset:{preset}'
            if team_id:
                with db.transaction() as c:
                    c.execute("update startup_radar.profile_calculation_requests set state='RUNNING',started_at=now(),finished_at=null,attempts=attempts+1,error_kind=null "
                              "where team_id=%s and profile_version=%s and state in ('PENDING','RUNNING','FAILED')", (team_id,scope['version']))
            profile = TeamProfile.model_validate(scope['profile'])
            # Historical facts remain browsable and are evaluated against the
            # current scope, explicitly identified as such by the GFC UI.
            cursor = None
            while True:
                with db.transaction() as c:
                    rows = c.execute('select v.* from startup_radar.program_versions v '
                        'where (%s::uuid is null or v.id>%s) order by v.id limit 100', (cursor, cursor)).fetchall()
                if not rows:
                    break
                with db.transaction() as c:
                    for row in rows:
                        at = now().astimezone(SEOUL)
                        existing = c.execute('select 1 from startup_radar.member_program_results where scope_key=%s and program_version_id=%s '
                            'and generation=%s and evaluated_on=%s and profile_snapshot=%s and profile_version is not distinct from %s',
                            (key,row['id'],generation,at.date(),Jsonb(scope['profile']),scope['version'])).fetchone()
                        if existing:
                            continue
                        program = Program.model_validate(row['normalized'])
                        eligibility = evaluate(profile, program.requirements, program.evidence_complete, as_of=at.date())
                        recommendation = rank(program, profile, eligibility, weights=weights, at=at)
                        c.execute('insert into startup_radar.member_program_results(scope_key,program_version_id,team_id,preset,profile_version,profile_snapshot,evaluated_on,generation,eligibility,recommendation) '
                            'values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(scope_key,program_version_id) do update set '
                            'profile_version=excluded.profile_version,profile_snapshot=excluded.profile_snapshot,evaluated_on=excluded.evaluated_on,generation=excluded.generation,'
                            'eligibility=excluded.eligibility,recommendation=excluded.recommendation,computed_at=now()',
                            (key,row['id'],team_id,preset,scope['version'],Jsonb(scope['profile']),at.date(),generation,
                             Jsonb(eligibility.model_dump(mode='json')),Jsonb(asdict(recommendation)) if recommendation else None))
                        computed += 1
                cursor = rows[-1]['id']
            if team_id:
                with db.transaction() as c:
                    c.execute("update startup_radar.profile_calculation_requests r set state=case when p.version=r.profile_version and p.profile=%s then 'SUCCESS' else 'SUPERSEDED' end,finished_at=now() "
                              "from startup_radar.team_profiles p where r.team_id=%s and r.profile_version=%s and p.team_id=r.team_id and r.state='RUNNING'",
                              (Jsonb(scope['profile']),team_id,scope['version']))
        with db.transaction() as c:
            c.execute("update startup_radar.member_read_state set state='SUCCESS',finished_at=now() where singleton")
    except Exception as error:
        with db.transaction() as c:
            c.execute("update startup_radar.member_read_state set state='FAILED',finished_at=now(),error_kind=%s where singleton", (type(error).__name__,))
            c.execute("update startup_radar.profile_calculation_requests set state='FAILED',finished_at=now(),error_kind=%s where state='RUNNING'", (type(error).__name__,))
        raise
    return {'status': 'SUCCESS', 'computed': computed, 'scopes': len(scopes), 'delivery': 'DISABLED'}
