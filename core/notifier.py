"""
core/notifier.py
텔레그램 Bot API로 창업 지원 정보를 알림 발송합니다.
requests만 사용하여 Bot API 직접 호출.
"""

import logging
import requests
from datetime import datetime, date
from typing import Optional
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    DEADLINE_URGENT_DAYS,
    MAX_ITEMS_PER_REPORT,
)

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _days_until_deadline(deadline_str: Optional[str]) -> Optional[int]:
    if not deadline_str:
        return None
    try:
        dl = date.fromisoformat(deadline_str)
        return (dl - date.today()).days
    except Exception:
        return None


def _format_deadline(deadline_str: Optional[str]) -> str:
    days = _days_until_deadline(deadline_str)
    if days is None:
        return "마감일 미정"
    if days < 0:
        return "마감됨"
    if days == 0:
        return "🔴 오늘 마감!"
    if days <= DEADLINE_URGENT_DAYS:
        return f"🔴 D-{days} (임박!)"
    return f"D-{days}"


def _format_amount(amount: Optional[str]) -> str:
    if not amount:
        return "혜택 상세 확인 필요"
    return amount


def _type_emoji(prog_type: str) -> str:
    mapping = {
        "지원사업": "🏛",
        "경진대회": "🏆",
        "액셀러레이터": "🚀",
        "보조금": "💰",
        "대학지원": "🎓",
        "투자연계": "💼",
        "AC": "🚀",
        "대학": "🎓",
    }
    return mapping.get(prog_type, "📋")


def _build_message(programs: list[dict], run_date: str) -> str:
    """텔레그램 Markdown 메시지 본문 생성"""
    urgent = [p for p in programs if (_days_until_deadline(p.get("deadline")) or 999) <= DEADLINE_URGENT_DAYS]
    normal = [p for p in programs if p not in urgent]

    lines = []
    lines.append(f"*[StartupRadar] {run_date} 창업 지원 리포트*")
    lines.append(f"총 {len(programs)}건 | 임박 {len(urgent)}건\n")

    if urgent:
        lines.append("━━ 🔴 *마감 임박* ━━")
        for p in urgent[:3]:
            emoji = _type_emoji(p.get("type", ""))
            title = p.get("title", "")
            org = p.get("organization", "")
            deadline = _format_deadline(p.get("deadline"))
            amount = _format_amount(p.get("amount"))
            url = p.get("apply_url") or p.get("source_url", "")

            if url:
                lines.append(f"{emoji} *[{title}]({url})*")
            else:
                lines.append(f"{emoji} *{title}*")
            lines.append(f"   {org} | {deadline}")
            lines.append(f"   💰 {amount}")
            lines.append("")

    if normal:
        lines.append("━━ 📋 *이번 주 추천* ━━")
        limit = MAX_ITEMS_PER_REPORT - min(len(urgent), 3)
        for p in normal[:limit]:
            emoji = _type_emoji(p.get("type", ""))
            title = p.get("title", "")
            org = p.get("organization", "")
            deadline = _format_deadline(p.get("deadline"))
            amount = _format_amount(p.get("amount"))
            score = p.get("relevance_score", 0)
            summary = p.get("summary", "")[:60]
            url = p.get("apply_url") or p.get("source_url", "")

            if url:
                lines.append(f"{emoji} *[{title}]({url})*  (적합도 {score}점)")
            else:
                lines.append(f"{emoji} *{title}*  (적합도 {score}점)")
            lines.append(f"   {org} | {deadline}")
            lines.append(f"   💰 {amount}")
            lines.append(f"   📝 {summary}...")
            lines.append("")

    lines.append("─────────────────")
    lines.append("자세한 내용은 각 링크에서 확인하세요.")
    lines.append("_StartupRadar 자동 발송_")

    return "\n".join(lines)


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    """텔레그램 4096자 제한에 맞게 분할"""
    if len(text) <= max_len:
        return [text]

    chunks = []
    lines = text.split("\n")
    current = ""

    for line in lines:
        if len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current.strip())
            current = line
        else:
            current += "\n" + line if current else line

    if current:
        chunks.append(current.strip())

    return chunks


def _send_message(text: str) -> bool:
    """텔레그램 Bot API sendMessage 호출"""
    url = TELEGRAM_API_URL.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200 and resp.json().get("ok"):
            return True
        else:
            logger.error(f"텔레그램 발송 실패: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        logger.error(f"텔레그램 발송 예외: {e}")
        return False


def send_telegram_notification(programs: list[dict]) -> bool:
    """텔레그램으로 창업 지원 공고 알림 발송"""
    if not programs:
        logger.info("발송할 프로그램 없음")
        return True

    run_date = datetime.now().strftime("%m/%d")
    message = _build_message(programs, run_date)
    chunks = _split_message(message)

    all_ok = True
    for i, chunk in enumerate(chunks):
        ok = _send_message(chunk)
        if ok:
            logger.info(f"텔레그램 메시지 {i+1}/{len(chunks)} 발송 성공")
        else:
            logger.error(f"텔레그램 메시지 {i+1}/{len(chunks)} 발송 실패")
            all_ok = False

    return all_ok


def send_test_message() -> bool:
    """연동 테스트용 간단 메시지"""
    test_program = {
        "title": "StartupRadar 연동 테스트",
        "organization": "시스템 테스트",
        "type": "지원사업",
        "amount": "최대 1억원",
        "deadline": None,
        "apply_url": "https://www.k-startup.go.kr",
        "summary": "텔레그램 알림 연동이 정상 작동합니다. 이 메시지가 보이면 설정 완료!",
        "relevance_score": 100,
        "source_name": "테스트",
        "source_url": "https://www.k-startup.go.kr",
    }
    return send_telegram_notification([test_program])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("텔레그램 연동 테스트 메시지 발송 중...")
    ok = send_test_message()
    print("✅ 성공!" if ok else "❌ 실패 - config.py의 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID를 확인하세요")
