StartupRadar 2.0의 사용자 경험과 웹 통합 방향을 아래와 같이 확정한다.

현재까지 구현된 StartupRadar V2 코드, 테스트, PostgreSQL 구조, eligibility engine, source adapters, recommendation logic을 폐기하지 않는다.

이번 변경의 핵심은 StartupRadar의 "사용자용 웹 대시보드"를 별도 서비스로 만드는 것이 아니라 기존 GFC 공식 웹사이트 `gfc-startup.com` 내부 기능으로 통합하는 것이다.

기존 StartupRadar backend는 데이터 수집·정규화·자격판정·추천 엔진으로 유지하고,
기존 GFC 웹사이트는 사용자-facing UI가 된다.

==================================================
1. FINAL PRODUCT ARCHITECTURE
==================================================

최종 구조는 다음을 목표로 한다.

GitHub Actions / StartupRadar Backend
→ 지원사업 자동 수집
→ 문서 분석
→ requirement extraction
→ eligibility calculation
→ recommendation generation
→ Supabase 저장

Supabase
→ GFC 수동 공지
→ StartupRadar 프로그램
→ 팀 프로필
→ eligibility
→ recommendation
→ notification history
→ authentication / authorization

gfc-startup.com
→ 사용자가 실제로 이용하는 웹 UI

Telegram
→ 중요한 신규 공고 및 마감 알림을 전달하는 보조 notification channel

즉:

수집/분석:
StartupRadar backend

저장/권한:
Supabase

사용자 UI:
gfc-startup.com

긴급 알림:
Telegram

으로 역할을 분리한다.

StartupRadar 자체의 별도 회원용 웹 대시보드를 장기 주 UI로 만들지 않는다.

==================================================
2. SUPABASE TARGET
==================================================

신규 Supabase 프로젝트는 만들지 않는다.

현재 GFC 공식 웹사이트가 사용하는 기존 Supabase 프로젝트를 공유한다.

Project:
jey24960-sketch's Project

Project ref:
etvffzxqdgblvkfdikwl

기존 GFC production 서비스와 같은 프로젝트이므로 데이터 격리와 backward compatibility가 최우선이다.

==================================================
3. DATABASE ISOLATION
==================================================

StartupRadar 전용 데이터는 계속 별도 PostgreSQL schema에 둔다.

Schema:
startup_radar

예:

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

기존:

public.profiles
public.projects
public.teams
public.problems
auction 관련 테이블

등은 StartupRadar 전용 데이터 모델로 재사용하거나 구조 변경하지 않는다.

==================================================
4. NEW /NOTICE INFORMATION HUB
==================================================

기존 GFC 웹사이트에 다음 하위 페이지를 만든다.

Primary route:

/notice

Detail route:

/notice/:id

필요하다면 StartupRadar 프로그램 상세는:

/notice/radar/:programId

처럼 별도 route를 사용할 수 있다.

단 URL 설계는 기존 GFC router conventions를 먼저 확인한 후 일관성 있게 구현한다.

`/notice`는 GFC의 통합 정보 허브다.

여기에는 서로 성격이 다른 두 종류의 콘텐츠가 존재한다.

A. GFC 공식 공지
- 운영진이 수동 작성
- 일반 공지
- 세션 공지
- 모집
- 행사
- 기타 GFC 운영 정보

B. StartupRadar 지원사업
- 자동 수집
- 프로그램 DB에서 조회
- 팀별 eligibility/recommendation 반영
- 인증된 GFC 학회원 전용

UI에서는 하나의 정보 페이지에 통합될 수 있지만,
DB 모델은 절대로 하나의 게시물 테이블로 합치지 않는다.

StartupRadar 프로그램을 manual notice row로 복제해 저장하지 않는다.

==================================================
5. MANUAL GFC NOTICE MODEL
==================================================

운영진이 작성하는 공식 공지용 데이터 모델을 추가한다.

기존 GFC DB에 이미 notice/announcement 성격의 기능이나 테이블이 있는지 먼저 audit한다.

있다면 기존 기능의 목적과 구조가 이번 요구사항과 호환되는지 검토한다.

