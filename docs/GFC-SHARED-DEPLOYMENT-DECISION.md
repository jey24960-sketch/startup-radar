StartupRadar 2.0의 Supabase 및 웹 배포 방향을 아래와 같이 변경·확정한다.

기존 구현 내용을 폐기하지 말고, 현재 StartupRadar 2.0 체크포인트를 기준으로 이 결정사항을 반영해 계속 구현하라.

==================================================
1. SUPABASE PROJECT DECISION
==================================================

신규 Supabase 프로젝트는 생성하지 않는다.

StartupRadar 2.0은 현재 GFC 공식 웹사이트 `gfc-startup.com`이 사용하는 기존 Supabase 프로젝트를 함께 사용한다.

Supabase project:

Name:
jey24960-sketch's Project

Project ref:
etvffzxqdgblvkfdikwl

이 프로젝트는 이미 GFC 운영 서비스가 실제로 사용하는 데이터베이스다.

따라서 StartupRadar 배포 작업은 기존 GFC 서비스를 절대로 손상시키지 않아야 한다.

현재 프로젝트에는 이미 public schema를 중심으로 다음과 같은 GFC 관련 객체가 존재한다.

예:
- public.profiles
- public.projects
- public.teams
- public.problems
- public.settings
- public.auction_settings
- public.coin_investments
- 기타 GFC 운영 테이블
- auction_private schema
- auth schema
- storage schema

StartupRadar가 이 기존 데이터 모델을 자신의 데이터 모델로 간주해서는 안 된다.

==================================================
2. DATABASE ISOLATION
==================================================

StartupRadar 2.0의 모든 전용 데이터는 별도의 PostgreSQL schema에 격리한다.

Schema name:

startup_radar

권장 구조 예:

startup_radar.sources
startup_radar.ingestion_runs
startup_radar.source_run_results

startup_radar.programs
startup_radar.program_sources
startup_radar.program_versions
startup_radar.documents
startup_radar.program_requirements
startup_radar.program_change_events

startup_radar.radar_teams
startup_radar.team_profiles
startup_radar.team_profile_versions

startup_radar.eligibility_evaluations
startup_radar.recommendations

startup_radar.telegram_subscriptions
startup_radar.notification_runs
startup_radar.notification_items

실제 명칭은 현재 V2 코드와 migration 구조를 검토하여 더 적절한 이름이 있다면 조정할 수 있다.

다만 아래 원칙은 반드시 유지한다.

- StartupRadar 객체는 `startup_radar` schema에 둔다.
- 기존 `public` schema의 GFC 테이블을 StartupRadar 전용 테이블로 재사용하지 않는다.
- 기존 public.teams를 StartupRadar의 teams 테이블로 간주하지 않는다.
- 기존 public.profiles를 StartupRadar team profile로 사용하지 않는다.
- 기존 public.projects 구조를 변경하지 않는다.
- StartupRadar 때문에 기존 GFC schema를 ALTER/DROP/RENAME하지 않는다.

==================================================
3. EXISTING GFC DATA RELATION
==================================================

StartupRadar와 기존 GFC 데이터는 강결합하지 않는다.

StartupRadar의 팀 개념과 현재 GFC 사이트의 팀 개념이 장기적으로 완전히 동일하다고 가정하지 않는다.

StartupRadar 내부에서는 독립적인 `radar_teams` 또는 이에 준하는 엔티티를 유지한다.

필요하다면 향후:

startup_radar.radar_teams
    -> optional reference
    -> public.teams

와 같은 mapping을 추가할 수 있다.

하지만 이 연결은 optional이어야 한다.

기존 GFC 팀 데이터가 없어도 StartupRadar 팀을 생성할 수 있어야 하고,
반대로 모든 GFC 팀이 반드시 StartupRadar 프로필을 가질 필요도 없다.

==================================================
4. AUTHENTICATION
==================================================

Supabase Auth는 기존 GFC 서비스와 공유한다.

즉:

auth.users

를 StartupRadar에서도 사용자 identity source로 사용할 수 있다.

목표는 기존 gfc-startup.com에 로그인한 GFC 학회원이 StartupRadar용 별도 계정을 만들지 않아도 사용할 수 있게 하는 것이다.

StartupRadar membership/profile 테이블은 필요하면:

auth.users.id

를 foreign/reference key로 연결한다.

다만 authorization은 반드시 StartupRadar 자체의 membership 및 RLS 규칙으로 통제한다.

기존 GFC 사용자가 로그인했다는 이유만으로 모든 StartupRadar 팀 정보를 열람할 수 있게 하지 않는다.

