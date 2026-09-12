# StartupRadar 2.0 — GFC 공유 Supabase staging 결과

작성일: 2026-09-12. 사용자 결정사항을 기존 V2 체크포인트에 반영했다. 공유 운영 DB에 StartupRadar 스키마와 제한된 실제 수집 결과를 적재했으며, 기존 GFC 객체·데이터가 변경되지 않았음을 확인했다. 웹·Telegram 운영 전환은 하지 않았다.

## SUPABASE TARGET

- 프로젝트: `jey24960-sketch's Project`
- Ref: `etvffzxqdgblvkfdikwl`
- API 주소: `https://etvffzxqdgblvkfdikwl.supabase.co`
- 사용 스키마: `startup_radar`
- 신규 프로젝트 생성: 없음.
- 내부 팀 엔티티: `startup_radar.teams`. public.teams와 별개이며 이름 공간이 독립성을 보장한다. 기존 GFC 팀 없이 생성할 수 있고 optional mapping도 이번에는 추가하지 않았다.

## DATABASE AUDIT

public·auction_private·auth·storage의 48개 relation, 426개 column, 175개 constraint, 134개 index, 70개 function/procedure, 114개 type, 14개 사용자 trigger, 32개 policy를 조사했다. 기본 권한 설정 24개와 전역 event trigger 7개도 확인했다. 전체 정의는 별도 GFC 소유 코드이므로 로컬 감사 작업 공간에 보존하고, 이 저장소에는 재사용 가능한 catalog 조회 SQL과 검증 요약을 남겼다.

검사 당시 `radar`와 `startup_radar` 스키마는 모두 없었다. 운영 migration 이력 10개 중 기존 StartupRadar migration은 없었다. schema 이름 충돌이나 public.teams/profiles/projects 재사용 가정은 발견되지 않았다. 최초 5개 migration의 변경 대상은 원래도 독립 radar schema였으므로, 최종 구조를 새로운 startup_radar baseline으로 재구성했다.

적용 전·후·실제 자료 적재 후에 기존 객체 정의를 비교해 동일함을 확인했다. 다음 테이블은 행 수와 내용 지문도 일치했다.

| 기존 GFC 테이블 | 행 수 | 적용 전후 |
|---|---:|---|
| public.profiles | 24 | 동일 |
| public.projects | 5 | 동일 |
| public.teams | 0 | 동일 |
| public.problems | 0 | 동일 |
| public.settings | 1 | 동일 |
| public.auction_settings | 1 | 동일 |
| public.coin_investments | 0 | 동일 |

스키마를 분리해도 DB CPU·메모리·연결 수·Auth·백업 자원은 공유한다. 운영 수집 동시성과 연결 예산을 별도로 제한해야 한다. 이번 DDL에는 2초 lock timeout, 30초 statement timeout을 설정했다. 일반 backend 작업의 제한된 DB 계정과 pooler 연결 검증은 아직 남아 있다.

기존 GFC의 보안 advisor 지적은 전후 동일하다. RLS 정책이 없는 3개 기존 테이블, authenticated에서 실행 가능한 SECURITY DEFINER 함수 37개, 유출 비밀번호 보호 미설정이 있었으며 이번 작업에서 임의 수정하지 않았다. 새 StartupRadar 객체의 보안 advisor 지적은 없다. 관련 문서: [RLS 무정책](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy), [SECURITY DEFINER 실행](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable), [비밀번호 보호](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection).

## MIGRATIONS

실제로 적용하고 서버 migration ledger와 파일 이름을 맞춘 migration은 다음 두 개다.

1. `20260912114449_startup_radar_shared_gfc_staging.sql`: 기존 V2 최종 모델을 startup_radar에 생성. 작업 취소, source snapshot, publisher identity, 알림 batch 등 기존 구현을 보존했다. 과거 migration의 constraint DROP을 초기 정의에 흡수했다.
2. `20260912114958_startup_radar_fk_indexes.sql`: 신규 schema에만 FK index 16개를 추가해 18개 미인덱싱 FK 지적을 해소했다. 복합 index가 일부 단일 FK도 함께 지원한다.