없다면 신규 manual notice entity를 만든다.

권장 개념:

id
title
body
category
visibility
is_pinned
published_at
created_by
created_at
updated_at

visibility:

PUBLIC
MEMBERS_ONLY

기본값:
PUBLIC

category 예:

GENERAL
SESSION
RECRUITMENT
EVENT
IMPORTANT

기존 DB naming conventions에 맞게 조정할 수 있다.

중요:

StartupRadar 자동 공고를 이 테이블에 저장하지 않는다.

==================================================
6. NOTICE VISIBILITY MODEL
==================================================

사용자 권한에 따라 `/notice`에서 보이는 내용이 다르다.

ROLE 1
Anonymous / unauthenticated external user

Can see:
- PUBLIC manual GFC notices

Cannot see:
- MEMBERS_ONLY notices
- StartupRadar programs
- team profile
- eligibility
- recommendations
- operational data

ROLE 2
Authenticated user but NOT verified GFC member

Can see:
- PUBLIC manual GFC notices

Cannot see:
- StartupRadar data
- members-only notices unless explicitly authorized
- team recommendation data

ROLE 3
Verified GFC member

Can see:
- PUBLIC notices
- MEMBERS_ONLY notices
- StartupRadar opportunity feed
- programs visible to GFC members
- own/authorized team eligibility and recommendations

ROLE 4
GFC admin/operator

Can see:
- all above
- notice create/edit/delete/publish controls
- StartupRadar administrative information appropriate for web UI
- source health / failures if implemented
- team/profile management where authorized

==================================================
7. IMPORTANT: LOGIN != VERIFIED MEMBER
==================================================

Supabase Auth 로그인 여부만으로 StartupRadar 접근을 허용하지 않는다.

Access rule:

authenticated
AND
verified GFC membership

이어야 한다.

현재 GFC 웹사이트가 학회원 권한을 어떤 데이터/role/claim으로 판정하는지 먼저 audit한다.

가능하면 현재 GFC membership model을 재사용한다.

새로운 membership system을 중복 구현하지 않는다.

단, 기존 membership 판정 방식에 보안상 문제가 있거나 StartupRadar RLS에서 안전하게 재사용하기 어려운 경우 그 문제를 보고하고 최소한의 안전한 integration layer를 설계한다.

==================================================
8. RLS IS THE REAL SECURITY BOUNDARY
==================================================

Frontend에서 StartupRadar 탭을 숨기는 것만으로 보안을 구현하지 않는다.

Database/RPC/API level에서도 접근이 차단되어야 한다.

Required behavior:

anon
→ StartupRadar SELECT denied

authenticated non-member
→ StartupRadar SELECT denied

verified member
→ permitted member-level StartupRadar reads

team member
→ permitted team-specific private recommendation/profile reads

admin
→ authorized management functions

Frontend visibility와 Supabase RLS를 둘 다 적용한다.

Service-role key는 browser bundle에 절대 포함하지 않는다.

==================================================
9. EXISTING SECURITY MUST NOT REGRESS
==================================================

기존 Supabase 프로젝트에는 현재 운영 중인 GFC functions와 RLS가 존재한다.

StartupRadar 통합 때문에 기존:

profiles
teams
projects
problems
auction
auth

권한을 느슨하게 만들지 않는다.

새 SECURITY DEFINER function을 무분별하게 추가하지 않는다.

필요한 경우:

- EXECUTE privilege 최소화
- authenticated role에 불필요한 RPC 노출 금지
- search_path 고정
- explicit authorization check
- RLS-compatible design

을 적용한다.

StartupRadar 기능 구현을 이유로 기존 GFC security policy를 광범위하게 수정하지 않는다.

==================================================
10. /NOTICE UX
==================================================

권장 기본 UX:

Page title:
NOTICE

Description:
GFC의 공지와 학회원에게 필요한 창업 기회를 확인하는 정보 허브.

Verified member tabs:

[전체]
[GFC 공지]
[StartupRadar]

External / non-member:

[GFC 공지]

또는 StartupRadar 탭을 disabled/locked 상태로 보여줄 수 있다.

