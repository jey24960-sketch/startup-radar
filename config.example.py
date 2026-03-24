"""
StartupRadar 설정 파일
여기서 API 키, 검색 대상, 알림 주기를 모두 관리합니다.
"""

# ── API 키 설정 ─────────────────────────────────────────────
ANTHROPIC_API_KEY = "YOUR_ANTHROPIC_API_KEY"   # https://console.anthropic.com
KAKAO_ACCESS_TOKEN = "YOUR_KAKAO_ACCESS_TOKEN"  # 아래 kakao_auth.py 실행해서 발급

# ── 모델 설정 ────────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 4096

# ── 실행 주기 (cron 표현식) ──────────────────────────────────
# 매주 월요일·목요일 오전 9시
SCHEDULE_CRON = "0 9 * * 1,4"

# ── 동아리 프로필 (AI 필터링 기준) ───────────────────────────
CLUB_PROFILE = """
- 대학생 연합 창업동아리 1기 (현재 팀빌딩 단계)
- 팀당 3~5명, 초기 아이디어/MVP 단계
- 지원 가능 금액: 100만원 ~ 1억원
- 관심 분야: IT, 테크, 소셜벤처, 플랫폼
- 서울 소재 대학 연합
- 사업자 등록 전 예비창업팀 지원 프로그램 우선
"""

# ── 수집 대상 소스 ────────────────────────────────────────────
SOURCES = {
    "정부·공공": [
        {
            "name": "K-Startup 창업진흥원",
            "url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do",
            "type": "지원사업",
        },
        {
            "name": "중소벤처기업부 공고",
            "url": "https://www.mss.go.kr/site/smba/01/10101010000002019101501.jsp",
            "type": "지원사업",
        },
        {
            "name": "서울산업진흥원 SBA",
            "url": "https://www.sba.seoul.kr/pages/bizSup/bizSupList.do",
            "type": "지원사업",
        },
        {
            "name": "청년창업사관학교",
            "url": "https://www.startup.go.kr/young",
            "type": "지원사업",
        },
        {
            "name": "서울시 청년 창업지원",
            "url": "https://youth.seoul.go.kr/site/main/content/startup",
            "type": "지원사업",
        },
        {
            "name": "TIPS 프로그램",
            "url": "https://www.jointips.or.kr/bbs/board.php?bo_table=notice",
            "type": "투자연계",
        },
    ],

    "경진대회·공모전": [
        {
            "name": "도전 K-스타트업",
            "url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schStatus=S&schBizGbn=CC",
            "type": "경진대회",
        },
        {
            "name": "대학 창업 300",
            "url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schBizGbn=UC",
            "type": "경진대회",
        },
        {
            "name": "씨엔티테크 공모전 캘린더",
            "url": "https://cnttech.co.kr/",
            "type": "경진대회",
        },
        {
            "name": "위비티 공모전",
            "url": "https://www.wevity.com/?c=find&s=1&gotopage=1",
            "type": "경진대회",
        },
    ],

    "서울 대학 창업지원단": [
        {"name": "서울대 창업지원단", "url": "https://startup.snu.ac.kr/notice", "type": "대학"},
        {"name": "연세대 창업지원단", "url": "https://startup.yonsei.ac.kr/", "type": "대학"},
        {"name": "고려대 창업지원단", "url": "https://startup.korea.ac.kr/", "type": "대학"},
        {"name": "성균관대 창업지원단", "url": "https://startup.skku.edu/startup/notice.do", "type": "대학"},
        {"name": "한양대 창업지원단", "url": "https://startup.hanyang.ac.kr/", "type": "대학"},
        {"name": "이화여대 창업지원단", "url": "https://startup.ewha.ac.kr/", "type": "대학"},
        {"name": "중앙대 창업지원단", "url": "https://startup.cau.ac.kr/", "type": "대학"},
        {"name": "경희대 창업지원단", "url": "https://startup.khu.ac.kr/", "type": "대학"},
        {"name": "서강대 창업지원단", "url": "https://startup.sogang.ac.kr/", "type": "대학"},
        {"name": "홍익대 창업지원단", "url": "https://startup.hongik.ac.kr/", "type": "대학"},
        {"name": "건국대 창업지원단", "url": "https://startup.konkuk.ac.kr/", "type": "대학"},
        {"name": "동국대 창업지원단", "url": "https://startup.dongguk.edu/", "type": "대학"},
        {"name": "국민대 창업지원단", "url": "https://startup.kookmin.ac.kr/", "type": "대학"},
        {"name": "세종대 창업지원단", "url": "https://startup.sejong.ac.kr/", "type": "대학"},
        {"name": "광운대 창업지원단", "url": "https://startup.kw.ac.kr/", "type": "대학"},
        {"name": "숙명여대 창업지원단", "url": "https://startup.sookmyung.ac.kr/", "type": "대학"},
        {"name": "한국외대 창업지원단", "url": "https://startup.hufs.ac.kr/", "type": "대학"},
        {"name": "서울시립대 창업지원단", "url": "https://startup.uos.ac.kr/", "type": "대학"},
    ],

    "액셀러레이터·VC": [
        {"name": "스파크랩", "url": "https://www.sparklabs.co.kr/", "type": "AC"},
        {"name": "프라이머", "url": "https://www.primer.kr/", "type": "AC"},
        {"name": "퓨처플레이", "url": "https://futureplay.co/", "type": "AC"},
        {"name": "블루포인트파트너스", "url": "https://bluepoint.ac/", "type": "AC"},
        {"name": "디캠프", "url": "https://dcamp.kr/programs", "type": "AC"},
        {"name": "매쉬업엔젤스", "url": "https://www.mashupangels.com/", "type": "AC"},
    ],
}

# ── 알림 메시지 설정 ──────────────────────────────────────────
MAX_ITEMS_PER_REPORT = 10       # 한 번에 알림할 최대 공고 수
DEADLINE_URGENT_DAYS = 7        # 이 일수 이내면 "마감 임박" 표시
MIN_RELEVANCE_SCORE = 50        # 이 점수 미만은 필터링 (0~100)

# ── 데이터 저장 경로 ──────────────────────────────────────────
DATA_DIR = "./data"
SEEN_DB = "./data/seen_programs.json"   # 이미 알림한 공고 중복 방지
LOG_FILE = "./logs/startup_radar.log"
