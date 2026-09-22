// Evaluate the actual workflow condition over its string inputs, and exercise
// its shell argument construction without running Python, HTTP or collection.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const workflow=readFileSync(new URL('../.github/workflows/startup_radar_v2.yml',import.meta.url),'utf8');
const condition=workflow.match(/    if: >-\r?\n((?:      .+\r?\n)+)/)?.[1].trim();
assert.ok(condition,'The job gate must be explicit');
// This condition only uses ==, !=, && and || on strings/booleans, whose semantics
// agree for the exact lower-case values used by the workflow.
const allowed=new Function('github','vars','inputs',`return (${condition});`);

test('disabled-coordinator rollout preserves Tuesday 09:00 legacy execution and both emergency gates',()=>{
  assert.match(workflow,/- cron: '0 0 \* \* 2'/);
  assert.match(workflow,/group: startup-radar-v2-state/);
  assert.match(workflow,/cancel-in-progress: false/);
  assert.match(workflow,/timeout-minutes: 60/);
  for(const mode of ['', 'github', 'supabase']){
    for(const enabled of ['', 'false', 'true']){
      for(const event of ['schedule','workflow_dispatch']){
        for(const requestId of ['', '00000000-0000-0000-0000-000000000001']){
          const actual=Boolean(allowed({event_name:event},
            {RADAR_WEEKLY_SCHEDULER:mode,RADAR_V2_ENABLED:enabled},
            {scheduler_request_id:requestId}));
          const expected=event==='schedule'
            ? enabled==='true' && mode!=='supabase'
            : requestId==='' || (enabled==='true' && mode==='supabase');
          assert.equal(actual,expected,JSON.stringify({mode,enabled,event,requestId}));
        }
      }
    }
  }
});

const bash=process.platform==='win32' ? 'C:/Program Files/Git/bin/bash.exe' : '/bin/bash';
test('workflow forwards scheduler/manual arguments literally and rejects non-weekly scheduler inputs',
  {skip:!existsSync(bash)},()=>{
    const script=workflow.match(/      - name: Execute persistent V2 task[\s\S]*?        run: \|\r?\n([\s\S]*?)      - name: Remove interrupted evidence workers/)?.[1]
      .split(/\r?\n/).map(line=>line.replace(/^          /,'')).join('\n');
    assert.ok(script,'The exact production task script is exercised');
    const invoke=env=>spawnSync(bash,['-c',`python() { printf '%s\\0' "$@"; };\n${script}`],{
      encoding:'utf8',env:{...process.env,KIND:'WEEKLY',SOURCE_SLUG:'',JOB_ID:'',REVISION_NOTE:'',
        CHECK_SOURCES:'false',SCHEDULER_REQUEST_ID:'',EXPECTED_WEEK_START:'',DELIVERY_ENABLED:'false',...env}
    });
    let run=invoke({});
    assert.equal(run.status,0,run.stderr);
    assert.deepEqual(run.stdout.split('\0').filter(Boolean),['-m','radar.cli','weekly']);
    const literal='$(printf unsafe); newline\n"quoted"';
    run=invoke({SCHEDULER_REQUEST_ID:literal,EXPECTED_WEEK_START:'2026-09-21',DELIVERY_ENABLED:'true'});
    assert.equal(run.status,0,run.stderr);
    assert.deepEqual(run.stdout.split('\0').filter(Boolean),['-m','radar.cli','weekly',
      '--scheduler-request-id',literal,'--expected-week-start','2026-09-21','--deliver']);
    run=invoke({KIND:'REFRESH',SCHEDULER_REQUEST_ID:'request'});
    assert.equal(run.status,2);
    assert.equal(run.stdout.includes('radar.cli'),false);
    run=invoke({REVISION_NOTE:literal,CHECK_SOURCES:'true'});
    assert.deepEqual(run.stdout.split('\0').filter(Boolean),['-m','radar.cli','weekly','--check-sources','--revision-note',literal]);
  });
