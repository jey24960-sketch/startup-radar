import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { PGlite } from '@electric-sql/pglite';

const migration = new URL('../supabase/migrations/20261026185312_radar_relevance_v12.sql', import.meta.url);
const sourceCases = JSON.parse(await readFile(new URL('./fixtures/relevance_omissions_20261027.json', import.meta.url), 'utf8'));

test('relevance v1.2 SQL recognises omitted official source programs and preserves exclusions', async () => {
  const db = new PGlite();
  try {
    await db.exec('create schema startup_radar; create role anon; create role authenticated; create role service_role;');
    await db.exec(await readFile(migration, 'utf8'));
    const classify = async (title, applicant = '', support = '') => {
      const result = await db.query('select startup_radar.gfc_relevance_v1_2($1,$2,$3) as decision', [title, applicant, support]);
      return result.rows[0].decision;
    };
    for (const row of sourceCases) {
      const decision = await classify(row.title, row.applicant_summary, row.support_summary);
      assert.ok(['GFC_RELEVANT', 'CONDITIONAL'].includes(decision.relevance_status), row.title);
    }
    assert.equal((await classify('모집')).relevance_status, 'OUT_OF_SCOPE');
    const uncertain = await classify('혁신 스타트업 지원 프로그램 모집', '서울시 소재 창업기업');
    assert.equal(uncertain.relevance_status, 'REVIEW_REQUIRED');
    assert.equal(uncertain.restriction_summary, '서울시 소재 기업');
    assert.equal((await classify('스타트업 MVP 제작 인턴 모집')).relevance_status, 'OUT_OF_SCOPE');
    assert.equal((await classify('지역 제조공정 개선 지원사업', '', '기존 제조기업의 실증 및 설비 개선 지원')).relevance_status, 'OUT_OF_SCOPE');
    assert.equal((await classify('스타트업 성공 사례 공유 특강')).relevance_status, 'OUT_OF_SCOPE');
    assert.equal((await classify('복합 쇼핑몰 입점자 모집')).relevance_status, 'OUT_OF_SCOPE');
    assert.equal((await classify('기업 AIR 시스템 지원사업')).relevance_status, 'OUT_OF_SCOPE');
    assert.equal((await classify('소상공인 카드수수료 지원 및 액셀러레이팅 배치 프로그램 모집')).relevance_status, 'REVIEW_REQUIRED');
  } finally {
    await db.close();
  }
});
