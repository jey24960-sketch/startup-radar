# StartupRadar 🚀

대학생 창업동아리 회장을 위한 **창업 지원금·경진대회·보조금 자동 수집 + 텔레그램 알림 시스템**

Claude API(web_search)로 전국 창업 지원 정보를 자동 수집하고, 텔레그램 봇으로 주기적으로 알림을 발송합니다.

---

## 수집 대상

| 분류 | 대상 |
|------|------|
| 정부·공공 | K-Startup, 중소벤처기업부, SBA, 청년창업사관학교, TIPS 등 |
| 경진대회 | 도전 K-스타트업, 대학창업300, 위비티 공모전 등 |
| 서울 대학 창업지원단 | 서울대·연세대·고려대·성균관대·한양대 등 18개 대학 |
| 액셀러레이터 | 스파크랩, 프라이머, 퓨처플레이, 블루포인트, 디캠프 등 |

---

## 빠른 시작

### Step 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### Step 2. Anthropic API 키 발급

1. https://console.anthropic.com 접속
2. API Keys → Create Key
3. 로컬에서는 환경변수 `ANTHROPIC_API_KEY`로 설정하고, GitHub Actions에서는 저장소 Secret으로 등록합니다.

### Step 3. 텔레그램 봇 설정

**봇 토큰 발급:**
1. 텔레그램에서 `@BotFather` 검색 → `/newbot`
2. 봇 이름·username 설정 후 토큰 발급
3. 로컬에서는 환경변수 `TELEGRAM_BOT_TOKEN`으로 설정하고, GitHub Actions에서는 저장소 Secret으로 등록합니다.

**Chat ID 확인:**
1. 텔레그램에서 내 봇에게 `/id`를 보냅니다.
2. 답장에 나온 `from.id` 값을 로컬 환경변수 `TELEGRAM_ADMIN_CHAT_ID`, GitHub Actions 저장소 Secret, 또는 Cloudflare Worker Secret으로 등록합니다.
3. `/id`에도 답장이 없으면 Cloudflare Worker가 최신 코드로 배포됐는지, Telegram webhook이 해당 Worker URL을 가리키는지 먼저 확인합니다.
4. 봇과 대화를 먼저 시작해야 메시지를 받을 수 있습니다 (`/start`)

**결과를 여러 사람이 받게 하기:**
1. 결과를 받을 텔레그램 채널 또는 그룹을 만듭니다.
2. 봇을 채널 관리자 또는 그룹 멤버로 추가하고 메시지 발송 권한을 줍니다.
3. 그 채널/그룹의 ID 또는 공개 채널 username을 `TELEGRAM_CHAT_ID`로 등록합니다.
4. 개인 관리자 `from.id`는 `TELEGRAM_ADMIN_CHAT_ID`로 따로 등록합니다.

### Step 4. 연동 테스트

```bash
ANTHROPIC_API_KEY="..." TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHAT_ID="..." TELEGRAM_ADMIN_CHAT_ID="..." python main.py --dry
```

수집 결과가 출력되면 기본 실행 환경이 준비된 것입니다.

### Step 5. 첫 실행

```bash
# 발송 없이 수집 결과만 확인 (추천: 처음엔 dry run으로 먼저 확인)
python main.py --dry

# 실제 수집 + 텔레그램 발송
python main.py
```

---

## 실행 옵션

```bash
python main.py                        # 전체 실행 (수집 + 발송)
python main.py --dry                  # 수집만 (발송 없음)
```

---

## GitHub Actions 자동화 (무료, 서버 불필요)

### 설정 방법

