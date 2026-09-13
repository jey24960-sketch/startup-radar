from datetime import datetime
import pytest
from core.clock import SEOUL
from radar.scheduler import due_tasks


def test_daily_ingestion_independent_from_weekly_delivery():
    t=datetime(2026,9,15,6,17,tzinfo=SEOUL)
    assert [k for k,_ in due_tasks({},t)]==['INGEST']
    assert [k for k,_ in due_tasks({},t.replace(hour=15))]==['INGEST','DIGEST','REMINDER']
    assert [k for k,_ in due_tasks({},t.replace(day=16,hour=15))]==['INGEST','REMINDER']


def test_cadence_stop_and_timezone():
    t=datetime(2026,9,15,16,tzinfo=SEOUL)
    assert due_tasks({'enabled':False},t)==[]
    assert [k for k,_ in due_tasks({'ingestion_enabled':False,'digest_weekday':2,'reminder_hour':17},t)]==[]
    with pytest.raises(ValueError):due_tasks({},t.replace(tzinfo=None))
