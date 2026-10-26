"""One audited continuation of the interrupted 2026-10-26 discovery baseline.

This tool is intentionally bound to one verified public Actions run and one
database owner. It never calls a publication planner or notification transport.
"""
import json
import time
import argparse
from datetime import datetime

import requests
from psycopg.types.json import Jsonb

from radar.database import Database
from radar.discovery import discovery_sources
from radar.executions import LOCK_KEY, claim_execution, finish_execution, recover_execution
from radar.ingestion import ingest


PRIOR_RUN_ID = '40350014904'
PRIOR_HEAD = '904f724deaca3528c7ac7d05913a105574787d7f'
PRIOR_BRANCH = 'main'
PRIOR_EXECUTION_ID = 'f77c47c2-f29b-4921-bd0b-d65a0f0c0c05'
PRIOR_INGESTION_ID = '56fc1a8e-73df-47a0-b54c-529faedb2757'
SLOT = datetime.fromisoformat('2026-10-26T18:00:00+09:00')
ACTION = 'DISCOVERY_BASELINE_CONTINUATION'
RUN_URL = 'https://api.github.com/repos/jey24960-sketch/startup-radar/actions/runs/'+PRIOR_RUN_ID


class ContinuationRefused(RuntimeError):
    """Only static, non-sensitive reason codes may be returned to the operator."""


def verify_prior_run(fetcher=None, *, clock=time.monotonic, sleep=time.sleep, wait_seconds=300):
    """Public GET only; a missing/uncertain termination never unlocks the owner."""
    if not 0 < wait_seconds <= 300:
        raise ValueError('Invalid bounded verification interval')
    fetcher = fetcher or requests.get
    deadline = clock()+wait_seconds
    while True:
        remaining = deadline-clock()
        if remaining <= 0:
            raise ContinuationRefused('PRIOR_RUN_TERMINATION_UNCONFIRMED')
        try:
            response = fetcher(RUN_URL, timeout=min(20,remaining), allow_redirects=False,
                               headers={'Accept':'application/vnd.github+json'})
        except requests.RequestException:
            raise ContinuationRefused('PUBLIC_RUN_LOOKUP_FAILED') from None
        if response.status_code != 200:
            raise ContinuationRefused('PUBLIC_RUN_LOOKUP_REJECTED')
        try:
            run = response.json()
        except (ValueError,TypeError):
            raise ContinuationRefused('PUBLIC_RUN_RESPONSE_INVALID') from None
        if (not isinstance(run,dict) or str(run.get('id')) != PRIOR_RUN_ID
                or run.get('head_sha') != PRIOR_HEAD or run.get('head_branch') != PRIOR_BRANCH):
            raise ContinuationRefused('PRIOR_RUN_IDENTITY_MISMATCH')
        if run.get('status') == 'completed':
            return {'run_id':PRIOR_RUN_ID,'head_sha':PRIOR_HEAD,'branch':PRIOR_BRANCH,'status':'completed'}
        if run.get('status') not in ('queued','in_progress','waiting','pending','requested'):
            raise ContinuationRefused('PRIOR_RUN_STATUS_UNRECOGNIZED')
        remaining = deadline-clock()
        if remaining <= 0:
            raise ContinuationRefused('PRIOR_RUN_TERMINATION_UNCONFIRMED')
        sleep(min(10,remaining))


