"""V1 compatibility entry point during the staged V2 migration."""
import argparse
import json
import logging
from pathlib import Path

from config import DATA_DIR, SOURCES, load_secrets
from core.clock import now
from core.crawler import crawl_all
from core.analyzer import analyze
from core.deduplicator import filter_new_programs, mark_as_sent, cleanup_expired
from core.notifier import send_telegram_notification

logger = logging.getLogger("main")


def save_results(programs, label="new"):
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    path = Path(DATA_DIR) / f"report_{now():%Y%m%d_%H%M%S_%f}_{label}.json"
    path.write_text(json.dumps(programs, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_full(dry_run=False):
    secrets = load_secrets()
    if not dry_run:
        cleanup_expired(days=90)
    raw, failed_sources = crawl_all()
    analysis = analyze(raw, api_key=secrets["ANTHROPIC_API_KEY"])
    programs = filter_new_programs(analysis.programs)
    save_results({"status": analysis.status, "programs": programs,"all_programs":analysis.programs,
                  "observed_at":now().isoformat(),"configured_source_count":len(SOURCES),
                  "failed_sources": failed_sources,
                  "analysis_failures": [vars(f) for f in analysis.failures]}, "run")
    logger.info("Analysis=%s programs=%s source_failures=%s", analysis.status, len(programs), len(failed_sources))
    failed = bool(failed_sources or analysis.failures)
    if dry_run:
        print(json.dumps(programs, ensure_ascii=False, indent=2))
        return 1 if failed else 0
    delivery = send_telegram_notification(
        programs, failed_sources, len(SOURCES), secrets["TELEGRAM_BOT_TOKEN"],
        secrets["TELEGRAM_CHAT_ID"], analysis_failures=analysis.failures,
        on_delivered=mark_as_sent,
    )
    logger.info("Delivered=%s failed=%s pending=%s", len(delivery.delivered), len(delivery.failed), len(delivery.pending))
    return 1 if failed or not delivery.ok else 0


def main():
    parser = argparse.ArgumentParser(description="StartupRadar V1 compatibility pipeline")
    parser.add_argument("--dry", action="store_true", help="Collect/analyze without program delivery")
    args = parser.parse_args()
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(),
        logging.FileHandler("logs/startup_radar.log", encoding="utf-8")])
    try:
        return run_full(args.dry)
    except Exception:
        logger.exception("StartupRadar run failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
