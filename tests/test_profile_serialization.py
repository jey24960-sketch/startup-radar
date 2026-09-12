"""Persisted profile/cache identities must survive process restarts."""
import json
import os
from pathlib import Path
import subprocess
import sys

from radar.models import TeamProfile, apply_preset, update_profile


def test_preset_json_and_cache_keys_are_stable_across_hash_seeds():
    code = '''
import json
from radar.models import TeamProfile, apply_preset
from radar.identity import digest
profiles = [apply_preset(TeamProfile(), i) for i in range(5)]
print(json.dumps([{'profile': p.model_dump(mode='json'), 'key': digest(p.model_dump(mode='json')),
                  'json': p.model_dump_json()} for p in profiles]))
'''
    outputs = [json.loads(subprocess.check_output(
        [sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, 'PYTHONHASHSEED': seed}, text=True, encoding='utf-8', timeout=30
    )) for seed in ('1', '2', '3')]
    assert outputs[0] == outputs[1] == outputs[2]


def test_serialization_keeps_explicit_values_and_preset_edit_semantics():
    old = apply_preset(TeamProfile(), 0).model_dump(mode='json')
    old['assumed_fields'].reverse()  # Existing snapshots need no data migration.
    profile = TeamProfile.model_validate(old)
    assert isinstance(profile.model_dump()['assumed_fields'], set)
    changed = update_profile(profile, {'business_status': 'CORPORATION'})
    switched = apply_preset(TeamProfile.model_validate_json(changed.model_dump_json()), 2)
    assert switched.business_status == 'CORPORATION'
    assert switched.product_stage == 'LANDING'
    assert 'business_status' not in switched.assumed_fields
    assert switched.region is None