권장:
외부 사용자에게 StartupRadar 존재는 보여주되 실제 데이터는 노출하지 않는다.

예:

StartupRadar
GFC 학회원에게 제공되는 맞춤형 창업지원사업 추천 기능입니다.
[로그인]

주의:
locked UI를 보여주더라도 StartupRadar 실제 프로그램 title/count/details를 외부에 반환하지 않는다.

==================================================
11. UNIFIED FEED BEHAVIOR
==================================================

Verified member의 "전체" 탭에서는 manual notice와 StartupRadar 결과를 하나의 timeline/feed처럼 보여줄 수 있다.

예:

[공지]
GFC 2기 세션 일정 변경
운영진 · 09.14

[지원사업]
2026 글로벌 창업 지원사업
서울경제진흥원 · D-12
지원 가능 · 적합도 94

[공지]
이번 주 세션 준비사항
운영진 · 09.12

하지만 데이터 계층은 각각 별도 source에서 조회한다.

Manual notice:
GFC notice table

StartupRadar:
startup_radar programs/recommendations/eligibility

Frontend에서 normalized feed DTO/view model로 합치는 방식이 권장된다.

==================================================
12. STARTUPRADAR DISPLAY FOR MEMBERS
==================================================

StartupRadar item에는 가능한 경우 다음을 표시한다.

- 프로그램명
- 기관
- program type
- 접수 기간
- D-day
- 주요 혜택
- eligibility status
- recommendation score
- 간단한 추천 이유

Eligibility states:

ELIGIBLE
→ "지원 가능"

NEEDS_INFO
→ "조건 확인 필요"

INELIGIBLE
→ 기본 추천 feed에서는 숨기거나 별도 필터로 제공

UNVERIFIABLE
→ "조건 확인 필요"로 UI 표현 가능하되 내부 상태는 유지

Program detail에서는:

FACT
지원사업 원문에서 확인된 정보

ELIGIBILITY
현재 팀 기준 지원 가능 여부

RECOMMENDATION
왜 이 팀에 추천하는지

를 명확히 분리한다.

원문과 첨부 공고문 링크도 제공한다.

==================================================
13. TEAM SELECTOR
==================================================

한 사용자가 여러 StartupRadar 팀에 속할 가능성을 지원한다.

Member UI에서 필요하면:

현재 팀: [ Sadstar ▼ ]

형태로 active radar team을 선택할 수 있게 한다.

선택한 팀에 따라:

eligibility
recommendation
missing profile info

가 변경된다.

한 공고에 대해 서로 다른 팀이 서로 다른 eligibility 결과를 받을 수 있어야 한다.

==================================================
14. STARTUPRADAR SETTINGS IN GFC WEBSITE
==================================================

팀 정보와 StartupRadar 설정 역시 GFC 웹사이트에서 관리한다.

추천 route 예:

/radar/settings

또는

/notice/settings

단 기존 사이트 IA를 audit하여 더 자연스러운 route를 선택할 수 있다.

권장 역할 분리:

/notice
→ 정보 소비

/radar/settings
→ StartupRadar team/profile/preferences 관리

Member가 설정할 수 있어야 하는 것:

- active team
- startup preset
- team status
- product stage
- business status
- 필요한 경우 추가 eligibility fields
- preferred program types
- notification preferences

초기 onboarding에서는 긴 form을 강제하지 않는다.

==================================================
15. FIVE PRESETS
==================================================

기존 승인된 preset을 유지한다.

0.
팀빌딩 전 · 아이디어

1.
팀 구성 · 아이디어

2.
랜딩 · 프리토타입

3.
MVP

4.
사업자등록 · 법인 보유

Preset은 UX shortcut이다.

Underlying model은:

team_status
product_stage
business_status

를 독립적으로 유지한다.

Stage 0은 추가 개인 정보 없이 바로 StartupRadar를 사용할 수 있어야 한다.

UNKNOWN 값을 false로 간주하지 않는다.

==================================================
16. PROGRESSIVE PROFILING IN WEB UI
==================================================

사용자가 처음부터 모든 프로필 정보를 작성하게 하지 않는다.

