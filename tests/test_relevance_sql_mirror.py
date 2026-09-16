"""The checked-in SQL mirror must never drift from radar/relevance.py.

The weekly publication path uses the Python classifier. The SQL function only
exists so an operator can classify already-stored program versions without
re-running collection. Two implementations are only safe while one is generated
from the other, so this test fails the build if the file is edited by hand or
if the rule tables change without regenerating.
"""
import io
from pathlib import Path

from tools.export_relevance_sql import generate

MIRROR = Path(__file__).resolve().parents[1] / 'supabase' / 'migrations' / '20260916121000_gfc_relevance_backfill_function.sql'


def test_sql_mirror_is_exactly_what_the_generator_produces():
    committed = io.open(MIRROR, encoding='utf-8').read()
    assert committed == generate(), (
        'supabase/migrations/20260916121000_gfc_relevance_backfill_function.sql is stale. '
        'Regenerate with: python -m tools.export_relevance_sql > <that file>')


def test_mirror_carries_every_rule():
    from radar import relevance
    committed = io.open(MIRROR, encoding='utf-8').read()
    tables = (relevance.HARD_EXCLUSION, relevance.CORE_STARTUP, relevance.GENERIC_SOFT_EXCLUSION,
              relevance.EVENT_SOFT_EXCLUSION, relevance.DELIVERABLE, relevance.RESTRICTION)
    for table in tables:
        for label, _ in table:
            assert label.replace("'", "''") in committed, f'rule {label!r} missing from the SQL mirror'


def test_word_boundaries_are_translated_to_posix():
    committed = io.open(MIRROR, encoding='utf-8').read()
    # Postgres ARE spells the word boundary \y; a stray \b would silently
    # become a backspace class and quietly stop matching.
    assert '\\y' in committed
    assert '\\b' not in committed
