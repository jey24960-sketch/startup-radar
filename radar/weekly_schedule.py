"""Admin-selected Seoul calendar; one automatic attempt per publication week."""
from datetime import timedelta
from core.clock import SEOUL


def due_at(settings, at):
    if at.tzinfo is None:
        raise ValueError('Timezone-aware clock required')
    local = at.astimezone(SEOUL)
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday + timedelta(days=settings['weekday'], hours=settings['hour'], minutes=settings['minute'])


def scheduled_week(db, at, execution_id=None):
    """Read-only preflight, or committed attempt after acquiring the worker owner.

    Failures stay visible and require an explicit manual weekly run. Polling must
    not silently retry publication or an uncertain Telegram delivery.
    """
    with db.transaction() as c:
        settings = c.execute('select * from startup_radar.weekly_schedule where singleton' +
                             (' for update' if execution_id else '')).fetchone()
        if not settings or not settings['enabled'] or at < due_at(settings, at):
            return False
        local = at.astimezone(SEOUL)
        week = local.date() - timedelta(days=local.weekday())
        if c.execute('select 1 from startup_radar.weekly_schedule_attempts where week_start=%s', (week,)).fetchone():
            return False
        if c.execute("select 1 from startup_radar.weekly_briefings where week_start=%s and status='PUBLISHED'", (week,)).fetchone():
            return False
        if execution_id:
            return bool(c.execute('insert into startup_radar.weekly_schedule_attempts(week_start,execution_id,schedule_revision) '
                                  'values(%s,%s,%s) on conflict do nothing returning week_start',
                                  (week, execution_id, settings['revision'])).fetchone())
        return True
