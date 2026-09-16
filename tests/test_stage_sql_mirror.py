"""The checked-in stage SQL mirror must never drift from radar/stage.py."""
import io
from pathlib import Path

from tools.export_stage_sql import generate, sql_regex

MIRROR = Path(__file__).resolve().parents[1] / 'supabase' / 'migrations' / '20260916135500_gfc_stage_backfill_function.sql'


def test_sql_mirror_is_exactly_what_the_generator_produces():
    assert io.open(MIRROR, encoding='utf-8').read() == generate(), (
        'stage SQL mirror is stale; regenerate with: python -m tools.export_stage_sql > <that file>')


def test_mirror_carries_every_rule_and_label():
    from radar import stage
    committed = io.open(MIRROR, encoding='utf-8').read()
    for code, label in stage.STAGES:
        assert f"('{code}','{label}')" in committed
    for code in stage.SIGNALS:
        for _, compiled in stage.SIGNALS[code]:
            assert sql_regex(compiled.pattern) in committed
    # Postgres ARE spells the word boundary \y; a stray \b would silently stop matching.
    assert '\\b' not in committed
