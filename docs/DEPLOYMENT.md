# StartupRadar V2 배포와 실수집 검증

**Phase A 완료: Python HTTP API A. NOT REQUIRED.** GFC React/Vercel이 회원 UI이며 기존 Supabase 세션과 RPC로 필수 Radar 경로를 처리한다. Python은 배치로 실행한다. 별도 Python 호스트와 VITE_RADAR_API_URL을 설정할 필요가 없다. [API 판정](PYTHON-API-DECISION.md), [설정/상태 계약](SETTINGS-HEALTH.md), [현재 운영 Goal](GFC-OPERATING-GOAL.md)을 따른다.

공유 Supabase는 `etvffzxqdgblvkfdikwl`, Radar 데이터는 `startup_radar`다. GFC 공지는 별도 `public.gfc_notices`다. 최신 적용은 `20260912143423_gfc_radar_preferences_and_health`이며 두 저장소의 공유 ledger를 일괄 push/repair하지 않는다. 현재 브랜치 구현·공유 DB 적용·자동 테스트는 운영 전환과 구분한다.

## 필요한 실행 설정

| 실행 위치 | 설정 이름 | 용도/현재 확인 |
|---|---|---|
| Radar GitHub Actions Secrets | RADAR_DATABASE_URL | Python에는 DATABASE_URL로 전달. 현재 저장소 Secrets 이름 목록에서 확인되지 않음 |
| 같은 위치 | KSTARTUP_API_KEY, BIZINFO_API_KEY | 두 공식 API. 현재 저장소 Secrets 이름 목록에서 확인되지 않음 |
| 같은 위치 | ANTHROPIC_API_KEY | 이름 존재 확인, 유효성·실제 호출 미검증 |
| 같은 위치 | TELEGRAM_BOT_TOKEN | 이름 존재 확인. 승인 수신자 실검증 전에는 전송하지 않음 |
| 로컬/기존 보안 배치 환경 | DATABASE_URL, 위 수집 키 | 기존 설정 환경이 있다면 그 환경에서 현재 코드로 검증 가능. 비밀값은 채팅/로그에 출력하지 않음 |
| 기존 GFC Vercel | VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY | 기존 설정·Google OAuth 유지. DB 비밀번호/service-role은 브라우저에 넣지 않음 |