Flow:

preset 선택
→ 즉시 추천 확인
→ 특정 프로그램 판정에 정보가 부족하면 NEEDS_INFO
→ 어떤 정보가 필요한지 표시
→ 사용자가 선택적으로 입력
→ eligibility 재평가

예:

조건 확인 필요

다음 정보를 입력하면 정확한 지원 여부를 확인할 수 있습니다.

- 대표자 연령
- 소재 지역

[정보 추가]

==================================================
17. MANUAL NOTICE ADMIN UI
==================================================

운영진은 GFC 웹사이트에서 공지를 작성할 수 있어야 한다.

Admin UI:

[공지 작성]

Fields:

제목
본문
카테고리
공개 범위
상단 고정
게시 상태/게시 시점

Visibility:

PUBLIC
MEMBERS_ONLY

Default:
PUBLIC

지원해야 할 actions:

create
edit
publish/unpublish if implemented
pin/unpin
delete or archive

기존 GFC admin authorization model을 우선 재사용한다.

Frontend button visibility뿐 아니라 backend/RLS authorization도 강제한다.

==================================================
18. STARTUPRADAR ADMINISTRATION
==================================================

일반 학회원과 관리자 기능을 분리한다.

초기 admin UI에서 최소한 유용한 정보:

- 마지막 ingestion 실행
- source 상태
- 성공/부분실패/실패
- 신규 프로그램 수
- document parsing failures
- eligibility pipeline failures

단 모든 backend 운영 기능을 웹에 한 번에 구현할 필요는 없다.

우선순위:

member-facing notice/radar experience
→ manual notice admin
→ essential health
→ advanced operational controls

순으로 한다.

==================================================
19. TELEGRAM ROLE CHANGE
==================================================

Telegram은 StartupRadar의 main user interface가 아니다.

Telegram의 역할은 notification이다.

Examples:

- weekly digest
- exceptional high-fit opportunity
- D-7 deadline
- D-3 deadline
- important operational alert to admins

사용자가 전체 데이터를 탐색하거나 팀 프로필을 관리하는 곳은 GFC 웹사이트다.

기존 Telegram 명령 중 웹에서 더 자연스럽게 처리되는 것은 장기적으로 축소 가능하다.

특히:

/stage

를 primary profile management path로 사용하지 않는다.

웹에서 팀 상태를 변경하고 Supabase에 저장한다.

==================================================
20. BACKEND RESPONSIBILITY
==================================================

StartupRadar Python/backend의 책임:

- scheduled ingestion
- source adapters
- raw acquisition
- attachment parsing
- normalization
- deduplication
- program versioning
- requirement extraction
- eligibility evaluation
- recommendation calculation
- notification generation
- source health tracking

이 backend가 직접 회원용 HTML dashboard를 제공할 필요는 없다.

이미 구현된 Python web UI/dashboard 코드가 있다면 즉시 삭제하지 않는다.

먼저 audit하여:

- reusable API/service logic
- admin utility
- dead UI code

를 구분한다.

재사용 가능한 backend/service layer는 유지한다.

회원용 UI와 중복되는 별도 dashboard는 production architecture에서 제거 또는 비활성화하는 방향을 검토한다.

==================================================
21. GFC FRONTEND INTEGRATION
==================================================

현재 gfc-startup.com의 실제 frontend repository/architecture를 먼저 확인한다.

React/Vite 또는 현재 사용 중인 stack과:

- routing
- auth
- Supabase client
- layout
- navigation
- design tokens
- member guards
- admin guards

를 재사용한다.

기존 사이트와 동떨어진 별도 UI framework를 도입하지 않는다.

새 `/notice` 페이지는 기존 GFC 사이트의 visual language와 component conventions를 따른다.

브랜드 원칙:

- dark navy / dark slate
- cyan / bright blue accent
- white-centered backgrounds
- professional
- restrained
- strong information hierarchy

과도한 neon / gradients / decorative effects는 피한다.

==================================================
22. REPOSITORY BOUNDARY
==================================================

StartupRadar repository와 GFC frontend repository가 분리되어 있을 수 있다.