def reserve_continuation(db, verification):
    """Reserve once and preserve complete preimages before recovering anything."""
    with db.transaction() as c:
        c.execute('select pg_advisory_xact_lock(%s)',(LOCK_KEY,))
        if c.execute('select 1 from startup_radar.admin_audit where action=%s and entity_id=%s',
                     (ACTION,PRIOR_EXECUTION_ID)).fetchone():
            raise ContinuationRefused('CONTINUATION_ALREADY_RESERVED')
        previous = c.execute('select to_jsonb(w) value from startup_radar.worker_executions w '
                             'where id=%s for update',(PRIOR_EXECUTION_ID,)).fetchone()
        if not previous:
            raise ContinuationRefused('PRIOR_DATABASE_OWNER_MISSING')
        worker = previous['value']
        if (worker.get('kind') != 'DISCOVER'
                or str((worker.get('owner') or {}).get('github_run_id')) != PRIOR_RUN_ID):
            raise ContinuationRefused('PRIOR_DATABASE_OWNER_MISMATCH')
        if worker.get('state') not in ('RUNNING','FAILED','PARTIAL_SUCCESS'):
            raise ContinuationRefused('PRIOR_DATABASE_OWNER_NOT_RECOVERABLE')
        if c.execute('select 1 from startup_radar.worker_executions '
                     'where finished_at is null and id<>%s limit 1',(PRIOR_EXECUTION_ID,)).fetchone():
            raise ContinuationRefused('ANOTHER_WORKER_IS_ACTIVE')
        slot = c.execute('select execution_id,to_jsonb(s) value from startup_radar.discovery_slots s '
                         'where slot_start=%s for update',(SLOT,)).fetchone()
        old_ingestion = c.execute('select to_jsonb(r) value from startup_radar.ingestion_runs r '
                                 'where id=%s for update',(PRIOR_INGESTION_ID,)).fetchone()
        if not slot or str(slot['execution_id']) != PRIOR_EXECUTION_ID:
            raise ContinuationRefused('PRIOR_SLOT_OWNER_MISMATCH')
        if not old_ingestion:
            raise ContinuationRefused('PRIOR_INGESTION_MISSING')
        if old_ingestion['value'].get('status') not in ('RUNNING','FAILED','PARTIAL_SUCCESS'):
            raise ContinuationRefused('PRIOR_INGESTION_NOT_RECOVERABLE')
        audit = c.execute('insert into startup_radar.admin_audit(action,entity_id,detail) '
                         'values(%s,%s,%s) returning id',(ACTION,PRIOR_EXECUTION_ID,Jsonb({
                             'state':'RESERVED','verification':verification,
                             'previous_worker':worker,'previous_slot':slot['value'],
                             'previous_ingestion':old_ingestion['value'],
                             'maximum_continuations':1,'notification_delivery':False,
                         }))).fetchone()
    return audit['id']


def official_baseline_verified(sources):
    """All configured sources of both official adapter kinds must complete."""
    official = [source for source in sources if source.get('adapter') in ('KSTARTUP','BIZINFO')]
    if {source.get('adapter') for source in official} != {'KSTARTUP','BIZINFO'}:
        return False
    return all(source.get('status') == 'SUCCESS'
               and source.get('coverage',{}).get('scope_completed') is True
               for source in official)


def activate_after_baseline(c, result, execution_id):
    if not result['core_baseline_verified']:
        return False
    reference = c.execute('select now() reference_at').fetchone()['reference_at']
    row = c.execute("select value from startup_radar.runtime_settings where key='early_announcements' for update").fetchone()
    if row is None or not isinstance(row['value'],dict):
        raise ContinuationRefused('EARLY_NOTICE_SETTING_MISSING')
    previous = row['value']
    replacement = {**previous,'enabled':True,'active_from':reference.isoformat()}
    c.execute("update startup_radar.runtime_settings set value=%s,updated_at=now() where key='early_announcements'",
              (Jsonb(replacement),))
    c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) "
              "values('EARLY_NOTICES_BASELINE_ACTIVATED',%s,%s)",(str(execution_id),Jsonb({
                  'reason':'BOTH_OFFICIAL_DISCOVERY_SCOPES_VERIFIED',
                  'previous_setting':previous,'replacement_setting':replacement,
                  'ingestion_run_id':result['ingestion_run_id'],
                  'retroactive_notifications':False,
              })))
    return True


