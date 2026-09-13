# StartupRadar / GFC 웹 통합 검토

기준: StartupRadar 현재 staging 코드, GFC-startup.com의 main `bff3859856532c65eb6e3b88d2d98637ef668493`. GFC 코드는 별도 로컬 사본에서 읽고 검사했으며 운영 프런트엔드와 배포 설정을 수정하지 않았다.

## 현재 구조

StartupRadar는 FastAPI가 `/api/*`, `/telegram/webhook` 및 정적 HTML/CSS/JS를 제공한다. UI는 React가 아니라 vanilla JavaScript와 esbuild다. Supabase JS는 로그인 세션을 얻고, API 요청에 Bearer JWT를 보낸다. Python은 Supabase `auth.get_user`로 identity를 확인한 뒤 PostgreSQL 트랜잭션에 `authenticated` 역할과 사용자 claim을 설정한다. 팀 권한은 `startup_radar.team_members`, 관리자 권한은 `startup_radar.admin_users`로 구분한다. 수집·문서·자격 판정·알림·작업 실행은 Python/GitHub Actions의 책임이다.

GFC는 React 18/Vite 5와 자체 pathname 기반 화면 전환을 사용한다. `src/App.jsx`의 switch가 `/profile`, `/auction`, `/tools` 등을 선택한다. `src/lib/supabase.js`에서 Supabase 클라이언트를 만들고 `src/lib/auth.js`의 Google OAuth와 `AuthContext`로 로그인 상태를 관리한다. Vercel 설정은 현재 모든 경로를 `/`로 보내는 SPA rewrite다. 운영 접속은 `https://www.gfc-startup.com/`으로 이동했다.

두 앱이 같은 Supabase 프로젝트를 쓴다는 사실은 계정 identity를 공유한다는 뜻이다. 별도 도메인·서브도메인에 있는 브라우저 localStorage 세션까지 자동 공유하지는 않는다. 현재 V2의 독립 이메일 링크 로그인은 기존 계정을 이용할 수 있으나 GFC에서 로그인한 뒤 클릭 한 번으로 이동하는 통합 UX는 아직 구현되지 않았다. JWT를 URL에 붙여 전달하는 방식은 사용하지 않는다.

## A/B/C 비교

| 기준 | A: Python 웹 별도 배포 | B: UI를 GFC React에 통합 | C: 기존 구조를 유지하며 점진적 통합 |
|---|---|---|---|
| 구현 재사용 | API·UI·문서 처리 모두 즉시 재사용 | Python 도메인은 유지, UI를 React로 옮겨야 함 | staging은 전부 재사용, 검증한 UI만 순차 이전 |
| 인증 | 계정은 공유, 별도 origin 로그인 세션 검증 필요 | 기존 GFC Supabase 클라이언트/세션 사용 가능 | 초기 별도 세션 → 최종 GFC 세션 재사용 |
| RLS | 현재 JWT 확인과 독립 membership 유지 | 동일 백엔드/RLS를 유지하면 동일 | 전 단계에서 동일한 권한 규칙 유지 |
| 배포 복잡도 | Python 호스트·HTTPS·Auth redirect 필요 | Python 호스트 외에 GFC 경로/API proxy 변경 | 초기 낮음, 통합 시 변경을 작은 단위로 검증 |
| 유지보수 | 두 UI의 로그인·스타일·메뉴를 관리 | UI를 한 곳에서 관리, GFC 릴리스에 결합 | 이전 기간 두 UI 유지 비용, 이후 단계적 정리 |
| GFC UX | 별도 서비스 느낌, 로그인 반복 가능 | `/radar`에서 자연스럽게 팀/단계 선택 | 최종 B의 UX를 목표로 하되 기존 웹 안정성 보존 |
| API 책임 | Python이 데이터/판정/작업을 담당 | React는 표시·입력, Python이 판정/작업 | 같은 책임 구분을 유지 |
| 비용 | 기존 DB 공유 + Python 실행·수집 비용 | Python 비용은 계속 필요, UI 개발 비용 큼 | 단기 별도 staging 비용 + 분할 이전 비용 |
| 외부 팀 확장 | 독립 UI 제공이 쉬움 | GFC 사이트 가입/브랜드 의존성 고려 필요 | 독립 API·팀 모델 유지로 외부 UI 추가 가능 |

## 권장: C안

먼저 현재 FastAPI 앱을 staging으로 연결해 DB·실제 로그인·문서·알림 검증을 끝낸다. 이후 GFC에 `/radar` 화면을 추가하면서 공고 탐색, 근거 상세, 팀 선택/프로필 순으로 이전한다. 운영 현황과 장애 복구 UI는 당분간 별도 관리자 화면으로 유지할 수 있다. 기존 UI는 검증 완료 전 제거하지 않는다.

통합 시 GFC의 기존 Supabase 클라이언트가 얻은 access token을 Radar API의 Authorization 헤더로 보낸다. 백엔드는 계속 서버에서 사용자 identity를 확인하며 GFC의 public.profiles role이나 public.teams를 Radar 권한으로 해석하지 않는다. 회원이더라도 Radar membership이 없으면 private 팀 데이터에 접근할 수 없다. 멤버십 생성은 지정된 관리자 작업 또는 검토한 별도 가입 흐름으로 처리한다.

`/radar` UI와 `/radar-api/*` 프록시를 같은 GFC origin에 두는 구성이 우선 검토 대상이다. 현재 Vercel catch-all rewrite보다 앞에 정확한 API proxy 규칙을 배치해야 한다. 대안으로 별도 API origin을 쓰면 FastAPI의 CORS allowlist와 CSP connect-src를 정확한 도메인으로 설정하고 테스트해야 한다. 현재 앱에는 이 cross-origin 설정이나 `/radar` 경로 지원이 구현되어 있지 않으므로 URL만 바꾸면 동작한다고 가정하면 안 된다.

현재 V2 UI에는 `/api/*`, `/static/*`, 로그인 redirect `/` 같은 루트 경로가 있다. 기존 정적 UI를 그대로 `/radar` 뒤에 reverse proxy하려면 base path/정적 파일/콜백 경로 수정이 추가로 필요하다. React 화면으로 옮기는 경우에는 표현 계층을 이전하고 API 계약·eligibility 엔진을 재사용한다. 문서 수집이나 판정 로직을 브라우저로 옮기지 않는다.

호스팅 업체는 이번 작업에서 확정하지 않았다. 장시간 Python 프로세스, HTTPS, 제한된 DB 연결, outbound HTTPS, 안전한 임시 문서 처리 공간과 Linux 프로세스 제한을 지원하는 호스트가 필요하다. 선택적 브라우저 수집을 켜면 Playwright/Chromium 자원도 별도로 검증한다. 가격은 업체·플랜·작업량을 정한 후 견적을 확인해야 하며 이번 비교는 실제 월 요금 견적이 아니다.

Supabase [RLS 안내](https://supabase.com/docs/guides/database/postgres/row-level-security)에 따라 브라우저 identity와 서버의 권한 검증을 분리한다. DB 스키마 격리는 공유 서버의 CPU·메모리·연결 수·Auth 장애까지 격리하지 않으므로, 운영 시 수집 동시성 및 DB 연결 예산도 GFC와 함께 관리해야 한다.