==================================================
5. RLS / SECURITY
==================================================

StartupRadar 사용자-facing 데이터에는 Row Level Security를 적용한다.

최소한 다음을 보장하라.

- 사용자는 본인이 속한 StartupRadar 팀의 private profile만 볼 수 있다.
- 다른 팀의 민감한 eligibility profile은 볼 수 없다.
- 관리자 권한과 일반 사용자 권한을 분리한다.
- Telegram ID, 내부 운영 메타데이터, private team attributes를 일반 공개하지 않는다.

Backend ingestion / document processing / eligibility batch / notification 작업은 필요한 경우 service role을 사용할 수 있다.

브라우저 클라이언트에 service-role key를 절대 노출하지 않는다.

Browser:
Supabase JWT + RLS

Backend / GitHub Actions:
service role where genuinely required

이 경계를 명확하게 유지한다.

==================================================
6. PRODUCTION DATABASE SAFETY
==================================================

이 Supabase 프로젝트는 기존 GFC production 서비스와 공유되므로 migration 적용 전에 반드시 안전성 검사를 수행한다.

Migration 전에 다음을 실행하고 결과를 보고하라.

1. 현재 database schema inventory 확인
2. 기존 tables/views/functions/types/triggers/policies 검사
3. StartupRadar migration과 이름 충돌 검사
4. public schema 변경 여부 검사
5. DROP / destructive ALTER 여부 검사
6. auth 관련 기존 정책 영향 여부 검사
7. 기존 GFC RLS 정책 영향 여부 검사

StartupRadar migration은 가능한 한 additive migration이어야 한다.

기존 production 객체를 변경해야만 구현할 수 있는 상황이 발생하면:

임의로 실행하지 말고 중지한 뒤
- 변경 대상
- 필요한 이유
- 기존 서비스 영향
- 대안

을 보고하라.

==================================================
7. MIGRATION POLICY
==================================================

StartupRadar migration은 source-controlled migration으로 유지한다.

실행 가능한 경우 transaction 기반으로 적용한다.

Migration 적용 후 다음을 검증한다.

- StartupRadar schema/table 생성 상태
- constraints
- foreign keys
- indexes
- RLS
- GRANT
- auth user 연결
- service role access
- authenticated user access
- cross-team isolation

그리고 기존 GFC 서비스에 regression이 없는지도 확인한다.

특히 기존:

profiles
projects
teams
problems
auction 관련 기능

의 schema/policy가 변경되지 않았는지 확인한다.

==================================================
8. CURRENT DEPLOYMENT STATUS
==================================================

현재 V1 운영 시스템을 V2로 전환하지 않는다.

StartupRadar V2는 계속 staging 상태로 유지한다.

현재 작업 목표는:

Supabase 연결
→ migration 검증
→ 실제 데이터 적재 검증
→ Auth/RLS 검증
→ 실제 API/문서 수집 검증
→ Telegram 테스트
→ V1/V2 병행 비교

까지다.

안정성이 검증되기 전에 V1을 비활성화하거나 V2로 production cutover하지 않는다.

==================================================
9. WEB ARCHITECTURE DECISION
==================================================

StartupRadar 웹 UI의 장기 목표는 GFC 사용자 경험과 통합하는 것이다.

이상적인 사용자 흐름:

gfc-startup.com 로그인
→ StartupRadar
→ 현재 팀 선택
→ 현재 단계/프로필 설정
→ 지원 가능한 사업 확인

장기적으로는 예:

gfc-startup.com/radar

형태의 통합 가능성을 우선 검토한다.

하지만 지금 단계에서는 이미 구현된 StartupRadar V2 웹 구조를 무조건 폐기하거나 GFC React 앱에 바로 합치지 않는다.

먼저 현재 V2 웹 구현을 audit하라.

다음을 비교해라.

OPTION A
현재 StartupRadar Python web application을 별도 서비스로 배포

OPTION B
API/backend는 별도 유지하고 UI를 기존 gfc-startup.com React 앱에 통합

OPTION C
기존 V2 구조 일부를 재사용하면서 점진적으로 GFC 웹에 통합

평가 기준:

- 기존 구현 재사용 가능성
- 인증 통합
- Supabase RLS
- 배포 복잡도
- 장기 유지보수
- GFC 사용자 UX
- API/backend 책임 분리
- 비용
- 향후 외부 사용자 확장성

이 분석이 끝나기 전에는 기존 GFC frontend를 대규모 수정하지 않는다.

웹 호스팅 결정을 성급하게 확정하지 말고 현재 코드 구조를 기준으로 가장 적절한 방안을 제안하라.

