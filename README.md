# StartupRadar 🚀

대학생 창업동아리 회장을 위한 **창업 지원금·경진대회·보조금 자동 수집 + 카카오톡 알림 시스템**

Claude API(web_search)로 전국 창업 지원 정보를 자동 수집하고, 카카오 '나에게 보내기'로 본인 카카오톡에 주기적으로 알림을 발송합니다.

---

## 수집 대상

| 분류 | 대상 |
|------|------|
| 정부·공공 | K-Startup, 중소벤처기업부, SBA, 청년창업사관학교, TIPS 등 |
| 경진대회 | 도전 K-스타트업, 대학창업300, 위비티 공모전 등 |
| 서울 대학 창업지원단 | 서울대·연세대·고려대·성균관대·한양대 등 18개 대학 |
| 액셀러레이터 | 스파크랩, 프라이머, 퓨처플레이, 블루포인트, 디캠프 등 |

---

## 빠른 시작 (Claude Code 바이브코딩)

### Step 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### Step 2. Anthropic API 키 발급

1. https://console.anthropic.com 접속
2. API Keys → Create Key
3. `config.py`의 `ANTHROPIC_API_KEY`에 붙여넣기

### Step 3. 카카오 액세스 토큰 발급

```bash
python kakao_auth.py
```

안내에 따라 진행하면 터미널에 토큰이 출력됩니다.
출력된 `access_token`을 `config.py`의 `KAKAO_ACCESS_TOKEN`에 붙여넣기.

> **참고**: 카카오 개발자 콘솔(https://developers.kakao.com)에서 앱을 먼저 생성해야 합니다.
> - 카카오 로그인 활성화
> - Redirect URI: `https://localhost` 추가
> - 동의항목: '카카오톡 메시지 전송' 활성화

### Step 4. 연동 테스트

```bash
# 카카오톡 연동 확인 (테스트 메시지 발송)
python main.py --test
```

카카오톡에 테스트 메시지가 오면 성공!

### Step 5. 첫 실행

```bash
# 발송 없이 수집 결과만 확인 (추천: 처음엔 dry run으로 먼저 확인)
python main.py --dry

# 실제 수집 + 카카오톡 발송
python main.py
```

---

## 실행 옵션

```bash
python main.py                        # 전체 실행 (수집 + 발송)
python main.py --dry                  # 수집만 (발송 없음)
python main.py --test                 # 카카오 연동 테스트
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
   - `KAKAO_ACCESS_TOKEN`: 카카오 액세스 토큰

4. Actions 탭 → "StartupRadar 자동 실행" → Enable

이후 **매주 월요일·목요일 오전 9시**에 자동 실행됩니다.

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

## 카카오 토큰 갱신

액세스 토큰은 약 6시간 유효합니다. 장기 사용을 위해:

**옵션 A: 수동 갱신** (가장 간단)
```bash
python kakao_auth.py   # 재실행해서 새 토큰 발급
```

**옵션 B: refresh_token으로 자동 갱신** (`kakao_auth.py` 내 `refresh_access_token()` 함수 활용)

GitHub Actions 사용 시에는 매 실행마다 토큰을 갱신하는 로직을 추가하거나,
카카오 채널에 연결된 비즈니스 계정을 사용하면 장기 토큰이 발급됩니다.

---

## 파일 구조

```
startup_radar/
├── main.py               # 메인 실행 파일
├── config.py             # 설정 (API 키, 수집 대상, 주기)
├── kakao_auth.py         # 카카오 토큰 발급 도우미
├── requirements.txt
├── core/
│   ├── crawler.py        # Claude AI 웹검색 수집 엔진
│   ├── deduplicator.py   # 중복 알림 방지 DB
│   └── notifier.py       # 카카오톡 발송
├── data/
│   ├── seen_programs.json  # 발송 완료 공고 DB (자동 생성)
│   └── report_*.json       # 수집 결과 히스토리
├── logs/
│   └── startup_radar.log
└── .github/
    └── workflows/
        └── startup_radar.yml  # GitHub Actions 스케줄러
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
| 카카오 나에게 보내기 | 완전 무료 |
| GitHub Actions | 완전 무료 (Private 저장소 2,000분/월) |
| **합계** | **월 약 3,000~8,000원** |

---

## 문제 해결

**카카오 발송 실패 시**
- `python main.py --test`로 토큰 유효 여부 확인
- 토큰 만료 시 `python kakao_auth.py` 재실행

**수집 결과가 없을 때**
- `python main.py --dry --cat "정부·공공"` 으로 부분 테스트
- `logs/startup_radar.log` 확인

**API 비용 절감**
- `MIN_RELEVANCE_SCORE`를 높여 필터링 강화
- 수집 주기를 주 1회로 변경
- `SOURCES`에서 불필요한 소스 제거
