"""
core/deduplicator.py
이미 알림한 공고를 추적해서 중복 알림을 방지합니다.
JSON 파일 기반의 경량 DB입니다.
"""

import json
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import SEEN_DB, DATA_DIR

logger = logging.getLogger(__name__)


def _ensure_dir():
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def _load_seen() -> dict:
    _ensure_dir()
    try:
        with open(SEEN_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_seen(seen: dict):
    _ensure_dir()
    with open(SEEN_DB, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def _program_hash(program: dict) -> str:
    """프로그램 고유 식별자 생성.
    title + organization + apply_url 기준으로 해시.
    같은 기관이 동일 제목으로 URL이 다른 공고를 재게시할 경우 별도 공고로 처리."""
    key = f"{program.get('title', '')}|{program.get('organization', '')}|{program.get('apply_url', '')}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def filter_new_programs(programs: list[dict]) -> list[dict]:
    """이미 알림한 공고 제거, 새 공고만 반환"""
    seen = _load_seen()
    new_programs = []

    for program in programs:
        pid = _program_hash(program)
        if pid not in seen:
            new_programs.append(program)

    logger.info(f"중복 필터링: {len(programs)}건 → {len(new_programs)}건 신규")
    return new_programs


def mark_as_sent(programs: list[dict]):
    """알림 발송 완료 처리"""
    seen = _load_seen()
    now = datetime.now().isoformat()

    for program in programs:
        pid = _program_hash(program)
        seen[pid] = {
            "title": program.get("title", ""),
            "sent_at": now,
            "deadline": program.get("deadline"),
        }

    _save_seen(seen)
    logger.info(f"{len(programs)}건 발송 완료 처리")


def cleanup_expired(days: int = 90):
    """마감일이 지난 공고 DB에서 제거 (주기적 정리용)"""
    seen = _load_seen()
    now = datetime.now()
    cutoff = now - timedelta(days=days)
    before = len(seen)

    cleaned = {}
    for pid, info in seen.items():
        sent_at_str = info.get("sent_at", "")
        try:
            sent_at = datetime.fromisoformat(sent_at_str)
            if sent_at > cutoff:
                cleaned[pid] = info
        except Exception:
            cleaned[pid] = info  # 파싱 실패 시 보존

    _save_seen(cleaned)
    removed = before - len(cleaned)
    logger.info(f"DB 정리: {removed}건 제거 (총 {len(cleaned)}건 유지)")


def get_stats() -> dict:
    seen = _load_seen()
    return {
        "total_seen": len(seen),
        "db_path": SEEN_DB,
    }