저장소 설정: [StartupRadar Actions Secrets](https://github.com/jey24960-sketch/startup-radar/settings/secrets/actions). 이름 목록 점검은 조직/Environment/다른 호스트에 키가 없다는 증거가 아니다. GitHub Secret은 값을 다시 읽을 수 있는 로컬 저장소가 아니므로, Secrets 추가만으로 이 로컬 Python에 값이 전달되지는 않는다.

DB 연결 주소는 해당 프로젝트의 Connect 화면에서 복사한다. IPv4 환경이면 session pooler를 사용하고 실제 host/사용자명을 추측하지 않는다. 현재 worker는 장시간 작업 동안 트랜잭션 advisory lock과 별도 DB 트랜잭션을 사용하므로 실제 연결 수·권한·SSL과 타임아웃을 검증한다. [Supabase 연결 안내](https://supabase.com/docs/guides/database/connecting-to-postgres).

## 스케줄을 켜지 않는 수동 검증

아래 명령은 현재 브랜치와 검토된 DB 연결이 있는 안전한 실행 환경에서 사용한다. 로컬 `.env.staging`은 자동 로드되지 않는다. 비밀값을 인자로 쓰거나 셸 출력에 표시하지 않는다.

```bash
python -m radar.deployment --component ingestion
# 등록된 한 소스로 수집·문서·판정·저장을 검증한다.
python -m radar.cli run --kind INGEST --source korea-startup-html
# 공식 키가 연결된 뒤 각각 실행한다.
python -m radar.cli run --kind INGEST --source kstartup
python -m radar.cli run --kind INGEST --source bizinfo
# 수집/AI/Telegram 없이 저장 조회 결과만 다시 계산한다.
python -m radar.cli run --kind REFRESH
```

설정 검사 성공은 존재 여부 확인이며 인증/외부 연결 성공을 뜻하지 않는다. 기본 ingestion 검사는 두 공식 키와 AI까지 요구하므로 개별 HTML 수집의 최소 조건보다 엄격하다. 명시적 INGEST/REFRESH는 비활성 정기 스케줄과 독립적으로 실행된다. `--deliver`를 사용하지 않으면 실제 전송하지 않는다. INGEST는 해당 소스 프로그램을 저장하고 기존 엔진으로 판정과 회원 조회 결과를 갱신한다. 기존 출처·프로필을 초기화하거나 합성 회원을 만들지 않는다.

실행 전후 scheduling.enabled=false와 ingestion_enabled=false, 구독/알림 상태를 확인한다. 결과에는 실행 ID·소스 상태·공고/문서/버전·추출/판정 근거를 연결한다. 실패를 EMPTY로 기록하지 않는다. 실제 GFC 회원 화면에서 같은 프로그램·버전·근거를 확인하기 전에는 end-to-end PASS로 보고하지 않는다.

## GitHub Actions의 현재 제약

`.github/workflows/startup_radar_v2.yml`은 기능 브랜치에 있으며 현재 기본 브랜치의 등록된 운영 워크플로 목록에는 없다. GitHub의 workflow_dispatch는 워크플로 파일이 기본 브랜치에 있어야 한다. `--ref feature/startup-radar-v2`만으로 이 선행 조건을 해결할 수 없다. [GitHub 수동 실행 안내](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

기존 V2 운영 job은 `RADAR_V2_ENABLED=true`일 때만 실행된다. 이 변수를 단순히 설정하거나 main에 전체 기능을 먼저 병합하지 않는다. 현재 가능한 첫 검증은 자격증명이 준비된 로컬/기존 보안 배치 환경에서 위 명시적 명령을 실행하는 것이다. Actions만 사용할 수 있다면 별도 검토된 수동 검증 진입점이 필요하며, 기본 브랜치 변경과 production schedule 활성화를 분리해야 한다. 현재 그런 변경·활성화는 수행하지 않았다.

정상 운영 시 workflow concurrency와 DB advisory lock이 중복 배치를 제한한다. DB TICK의 정기 수집·요약·마감 작업은 서울 기준 runtime_settings를 따른다. V2 repo/DB schedule과 delivery gate는 실운영 수락 기준 확인 전까지 비활성 유지한다.

## 보존한 선택적 Python HTTP 유틸리티

기존 FastAPI, Dockerfile, 정적 dashboard, 설정 검사기는 호환성과 진단용으로 보존했다. GFC 배포 요건은 아니다. 필요할 때 기존 절차 `docker build -t startup-radar-v2 .` 및 `python -m radar.deployment --serve`로 검증할 수 있다. HTTP 사용 시에만 web 설정·정적 자산·HTTPS 프록시·허용 CORS를 검토한다. 기존 dashboard는 기본 비활성이고 `RADAR_LEGACY_UI_ENABLED=true`는 별도 유틸리티 검증용이다. 현재 GFC 코드는 VITE_RADAR_API_URL을 읽지 않는다.

컨테이너는 일반 사용자로 실행하며 `.env`와 작업 자료를 빌드에서 제외한다. 선택적 JS 소스 수집용 Chromium은 포함하지 않는다. Container CI 성공은 실제 DB/OAuth/수집 성공을 대신하지 않는다.

## 남은 운영 검증

실제 공식 API/허용 HTML 수집 → 배치/Supabase 저장 → 실제 OAuth 역할과 팀별 GFC 화면 → 승인된 수신자의 요약·중요 공고·마감 알림 → 동일 기간 V1/V2 비교 → cutover 제안 순서다. 이전 profile trigger 이전 Python 코드의 수동 이력 INSERT는 현재 DB와 중복 키 충돌이 생기므로, 현재 브랜치 코드와 DB를 함께 검증해야 한다. [프로필 전환 계약](PROFILE-COMMANDS.md).

실제 수집·계정·알림·병행 근거가 모이기 전에는 DONE/READY로 표시하지 않는다. V1 코드와 워크플로를 유지하며 main 병합·V2 운영 활성화·V1 교체는 수행하지 않았다.
