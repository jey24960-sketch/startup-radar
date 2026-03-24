"""
config.py
환경변수 기반 설정. 값이 비어있으면 시작 시점에 ValueError로 종료.
"""

import os

# ──────────────────────────────────────────────
# 환경변수 검증 헬퍼
# ──────────────────────────────────────────────

def _require_env(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise ValueError(
            f"[ERROR] 환경변수 '{key}'가 설정되지 않았습니다. "
            f"GitHub Secrets 또는 로컬 환경에서 확인하세요."
        )
    return val


def load_secrets() -> dict:
    """필수 환경변수를 로드합니다. 없으면 ValueError를 발생시킵니다."""
    return {
        "ANTHROPIC_API_KEY": _require_env("ANTHROPIC_API_KEY"),
        "TELEGRAM_BOT_TOKEN": _require_env("TELEGRAM_BOT_TOKEN"),
        "TELEGRAM_CHAT_ID": _require_env("TELEGRAM_CHAT_ID"),
    }


# ──────────────────────────────────────────────
# 동아리 프로필 (AI 필터링 기준)
# 단계별 변경: '현재 단계'를 아래 순서로 수정하세요.
#   팀빌딩 → 아이디어 → MVP → 초기매출
# ──────────────────────────────────────────────

CLUB_PROFILE = """
- 대학생 연합 창업동아리 1기
- 현재 단계: 아이디어
- 팀당 3~5명
- 지원 가능 금액: 100만원 ~ 1억원
- 관심 분야: IT, 테크, 소셜벤처, 플랫폼
- 서울 소재 대학 연합
- 사업자 등록 전 예비창업팀 지원 프로그램 우선
- 글로벌 진출 관심 있음
"""
# 팀빌딩 완료 후 '현재 단계'를 '아이디어' → 'MVP' 순으로 변경하세요.

# ──────────────────────────────────────────────
# 수치 설정
# ──────────────────────────────────────────────

CLAUDE_MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 8192
CRAWL_DELAY_SECONDS = 0.5       # 소스 간 딜레이 (API 없으므로 짧게)
CHUNK_MAX_CHARS = 10000          # AI 분석 청크 최대 문자 수
MIN_RELEVANCE_SCORE = 60         # 이 점수 미만은 필터링
MAX_ITEMS_PER_REPORT = 7         # 텔레그램 메시지당 최대 공고 수
DEADLINE_URGENT_DAYS = 7         # 마감 임박 기준 (일)
DATA_DIR = "./data"
SEEN_DB = "./data/seen_programs.json"

# ──────────────────────────────────────────────
# 크롤링 소스 목록 (15개, 접근 가능한 소스만)
# key: 소스명(표시용), value: URL
# ──────────────────────────────────────────────

SOURCES = {
    # 정부·공공 (2개)
    "K-Startup": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do",
    "서울산업진흥원": "https://www.sba.seoul.kr/pages/bizSup/bizSupList.do",

    # 대학 창업지원단 (5개)
    "고려대 창업지원단": "https://startup.korea.ac.kr/rss",   # RSS 피드 (application/rss+xml)
    "한양대 창업지원단": "https://startup.hanyang.ac.kr/",
    "경희대 창업지원단": "https://startup.khu.ac.kr/",
    "동덕여대 창업지원단": "https://startup.dongduk.ac.kr/",
    "숙명여대 창업지원단": "https://startup.sookmyung.ac.kr/",

    # 액셀러레이터·VC (4개)
    "스파크랩": "https://www.sparklabs.co.kr/",
    "프라이머": "https://www.primer.kr/",
    "매쉬업엔젤스": "https://www.mashupangels.com/portfolio",
    "퓨처플레이": "https://futureplay.co/",

    # 재단·임팩트 (3개)
    "아산나눔재단": "https://www.asan-nanum.org/program/",
    "아산 두어스": "https://doers.asan-nanum.org/",
    "카카오임팩트": "https://kakaoimpact.org/",

    # 커뮤니티·행사 (1개)
    "스타트업얼라이언스": "https://startupall.kr/",

    # 창업 허브 (1개)
    "D.Camp": "https://dcamp.kr/",
}
