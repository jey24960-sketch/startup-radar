"""Whether a member could still realistically act on a stored opportunity.

This is a publication gate only. Nothing here deletes, hides or rewrites a
program, a version or any source fact: an opportunity that fails the gate is
still collected, versioned and auditable, it is simply not put in front of
members as if it were actionable.

The reference timestamp is always supplied by the caller. Future weekly runs
pass their own publication time; the one-time correction of an already
published article passes that article's original publication/snapshot time, so
history is judged as it stood when it was published.
"""
from datetime import datetime, timedelta

# A member needs enough runway to read the notice, decide, prepare documents and
# apply. Anything under three days is not a usable weekly recommendation.
MINIMUM_APPLICATION_LEAD_TIME = timedelta(hours=72)

# Only these normalized deadline types are trusted to mean "still accepting"
# without an end date. UNKNOWN is never promoted to ongoing.
ONGOING_DEADLINE_TYPES = ('ROLLING', 'UNTIL_BUDGET_EXHAUSTED')

PUBLISHABLE_REASONS = ('ACTIONABLE', 'ONGOING')


def _aware(value):
    """Parse a stored editorial snapshot timestamp into an aware datetime."""
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        # A naive stored value cannot be compared safely against an aware clock.
        return None
    return parsed


def actionability(facts, at):
    """Return (publishable, reason) for one stored editorial snapshot.

    `facts` is the `weekly_briefing_items.snapshot` shape: application_start_at,
    application_end_at and deadline_type as normalized by the adapters. The
    date-only end normalization (end of the Seoul calendar day) is preserved as
    is; precision fields are never rewritten, so the member view keeps showing
    the date exactly as precisely as the source stated it.
    """
    if at is None or at.tzinfo is None:
        raise ValueError('Aware reference timestamp required for actionability')
    start = _aware(facts.get('application_start_at'))
    end = _aware(facts.get('application_end_at'))
    kind = facts.get('deadline_type')
    if end is not None and end <= at:
        return False, 'CLOSED'
    if start is not None and at < start:
        # Announced but not yet open. Stored, but not presented as actionable now.
        return False, 'UPCOMING'
    if end is None:
        if kind in ONGOING_DEADLINE_TYPES:
            return True, 'ONGOING'
        # No trusted end and no trusted ongoing type. Never inferred from prose.
        return False, 'DEADLINE_UNKNOWN'
    if end - at < MINIMUM_APPLICATION_LEAD_TIME:
        return False, 'NEAR_DEADLINE'
    return True, 'ACTIONABLE'


def publishable(facts, at):
    return actionability(facts, at)[0]
