from datetime import datetime, time
from core.clock import SEOUL, now
from radar.models import Program


def program_status(program: Program, at: datetime | None=None):
    at=at or now()
    if at.tzinfo is None: raise ValueError('Aware timestamp required')
    if program.application_end_at and at>program.application_end_at: return 'CLOSED'
    if program.application_start_at and at<program.application_start_at: return 'UPCOMING'
    if program.deadline_type in ('ROLLING','UNTIL_BUDGET_EXHAUSTED'): return 'OPEN'
    if program.application_end_at: return 'OPEN'
    return 'UNKNOWN'


def days_left(program: Program, at: datetime | None=None):
    at=at or now()
    if at.tzinfo is None: raise ValueError('Aware timestamp required')
    if not program.application_end_at: return None
    return (program.application_end_at.astimezone(SEOUL).date()-at.astimezone(SEOUL).date()).days


def korean_date(value: str, end=False):
    day=datetime.strptime(value.replace('-','').replace('.',''),'%Y%m%d').date()
    return datetime.combine(day,time.max if end else time.min,SEOUL)