최종 상태: **28 tables / 124 constraints / 40 foreign keys / 84 indexes / 31 RLS policies**. 미검증 constraint, RLS 미적용 테이블, anon 테이블 권한은 모두 0이다. 새 migration은 GFC public 객체의 ALTER/DROP/RENAME, 기존 정책 변경, auth 설정 변경, extension 변경을 수행하지 않았다.

auth.users를 참조하는 FK 때문에 PostgreSQL 내부 참조 무결성 trigger는 추가된다. 기존 GFC 사용자 trigger의 정의는 바뀌지 않았다. Auth 계정 삭제 시 Radar membership/admin mapping은 cascade, job/audit actor는 SET NULL로 처리해 Radar 이력이 계정 삭제를 막지 않게 했다. 실제 사용자 삭제는 하지 않고 로컬 DB에서 이 동작을 검증했다.

과거 migration 5개는 `docs/legacy-migrations`에 원문 그대로 보관했다. executable migration directory에는 현행 두 개만 있다. 공유 Supabase에는 GFC 저장소의 migration 이력도 있으므로 이 저장소에서 bulk db push나 migration repair를 실행하면 안 된다. 앞으로도 범위를 검토한 새 migration만 개별 적용한다.

## AUTH / RLS

기존 GFC `auth.users`를 identity source로 사용한다. 새 계정을 만들거나 공유 signup/provider/redirect 설정을 변경하지 않았다. 기존 GFC 사용자가 로그인했다고 Radar 팀 권한이나 관리자 권한을 얻지는 않는다. public.profiles의 role도 Radar 관리자 판정에 사용하지 않는다.

운영 DB에서 기존 Auth identity 3개를 선택하되 이미 Radar membership/admin이 있는 identity는 제외했다. 트랜잭션 안에서 다섯 가상 팀을 구성하고 두 identity를 서로 다른 팀에 연결해 아래 항목을 확인했다. 외부 메시지·이메일·실제 사용자 정보 변경 없이 검증 후 전부 롤백했다.

- 소속 팀 profile/version 조회 허용, 다른 팀 profile/version 조회 차단.
- 다른 팀 profile 수정, version 추가, team_id 재할당 차단.
- 일반 사용자의 관리자 자기 승격 차단.
- Radar membership 없는 공유 Auth 사용자의 접근 차단.
- 일반 사용자의 Telegram ID 조회 차단, 지정된 Radar 관리자 운영 조회 허용.
- 관리자의 private profile 조회도 membership 범위 유지.
- anon 접근 차단, service_role의 필요한 읽기/쓰기 허용.

이는 **실제 hosted PostgreSQL의 role/claim·FK·RLS 검증**이다. 브라우저 Google OAuth, 실제 JWT를 통한 Python `auth.get_user`, 호스팅 서버의 DB 연결을 검증한 것은 아니다. 현재 영구 Radar 팀·membership·관리자 mapping은 0개이며, 실사용 계정을 지정한 뒤 필요한 권한만 연결해야 한다.

## TESTS

| 구분 | 결과와 범위 |
|---|---|
| Python | 새 native PostgreSQL 18.4 cluster에 현행 두 migration을 처음부터 적용한 뒤 **144개 통과**. Starlette/AnyIO deprecation warning 1개 |
| Worker | **4개 통과**. forged/unauthorized webhook, 설정 누락, 중복 요청 방지 |
| DB | Fresh PGlite migration/RLS/공유 Auth 삭제 의미 검증 통과. Hosted RLS 시나리오 통과. 16개 FK index 적용 후 새 schema의 unindexed FK 지적 0 |
| Browser/frontend | V2 esbuild 통과. GFC Vite build 통과. 운영 홈페이지·Projects 확인, 적용 전후 Projects DOM 일치 |
| GFC regression | 기존 GFC 테스트 **55개 통과**. 그 테스트 DB에 StartupRadar migration 두 개를 함께 적용한 상태에서도 **55개 통과** |
| 실제 자료 | 공식 HTML 공고 1건, HWP 2개 수집·추출·hosted DB 적재 및 관계 확인 |
| 제한 | 실제 로그인 후 GFC 경매/투자 transaction을 운영 DB에서 실행하지 않았다. 해당 기능은 기존 schema/data 동일성 및 로컬 통합 회귀 검사로 확인 |

