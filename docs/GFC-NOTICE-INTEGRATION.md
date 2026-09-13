> **최신 판정: Phase A 완료 / Python API A. NOT REQUIRED.** 필수 GFC Radar 9개 경로가 Supabase RPC로 전환됐다. 아래 초기 통합 수치와 구분하여 최신 계약·검증은 [설정/상태 계약](SETTINGS-HEALTH.md), [API 판정](PYTHON-API-DECISION.md), GFC-RADAR-SETTINGS-VERIFICATION.json을 참고한다. 실운영 수락 기준과 cutover는 미완료다.

> **Current goal:** [GFC integrated operation](GFC-OPERATING-GOAL.md) supersedes earlier hosting assumptions. A permanent Python API is not a prerequisite. [Phase A endpoint audit](PYTHON-API-DECISION.md) tracks direct Supabase conversion, async recalculation and the final NOT REQUIRED decision.

# StartupRadar 2.0 — GFC 공지 허브 통합 보고서

작성 기준: 2026-09-12. 기존 V2와 GFC 통합 구현을 보존하며 Phase A를 완료했다. 필수 9개 GFC Radar 경로가 Supabase RPC를 사용하고 Python HTTP 의존성은 제거됐다. 실제 소스·OAuth·알림·V1/V2 병행 검증은 남아 있으며 운영 전환을 수행하지 않았다.

## ARCHITECTURE AUDIT

```text
GitHub Actions / Python StartupRadar
  소스 수집 → 원문·첨부문서 분석 → 정규화·동일성 확인 → 요건 추출
  → 결정론적 자격판정 → 추천·설명 저장 → 필요한 알림만 Telegram
                   │
        shared Supabase: etvffzxqdgblvkfdikwl
          public.gfc_notices: 운영진 수동 공지
          startup_radar: 지원사업·팀 프로필·판정·추천·수집 이력
          public.profiles.role: 기존 GFC 학회원·운영진 판정
                   │
gfc-startup.com     │
  /notice: 공지 Supabase 조회 + Radar 저장 결과 RPC 조회 → 화면에서 DTO 통합
  /notice/:id: 공지 상세
  /notice/radar/:id: 지원사업의 사실 / 자격 / 추천 / 근거
  /radar/settings: 팀·단계·선호·선택 정보·알림 설정
```

기존 Python 모델, 수집기, 파서, eligibility engine, 추천 엔진, DB 이력, outbox를 유지했다. 기존 GFC 경매의 `public.teams`는 Radar 팀으로 재사용하지 않는다. 별도 `startup_radar.teams`를 계속 사용한다. GFC 회원 자격과 Radar 팀 편집 권한은 별개의 조건이다.

기존 FastAPI의 인증·API·서비스는 재사용한다. 별도 회원용 HTML·정적 대시보드는 소스에 보존하되 운영 기본값에서 비활성화했다. 로컬 검증 또는 `RADAR_LEGACY_UI_ENABLED=true`일 때만 열린다. 새 회원 경험은 GFC React 화면을 기준으로 한다.

## GFC FRONTEND

| 항목 | 확인 결과 |
|---|---|
| 저장소 | `jey24960-sketch/GFC-startup.com` (기존 비공개 저장소) |
| 확인한 기존 main | `bff3859856532c65eb6e3b88d2d98637ef668493` |
| 작업 브랜치 | `feature/notice-radar-integration` |
| 기술 | React 18, Vite 5, Tailwind, 기존 framer-motion/lucide |
| 라우터 | 별도 React Router 없이 App.jsx 경로 분기 + history.pushState |
| 로그인 | 기존 Google OAuth, Supabase AuthContext/useAuth/로그인 모달 |
| 회원 | DB `public.profiles.role IN ('member','admin')` |
| 관리자 | DB `role='admin'`; UI에서는 기존 `operator_mode` 토글도 반영 |
| 검증 함수 | 기존 `public.my_role()` 재사용; 회원 역할을 클라이언트가 직접 변경하지 못하는 컬럼 권한도 확인 |
| 배포 구성 | 기존 Vercel SPA catch-all rewrite, 기존 GFC Header/Footer와 한·영 메뉴 유지 |
| 신규 프레임워크 | 없음. Playwright만 테스트용으로 추가, 버전 고정 |