==================================================
10. STARTUPRADAR PRODUCT MODEL 유지
==================================================

기존에 승인된 StartupRadar 2.0 제품 설계는 유지한다.

특히 다음을 변경하지 않는다.

사용자-facing preset:

0. 팀빌딩 전 · 아이디어
1. 팀 구성 · 아이디어
2. 랜딩 · 프리토타입
3. MVP
4. 사업자등록 · 법인 보유

단 이것은 UX preset이다.

내부 모델은 계속 독립적으로 관리한다.

team_status
product_stage
business_status

Stage 0은 추가 개인정보 입력 없이 사용할 수 있어야 한다.

UNKNOWN profile field는 false로 간주하지 않는다.

Eligibility:

ELIGIBLE
NEEDS_INFO
INELIGIBLE
UNVERIFIABLE

판정은 근거 기반 deterministic rule engine이 담당하며,
LLM은 hard eligibility failure를 override할 수 없다.

==================================================
11. DATA PIPELINE 유지
==================================================

기존 V2 목표 구조 역시 유지한다.

multi-source discovery
→ official/detail acquisition
→ attachment extraction
→ canonical program normalization
→ requirement extraction
→ deterministic eligibility
→ recommendation ranking
→ Telegram/Web delivery
→ source health monitoring

K-Startup과 기업마당을 backbone source로 유지한다.

기존 대학/기관/AC/재단 크롤러는 long-tail adapter 역할을 한다.

PDF/HWP/HWPX 등 첨부문서는 first-class evidence로 취급한다.

==================================================
12. IMMEDIATE NEXT TASKS
==================================================

현재 checkpoint에서 다음 순서로 작업하라.

STEP 1
현재 StartupRadar V2 코드와 DB migration 전체 audit

STEP 2
기존 V2 migration이 public schema 또는 기존 GFC 객체를 전제로 작성되어 있는지 확인

STEP 3
필요한 경우 migration을 `startup_radar` schema 기반으로 안전하게 재구성

STEP 4
현재 Supabase production database와 migration 충돌 검사

STEP 5
기존 GFC database 객체에 영향을 주지 않는 것이 확인되면 StartupRadar migration 적용

STEP 6
RLS / team isolation / auth.users 연결 실제 검증

STEP 7
최소 staging seed data를 넣어 다음 시나리오 검증

- Stage 0 user
- Team/Idea
- Landing
- MVP + PRE_BUSINESS
- MVP + CORPORATION

STEP 8
서로 다른 두 팀이 동일 공고에 대해 서로 다른 eligibility 결과를 얻는지 검증

STEP 9
기존 GFC 서비스 regression 여부 확인

STEP 10
그 다음 실제 K-Startup / 기업마당 / 문서 처리 / Telegram 연결 작업으로 진행

==================================================
13. IMPORTANT RESTRICTIONS
==================================================

절대 하지 말 것:

- 기존 public.teams를 임의 변경
- 기존 public.profiles 구조 변경
- 기존 GFC RLS 정책 제거
- production 데이터를 테스트 데이터로 덮어쓰기
- destructive migration 실행
- service-role key를 frontend에 포함
- 기존 GFC 로그인 사용자에게 모든 StartupRadar 데이터 공개
- StartupRadar 설정을 Git commit으로 저장하는 구조로 회귀
- V1을 검증 없이 종료
- migration 실패를 무시하고 다음 단계 진행
- schema 충돌을 임의 이름 변경만으로 숨기기

==================================================
14. REPORTING FORMAT
==================================================

이번 작업이 끝나면 아래 형식으로 보고하라.

SUPABASE TARGET
- project ref
- schema used

DATABASE AUDIT
- existing relevant objects
- detected conflicts
- production risks

MIGRATIONS
- migrations added/changed
- objects created
- existing GFC objects modified 여부

AUTH / RLS
- auth integration
- policies
- team isolation test

TESTS
- Python
- Worker
- DB
- browser/frontend
- regression

WEB ARCHITECTURE
- current structure
- recommended deployment/integration option
- rationale

EXTERNAL SETUP REQUIRED
- secrets
- API keys
- hosting settings
- Telegram settings

KNOWN LIMITATIONS

NEXT MILESTONE

CUTOVER STATUS
- 반드시 아직 V1/V2 병행 여부와 production 전환 여부를 명시할 것

핵심 원칙:

"Supabase 프로젝트는 GFC와 공유하지만, StartupRadar 데이터와 권한 모델은 독립적으로 격리한다."

기존 GFC production 서비스를 보호하는 것을 StartupRadar 구현 속도보다 우선한다.