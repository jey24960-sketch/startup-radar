"""
core/notifier.py
Phase 3: 텔레그램으로 창업 지원 공고를 발송합니다.
메시지 4096자 초과 시 자동 분할 발송.
"""

import logging
import requests
from datetime import datetime, date, timedelta
from typing import Optional
import sys
import os
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DEADLINE_URGENT_DAYS, MAX_ITEMS_PER_REPORT, SOURCES

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_MSG_LEN = 4096

_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _md_escape(text: str) -> str:
    """Telegram Markdown v1에서 특수 의미를 갖는 문자를 이스케이프합니다."""
    if not text:
        return text
    for ch in ("*", "_", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


def _redact_token(text: object, token: str) -> str:
    """로그에 Telegram Bot Token이 섞이지 않도록 마스킹합니다."""
    safe = str(text)
    if token:
        safe = safe.replace(token, "<telegram-token>")
    return safe


def _host_matches(host: str, allowed_host: str) -> bool:
    host = host.lower().removeprefix("www.")
    allowed_host = allowed_host.lower().removeprefix("www.")
    return host == allowed_host or host.endswith(f".{allowed_host}")


def _source_url(source_name: str) -> str:
    if not source_name:
        return ""
    return SOURCES.get(source_name, "")


def _allowed_hosts(source_name: str) -> set[str]:
    source_url = _source_url(source_name)
    if source_url:
        parsed = urlparse(source_url)
        return {parsed.hostname.lower()} if parsed.hostname else set()

    hosts = set()
    for url in SOURCES.values():
        parsed = urlparse(url)
        if parsed.hostname:
            hosts.add(parsed.hostname.lower())
    return hosts


def _safe_apply_url(raw_url: str, source_name: str = "") -> str:
    """Claude가 만든 URL이 수집 소스 도메인에 속하는 http/https 링크인지 검증합니다."""
    if not raw_url:
        return ""

    candidate = str(raw_url).strip()
    if len(candidate) > 2048 or any(ch.isspace() for ch in candidate):
        return ""

    source_url = _source_url(source_name)
    parsed = urlparse(candidate)
    if not parsed.scheme and source_url:
        candidate = urljoin(source_url, candidate)
        parsed = urlparse(candidate)

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""

    allowed_hosts = _allowed_hosts(source_name)
    if not allowed_hosts:
        return ""

    hostname = parsed.hostname.lower()
    if not any(_host_matches(hostname, allowed) for allowed in allowed_hosts):
        logger.warning("허용되지 않은 신청 URL 도메인 제거: %s", hostname)
        return ""

    if any(ch in candidate for ch in ("(", ")", "[", "]", "`")):
        logger.warning("Markdown 안전성 검사를 통과하지 못한 신청 URL 제거: %s", hostname)
        return ""

    return candidate


# ──────────────────────────────────────────────
# 날짜 / 마감 헬퍼
# ──────────────────────────────────────────────

def _days_until(deadline_str: Optional[str]) -> Optional[int]:
    if not deadline_str:
        return None
    try:
        dl = date.fromisoformat(deadline_str)
        return (dl - date.today()).days
    except Exception:
        return None


def _format_deadline(deadline_str: Optional[str]) -> str:
    days = _days_until(deadline_str)
    if days is None:
        return "마감일 미정"
    if days < 0:
        return "마감됨"
    if days == 0:
        return "🔴 오늘 마감!"
    if days <= 7:
        return f"🔴 D-{days}"
    if days <= 14:
        return f"🟡 D-{days}"
    return f"D-{days}"


def _next_report_date() -> str:
    """다음 화요일 또는 금요일을 반환합니다."""
    today = date.today()
    # weekday(): 0=월, 1=화, 4=금
    for delta in range(1, 8):
        nxt = today + timedelta(days=delta)
        if nxt.weekday() in (1, 4):  # 화, 금
            return f"{nxt.month}월 {nxt.day}일({_WEEKDAY_KO[nxt.weekday()]})"
    return ""


# ──────────────────────────────────────────────
# 메시지 빌더
# ──────────────────────────────────────────────

def _header_line() -> str:
    today = date.today()
    wd = _WEEKDAY_KO[today.weekday()]
    return f"*📡 StartupRadar* | {today.month}월 {today.day}일 ({wd})"


def _format_program(p: dict) -> str:
    title = _md_escape(p.get("title", "(제목 없음)"))
    org = _md_escape(p.get("organization", ""))
    deadline_str = _format_deadline(p.get("deadline"))
    score = p.get("relevance_score", 0)
    amount = _md_escape(p.get("amount") or "혜택 확인 필요")
    summary = _md_escape(p.get("summary", ""))
    url = _safe_apply_url(p.get("apply_url") or "", p.get("source", ""))

    lines = [f"*{title}*"]
    lines.append(f"{org} · {deadline_str} · 적합도 {score}점")
    lines.append(f"💰 {amount}")
    lines.append(f"📝 {summary}")
    if url:
        lines.append(f"🔗 [신청/공고 보기]({url})")
    return "\n".join(lines)


def _build_message_with_programs(
    programs: list[dict],
    failed_sources: list[str],
    total_sources: int,
) -> str:
    failed_count = len(failed_sources)

    header = _header_line()
    summary = f"수집 {total_sources}개 소스 · 신규 {len(programs)}건"
    fail_line = f"⚠️ {failed_count}개 소스 수집 실패" if failed_count else ""
    sep = "━━━━━━━━━━━━━━━"

    parts = [header, summary]
    if fail_line:
        parts.append(fail_line)
    parts.append(sep)
    parts.append("")

    # 마감 임박 섹션 (D-7 이내)
    urgent = [
        p for p in programs
        if (_days_until(p.get("deadline")) is not None
            and 0 <= _days_until(p.get("deadline")) <= DEADLINE_URGENT_DAYS)
    ]
    if urgent:
        parts.append("🔴 *마감 임박*")
        for p in urgent:
            parts.append(_format_program(p))
            parts.append("")

    # 일반 추천 섹션 (최대 MAX_ITEMS_PER_REPORT)
    normal = [p for p in programs if p not in urgent]
    if normal:
        parts.append("✅ *이번 추천 공고*")
        for p in normal[:MAX_ITEMS_PER_REPORT]:
            parts.append(_format_program(p))
            parts.append("")

    parts.append(sep)
    parts.append(f"다음 리포트: {_next_report_date()} 오후 3시")

    return "\n".join(parts)


def _build_message_empty(failed_sources: list[str], total_sources: int) -> str:
    failed_count = len(failed_sources)

    parts = [_header_line(), "━━━━━━━━━━━━━━━"]
    parts.append("이번 수집에서 새로운 공고가 없습니다.")
    if failed_count:
        fail_names = ", ".join(failed_sources)
        parts.append(f"⚠️ {failed_count}개 소스 수집 실패: {fail_names}")
    parts.append(f"다음 리포트: {_next_report_date()} 오후 3시")

    return "\n".join(parts)


# ──────────────────────────────────────────────
# 발송
# ──────────────────────────────────────────────

def _split_message(text: str) -> list[str]:
    """4096자 초과 시 줄 단위로 분할합니다. 단일 줄이 4096자를 초과하면 강제 분할합니다."""
    if len(text) <= _MAX_MSG_LEN:
        return [text]

    chunks = []
    lines = text.split("\n")
    current = ""

    for line in lines:
        # 단일 줄 자체가 4096자 초과인 경우 강제 분할
        if len(line) > _MAX_MSG_LEN:
            if current:
                chunks.append(current.strip())
                current = ""
            for i in range(0, len(line), _MAX_MSG_LEN):
                chunks.append(line[i:i + _MAX_MSG_LEN])
            continue

        candidate = (current + "\n" + line) if current else line
        if len(candidate) > _MAX_MSG_LEN:
            if current:
                chunks.append(current.strip())
            current = line
        else:
            current = candidate

    if current:
        chunks.append(current.strip())

    return chunks


def _send_one(text: str, token: str, chat_id: str) -> bool:
    url = _TELEGRAM_API.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        try:
            data = resp.json()
        except ValueError:
            logger.error("텔레그램 오류: %s non-JSON response", resp.status_code)
            return False

        if resp.status_code == 200 and data.get("ok"):
            return True

        description = _redact_token(data.get("description", data), token)
        logger.error("텔레그램 오류: %s %s", resp.status_code, description)
        return False
    except requests.RequestException as e:
        logger.error("텔레그램 요청 예외: %s", _redact_token(e, token))
        return False
    except Exception as e:
        logger.error("텔레그램 예외: %s", type(e).__name__)
        return False


def send_telegram_notification(
    programs: list[dict],
    failed_sources: list[str],
    total_sources: int,
    token: str,
    chat_id: str,
) -> bool:
    """
    텔레그램으로 공고 알림을 발송합니다.

    Args:
        programs: 신규 공고 목록
        failed_sources: 수집 실패한 소스명 목록
        total_sources: 전체 수집 시도 소스 수
        token: Telegram Bot Token
        chat_id: Telegram Chat ID

    Returns:
        bool: 모든 메시지 발송 성공 여부
    """
    if programs:
        text = _build_message_with_programs(programs, failed_sources, total_sources)
    else:
        text = _build_message_empty(failed_sources, total_sources)

    chunks = _split_message(text)
    logger.info(f"텔레그램 발송: {len(chunks)}개 메시지 ({len(text)}자)")

    all_ok = True
    for i, chunk in enumerate(chunks, 1):
        ok = _send_one(chunk, token, chat_id)
        if ok:
            logger.info(f"메시지 {i}/{len(chunks)} 발송 성공")
        else:
            logger.error(f"메시지 {i}/{len(chunks)} 발송 실패")
            all_ok = False

    return all_ok
