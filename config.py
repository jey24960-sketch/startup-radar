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
- 현재 단계: 팀빌딩 (아이디어 구체화 직전)
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
MAX_TOKENS = 4096
CRAWL_DELAY_SECONDS = 0.5       # 소스 간 딜레이 (API 없으므로 짧게)
CHUNK_MAX_CHARS = 15000          # AI 분석 청크 최대 문자 수
MIN_RELEVANCE_SCORE = 60         # 이 점수 미만은 필터링
MAX_ITEMS_PER_REPORT = 7         # 텔레그램 메시지당 최대 공고 수
DEADLINE_URGENT_DAYS = 7         # 마감 임박 기준 (일)
DATA_DIR = "./data"
SEEN_DB = "./data/seen_programs.json"

# ──────────────────────────────────────────────
# 크롤링 소스 목록 (24개)
# key: 소스명(표시용), value: URL
# ──────────────────────────────────────────────

SOURCES = {
    # 정부·공공 (6개)
    "K-Startup": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do",
    "중소벤처기업부": "https://www.mss.go.kr/site/smba/01/10101010000002019101501.jsp",
    "서울산업진흥원": "https://www.sba.seoul.kr/pages/bizSup/bizSupList.do",
    "청년창업사관학교": "https://www.startup.go.kr/young",
    "서울시 청년창업": "https://youth.seoul.go.kr/site/main/content/startup",
    "TIPS": "https://www.jointips.or.kr/bbs/board.php?bo_table=notice",

    # 경진대회·공모전 (3개)
    "위비티": "https://www.wevity.com/?c=find&s=1&gotopage=1",
    "씨엔티테크": "https://cnttech.co.kr/",
    "링커리어": "https://linkareer.com/list/contest",

    # 대학 창업지원단 (11개)
    "서울대 창업지원단": "https://startup.snu.ac.kr/notice",
    "연세대 창업지원단": "https://startup.yonsei.ac.kr/",
    "고려대 창업지원단": "https://startup.korea.ac.kr/",
    "한양대 창업지원단": "https://startup.hanyang.ac.kr/",
    "성균관대 창업지원단": "https://startup.skku.edu/startup/notice.do",
    "서강대 창업지원단": "https://startup.sogang.ac.kr/",
    "경희대 창업지원단": "https://startup.khu.ac.kr/",
    "건국대 창업지원단": "https://startup.konkuk.ac.kr/",
    "동덕여대 창업지원단": "https://startup.dongduk.ac.kr/",
    "숙명여대 창업지원단": "https://startup.sookmyung.ac.kr/",

    # 액셀러레이터·VC (4개)
    "스파크랩": "https://www.sparklabs.co.kr/",
    "디캠프": "https://dcamp.kr/",
    "프라이머": "https://www.primer.kr/",
    "블루포인트": "https://bluepoint.ac/",
}
