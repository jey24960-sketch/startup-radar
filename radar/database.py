"""Transactional PostgreSQL repository; no JSON/cache primary state in V2."""
import os
from contextlib import contextmanager,nullcontext
from contextvars import ContextVar
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from radar.models import TeamProfile, Program
from radar.identity import normalize_url,normalize_text,digest,changed_fields,duplicate_confidence
from radar.dates import program_status

_CURRENT_OBSERVATION=object()

class Database:
    def __init__(self,url=None):
        self.url=url or os.environ.get('DATABASE_URL')
        if not self.url: raise ValueError('DATABASE_URL is required')
        self._session_connection=ContextVar('radar_database_session',default=None)

    @contextmanager
    def session(self):
        """Reuse a connection inside one synchronous, deterministic batch only."""
        if self._session_connection.get() is not None:
            yield self
            return
        with psycopg.connect(self.url,row_factory=dict_row,prepare_threshold=None) as connection:
            token=self._session_connection.set(connection)
            try:yield self
            finally:self._session_connection.reset(token)

    @contextmanager
    def transaction(self,user_id=None):
        borrowed=self._session_connection.get()
        # A nested actor operation is a separate transaction, not a savepoint:
        # SET LOCAL role/JWT would otherwise survive savepoint release.
        if borrowed is not None and borrowed.info.transaction_status!=psycopg.pq.TransactionStatus.IDLE:
            borrowed=None
        with (nullcontext(borrowed) if borrowed is not None else psycopg.connect(self.url,row_factory=dict_row,prepare_threshold=None)) as connection:
            with connection.transaction():
                connection.execute("set local timezone='Asia/Seoul'")
                if user_id:
                    connection.execute('set local role authenticated')
                    connection.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(user_id),))
                yield connection

    def create_team(self,name,owner_id,profile=None):
        # Privileged invitation/bootstrap operation. Never exposed anonymously.
        profile=profile or TeamProfile()
        with self.transaction() as c:
            team=c.execute('insert into startup_radar.teams(name) values(%s) returning *',(name,)).fetchone()
            c.execute("insert into startup_radar.team_members(team_id,user_id,role) values(%s,%s,'OWNER')",(team['id'],owner_id))
            c.execute('insert into startup_radar.team_profiles(team_id,profile) values(%s,%s)',(team['id'],Jsonb(profile.model_dump(mode='json'))))
            return team

    def save_profile(self,team_id,profile,user_id,expected_version):
        with self.transaction(user_id) as c:
            current=c.execute('select * from startup_radar.team_profiles where team_id=%s for update',(team_id,)).fetchone()
            if not current: raise PermissionError('Team is not accessible')
            if current['version']!=expected_version: raise ValueError('Profile changed; refresh before editing')
            row=c.execute('update startup_radar.team_profiles set profile=%s,version=version+1,updated_at=now() where team_id=%s returning *',
                          (Jsonb(profile.model_dump(mode='json')),team_id)).fetchone()
            if not row: raise PermissionError('Editing requires owner/editor membership')
            return row

    def upsert_source(self,slug,name,adapter,config):
        with self.transaction() as c:
            return c.execute('insert into startup_radar.sources(slug,name,adapter,config) values(%s,%s,%s,%s) '
              'on conflict(slug) do update set name=excluded.name,adapter=excluded.adapter,config=excluded.config returning *',
              (slug,name,adapter,Jsonb(config))).fetchone()

    def save_program(self,program:Program,source_id,source_program_id,discovery_url,raw_metadata,raw_text='',documents=None,extraction_metadata=None,expected_version_id=None,connection=None,source_observed_at=_CURRENT_OBSERVATION):
        from radar.ocr import review_metadata
        from radar.quality import save_assessment
        extraction_metadata=review_metadata(documents,extraction_metadata)
        normal=program.model_dump(mode='json'); canonical_url=normalize_url(program.official_url)
        fingerprint=digest({'normalized':normal,'raw':raw_text,'documents':[
            {key:doc.get(key) for key in ('original_url','content_hash','fetch_status','extraction_status','extracted_text')}
            for doc in sorted(documents or [],key=lambda doc:doc['original_url'])]})
        with (self.transaction() if connection is None else nullcontext(connection)) as c:
            # One transaction-scoped lock serializes canonical matching/versioning.
            # Ingestion stays concurrent outside this short database critical section.
            c.execute('select pg_advisory_xact_lock(782394201)')
            existing=c.execute('select p.* from startup_radar.program_sources s join startup_radar.programs p on p.id=s.program_id '
                'where s.source_id=%s and s.source_program_id=%s',
                (source_id,source_program_id)).fetchone() if source_program_id is not None else c.execute(
                'select p.* from startup_radar.program_sources s join startup_radar.programs p on p.id=s.program_id '
                'where s.source_id=%s and s.source_program_id is null and s.discovery_url=%s',
                (source_id,discovery_url)).fetchone()
            url_candidates=[]
            if not existing:
                url_candidates=c.execute('select p.* from startup_radar.programs p where exists '
                    '(select 1 from startup_radar.program_sources s where s.program_id=p.id and s.official_detail_url=%s)',(canonical_url,)).fetchall()
                matches=[]
                for candidate in url_candidates:
                    conflict=source_program_id is not None and c.execute(
                        'select 1 from startup_radar.program_sources where program_id=%s and source_id=%s '
                        'and source_program_id is not null and source_program_id<>%s limit 1',
                        (candidate['id'],source_id,source_program_id)).fetchone()
                    same_notice=(normalize_text(candidate['title'])==normalize_text(program.title)
                        and normalize_text(candidate['organization'])==normalize_text(program.organization))
                    if not conflict and same_notice:matches.append(candidate)
                # A shared URL is only corroboration, never an override of publisher IDs.
                if len(matches)==1:existing=matches[0]
            candidates=[]
            if not existing:
                # No fuzzy auto-merge. Keep possible relationships for human review.
                candidates=c.execute('select id,title,organization,official_url from startup_radar.programs where organization=%s',(program.organization,)).fetchall()
                candidates=list({row['id']:row for row in candidates+url_candidates}.values())
                identity={'source_id':str(source_id),'source_program_id':source_program_id} if source_program_id is not None else {
                    'source_id':str(source_id),'discovery_url':discovery_url}
                existing=c.execute('insert into startup_radar.programs(canonical_key,title,organization,program_types,status,deadline_type,official_url) '
                    'values(%s,%s,%s,%s,%s,%s,%s) returning *',
                    (digest(identity),program.title,program.organization,program.program_types,program_status(program),program.deadline_type,program.official_url)).fetchone()
            pid=existing['id']
            c.execute('insert into startup_radar.program_sources(program_id,source_id,source_program_id,discovery_url,official_detail_url,raw_metadata) '
                'values(%s,%s,%s,%s,%s,%s) on conflict(source_id,discovery_url) where source_program_id is null do update set last_seen_at=now(),official_detail_url=excluded.official_detail_url,raw_metadata=excluded.raw_metadata',
                (pid,source_id,source_program_id,discovery_url,canonical_url,Jsonb(raw_metadata))) if source_program_id is None else c.execute(
                'insert into startup_radar.program_sources(program_id,source_id,source_program_id,discovery_url,official_detail_url,raw_metadata) '
                'values(%s,%s,%s,%s,%s,%s) on conflict(source_id,source_program_id) do update set last_seen_at=now(),discovery_url=excluded.discovery_url,official_detail_url=excluded.official_detail_url,raw_metadata=excluded.raw_metadata',
                (pid,source_id,source_program_id,discovery_url,canonical_url,Jsonb(raw_metadata)))
            previous=c.execute('select * from startup_radar.program_versions where id=%s',(existing['current_version_id'],)).fetchone() if existing['current_version_id'] else None
            if expected_version_id is not None and (not previous or str(previous['id'])!=str(expected_version_id)):
                raise ValueError('Program changed while reviewing; inspect the latest evidence')
            if previous and previous['content_hash']==fingerprint:
                # Dates can close a notice without a new content version.
                c.execute('update startup_radar.programs set status=%s,updated_at=now() where id=%s',(program_status(program),pid))
                self._snapshot(c,pid,previous['id'],source_id,source_program_id,discovery_url,program.official_url,raw_metadata,raw_text,extraction_metadata,source_observed_at)
                save_assessment(c,previous['id'],program,documents,extraction_metadata,raw_text)
                return {'program_id':pid,'version_id':previous['id'],'event':None}
            version=c.execute('insert into startup_radar.program_versions(program_id,version,content_hash,normalized,raw_text,evidence_complete) '
                'values(%s,%s,%s,%s,%s,%s) returning *',(pid,previous['version']+1 if previous else 1,fingerprint,Jsonb(normal),raw_text,program.evidence_complete)).fetchone()
            vid=version['id']
            self._snapshot(c,pid,vid,source_id,source_program_id,discovery_url,program.official_url,raw_metadata,raw_text,extraction_metadata,source_observed_at)
            c.execute('update startup_radar.programs set title=%s,organization=%s,program_types=%s,status=%s,application_start_at=%s,application_end_at=%s,'
                'deadline_type=%s,official_url=%s,application_url=%s,applicant_summary=%s,support_summary=%s,benefit_summary=%s,'
                'amount_min=%s,amount_max=%s,currency=%s,current_version_id=%s,updated_at=now() where id=%s',
                (program.title,program.organization,program.program_types,program_status(program),program.application_start_at,program.application_end_at,
                 program.deadline_type,program.official_url,program.application_url,program.applicant_summary,program.support_summary,program.benefit_summary,
                 program.amount_min,program.amount_max,program.currency,vid,pid))
            document_ids={}
            for doc in documents or []:
                saved=c.execute('insert into startup_radar.documents(program_version_id,original_url,filename,detected_mime,content_hash,fetch_status,extraction_status,extracted_text,error_kind,error_message,fetched_at) '
                    'values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id',(vid,doc['original_url'],doc['filename'],doc.get('detected_mime'),doc.get('content_hash'),
                    doc['fetch_status'],doc['extraction_status'],doc.get('extracted_text'),doc.get('error_kind'),doc.get('error_message'),doc.get('fetched_at'))).fetchone()
                if doc.get('content_hash'):document_ids[doc['content_hash']]=saved['id']
            for rule in program.requirements:
                # Evidence retains stable content hashes; the first referenced document
                # also has a version-constrained relational FK for trace queries.
                doc_id=next((document_ids[e.document_id] for e in rule.evidence if e.document_id in document_ids),None)
                c.execute('insert into startup_radar.program_requirements(program_version_id,document_id,requirement) values(%s,%s,%s)',(vid,doc_id,Jsonb(rule.model_dump(mode='json'))))
            changed=changed_fields(previous['normalized'],normal) if previous else list(normal)
            event='UPDATE' if previous else 'NEW'
            if changed:
                c.execute('insert into startup_radar.program_change_events(program_id,version_id,event_type,changed_fields) values(%s,%s,%s,%s)',(pid,vid,event,changed))
            for candidate in candidates:
                confidence=duplicate_confidence(dict(candidate),normal)
                if confidence>=0.8:
                    c.execute('insert into startup_radar.possible_duplicates(program_id,candidate_program_id,confidence,reason) values(%s,%s,%s,%s) on conflict do nothing',
                              (pid,candidate['id'],confidence,'Shared URL or similar title/organization; publisher IDs and ambiguity require review'))
            save_assessment(c,vid,program,documents,extraction_metadata,raw_text)
            return {'program_id':pid,'version_id':vid,'event':event if changed else None}

    @staticmethod
    def _snapshot(c,pid,vid,source_id,source_program_id,discovery_url,detail_url,raw_metadata,raw_text,extraction_metadata,source_observed_at=_CURRENT_OBSERVATION):
        source=c.execute('select adapter,config from startup_radar.sources where id=%s',(source_id,)).fetchone()
        source_config={'adapter':source['adapter'],'config':source['config']}
        observation={'source_program_id':source_program_id,'discovery_url':discovery_url,'official_detail_url':detail_url,
                     'raw_metadata':raw_metadata,'source_config':source_config,'detail_hash':digest(raw_text),'extraction_metadata':extraction_metadata or {}}
        c.execute('insert into startup_radar.program_source_snapshots(program_id,program_version_id,source_id,source_program_id,discovery_url,official_detail_url,raw_metadata,source_config,detail_hash,observation_hash,extraction_metadata) '
                  'values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing',
                  (pid,vid,source_id,source_program_id,discovery_url,detail_url,Jsonb(raw_metadata),Jsonb(source_config),digest(raw_text),digest(observation),Jsonb(extraction_metadata or {})))
        # Deduplication does not suppress a real re-observation. Conversely,
        # reviewing stored evidence inherits its clock instead of claiming a fetch.
        current=source_observed_at is _CURRENT_OBSERVATION
        c.execute('update startup_radar.program_versions set last_observed_at=greatest(last_observed_at,case when %s then now() else %s::timestamptz end) where id=%s',
                  (current,None if current else source_observed_at,vid))