먼저 실제 repository layout과 deploy target을 확인한다.

만약 Codex가 현재 StartupRadar repo만 수정할 수 있고 GFC frontend repo에 접근할 수 없다면:

절대 존재하지 않는 frontend 파일을 가정하여 수정하지 않는다.

대신:

1. StartupRadar backend/API/DB integration을 준비
2. required frontend data contract 정리
3. required Supabase queries/RPC/views 정리
4. exact integration checklist 작성
5. GFC frontend repo access가 필요하다고 보고

한다.

두 저장소 모두 접근 가능하다면 각각 명확한 변경 범위로 구현한다.

==================================================
23. API / DATA ACCESS STRATEGY
==================================================

Frontend에서 복잡한 raw StartupRadar tables를 직접 조합하도록 만들지 않는다.

필요하다면 안전한:

- views
- RPC
- backend API endpoints

를 제공하여 frontend consumption contract를 단순화한다.

예:

get_notice_feed()
get_my_radar_teams()
get_team_recommendations(team_id)
get_program_detail(program_id)
update_team_profile(...)
create_notice(...)

실제 구현은 기존 architecture에 맞춰 선택하되:

- security
- RLS
- pagination
- query performance
- maintainability

를 고려한다.

SECURITY DEFINER RPC는 정말 필요한 경우에만 사용하고 authorization을 내부에서 강제한다.

==================================================
24. PERFORMANCE
==================================================

`/notice`가 매번 모든 StartupRadar 데이터를 브라우저에 로드해서 filtering하지 않도록 한다.

Server/database side에서:

- pagination
- visibility
- membership
- active team
- eligibility
- date/status

조건을 적용한다.

필요한 indexes도 추가한다.

==================================================
25. EXTERNAL VISIBILITY GUARANTEE
==================================================

매우 중요한 acceptance requirement:

비로그인 사용자가:

- browser DevTools
- REST call
- direct Supabase query

등을 통해 StartupRadar 프로그램 데이터를 우회 조회할 수 없어야 한다.

단순 UI 숨김은 PASS가 아니다.

같은 요구가 authenticated non-member에도 적용된다.

==================================================
26. MANUAL NOTICE VISIBILITY
==================================================

PUBLIC notice:
누구나 읽을 수 있다.

MEMBERS_ONLY notice:
verified member 이상만 읽을 수 있다.

Admin write:
authorized operator/admin만 가능.

Author identity를 public 페이지에 어떤 형태로 표시할지는 UX 선택이다.

내부적으로 created_by audit은 반드시 남긴다.

==================================================
27. AUTOMATION FLOW
==================================================

정상 운영 시 자동 흐름:

Daily scheduled GitHub Actions
→ K-Startup / 기업마당 / RSS / HTML / other adapters
→ discover new/updated opportunities
→ fetch detail
→ parse attachments
→ normalize
→ deduplicate/version
→ extract requirements
→ eligibility evaluation
→ recommendation generation
→ Supabase

사용자가 `/notice`에 접근:
→ auth/membership 판정
→ 허용된 manual notices 로드
→ verified member라면 active team's StartupRadar recommendations도 로드
→ unified feed render

Telegram:
→ 중요한 event만 push

이 흐름을 documentation에도 반영한다.

==================================================
28. BILLING / COST AWARENESS
==================================================

아키텍처에서 불필요한 비용 증가를 피한다.

특히 AI 분석은:

new program
또는
materially changed program/document

에 대해서만 실행하는 것이 기본이다.

동일 document/content hash이면 재분석하지 않는다.

Eligibility engine은 가능한 한 deterministic code로 실행하여 LLM 호출을 반복하지 않는다.

Recommendation explanation도 불필요하게 매 page request마다 생성하지 않는다.

생성 결과를 저장하여 재사용한다.

==================================================
29. IMPLEMENTATION ORDER
==================================================

현재 V2 checkpoint에서 다음 순서로 진행한다.

PHASE 1
Current architecture audit
- StartupRadar repo
- GFC frontend repo
- current auth/member/admin models
- current DB
- current V2 web dashboard

