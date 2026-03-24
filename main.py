"""
main.py
StartupRadar 메인 실행 파일

실행 방법:
  python main.py          # 전체 수집 + 카카오 발송
  python main.py --test   # 카카오 연동 테스트만
  python main.py --dry    # 수집만 (발송 없음, 결과 출력)
  python main.py --cat "정부·공공"  # 특정 카테고리만
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

from core.crawler import crawl_all_sources, crawl_category, fetch_programs_from_source
from core.deduplicator import filter_new_programs, mark_as_sent, cleanup_expired, get_stats
from core.notifier import send_telegram_notification, send_test_message
from config import SOURCES, DATA_DIR


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
    print(f"  수집 결과: {len(programs)}건")
    print("=" * 60)
    for i, p in enumerate(programs[:15], 1):
        deadline = p.get("deadline") or "미정"
        score = p.get("relevance_score", 0)
        print(f"\n{i:2}. [{score:3}점] {p.get('title', 'N/A')}")
        print(f"    기관: {p.get('organization', 'N/A')}")
        print(f"    마감: {deadline} | 금액: {p.get('amount', 'N/A')}")
        print(f"    {p.get('summary', '')[:80]}")
    if len(programs) > 15:
        print(f"\n  ... 외 {len(programs)-15}건")
    print("=" * 60)


def run_full(dry_run: bool = False):
    """전체 수집 → 중복 제거 → 카카오 발송"""
    logger.info("=" * 60)
    logger.info("StartupRadar 실행 시작")
    logger.info(f"모드: {'DRY RUN (발송 없음)' if dry_run else '정상 실행'}")
    logger.info("=" * 60)

    # 1. 오래된 DB 정리
    cleanup_expired(days=90)
    stats = get_stats()
    logger.info(f"기존 DB: {stats['total_seen']}건")

    # 2. 전체 수집
    logger.info("\n[Step 1] 전체 소스 수집 시작...")
    all_programs = crawl_all_sources(delay_seconds=2.0)
    save_results(all_programs, "all")

    # 3. 중복 제거
    logger.info("\n[Step 2] 중복 필터링...")
    new_programs = filter_new_programs(all_programs)

    if not new_programs:
        logger.info("신규 공고 없음 - 발송 건너뜀")
        print("\n신규 공고가 없습니다. 다음 수집 때 확인하세요.")
        return

    # 4. 결과 출력
    print_summary(new_programs)
    save_results(new_programs, "new")

    # 5. 카카오 발송
    if dry_run:
        logger.info("\n[Step 3] DRY RUN - 발송 건너뜀")
        print("\n✅ DRY RUN 완료. 위 결과가 실제로 발송될 내용입니다.")
        return

    logger.info("\n[Step 3] 텔레그램 발송...")
    ok = send_telegram_notification(new_programs)

    if ok:
        mark_as_sent(new_programs)
        logger.info("✅ 전체 완료")
        print(f"\n✅ {len(new_programs)}건 텔레그램 발송 완료!")
    else:
        logger.error("❌ 텔레그램 발송 실패 - 발송 완료 처리 건너뜀")
        print("\n❌ 텔레그램 발송 실패. logs/startup_radar.log를 확인하세요.")


def run_category(category: str, dry_run: bool = False):
    """특정 카테고리만 실행"""
    logger.info(f"카테고리 실행: {category}")
    programs = crawl_category(category)
    new_programs = filter_new_programs(programs)
    print_summary(new_programs)

    if not dry_run and new_programs:
        ok = send_telegram_notification(new_programs)
        if ok:
            mark_as_sent(new_programs)


def main():
    parser = argparse.ArgumentParser(description="StartupRadar - 창업 지원 정보 수집·알림 시스템")
    parser.add_argument("--test", action="store_true", help="카카오 연동 테스트 메시지 발송")
    parser.add_argument("--dry", action="store_true", help="수집만, 발송 없음")
    parser.add_argument("--cat", type=str, help="특정 카테고리만 실행 (예: '정부·공공')")
    args = parser.parse_args()

    if args.test:
        print("텔레그램 연동 테스트 메시지 발송 중...")
        ok = send_test_message()
        print("[OK] 텔레그램 확인하세요!" if ok else "[FAIL] config.py의 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 확인")
        return

    if args.cat:
        run_category(args.cat, dry_run=args.dry)
    else:
        run_full(dry_run=args.dry)


if __name__ == "__main__":
    main()
