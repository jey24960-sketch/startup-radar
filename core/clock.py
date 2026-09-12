"""Business time is always Asia/Seoul, independent of runner timezone."""
from datetime import datetime
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")


def now():
    return datetime.now(SEOUL)


def today():
    return now().date()
