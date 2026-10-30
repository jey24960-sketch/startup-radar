import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { PGlite } from '@electric-sql/pglite';

const migration = new URL('../supabase/migrations/20261030135830_radar_curated_relevance_v13.sql', import.meta.url);
const sourceCases = JSON.parse(await readFile(new URL('./fixtures/relevance_omissions_20261027.json', import.meta.url), 'utf8'));
const auditCases = JSON.parse(await readFile(new URL('./fixtures/relevance_audit_20261027.json', import.meta.url), 'utf8'));

test('relevance v1.3 SQL recognises omitted official source programs and preserves exclusions', async () => {
  const db = new PGlite();
  try {
    await db.exec('create schema startup_radar; create role anon; create role authenticated; create role service_role;');
    await db.exec(await readFile(migration, 'utf8'));
    const classify = async (title, applicant = '', support = '') => {
      const result = await db.query('select startup_radar.gfc_relevance_v1_3($1,$2,$3) as decision', [title, applicant, support]);
      return result.rows[0].decision;
    };
    for (const row of sourceCases) {
      const decision = await classify(row.title, row.applicant_summary, row.support_summary);
      assert.ok(['GFC_RELEVANT', 'CONDITIONAL'].includes(decision.relevance_status), row.title);
    }
    for (const row of auditCases) {
      const decision = await classify(row.title, row.applicant_summary, row.support_summary);
      assert.equal(decision.relevance_status, row.expected_status, `audit #${row.number}: ${row.title}`);
      assert.equal(decision.restriction_summary, row.expected_restriction, `audit #${row.number} restriction`);
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
    const runningMate = await classify('예비 초기 스타트업을 위한 창업 교육 프로그램 러닝메이트 9기 모집',
      '극초기 창업팀(예비창업가 또는 법인 3년 이내)\n제외대상\n별도 신청 제한은 없으나, 바이오·소부장 분야의 경우 프로그램 커리큘럼 적합성을 충분히 검토한 후 신청하기를 권장 드립니다.',
      '무료 5주간 온라인 학습과 과제 제출, 창업가들과 피어피드백, 네트워킹 파티와 멘토링을 제공합니다.');
    assert.equal(runningMate.relevance_status, 'GFC_RELEVANT');
    assert.equal(runningMate.restriction_summary, null);
    for (const support of ['바이오 분야 전문가 멘토링을 제공합니다.',
      '반도체 전문 투자사에서 멘토로 참여합니다.', '한국관광공사에서 창업기업의 사업화를 지원합니다.']) {
      assert.equal((await classify('예비창업자 액셀러레이팅 모집', '분야 무관 예비창업자', support)).relevance_status, 'GFC_RELEVANT');
    }
    for (const applicant of ['바이오·헬스케어 분야 창업기업', '반도체 분야에서 투자를 희망하는 국내 창업기업',
      '바이오 분야 스타트업만 신청 가능하며, 지역 제한은 없습니다.', '바이오 분야 창업기업이며 지역 제한은 없습니다.']) {
      const restricted = await classify('예비창업자 액셀러레이팅 모집', applicant);
      assert.equal(restricted.relevance_status, 'CONDITIONAL');
      assert.equal(restricted.restriction_summary, '특정 산업 분야 한정');
    }
    for (const [title, applicant, support, expected] of [
      ['[온라인·무료] 예비창업자 실행 교육 모집', '사업자 등록 필요 없음, 분야 무관 예비창업자', '시제품 제작 과제 수행', null],
      ['[모집공고] 예비창업팀 시제품 제작 지원', '예비창업팀', '', null],
      ['캠퍼스 액셀러레이팅 모집', '분야 무관 학생창업팀', '바이오·헬스케어 기업 투자 사례와 반도체 창업기업 사례 소개', null],
      ['[충남] 액셀러레이팅 프로그램 모집', '도내 소재 기업', '', '충남 소재 기업'],
      ['[충남] 액셀러레이팅 프로그램 모집', '전국 예비창업팀 누구나', '', null],
      ['액셀러레이팅 모집', '개인, 팀, 기업 누구나\n호남지역 소재 기업 가점', '', null],
      ['액셀러레이팅 모집', '법인 설립 필수 아님\n수출 실적 우대', '', null],
      ['액셀러레이팅 모집', '만 40세 이상 예비창업자', '', '중장년 연령 조건'],
      ['액셀러레이팅 모집', '전체', '신청대상: 반도체 분야 창업기업', '특정 산업 분야 한정'],
      ['액셀러레이팅 모집', '분야 무관 창업팀', '☞ 기업당 최대 5천만원 사업화 지원', null],
    ]) {
      const decision = await classify(title, applicant, support);
      assert.equal(decision.relevance_status, expected ? 'CONDITIONAL' : 'GFC_RELEVANT', title);
      assert.equal(decision.restriction_summary, expected, title);
    }
  } finally {
    await db.close();
  }
});
