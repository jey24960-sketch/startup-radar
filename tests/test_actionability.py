"""Minimum application lead time. No database required."""
from datetime import datetime, timedelta

import pytest
from core.clock import SEOUL
from radar.actionability import MINIMUM_APPLICATION_LEAD_TIME, actionability

AT = datetime(2026, 9, 15, 15, tzinfo=SEOUL)


def facts(end=None, start=None, kind='FIXED_DATE', **extra):
    return {'title': 'Official notice', 'application_start_at': start.isoformat() if start else None,
            'application_end_at': end.isoformat() if end else None, 'deadline_type': kind, **extra}


def test_minimum_lead_time_is_72_hours():
    assert MINIMUM_APPLICATION_LEAD_TIME == timedelta(hours=72)


def test_already_expired_is_never_published():
    assert actionability(facts(AT - timedelta(seconds=1)), AT) == (False, 'CLOSED')
    assert actionability(facts(AT - timedelta(days=30)), AT) == (False, 'CLOSED')
    # The boundary itself is closed: no remaining time is not actionable.
    assert actionability(facts(AT), AT) == (False, 'CLOSED')


@pytest.mark.parametrize('remaining', [timedelta(hours=24), timedelta(hours=48),
                                       timedelta(hours=71, minutes=59)])
def test_near_deadline_is_withheld(remaining):
    assert actionability(facts(AT + remaining), AT) == (False, 'NEAR_DEADLINE')


def test_exactly_seventy_two_hours_passes():
    assert actionability(facts(AT + timedelta(hours=72)), AT) == (True, 'ACTIONABLE')
    assert actionability(facts(AT + timedelta(hours=72, seconds=1)), AT) == (True, 'ACTIONABLE')


def test_unknown_deadline_without_trusted_ongoing_type_is_withheld():
    assert actionability(facts(None, kind='UNKNOWN'), AT) == (False, 'DEADLINE_UNKNOWN')
    assert actionability(facts(None, kind='FIXED_DATE'), AT) == (False, 'DEADLINE_UNKNOWN')


@pytest.mark.parametrize('kind', ['ROLLING', 'UNTIL_BUDGET_EXHAUSTED'])
def test_trusted_ongoing_acceptance_may_publish_without_an_end_date(kind):
    assert actionability(facts(None, kind=kind), AT) == (True, 'ONGOING')


def test_announced_but_not_yet_open_is_withheld():
    upcoming = facts(AT + timedelta(days=90), start=AT + timedelta(days=10))
    assert actionability(upcoming, AT) == (False, 'UPCOMING')
    # Already open with the same generous deadline is actionable.
    assert actionability(facts(AT + timedelta(days=90), start=AT - timedelta(days=1)), AT)[0]


def test_rolling_program_that_has_not_opened_yet_is_still_withheld():
    assert actionability(facts(None, start=AT + timedelta(days=3), kind='ROLLING'), AT) == (False, 'UPCOMING')


def test_date_only_deadline_keeps_its_precision_and_is_not_mutated():
    # The end-of-Seoul-day normalization is an internal comparison aid. It must
    # not be re-stated to members as an exact official time.
    row = facts(datetime(2026, 9, 30, 23, 59, 59, 999999, tzinfo=SEOUL),
                application_end_precision='DATE')
    before = dict(row)
    assert actionability(row, AT) == (True, 'ACTIONABLE')
    assert row == before
    assert row['application_end_precision'] == 'DATE'


def test_unparsable_or_naive_timestamps_never_silently_pass():
    assert actionability(facts(None) | {'application_end_at': 'not-a-date'}, AT) == (False, 'DEADLINE_UNKNOWN')
    assert actionability(facts(None) | {'application_end_at': '2026-12-01T00:00:00'}, AT) == (False, 'DEADLINE_UNKNOWN')


def test_reference_timestamp_must_be_aware():
    with pytest.raises(ValueError):
        actionability(facts(AT + timedelta(days=30)), AT.replace(tzinfo=None))