`operator_mode`는 기존과 동일하게 UI 토글이며 DB 보안 역할이 아니다. 꺼져 있어도 사용자의 실제 admin 역할 자체가 박탈되는 것은 아니다. 학회원 확인에 `user_metadata`를 사용하지 않는다.

## DATABASE

적용 대상은 기존 공유 Supabase이며 새 프로젝트를 만들지 않았다.

| 소유 저장소 | 실제 적용한 마이그레이션 | 내용 |
|---|---|---|
| StartupRadar | `20260912123752_gfc_member_access_and_feed_cache.sql` | GFC 회원 필수 RLS, Stage 0 공고 읽기, 판정 피드 캐시·분석 캐시·알림 선호 |
| GFC | `20260912123813_gfc_manual_notices.sql` | 수동 공지 모델·권한·편집 버전 |

공유 migration ledger에는 두 저장소의 이력이 함께 있다. **한 저장소에서 무조건 `supabase db push` 또는 migration repair를 실행하면 안 된다.** 새 마이그레이션 하나씩 검토·적용하고 ledger와 파일명을 맞춘다. GFC 테스트에 포함된 `tests/fixtures/radar-migrations`는 실제 Radar 마이그레이션의 검증용 사본이며 GFC의 배포 migration 경로가 아니다.

### 수동 공지

`public.gfc_notices`: id, title(1–200자), body(1–50,000자), category, visibility, is_pinned, state, published_at, created_by, created_at, updated_at, revision.

- 카테고리: GENERAL / SESSION / RECRUITMENT / EVENT / IMPORTANT.
- 공개 범위 기본값 PUBLIC. 선택하면 MEMBERS_ONLY.
- 상태: DRAFT / PUBLISHED / ARCHIVED. 실제 공개는 PUBLISHED이면서 게시 시점이 지난 행만 허용한다.
- 작성자 ID는 서버의 auth.uid()로 기록하고 클라이언트 입력·변경을 금지한다. 읽기 DTO에는 내부 작성자 UUID를 포함하지 않는다. 계정 삭제 시 FK는 SET NULL이므로 기존 GFC 계정 삭제를 막지 않는다.
- 편집 시 revision을 증가시키며 프런트엔드는 기존 revision을 조건으로 UPDATE해 다른 운영진의 변경 덮어쓰기를 감지한다.
- 본문은 React의 일반 텍스트로 렌더링한다. HTML 삽입이나 스크립트 실행을 허용하지 않는다.
- 삭제 대신 보관을 제공한다. 게시 취소·고정 해제·재게시도 가능하다.
- Radar 자동 공고를 이 테이블에 복제하지 않는다.

### Radar 및 보안

현재 `startup_radar`는 **35개 테이블** (정책·인덱스 초기 집계 이후 후속 마이그레이션 추가)다. 기존 28개 테이블 전부에 GFC 회원 필수의 RESTRICTIVE 정책을 추가했다. 원래 팀별 permissive 정책과 AND로 결합되므로 Radar 팀 기록만으로 GFC 비회원이 접근할 수 없다.

프로그램·버전·문서·요건·변경 이력은 검증된 GFC 회원에게 열고, 팀 프로필·판정·추천·팀별 캐시는 그 회원의 소속 팀으로 제한한다. 관리자 API는 기존 GFC admin을 사용한다. 관리자 전체 팀 목록에서도 개인 프로필을 일괄 반환하지 않으며 상세 추적은 해당 팀 접근을 추가 확인한다.

새 테이블:

- `feed_snapshots`: 프로그램 버전·팀 또는 preset·프로필/가중치/판정 버전/날짜 키에 따른 계산 결과. 자격 상태·점수·설명과 DTO를 저장한다.
- `extraction_cache`: 수집 원문·첨부 내용·정규화 입력·모델·추출기 버전이 같은 성공 분석을 재사용한다. 브라우저 역할에는 권한이 없다.
- `team_notification_preferences`: Telegram을 연결하기 전에도 알림 선호를 저장한다. 연결된 채널에는 설정을 반영하고, 이후 운영진이 연결할 때 저장된 선호를 적용한다.

기존 GFC의 profiles/projects/teams/problems/auction/Auth 정책·함수·컬럼을 변경하지 않았다. 최초 공지 통합에는 SECURITY DEFINER를 추가하지 않았다. 후속 팀 최초 생성 및 설정/운영 조회에는 명시적 권한 검사를 수행하는 제한된 private 함수를 추가했다. 공지의 수정 시각·revision 트리거만 SECURITY INVOKER로 추가했다.