GFC 코드는 `bff3859856532c65eb6e3b88d2d98637ef668493` 사본을 기준으로 검사했다. 임시 테스트 helper 변경은 원상복구했으며 원격 GFC 코드와 배포에는 변경이 없다. 기존 GFC npm 설치 결과에 취약점 10개(낮음 2, 중간 2, 높음 6)가 표시됐지만 dependency 변경을 섞지 않았다. 개별 도달 가능성과 수정 범위는 별도 분석 대상이다.

### 단계별 eligibility 검증

Hosted DB에 넣었다가 다시 읽은 가상 profile을 실제 Python 엔진에 전달했다. 동일한 **법인 전용 가상 공고**에 대한 결과다. 실제 공고 정확도나 AI 추출 정확도를 입증하는 시험은 아니다.

| Profile | 결과 |
|---|---|
| Stage 0: PRE_TEAM / IDEA / PRE_BUSINESS | INELIGIBLE |
| Team / IDEA / PRE_BUSINESS | INELIGIBLE |
| Team / LANDING / PRE_BUSINESS | INELIGIBLE |
| Team / MVP / PRE_BUSINESS | INELIGIBLE |
| Team / MVP / CORPORATION | ELIGIBLE |

Stage 0은 추가 개인정보 없이 profile 검증에 성공했다. 조건 없는 근거 완비 가상 공고에는 ELIGIBLE, 연령 제한이 있지만 나이가 UNKNOWN이면 NEEDS_INFO, 근거가 부족하면 UNVERIFIABLE이었다. 제품 단계와 사업자 상태를 독립적으로 유지하며 LLM이 hard failure를 덮어쓰지 않는다.

### 실제 수집·적재

기존 HtmlAdapter/SafeHttp/문서 추출기를 사용해 고려대 세종창업교육센터의 창업동아리 추가모집 공고와 HWP 2개를 가져왔다. 문서 텍스트 길이는 각각 3,595자와 1,924자다. 기존 운영 DB 접속 문자열이 없으므로, 검토한 일회성 SQL로 수집 결과를 staging에 적재했다. 이 경로는 Python 서버의 실제 DB 연결이나 전체 scheduled ingestion 성공을 의미하지 않는다.

DB에는 3개 source 상태, 공고 1개, version 1개, 문서 2개, source snapshot 1개, source별 실패 이유가 보존된다. 공고의 evidence_complete는 false, 일정은 UNKNOWN이고 자격은 UNVERIFIABLE로 남긴다. 원문에 적힌 날짜와 조건을 AI/검증된 구조화 결과 없이 지원 가능으로 단정하지 않는다.

- K-Startup: `FAILED / MISSING_CREDENTIAL` — KSTARTUP_API_KEY 필요.
- 기업마당: `FAILED / MISSING_CREDENTIAL` — BIZINFO_API_KEY 필요.
- 고려대 HTML: `PARTIAL` — 자료 수집·HWP 추출 성공, ANTHROPIC_API_KEY가 없어 요건 추출 미실행.

이번 적재는 첫 공고 1건의 제한된 샘플이며 전체 수집 성공률이나 전국 coverage를 뜻하지 않는다. 가상 RLS 팀은 모두 롤백됐고 실제 수집 자료만 남았다. 전체 16개 source registry의 운영 적용과 주기 수집은 아직 실행하지 않았다.

## WEB ARCHITECTURE

**권장안은 C: 기존 V2 구조를 유지하며 GFC 웹에 점진적으로 통합**이다. 현재 Python API·문서 처리·판정 엔진·웹을 staging 검증에 재사용한 뒤, GFC React 앱의 `/radar`로 팀 선택·목록·근거 상세·프로필 UI를 순차적으로 옮긴다.

