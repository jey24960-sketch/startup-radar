# StartupRadar V2 배포 준비

현재는 배포 준비 단계다. Supabase 프로젝트와 Python 서버 호스팅을 지정한 뒤 실제 연결을 검증해야 한다. 기존 V1 운영 전환은 별도 검증이 끝난 뒤 진행한다.

## 준비된 실행 방법

저장소 루트의 Dockerfile은 Node로 프런트엔드를 빌드하고 Python 실행 이미지에 정적 파일을 포함한다. 실행 프로세스는 일반 사용자 권한으로 구동한다. 빌드 대상은 `.dockerignore` 허용 목록으로 제한하며 `.env`, 로컬 작업 자료, Git 기록은 제외한다. 비밀값은 이미지 빌드가 아니라 호스팅의 런타임 환경변수에 설정한다.

```bash
docker build -t startup-radar-v2 .
# .env는 사용자가 별도로 설정한 로컬 파일이며 저장소에 커밋하지 않는다.
docker run --rm --env-file .env -p 127.0.0.1:8000:8000 startup-radar-v2
```

Docker 없이 배포하는 Python 호스트는 기존 설치·웹 빌드 절차 후 아래 명령으로 시작할 수 있다. 이 명령은 `0.0.0.0`에 바인딩하므로 HTTPS 프록시 뒤의 서버에서 사용한다.

```bash
python -m radar.deployment --serve
```

`PORT`는 호스팅에서 제공하는 포트를 사용하고 기본값은 8000이다. 필수 웹 설정이나 정적 파일이 없으면 서버 시작 전에 종료 코드 1로 실패한다. 프록시 전달 헤더는 기본적으로 신뢰하지 않는다. 애플리케이션은 도메인 루트에 배포한다. `/` 응답은 정적 화면의 생존 확인용이며 DB·로그인 정상 동작을 보증하지 않는다.

## 설정 점검

```bash
python -m radar.deployment
python -m radar.deployment --component web
python -m radar.deployment --component ingestion
python -m radar.deployment --component delivery
python -m radar.deployment --component webhook
python -m radar.deployment --component dispatch
```

이 점검은 환경변수의 존재 여부와 웹 정적 파일·포트만 검사한다. 값, 비밀번호, 토큰은 출력하지 않는다. 외부 연결과 키 유효성을 검사하거나 공고 수집·메일·텔레그램 발송을 실행하지 않는다. `CONFIGURED`는 입력 준비 상태이며 운영 검증 통과를 의미하지 않는다. `ingestion`은 두 공식 API를 모두 사용하는 기본 수집 구성을 기준으로 한다. 특정 HTML 소스만 실행할 때의 최소 요건과 다르다.

| 용도 | 환경변수 |
|---|---|
| 웹 | DATABASE_URL, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY |
| 기본 수집 | DATABASE_URL, ANTHROPIC_API_KEY, KSTARTUP_API_KEY, BIZINFO_API_KEY |
| 알림 발송 | DATABASE_URL, TELEGRAM_BOT_TOKEN |
| 텔레그램 명령 수신 | DATABASE_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET |
| GitHub 작업 요청 | DATABASE_URL, RADAR_GITHUB_TOKEN, GITHUB_REPOSITORY, RADAR_GITHUB_REF |

## 배포 대상 확정 후 순서

1. 지정한 Supabase에 다섯 마이그레이션을 순서대로 적용하고 RLS·권한·연결 방식을 확인한다.
2. 지정한 웹 호스트에 런타임 설정을 등록하고 이미지를 빌드·실행한다. DB 접속 주소는 Supabase Connect 화면에서 얻는다.
3. HTTPS 주소를 Supabase Auth의 사이트·리디렉션 설정에 반영하고 지정된 계정의 로그인과 GFC 멤버십을 구성한다.
4. 서로 다른 팀으로 권한 분리를 검증하고 실제 공고 수집·첨부문서·자격 판정 결과를 확인한다.
5. V2 코드가 있는 GitHub 브랜치에 맞춰 RADAR_GITHUB_REF를 설정한다. 현재 로컬 V2 브랜치는 아직 GitHub에 올리지 않았다. main은 V2 실행 준비 상태로 간주하면 안 된다.
6. 별도 테스트 봇과 지정한 채팅에서 발송·명령·실패 복구를 검증한다. DB 구독 설정도 필요하다.
7. V1/V2를 같은 기간에 비교한 뒤 운영 전환을 결정한다.

상세 설정은 [V2-SETUP.md](V2-SETUP.md), 완료 기준은 [COMPLETION-AUDIT.md](COMPLETION-AUDIT.md)를 따른다. 애플리케이션 시작은 마이그레이션, 팀 생성, 스케줄 활성화, 알림 발송을 자동 실행하지 않는다.

## 이번 검증과 한계

- 배포 설정 검사·시작 제어 테스트 4개 통과, 프런트엔드 빌드 통과.
- 로컬 Docker/Podman이 없어 Linux 컨테이너 빌드·실행은 미검증이다. GitHub 검증 워크플로에 이미지 빌드·앱 import·정적 파일 검사를 추가했으며 아직 원격 실행하지 않았다.
- Docker 기본 이미지 태그는 보안 업데이트에 따라 바뀔 수 있다. 운영에서 검증한 이미지 digest를 기록해 재배포·복구한다.
- 이 이미지는 Python HTTP/문서 수집용이다. 선택적 Playwright/Chromium 브라우저 수집 런타임은 포함하지 않는다.
- 현재 로컬 환경에서 필요한 외부 설정이 없다. GitHub나 기존 운영 서비스의 저장된 비밀값 상태는 이번 검사로 확인하지 않았다.

컨테이너 구성은 [Docker의 다단계 빌드 문서](https://docs.docker.com/build/building/multi-stage/)를 참고했다.