## BACKEND CONTRACTS

GFC 공지는 기존 Supabase JS 클라이언트로 `gfc_notices`만 조회한다. 명시적 컬럼 목록, title 검색, 공개 상태, 게시 시점, 정렬, range 및 exact count를 사용한다. RLS가 비회원에게 회원 공지와 초안을 숨긴다.

Radar 팀·프로필·공고·상세 조회는 기존 Supabase 세션과 RLS를 적용하는 RPC를 호출한다. 프로필 생성/저장은 RPC와 원자적 이력/재계산 요청을 사용한다. 알림 선호·운영 상태도 안전한 RPC로 전환되어 필수 Python HTTP 경로는 없다. 브라우저에는 DB 비밀번호·service-role·AI 키·Telegram 토큰이 없다.

| 계약 | 용도 / 강제 권한 |
|---|---|
| GET `/api/me` | 현재 사용자의 Radar 팀과 GFC 관리자 여부; 비회원은 팀 자료를 얻지 못함 |
| GET `/api/programs` | 팀 또는 preset, 검색, 유형, 마감일 범위, 자격 상태, 마감 이력, 추천 필터, limit/offset |
| GET `/api/programs/{id}` | 사실·판정·추천·원문·문서·버전·변경 이력; 회원 필수, 팀 선택 시 팀 권한 필수 |
| POST `/api/teams` | 회원이 자신의 Stage 0–4 프로필 생성; 다른 소유자 ID를 제출할 수 없음 |
| GET/PATCH `/api/teams/{id}/profile` | 자기 팀 프로필, 기대 버전 기반 갱신, OWNER/EDITOR 편집 제한, 저장 후 결정론적 재평가 |
| GET/PUT `/api/teams/{id}/preferences` | 자기 팀 알림 선호, Telegram 대화 ID는 반환하지 않음 |
| GET `/api/admin/health` | GFC 관리자만 소스·실행·실패·운영 상태 확인 |

피드 결과는 PostgreSQL에서 검색·유형·날짜·자격·추천 필터를 적용한 뒤 페이지 단위로 반환한다. limit 기본 30, 최대 100이며 GFC는 소스별 20개를 요청한다. 가입 전 Stage 0부터 4까지 팀 없이 미리 볼 수 있다. 단 GFC 학회원 자격은 필요하다.

최초 또는 변경된 추천 범위는 100개씩 결정론적으로 계산해 저장한다. 같은 키의 재조회는 설명을 재사용한다. 시간에 민감한 마감 상태는 DB에서 다시 확인하므로 같은 날 접수 종료 후 열린 공고로 남지 않는다. GitHub Actions의 정기 처리도 독립적으로 기존 추천 테이블을 갱신한다.

## FRONTEND IMPLEMENTATION

| 경로 | 구현 |
|---|---|
| `/notice` | 공개 공지, 회원의 전체/공지/Radar 탭, 잠금 안내, 검색·페이지, 팀/preset·자격·유형·마감 필터 |
| `/notice/:id` | 공지 상세·공개 범위·카테고리·운영진 편집 진입 |
| `/notice/radar/:id` | FACT / ELIGIBILITY / RECOMMENDATION 구분, 인용 근거, 원문·첨부 링크, 팀 전환 |
| `/notice/admin/new` | 기본 PUBLIC·DRAFT 공지 작성 |
| `/notice/admin/:id` | 수정·게시·예약 시점·게시 취소·고정·보관 |
| `/radar/settings` | 여러 팀, 5 preset, 독립 3축, 선택 필드, 선호 유형, Telegram 선호 |
| `/radar/admin` | 최근 수집, 활성·성공 소스, 문서 실패, 자격 파이프라인 오류 |

기존 GFC의 어두운 내비게이션·푸터를 유지하고 본문은 밝은 slate/white, 강조는 cyan, 버튼은 navy로 구성했다. 390px 모바일에서 가로 넘침을 검사했다. 외부 링크는 HTTPS만 허용한다. 계정 또는 회원 자격 변경 시 해당 페이지의 개인 상태를 재설정하고, 이전 요청 응답이 새 계정 화면에 섞이지 않도록 처리한다.

