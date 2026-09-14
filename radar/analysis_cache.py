"""Evidence-keyed extraction claims: commit before AI, compare-and-set afterwards."""
from datetime import timedelta
import time
import os
from uuid import uuid4
from psycopg.types.json import Jsonb
from core.clock import now
from radar.adapters.base import SourceFailure
from radar.executions import owner_identity
from radar.identity import digest
from radar.models import Program

MAX_ATTEMPTS=3
LEASE_SECONDS=600
TRANSIENT_FAILURES={'AI_TIMEOUT','AI_CONNECTION','AI_RATE_LIMIT','AI_SERVER'}


def input_key(extractor,program,detail,documents,source_id):
    return digest({'source_id':str(source_id),'normalized':program.model_dump(mode='json'),
        'detail':detail.text,'documents':[{k:d.get(k) for k in
        ('original_url','content_hash','extracted_text','fetch_status','extraction_status')}
        for d in sorted(documents,key=lambda d:d['original_url'])],
        'model':getattr(extractor,'model',None),'version':getattr(extractor,'version',None),
        'configuration_revision':os.environ.get('RADAR_AI_CONFIGURATION_REVISION','1'),
        'extractor':type(extractor).__module__+'.'+type(extractor).__qualname__})


def extract_cached(db,extractor,program,detail,documents,source_id,metadata):
    key=input_key(extractor,program,detail,documents,source_id)
    owner=uuid4();at=now();blocked=None
    with db.transaction() as c:
        c.execute('select pg_advisory_xact_lock(%s)',(int(key[:15],16),))
        cached=c.execute('select normalized,metadata from startup_radar.extraction_cache where input_hash=%s',(key,)).fetchone()
        if cached:
            metadata.update(cached['metadata'],cache_hit=True,cache_status='HIT',input_hash=key)
            # Original usage stays in the attempt ledger, not counted as a new call.
            metadata['current_usage']={'request_count':0,'cache_hits':1}
            return Program.model_validate(cached['normalized'])
        previous=c.execute('select * from startup_radar.extraction_attempts where input_hash=%s order by attempt_number desc limit 1',(key,)).fetchone()
        if previous:
            if previous['operator_retry_allowed'] and previous['state'] in ('FAILED','UNCERTAIN'):
                c.execute('update startup_radar.extraction_attempts set operator_retry_allowed=false where id=%s',(previous['id'],))
            elif previous['state']=='RUNNING':
                if at>=previous['lease_expires_at']:
                    c.execute("update startup_radar.extraction_attempts set state='UNCERTAIN',error_kind='AI_OWNER_EXPIRED',finished_at=%s where id=%s",(at,previous['id']))
                    blocked='AI_OWNER_EXPIRED'
                else:blocked='AI_IN_PROGRESS'
            elif previous['state']=='UNCERTAIN':blocked=previous['error_kind'] or 'AI_OWNER_EXPIRED'
            elif previous['state']=='FAILED' and (not previous['retryable'] or previous['attempt_number']>=MAX_ATTEMPTS
                    or not previous['next_retry_at'] or at<previous['next_retry_at']):
                blocked=previous['error_kind']
            elif previous['state']=='SUCCESS':blocked='AI_CACHE_MISSING'
        if blocked:
            metadata.update(cache_hit=False,cache_status='IN_PROGRESS' if blocked=='AI_IN_PROGRESS' else 'FAILURE_HIT',
                input_hash=key,attempt_id=str(previous['id']),original_error_kind=blocked,
                next_retry_at=previous['next_retry_at'].isoformat() if previous['next_retry_at'] else None,
                current_usage={'request_count':0,'failure_cache_hits':1})
        else:
            number=previous['attempt_number']+1 if previous else 1
            attempt=c.execute("insert into startup_radar.extraction_attempts(input_hash,attempt_number,source_id,state,owner_token,owner_identity,lease_expires_at) "
                "values(%s,%s,%s,'RUNNING',%s,%s,%s) returning id",
                (key,number,source_id,owner,Jsonb(owner_identity()),at+timedelta(seconds=LEASE_SECONDS))).fetchone()['id']
    if blocked:raise SourceFailure(blocked,'Identical extraction is pending or failure-cached; inspect its attempt before retrying')
    metadata.update(cache_hit=False,cache_status='MISS',input_hash=key,attempt_id=str(attempt),attempt=number)
    started=time.monotonic();failure=None;result=None
    try:result=extractor.extract(program,detail,documents,source_id)
    except SourceFailure as error:failure=error
    except Exception:failure=SourceFailure('AI_INTERNAL','Extraction failed locally; input retained for review')
    metadata.update(review_flags=getattr(extractor,'review_flags',[]),current_usage=getattr(extractor,'metrics',{'request_count':0}),
                    extraction_latency_ms=round((time.monotonic()-started)*1000))
    at=now()
    retryable=bool(failure and failure.retryable and failure.kind in TRANSIENT_FAILURES and number<MAX_ATTEMPTS)
    next_at=at+timedelta(minutes=15*4**(number-1)) if retryable else None
    metadata.update(status='FAILED' if failure else 'SUCCESS',error_kind=failure.kind if failure else None)
    with db.transaction() as c:
        updated=c.execute("update startup_radar.extraction_attempts set state=%s,metadata=%s,error_kind=%s,retryable=%s,next_retry_at=%s,finished_at=%s "
            "where id=%s and owner_token=%s and state='RUNNING' and lease_expires_at>%s returning id",
            ('FAILED' if failure else 'SUCCESS',Jsonb(metadata),failure.kind if failure else None,retryable,next_at,at,attempt,owner,at)).fetchone()
        if updated and not failure:
            c.execute('insert into startup_radar.extraction_cache(input_hash,normalized,metadata) values(%s,%s,%s)',
                      (key,Jsonb(result.model_dump(mode='json')),Jsonb(metadata)))
        if not updated:
            c.execute("update startup_radar.extraction_attempts set state='UNCERTAIN',error_kind='AI_OWNER_EXPIRED',finished_at=%s,metadata=%s "
                "where id=%s and owner_token=%s and state in ('RUNNING','UNCERTAIN')",(at,Jsonb(metadata),attempt,owner))
    if not updated:raise SourceFailure('AI_OWNER_EXPIRED','Extraction ownership expired; late result not accepted')
    if failure:raise failure
    return result