def continue_baseline(db, *, verifier=None, collector=None):
    verification = (verifier or verify_prior_run)()
    audit_id = reserve_continuation(db,verification)
    # This existing recovery path requires explicit termination verification and
    # never treats a mere age/timeout as proof that a process has stopped.
    recover_execution(db,PRIOR_EXECUTION_ID,
        'Verified completed Actions run '+PRIOR_RUN_ID+' before one-off discovery continuation',
        confirmed_stopped=True)
    claim = claim_execution(db,'DISCOVER')
    if 'execution_id' not in claim:
        return {'status':'FAILED','reason':'CONTINUATION_CLAIM_BLOCKED',
                'continuation_audit_id':str(audit_id),'core_baseline_verified':False}
    execution_id = claim['execution_id']
    result = None
    try:
        with db.session():
            with db.transaction() as c:
                slot = c.execute('select execution_id from startup_radar.discovery_slots '
                                 'where slot_start=%s for update',(SLOT,)).fetchone()
                if slot is None or str(slot['execution_id']) != PRIOR_EXECUTION_ID:
                    raise ContinuationRefused('PRIOR_SLOT_CHANGED_AFTER_RESERVATION')
                c.execute("update startup_radar.ingestion_runs set status='FAILED',finished_at=now(),"
                          "summary=coalesce(summary,'{}'::jsonb)||%s where id=%s and status='RUNNING'",
                          (Jsonb({'partial_effects':True,'termination_verified':verification,
                                  'continuation_execution_id':str(execution_id)}),PRIOR_INGESTION_ID))
                c.execute('update startup_radar.discovery_slots set execution_id=%s,created_at=now(),'
                          'finished_at=null,result=null where slot_start=%s',(execution_id,SLOT))
                config_row = c.execute("select value from startup_radar.runtime_settings where key='daily_discovery'").fetchone()
                config = config_row['value'] if config_row else {}
                if not config.get('enabled'):
                    raise ContinuationRefused('DAILY_DISCOVERY_DISABLED')
                registry = c.execute('select * from startup_radar.sources where enabled order by slug').fetchall()
            sources = discovery_sources(registry,config)
            if not {'KSTARTUP','BIZINFO'} <= {source['adapter'] for source in sources}:
                raise ContinuationRefused('BOTH_OFFICIAL_SOURCES_REQUIRED')
            collection = (collector or ingest)(db,sources,structured_only=True,
                trigger='daily-discovery-baseline-continuation')
            if collection.get('status') not in ('SUCCESS','PARTIAL_SUCCESS','FAILED'):
                raise ContinuationRefused('COLLECTION_RESULT_UNCERTAIN')
            result = {'status':collection['status'],'state':'BASELINE_CONTINUATION_COMPLETED',
                      'execution_id':str(execution_id),'continuation_audit_id':str(audit_id),
                      'ingestion_run_id':collection['id'],'sources':collection['sources'],
                      'core_baseline_verified':collection['status'] in ('SUCCESS','PARTIAL_SUCCESS')
                      and official_baseline_verified(collection['sources'])}
            # Activation is anchored AFTER the imported baseline, making every
            # pre-baseline first discovery ineligible for retrospective alerts.
            with db.transaction() as c:
                result['early_announcements_activated'] = activate_after_baseline(c,result,execution_id)
                c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) "
                          "values('DISCOVERY_BASELINE_CONTINUATION_COMPLETED',%s,%s)",
                          (str(execution_id),Jsonb({key:result[key] for key in (
                              'status','ingestion_run_id','core_baseline_verified','early_announcements_activated')})))
    except Exception as error:
        # Collection/persistence acknowledgements may be lost. Keep the durable
        # owner RUNNING until the stopped process and its partial effects are
        # explicitly inspected; never release an uncertain owner automatically.
        result = {'status':'UNCERTAIN','reason':error.args[0] if isinstance(error,ContinuationRefused)
                  else type(error).__name__,'execution_id':str(execution_id),
                  'continuation_audit_id':str(audit_id),'core_baseline_verified':False}
        try:
            with db.transaction() as c:
                c.execute('update startup_radar.discovery_slots set finished_at=now(),result=%s '
                          'where execution_id=%s',(Jsonb(result),execution_id))
        except Exception:
            pass
        return result
    try:
        with db.transaction() as c:
            slot = c.execute('update startup_radar.discovery_slots set finished_at=now(),result=%s '
                             'where execution_id=%s returning slot_start',(Jsonb(result),execution_id)).fetchone()
            if slot is None:
                raise ContinuationRefused('CONTINUATION_SLOT_OWNERSHIP_CHANGED')
    except Exception:
        return {**result,'status':'UNCERTAIN','reason':'CONTINUATION_SLOT_FINALIZATION_UNCERTAIN'}
    try:
        finish_execution(db,execution_id,result)
    except Exception:
        return {**result,'status':'UNCERTAIN','reason':'CONTINUATION_OWNER_FINALIZATION_UNCERTAIN'}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Continue the fixed verified discovery baseline once; never publish or send notices')
    parser.parse_args(argv)
    try:
        from radar.discovery_connection import discovery_database_options
        result = continue_baseline(Database(**discovery_database_options()))
    except Exception as error:
        result = {'status':'FAILED','reason':error.args[0] if isinstance(error,ContinuationRefused)
                  else type(error).__name__,'core_baseline_verified':False}
    # URLs, HTTP response bodies and exception messages are never printed.
    output = {key:value for key,value in result.items() if key != 'sources'}
    output['source_health'] = [{
        'adapter':source.get('adapter'),'status':source.get('status'),
        'discovered':source.get('discovered'),'parsed':source.get('parsed'),
        'scope_completed':source.get('coverage',{}).get('scope_completed'),
        'failure_codes':[failure.get('reason_code') or failure.get('kind')
                         for failure in source.get('failures',[])],
    } for source in result.get('sources',[])]
    print(json.dumps(output,ensure_ascii=False,default=str))
    return 0 if (result.get('status') in ('SUCCESS','PARTIAL_SUCCESS')
                 and result.get('core_baseline_verified')
                 and result.get('early_announcements_activated')) else 1


if __name__ == '__main__':
    raise SystemExit(main())
