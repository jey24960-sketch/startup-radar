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
3. `config.py`의 `ANTHROPIC_API_KEY`에 붙여넣기

### Step 3. 텔레그램 봇 설정

**봇 토큰 발급:**
1. 텔레그램에서 `@BotFather` 검색 → `/newbot`
2. 봇 이름·username 설정 후 토큰 발급
3. `config.py`의 `TELEGRAM_BOT_TOKEN`에 붙여넣기

**Chat ID 확인:**
1. 텔레그램에서 `@userinfobot` 검색 → `/start`
2. 출력된 `Id` 값을 `config.py`의 `TELEGRAM_CHAT_ID`에 붙여넣기
3. 봇과 대화를 먼저 시작해야 메시지를 받을 수 있습니다 (`/start`)

### Step 4. 연동 테스트

```bash
python main.py --test
```

텔레그램에 테스트 메시지가 오면 성공!

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
python main.py --test                 # 텔레그램 연동 테스트
python main.py --cat "정부·공공"      # 특정 카테고리만
python main.py --cat "서울 대학 창업지원단" --dry
```

---

## GitHub Actions 자동화 (무료, 서버 불필요)

### 설정 방법

1. GitHub에 이 프로젝트를 Private 저장소로 push
2. 저장소 Settings → Secrets and variables → Actions
3. 다음 시크릿 추가:
   - `ANTHROPIC_API_KEY`: Anthropic API 키
   - `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰
   - `TELEGRAM_CHAT_ID`: 텔레그램 Chat ID
   - `GH_PAT`: GitHub Personal Access Token (아래 참고)

4. Actions 탭 → "StartupRadar 자동 실행" → Enable

이후 **매주 화요일·금요일 오후 3시 (KST)**에 자동 실행됩니다.

### GH_PAT 발급 방법

텔레그램 `/run`, `/dry` 명령어로 수동 실행하려면 `GH_PAT`가 필요합니다.

1. GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens**
2. **Generate new token** 클릭
3. 설정:
   - **Repository access**: 이 저장소만 선택
   - **Permissions → Actions**: `Read and write`
4. 토큰 복사 후 저장소 **Secrets**에 `GH_PAT` 이름으로 추가

### 수동 실행

Actions 탭 → "StartupRadar 자동 실행" → "Run workflow" 버튼

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
- `python main.py --test`로 토큰·Chat ID 유효 여부 확인
- 봇과 대화를 시작했는지 확인 (텔레그램에서 봇 검색 후 `/start`)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 값 재확인

**수집 결과가 없을 때**
- `python main.py --dry --cat "정부·공공"` 으로 부분 테스트
- `logs/startup_radar.log` 확인

**API 비용 절감**
- `MIN_RELEVANCE_SCORE`를 높여 필터링 강화
- 수집 주기를 주 1회로 변경
- `SOURCES`에서 불필요한 소스 제거