A는 가장 빠르게 기존 UI를 별도 실행할 수 있지만 origin이 달라 기존 GFC 로그인 세션이 자동 공유되지는 않는다. B는 최종 UX가 자연스럽지만 현재 vanilla JS UI를 React로 이전해야 한다. C는 두 장점을 단계적으로 활용하며 API와 권한 규칙을 유지한다. 상세한 9개 기준 비교와 경로·세션·proxy/CORS 변경점은 [WEB-INTEGRATION.md](WEB-INTEGRATION.md)에 있다.

호스팅 업체·유료 플랜은 확정하거나 구매하지 않았다. 현재 root 경로 기반 UI를 `/radar`에 단순 연결하면 바로 동작한다고 가정하지 않는다. GFC의 현재 catch-all Vercel rewrite와 API proxy, base path, Auth callback을 함께 검증해야 한다.

## EXTERNAL SETUP REQUIRED

- **Runtime DB:** Connect 화면에서 확인한 DATABASE_URL, TLS, pooler 모드, startup_radar에 필요한 권한으로 제한한 backend DB identity. 프로젝트 전체에 접근 가능한 postgres/service_role credential 사용 여부는 별도로 검토해야 한다.
- **Auth:** 실제 테스트할 기존 GFC 계정과 Radar administrator/member 지정. 공용 Auth 설정을 그대로 유지하면서 웹 로그인·토큰 만료·접근 차단 확인.
- **API/AI:** ANTHROPIC_API_KEY, KSTARTUP_API_KEY, BIZINFO_API_KEY.
- **Web:** C안의 첫 단계인 Python staging 호스트·HTTPS 주소와 필요한 정확한 redirect/proxy 설정. 운영 GFC 경로 전환은 미실행.
- **Telegram:** 별도 테스트 bot token, webhook secret, 지정된 테스트 chat/sender, Radar subscription/admin mapping.
- **GitHub:** V2 코드가 존재하는 원격 ref, Actions 실행 권한·DB/API secrets. V2 branch는 아직 push하지 않았다. 현재 main을 V2 workflow ref로 사용하면 안 된다.

선택된 프로젝트 URL과 활성 modern publishable key는 로컬 `.env.staging`에 준비했다. 이 파일은 Git·Docker build context에서 제외되며 앱이 자동 로드하지 않는다. 나머지 비밀값은 환경변수/secret 설정으로 전달해야 한다. 채팅에 비밀번호나 API 키를 붙여 넣을 필요는 없다.

## KNOWN LIMITATIONS

실제 API pagination·AI 요건 추출 품질, 운영 pooler lock 동작, 브라우저 로그인, Telegram 전송·복구, 장기간 비교는 남아 있다. Docker 파일은 준비됐지만 이 환경에 Docker/Podman이 없어 실제 이미지 실행을 검증하지 못했다. 브라우저 수집 runtime, OCR, 장기 원본 binary 보관, 대규모 catalog query 성능, 자동 운영자 paging 등 기존 제한도 유지된다.

새 schema의 index는 아직 사용량이 적어 unused-index advisor 안내가 남는다. 이는 방금 생성한 staging index의 관측 결과이며 무조건 삭제할 근거는 아니다. 기존 GFC의 별도 보안·성능 지적은 이번 격리 작업의 변경 대상에 포함하지 않았다.

## NEXT MILESTONE

제한된 DB 연결과 지정된 계정을 준비해 Python staging 웹에서 실제 GFC identity 로그인 → Radar membership 확인 → Stage 0/팀 profile/근거 조회를 검증한다. 이어 공식 API·AI 추출과 별도 테스트 Telegram 연결을 검증하고, 같은 기간의 V1/V2 수집 결과를 비교한다.

## CUTOVER STATUS

**V1 운영 유지. V2는 staging. Production cutover 없음.** V2 정기 실행과 자동 수집은 disabled이고 Telegram 구독·발송도 없다. 실제 V1/V2 동시 운영 결과를 수집하는 병행 검증은 아직 시작하지 않았다. 기존 V1 코드·webhook·스케줄을 제거하거나 변경하지 않았다.