PHASE 2
DB safety
- startup_radar schema migration 검증
- notice model 검토/추가
- membership/RLS design
- no regression to existing GFC service

PHASE 3
Backend data contracts
- member feed
- team recommendation
- program detail
- team settings
- notice CRUD

PHASE 4
GFC frontend
- /notice
- notice tabs/feed
- Radar member-only UI
- detail pages
- team selector
- settings
- admin notice composer

PHASE 5
Telegram role adjustment

PHASE 6
source health/admin features

PHASE 7
V1/V2 parallel verification

PHASE 8
production cutover decision

==================================================
30. REQUIRED TESTS
==================================================

Add tests covering at minimum:

NOTICE ACCESS

anonymous:
- PUBLIC notice visible
- MEMBERS_ONLY notice denied
- Radar denied

authenticated non-member:
- PUBLIC notice visible
- member notice denied
- Radar denied

verified member:
- public notice visible
- member notice visible
- Radar accessible

admin:
- notice CRUD allowed

unauthorized member:
- notice write denied

RADAR TEAM ACCESS

- own authorized team recommendation visible
- unauthorized team's private profile denied
- unauthorized team's private recommendation denied

PRESET

- Stage 0 works without additional personal info

ELIGIBILITY

- same program can produce different result for two teams

FRONTEND

- anonymous notice page
- member notice page
- locked Radar presentation
- member Radar feed
- team switch
- program detail
- notice admin flow

REGRESSION

Existing GFC:
- login
- profile
- teams
- project/auction functionality relevant to current production

must remain functional.

==================================================
31. ACCEPTANCE CRITERIA
==================================================

This integration is successful when all of the following are true.

1.
`gfc-startup.com/notice` exists.

2.
External users can read PUBLIC manual GFC notices without login.

3.
External users cannot retrieve StartupRadar opportunity data.

4.
Logged-in but unverified users cannot retrieve StartupRadar opportunity data.

5.
Verified members can access StartupRadar results.

6.
Manual notices and Radar items can appear together in a member's feed without being stored in the same DB entity.

7.
Administrators can create/edit/publish GFC notices from the website.

8.
A manual notice can be PUBLIC or MEMBERS_ONLY.

9.
StartupRadar team/profile settings can be managed from the GFC website.

10.
Stage 0 is usable without filling a large profile form.

11.
A member can see eligibility evidence for a recommended program.

12.
Different teams can receive different results for the same program.

13.
RLS prevents cross-team private data access.

14.
StartupRadar automation continues independently of whether users visit the website.

15.
Telegram remains functional as an alert channel.

16.
Existing GFC production features are not broken.

17.
No service-role credentials exist in frontend code.

18.
No V1 production cutover occurs before parallel verification.

==================================================
32. REPORTING
==================================================

When this milestone finishes, report:

ARCHITECTURE AUDIT

GFC FRONTEND
- repository
- framework
- routes
- auth
- membership model
- admin model

DATABASE
- notice objects
- StartupRadar objects
- RLS changes
- existing GFC objects modified

BACKEND CONTRACTS

FRONTEND IMPLEMENTATION

ACCESS CONTROL TEST MATRIX

STARTUPRADAR SETTINGS

TELEGRAM CHANGES

TEST RESULTS

BUILD RESULTS

PRODUCTION REGRESSION RESULTS

EXTERNAL SETUP REQUIRED

KNOWN LIMITATIONS

V1/V2 PARALLEL STATUS

NEXT MILESTONE

CUTOVER STATUS

==================================================
33. CORE PRINCIPLE
==================================================

The product should feel like:

"GFC 웹사이트 안에서 운영진 공지와 나에게 필요한 창업지원사업을 한 곳에서 확인하는 것."

It should NOT feel like:

"GFC 웹사이트에서 별도의 StartupRadar SaaS로 이동하는 것."

At the same time, keep the backend architecture modular enough that StartupRadar can support external startup teams in the future without rewriting its core ingestion and eligibility engine.

Protect the existing GFC production system first.
Integrate progressively.
Do not perform an unreviewed destructive migration or premature V1 cutover.