1. GitHub에 이 프로젝트를 Private 저장소로 push
2. 저장소 Settings → Secrets and variables → Actions
3. 다음 시크릿 추가:
   - `ANTHROPIC_API_KEY`: Anthropic API 키
   - `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰
   - `TELEGRAM_CHAT_ID`: 결과를 받을 개인/그룹/채널 ID 또는 공개 채널 username
   - `TELEGRAM_ADMIN_CHAT_ID`: `/run`, `/dry`, `/stop` 명령을 허용할 관리자 개인 `from.id`
   - `GH_PAT`: GitHub Personal Access Token (아래 참고)

4. Actions 탭 → "StartupRadar 자동 실행" → Enable

이후 **매주 화요일·금요일 오후 3시 (KST)**에 자동 실행됩니다.
텔레그램에서 `/stop`을 보내면 화·금 자동 실행만 중지됩니다. 수동 `/run` 실행은 계속 사용할 수 있습니다.
텔레그램에서 `/share`를 보내면 결과를 채널/그룹으로 보내는 설정 방법을 확인할 수 있습니다.
텔레그램에서 `/id`를 보내면 관리자 Secret에 넣어야 할 `from.id`를 확인할 수 있습니다.

### GH_PAT 발급 방법

텔레그램 `/run`, `/dry`, `/stop` 명령어로 GitHub Actions를 제어하려면 `GH_PAT`가 필요합니다.

1. GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens**
2. **Generate new token** 클릭
3. 설정:
   - **Repository access**: 이 저장소만 선택
   - **Permissions → Actions**: `Read and write`
4. 토큰 복사 후 저장소 **Secrets**에 `GH_PAT` 이름으로 추가

### 수동 실행

Actions 탭 → "StartupRadar 자동 실행" → "Run workflow" 버튼

### 자동 실행 중지

텔레그램 봇에게 `/stop`을 보내면 `.startup_radar_auto_run` 값이 `false`로 커밋되고, 이후 화·금 scheduled run은 결과 발송 없이 건너뜁니다.
다시 켜려면 Actions 탭의 "StartupRadar auto-run control" workflow를 수동 실행하고 `enabled` 값을 `true`로 입력하세요.

### 주기 변경

`.github/workflows/startup_radar.yml`의 cron 표현식 수정:

```yaml
# 매일 오전 9시
- cron: "0 0 * * *"

# 매주 월·수·금
- cron: "0 0 * * 1,3,5"

# 매주 월요일·목요일 (기본값)
- cron: "0 0 * * 1,4"
```

---

## 파일 구조

```
startup_radar/
├── main.py               # 메인 실행 파일
├── config.py             # 설정 (API 키, 수집 대상, 주기)
├── requirements.txt
├── core/
│   ├── crawler.py        # Claude AI 웹검색 수집 엔진
│   ├── deduplicator.py   # 중복 알림 방지 DB
│   └── notifier.py       # 텔레그램 발송
├── data/
│   ├── seen_programs.json  # 발송 완료 공고 DB (자동 생성)
│   └── report_*.json       # 수집 결과 히스토리
├── logs/
│   └── startup_radar.log
└── .github/
    └── workflows/
        ├── startup_radar.yml    # 자동 수집·발송 (화·금 15시 KST)
        └── telegram_polling.yml # 텔레그램 명령어 수신 (5분마다)
```

---

## 설정 커스터마이징

`config.py`에서 모든 설정을 조정할 수 있습니다.

```python
# 동아리 프로필 (AI 필터링 기준) - 팀 상황에 맞게 수정
CLUB_PROFILE = """
- 대학생 연합 창업동아리 1기
- 팀당 3~5명, 초기 아이디어/MVP 단계
...
"""

# 알림 설정
MAX_ITEMS_PER_REPORT = 10       # 한 번에 알림할 최대 공고 수
DEADLINE_URGENT_DAYS = 7        # 이 일수 이내면 마감 임박 표시
MIN_RELEVANCE_SCORE = 50        # AI 적합도 점수 50점 미만은 필터링
```

### 새 수집 대상 추가

`config.py`의 `SOURCES`에 추가하면 됩니다:

```python
"서울 대학 창업지원단": [
    # 기존 목록에 추가
    {"name": "XX대 창업지원단", "url": "https://startup.xx.ac.kr/", "type": "대학"},
],
```

---

## 예상 비용

| 항목 | 비용 |
|------|------|
| Claude API | 주 2회 기준 월 약 3,000~8,000원 |
| 텔레그램 봇 | 완전 무료 |
| GitHub Actions | 완전 무료 (Private 저장소 2,000분/월) |
| **합계** | **월 약 3,000~8,000원** |

---

## 문제 해결

**텔레그램 발송 실패 시**
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 환경변수 또는 GitHub Secrets 설정 확인
- 채널로 보내는 경우 봇이 채널 관리자이고 메시지 게시 권한이 있는지 확인
- 봇과 대화를 시작했는지 확인 (텔레그램에서 봇 검색 후 `/start`)
- `/id`가 답장하면 나온 `from.id`를 `TELEGRAM_ADMIN_CHAT_ID`에 넣었는지 확인
- `/id`도 답장이 없으면 Telegram webhook이 최신 Cloudflare Worker URL을 가리키는지 확인
- Cloudflare Worker URL을 브라우저에서 열었을 때 `StartupRadar Telegram webhook is live` 문구가 보이면 최신 Worker 코드가 배포된 것입니다.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ADMIN_CHAT_ID` 값 재확인

**수집 결과가 없을 때**
- `python main.py --dry` 로 수집 결과 확인
- `logs/startup_radar.log` 확인

**API 비용 절감**
- `MIN_RELEVANCE_SCORE`를 높여 필터링 강화
- 수집 주기를 주 1회로 변경
- `SOURCES`에서 불필요한 소스 제거