비회원에게는 Radar 탭의 실제 데이터·제목·건수를 가져오지 않는다. 학회원 전용 기능 설명과 로그인/기존 초대 코드 인증 안내만 표시한다. 로그인한 external도 동일하다. Radar RPC 장애 시 GFC 공지는 독립적으로 이용 가능하고 Radar에 준비/재시도 상태를 표시한다.

## ACCESS CONTROL TEST MATRIX

| 항목 | 익명 | 로그인 external | GFC member | GFC admin |
|---|---|---|---|---|
| 게시된 PUBLIC 공지 | 허용 | 허용 | 허용 | 허용 |
| MEMBERS_ONLY 공지 | 차단 | 차단 | 허용 | 허용 |
| 미공개·예약 전·보관 공지 | 차단 | 차단 | 차단 | 관리 가능 |
| Radar 프로그램 제목·건수·상세 | 차단 | 차단 | 허용 | 허용 |
| 자기 Radar 팀 프로필·추천 | 차단 | 차단 | 소속 팀만 | 소속 팀만 |
| 다른 팀의 개인 프로필 | 차단 | 차단 | 차단 | 팀 권한 없으면 차단 |
| 프로필·알림 수정 | 차단 | 차단 | OWNER/EDITOR | 해당 팀 권한 필요 |
| 공지 작성·수정·게시·보관 | 차단 | 차단 | 차단 | 허용 |
| 소스 건강도·실패 운영 정보 | 차단 | 차단 | 차단 | 관리 RPC 허용 |

공유 실제 DB에서도 기존 member 2명/external/admin의 역할을 이용한 SQL role 테스트를 수행했다. 권한 검증용 공지·팀은 예외 서브트랜잭션으로 모두 롤백했다. 새 Auth 계정이나 실제 공지를 만들지 않았다. 회원 역할이나 초대 코드를 수정하지 않았다.

실제 익명 REST: 공지 HTTP 200, 행 0개. Radar custom schema 요청 HTTP 406으로 차단. 별도로 PostgreSQL authenticated external 역할에서 실제 Radar 행이 0개인 것을 확인했으므로 스키마 비노출만 의존하지 않는다. 실제 브라우저 OAuth 로그인을 한 네 역할의 테스트는 아직 수행하지 않았다.

## STARTUPRADAR SETTINGS

0 팀빌딩 전·아이디어 / 1 팀 구성·아이디어 / 2 랜딩·프리토타입 / 3 MVP / 4 사업자등록·법인 보유를 유지한다. preset은 기본값을 채우는 도우미이며 team_status/product_stage/business_status는 독립이다. 기존 직접 입력 값은 preset 변경으로 덮어쓰지 않는다. 미확인 값을 false로 치환하지 않는다.

초기에는 이름과 단계만으로 팀 프로필을 만들 수 있다. 대표자 나이, 지역, 소속 대학, 학생 여부, 팀 인원, 사업 개월 수, 사업자등록일, 업종, 매출, 투자, 해외 진출 관심, 신청자 유형, 지원 이력은 선택 입력이다. 상세 화면에서는 부족한 필드 이름을 알려주고 설정으로 연결한다. PROFILE 저장 후 기존 Python engine이 재평가한다.

팀이 없는 검증 회원도 preset=0으로 즉시 조회된다. 한 사용자의 여러 팀은 각각 다른 결과를 얻을 수 있고, 이전 프로필 버전의 추천과 새 프로필 결과를 혼용하지 않는다.

## TELEGRAM CHANGES

V2 알림에 GFC `/notice` 링크를 추가했다. `/help`는 추천 탐색과 팀 설정의 웹 주소를 우선 안내한다. `/stage` 등 기존 운영 명령은 보존한다. V1 파일·명령·실제 수신자를 바꾸지 않았다. 알림 수신자·대화 ID를 회원 프런트엔드에 노출하거나 임의로 새 대화를 연결하지 않는다.

주간 요약, 중요 신규·변경 추천, D-7/D-3 outbox와 발송 영수증·UNCERTAIN 처리 규칙은 유지한다. 이번 검증에서 실제 Telegram 메시지를 전송하지 않았다.

## TEST RESULTS

