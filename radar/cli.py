"""V2 operations CLI. Importing or asking for help never requires secrets."""
import argparse
import json
import os
from pathlib import Path
from uuid import UUID
from radar.database import Database
from radar.models import TeamProfile,apply_preset
from radar.notifications import TelegramTransport
from radar.scheduler import run_job


def main(argv=None):
    parser=argparse.ArgumentParser(description='StartupRadar V2 PostgreSQL operations')
    commands=parser.add_subparsers(dest='command',required=True)
    weekly=commands.add_parser('weekly',help='Collect official APIs and publish one Seoul-week briefing; no AI, OCR or team calculation')
    weekly.add_argument('--draft',action='store_true',help='Regenerate unpublished draft only')
    weekly.add_argument('--deliver',action='store_true',help='Announce a published briefing to existing enabled subscribers only')
    weekly.add_argument('--check-sources',action='store_true',help='Recheck the bounded official sources without rewriting an already published issue')
    weekly.add_argument('--revision-note',help='Explicitly recollect and revise the current published issue, keeping its ID and prior-item audit; never duplicates announcements')
    seed=commands.add_parser('seed-sources');seed.add_argument('--file',default='sources.json')
    bootstrap=commands.add_parser('bootstrap-team');bootstrap.add_argument('--user-id',type=UUID,required=True)
    bootstrap.add_argument('--name',default='GFC');bootstrap.add_argument('--admin',action='store_true')
    run=commands.add_parser('run');run.add_argument('--kind',choices=['INGEST','DIGEST','REMINDER','HIGH_FIT','TICK','REFRESH'],default='TICK')
    run.add_argument('--source');run.add_argument('--job-id');run.add_argument('--deliver',action='store_true',help='Actually send Telegram; default is disabled')
    comparison=commands.add_parser('compare');comparison.add_argument('--v1',required=True);comparison.add_argument('--team-id',type=UUID,required=True)
    comparison.add_argument('--output',required=True)
    commands.add_parser('execution-status',help='Inspect the durable active batch owner')
    quality=commands.add_parser('quality-report',help='Current-version evidence quality, reasons and prioritized review queue')
    quality.add_argument('--refresh',action='store_true',help='Reassess stored official evidence only; no AI, network or delivery')
    retry=commands.add_parser('retry-ingest',help='Queue an explicit auditable ingestion retry; never delivers notifications')
    retry.add_argument('--task-key',required=True)
    retry.add_argument('--note',required=True)
    extraction_retry=commands.add_parser('retry-extraction',help='Authorize one changed-condition retry of an exact failed input; no immediate AI call')
    extraction_retry.add_argument('--input-hash',required=True);extraction_retry.add_argument('--note',required=True)
    extraction_retry.add_argument('--confirm-stopped',action='store_true')
    recovery=commands.add_parser('recover-execution',help='Release a verified stopped owner; never dispatches a retry')
    recovery.add_argument('--execution-id',type=UUID,required=True)
    recovery.add_argument('--note',required=True)
    recovery.add_argument('--confirm-stopped',action='store_true',help='Affirm the recorded process/Actions run is terminal, not just disconnected')
    args=parser.parse_args(argv);db=Database()
    if args.command=='weekly':
        from radar.weekly import run_weekly
        transport=None
        if args.deliver:
            token=os.environ.get('TELEGRAM_BOT_TOKEN')
            if not token:raise ValueError('TELEGRAM_BOT_TOKEN is required for --deliver')
            transport=TelegramTransport(token)
        result=run_weekly(db,transport,publish=not args.draft,revision_note=args.revision_note,check_sources=args.check_sources)
    elif args.command=='quality-report':
        from radar.quality import refresh_quality,quality_report
        if args.refresh:refresh_quality(db)
        result=quality_report(db)
    elif args.command=='execution-status':
        from radar.executions import active_execution
        result={'status':'SUCCESS','active_execution':active_execution(db)}
    elif args.command=='retry-ingest':
        from radar.schedule_attempts import request_ingest_retry
        result=request_ingest_retry(db,args.task_key,args.note)
    elif args.command=='retry-extraction':
        from radar.analysis_cache import request_extraction_retry
        result=request_extraction_retry(db,args.input_hash,args.note,args.confirm_stopped)
    elif args.command=='recover-execution':
        from radar.executions import recover_execution
        result=recover_execution(db,args.execution_id,args.note,args.confirm_stopped)
    elif args.command=='seed-sources':
        rows=json.loads(Path(args.file).read_text(encoding='utf-8'))
        for row in rows:
            source=db.upsert_source(row['slug'],row['name'],row['adapter'],row['config'])
            with db.transaction() as c:c.execute('update startup_radar.sources set enabled=%s where id=%s',(row.get('enabled',True),source['id']))
        result={'status':'SUCCESS','registered':len(rows)}
    elif args.command=='bootstrap-team':
        with db.transaction() as c:
            if not c.execute('select 1 from auth.users where id=%s',(args.user_id,)).fetchone():raise ValueError('Invite/create the Supabase Auth user first')
            if c.execute('select 1 from startup_radar.team_members where user_id=%s',(args.user_id,)).fetchone():raise ValueError('User already belongs to a team; use the administrator API to add another')
        team=db.create_team(args.name,args.user_id,apply_preset(TeamProfile(),0))
        if args.admin:
            with db.transaction() as c:c.execute('insert into startup_radar.admin_users(user_id) values(%s) on conflict do nothing',(args.user_id,))
        result={'status':'SUCCESS','team_id':str(team['id'])}
    elif args.command=='compare':
        from radar.parallel import v2_snapshot,compare
        v1=json.loads(Path(args.v1).read_text(encoding='utf-8'))
        report=compare(v1,v2_snapshot(db,args.team_id))
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        result={'status':'SUCCESS','report':str(Path(args.output).resolve()),'counts':report['counts'],'cutover_approved':False}
    else:
        transport=None
        if args.deliver:
            token=os.environ.get('TELEGRAM_BOT_TOKEN')
            if not token:raise ValueError('TELEGRAM_BOT_TOKEN is required for --deliver')
            transport=TelegramTransport(token)
        result=run_job(db,args.kind,args.source or None,args.job_id or None,transport)
    print(json.dumps(result,ensure_ascii=False,default=str))
    return 0 if result['status']=='SUCCESS' else 1


if __name__=='__main__':raise SystemExit(main())