def request_extraction_retry(db,key,note,confirm_stopped=False):
    from radar.executions import LOCK_KEY
    if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('A recorded input hash is required')
    if not 5<=len(note.strip())<=500:raise ValueError('An operator reason of 5..500 characters is required')
    with db.transaction() as c:
        c.execute('select pg_advisory_xact_lock(%s)',(LOCK_KEY,))
        if c.execute('select 1 from startup_radar.worker_executions where finished_at is null').fetchone():
            raise ValueError('Recover the verified stopped batch owner first')
        c.execute('select pg_advisory_xact_lock(%s)',(int(key[:15],16),))
        row=c.execute('select * from startup_radar.extraction_attempts where input_hash=%s order by attempt_number desc limit 1 for update',(key,)).fetchone()
        if not row:raise ValueError('Extraction attempt not found')
        if row['state']=='SUCCESS':raise ValueError('Successful extraction does not need a retry')
        if row['state'] in ('RUNNING','UNCERTAIN') and not confirm_stopped:
            raise ValueError('Verify the recorded process/Actions owner is stopped and confirm explicitly')
        c.execute("update startup_radar.extraction_attempts set state=case when state='RUNNING' then 'UNCERTAIN' else state end, "
            'operator_retry_allowed=true where id=%s',(row['id'],))
        c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('EXTRACTION_RETRY_ALLOWED',%s,%s)",
            (str(row['id']),Jsonb({'input_hash':key,'previous_state':row['state'],'original_error':row['error_kind'],
                'reason':note.strip(),'operator':owner_identity(),'owner_termination_confirmed':confirm_stopped})))
    return {'status':'SUCCESS','attempt_id':str(row['id']),'retry_on_next_acquisition':True,'executed':False,'delivery':'DISABLED'}