- 최신 로컬 Python 전체 **166 passed**, GFC Node/PGlite **65 passed**, Playwright **15 passed**, Vite build PASS.
- 브라우저 전체는 Python API origin 없이 실행한다. 기존 GFC/경매 회귀, 네 역할, 팀 전환, 근거/이력, 프로필 충돌·재시도, 설정 저장·다시 읽기, 관리자 실패 상태와 모바일을 검사한다.
- 브라우저 Auth/REST는 합성 fixture이며 실제 OAuth end-to-end 성공을 뜻하지 않는다.
- 실제 공유 DB의 초기 통합 13개, 저장 공고 조회 12개, 프로필 명령 13개, 최신 설정/상태 11개 묶음 검사를 각 적용 시점에 수행했다. 테스트 행은 모두 롤백했다.
- 최신 설정 적용 전 기존 GFC/Auth/Storage 메타 객체 1,085개 변경·삭제 0. public wrapper 3개 추가, security advisor 결과 동일. 새 RPC 3개 익명 REST 모두 401.
- 최신 커밋 CI와 배포 식별자는 전달물 startup-radar-gfc-delivery.json에 기록한다.

## BUILD RESULTS

GFC `vite build` 성공. 신규 프런트엔드는 기존 스택과 lockfile을 사용한다. 메인 JS 약 471kB, gzip 약 143kB 수준이다. Radar 기존 정적 자산 빌드도 유지한다. 추가한 GFC CI는 PR에서 DB·브라우저·빌드를 검증한다.

로컬 Docker/Podman이 없어 컨테이너 이미지는 로컬에서 직접 빌드하지 못했다. Radar PR의 기존 container job이 이를 검증하도록 구성되어 있다. 기존 GFC npm audit 결과 10개(낮음 2, 중간 2, 높음 6)는 이번 통합과 별개의 잔존 의존성 문제이며 무차별 강제 업그레이드는 수행하지 않았다.

## PRODUCTION REGRESSION RESULTS

- 적용 전후 기존 객체 **1,048개**의 정의·권한·정책·트리거 등을 전체 JSON 다중집합으로 비교해 차이 0개를 확인했다. 같은 이름의 제약조건이 있는 시스템 객체도 중복 개수까지 보존해 비교했다.
- 기존 GFC 테이블의 행 수와 내용 해시: profiles 24, projects 5, teams 0, problems 0, coin_investments 0, settings 1, auction_settings 1 — 전부 동일.
- 새 공지 관련 객체 32개(컬럼·정책·인덱스 등 메타 객체 포함)가 public에 추가됐다. 기존 객체를 삭제·교체한 것은 아니다.
- 현재 실제 수동 공지 0, Radar 팀 0, 기존 실공고 1, Auth 사용자 24. Stage 0/법인 테스트 팀은 남아 있지 않다.
- Supabase advisor에 신규 보안 WARNING/ERROR는 없다. `extraction_cache`의 RLS-no-policy INFO는 backend 전용으로 authenticated/anon 권한을 제거한 의도적 기본 차단이다. 새 인덱스의 unused INFO는 실제 운영 데이터가 아직 쌓이지 않은 상태다.
- 기존 GFC 관련 advisor 결과는 수정하지 않았다. [RLS 기본 차단 안내](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy), [미사용 인덱스 안내](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index).
- 실제 Google 로그인·개인 계정 수정·운영 경매 트랜잭션을 production에서 실행하지 않았다. 해당 동작의 회귀 근거는 실제 기존 마이그레이션을 사용하는 로컬 테스트다.

## EXTERNAL SETUP REQUIRED

1. GitHub Actions 배치에 `RADAR_DATABASE_URL`을 안전하게 연결하고, 공식 수집용 `KSTARTUP_API_KEY`, `BIZINFO_API_KEY` 및 기존 Anthropic 설정을 확인한다. 비밀값은 채팅·브라우저·출력 ZIP에 넣지 않는다.
2. GFC의 기존 Supabase VITE 설정과 Google OAuth redirect를 유지한다. `VITE_RADAR_API_URL`이나 새 호스팅 제공자를 현재 단계의 필수 설정으로 요구하지 않는다.
3. 실제 테스트 계정으로 external/member/admin, 두 Radar 팀, 로그아웃·회원 회수·모바일·공지 공개를 배포된 preview에서 확인한다.
4. 승인된 Telegram 수신 팀을 연결해 실제 발송을 검증한다. 웹훅은 알림 전송만 하는 배치의 필수 요소가 아니다.
5. Phase A 판정은 A. NOT REQUIRED로 확정했다. 배치 런타임과 실운영 검증을 진행하며 Python API 호스팅을 추가 요건으로 요구하지 않는다.

