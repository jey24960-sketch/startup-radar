"""
main.py
StartupRadar 메인 실행 파일

실행 방법:
  python main.py          # 전체 수집 + 텔레그램 발송
  python main.py --dry    # 수집만 (발송 없음, 결과 출력)
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# 로깅 설정
Path("./logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("./logs/startup_radar.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

# 환경변수 검증 (없으면 즉시 종료)
try:
    from config import load_secrets, SOURCES, DATA_DIR
    SECRETS = load_secrets()
except ValueError as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)

from core.crawler import crawl_all
from core.analyzer import analyze
from core.deduplicator import filter_new_programs, mark_as_sent, cleanup_expired, get_stats
from core.notifier import send_telegram_notification


def save_results(programs: list[dict], label: str = ""):
    """수집 결과를 JSON으로 저장 (히스토리용)"""
    Path(DATA_DIR).mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    suffix = f"_{label}" if label else ""
    path = f"{DATA_DIR}/report_{ts}{suffix}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(programs, f, ensure_ascii=False, indent=2)
    logger.info(f"결과 저장: {path}")
    return path


def print_summary(programs: list[dict]):
    """터미널 요약 출력"""
    print("\n" + "=" * 60)
    print(f"  신규 공고: {len(programs)}건")
    print("=" * 60)
    for i, p in enumerate(programs[:15], 1):
        deadline = p.get("deadline") or "미정"
        score = p.get("relevance_score", 0)
        print(f"\n{i:2}. [{score:3}점] {p.get('title', 'N/A')}")
        print(f"    기관: {p.get('organization', 'N/A')}")
        print(f"    마감: {deadline} | 금액: {p.get('amount') or 'N/A'}")
        print(f"    {p.get('summary', '')[:80]}")
    if len(programs) > 15:
        print(f"\n  ... 외 {len(programs) - 15}건")
    print("=" * 60)


def run_full(dry_run: bool = False):
    """전체 파이프라인: 크롤링 → AI 분석 → 텔레그램 발송"""
    logger.info("=" * 60)
    logger.info("StartupRadar 실행 시작")
    logger.info(f"모드: {'DRY RUN (발송 없음)' if dry_run else '정상 실행'}")
    logger.info("=" * 60)

    total_sources = len(SOURCES)

    # 1. 환경변수는 시작 시 이미 검증 완료

    # 2. 오래된 DB 정리
    cleanup_expired(days=90)
    stats = get_stats()
    logger.info(f"기존 DB: {stats['total_seen']}건")

    # 3. Phase 1: 크롤링
    logger.info("\n[Phase 1] 크롤링 시작...")
    raw_data, failed_sources = crawl_all()

    if not raw_data:
        logger.error("모든 소스 수집 실패 - 텔레그램에 오류 알림 발송")
        if not dry_run:
            send_telegram_notification(
                programs=[],
                failed_sources=failed_sources,
                total_sources=total_sources,
                token=SECRETS["TELEGRAM_BOT_TOKEN"],
                chat_id=SECRETS["TELEGRAM_CHAT_ID"],
            )
        return

    # 4. Phase 2: AI 분석
    logger.info("\n[Phase 2] AI 분석 시작...")
    programs, analysis_failed = analyze(raw_data, api_key=SECRETS["ANTHROPIC_API_KEY"])

    if analysis_failed:
        logger.warning("AI 분석 전체 실패 - programs 비어있을 수 있음")

    # 5. 중복 필터링
    logger.info("\n[Step] 중복 필터링...")
    new_programs = filter_new_programs(programs)

    if not new_programs:
        logger.info("신규 공고 없음")
        print("\n신규 공고가 없습니다. 다음 수집 때 확인하세요.")
        if not dry_run:
            send_telegram_notification(
                programs=[],
                failed_sources=failed_sources,
                total_sources=total_sources,
                token=SECRETS["TELEGRAM_BOT_TOKEN"],
                chat_id=SECRETS["TELEGRAM_CHAT_ID"],
            )
        return

    # 6. 결과 출력
    print_summary(new_programs)
    save_results(new_programs, "new")

    # 7. Dry run 이면 여기서 종료
    if dry_run:
        logger.info("\n[Phase 3] DRY RUN - 발송 건너뜀")
        print("\n✅ DRY RUN 완료. 위 결과가 실제로 발송될 내용입니다.")
        return

    # 8. Phase 3: 텔레그램 발송
    logger.info("\n[Phase 3] 텔레그램 발송...")
    ok = send_telegram_notification(
        programs=new_programs,
        failed_sources=failed_sources,
        total_sources=total_sources,
        token=SECRETS["TELEGRAM_BOT_TOKEN"],
        chat_id=SECRETS["TELEGRAM_CHAT_ID"],
    )

    # 9. 발송 성공 시에만 mark_as_sent
    if ok:
        mark_as_sent(new_programs)
        logger.info("✅ 전체 완료")
        print(f"\n✅ {len(new_programs)}건 텔레그램 발송 완료!")
    else:
        logger.error("❌ 텔레그램 발송 실패 - mark_as_sent 건너뜀")
        print("\n❌ 텔레그램 발송 실패. logs/startup_radar.log를 확인하세요.")


def main():
    parser = argparse.ArgumentParser(description="StartupRadar - 창업 지원 정보 수집·알림")
    parser.add_argument("--dry", action="store_true", help="수집·분석만, 발송 없음")
    args = parser.parse_args()

    run_full(dry_run=args.dry)


if __name__ == "__main__":
    main()