## KNOWN LIMITATIONS

- **운영 `gfc-startup.com/notice`의 공개 배포와 전체 실운영 검증은 아직 미완료**다. Python API 호스팅은 선행 요건이 아니다. 브랜치 구현·공유 DB 적용·테스트 성공을 production 완성으로 간주하지 않는다.
- 현재 GFC 피드는 Python 배치가 저장한 결과를 읽는다. 아직 계산하지 않았거나 최신 프로필·공고·서울 날짜·엔진 세대와 맞지 않으면 계산 대기로 표시한다. 계산·저장 비용은 팀과 보존 공고 버전 수에 비례하며 RPC 실행계획 측정이 필요하다. 프로필 저장·불변 이력·재계산 요청은 현재 원자적 트리거/RPC로 구현되어 있다. [계약과 전환 주의사항](PROFILE-COMMANDS.md)을 참고한다.
- 전체 탭은 별도 두 소스의 각 페이지를 DTO로 합친다. 단일 전역 커서의 완전한 시간순 페이지 계약은 아직 아니므로 소스 간 시점 분포가 크게 다를 때 다음 페이지 경계의 시간순이 완벽하지 않을 수 있다.
- 자연어 OR/복잡한 예외 조항, 손상된 HWP, 스캔 문서 OCR, 비공개 신청 페이지 등 기존 한계는 유지된다. 확정 근거가 부족한 공고는 UNVERIFIABLE로 남는다.
- 실제 수집 확인은 이전 단계의 대학 공고 1건·HWP 2개에 한정된다. 이 공고도 evidence_complete=false이며 공식 두 API는 인증 키 없어서 실패로 기록돼 있다. 국내 전체 공고 커버리지나 AI 정확도를 입증한 상태가 아니다.
- AI 캐시 검증은 mock 호출 횟수와 DB 결과를 사용했다. 실제 API 과금액이나 운영 비용 절감률을 측정하지 않았다.
- 본문 에디터는 일반 텍스트다. 파일 업로드·풍부한 문서 서식·공지 수정 전체 이력·회원 자체 팀 초대·Telegram self-service 연결은 이번 범위에 포함하지 않았다.
- 연결된 팀의 여러 Telegram 구독은 팀 공통 알림 선호를 함께 적용한다. 저장된 팀 공통 선호가 채널 플래그보다 우선하며 발송 계획·클레임 시 재확인한다. 이미 SENDING으로 실행 중인 전송은 소급 취소할 수 없다.
- 새 공지·Radar 페이지 내용은 한국어 중심이다. 기존 한·영 내비게이션은 유지하지만 새 페이지 전체 영문 번역은 후속 작업이다.

## V1/V2 PARALLEL STATUS

실제 동일 기간 V1/V2 병행 수집·누락률·중복률·자격 오판·발송 결과 비교는 **아직 수행하지 않았다**. 기존 로컬 비교 도구와 합성 시나리오 검증을 유지한다.

2026-09-12 GitHub read-only 확인에서 V1 `StartupRadar 자동 실행`은 **disabled_inactivity**, Telegram polling·자동 실행 제어·stage 변경 워크플로는 active로 표시됐다. 이 상태를 이번 변경이 만들거나 자동으로 해제하지 않았다. active 표시는 최근 성공 실행 증거와 동일하지 않다.

V2 DB scheduling.enabled=false, ingestion_enabled=false를 유지했다. V2 실알림을 켜지 않았고 V1을 교체하지 않았다.

## NEXT MILESTONE

Phase A 완료 → 배치 런타임 자격 증명 연결 → GFC preview의 실제 OAuth 계정·실데이터 검증 → 승인된 수신자 알림 검증 → 동일 기간 V1/V2 비교 → cutover 제안 순서다.

## CUTOVER STATUS

**NOT READY / NOT PERFORMED.** 이번 결과물은 통합 구현과 DB 접근 경계를 검증한 단계다. 운영 도메인 배포, 실자격 증명 연결, 실제 OAuth 계정 검증, 지속 수집 및 V1/V2 병행 비교가 남아 있다.
