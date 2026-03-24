"""
core/notifier.py
카카오 '나에게 보내기' API로 회장에게 알림을 발송합니다.
비즈니스 계정 없이 개인 카카오 계정으로 즉시 사용 가능합니다.
"""

import json
import logging
import requests
from datetime import datetime, date
from typing import Optional
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    KAKAO_ACCESS_TOKEN,
    DEADLINE_URGENT_DAYS,
    MAX_ITEMS_PER_REPORT,
)

logger = logging.getLogger(__name__)

KAKAO_ME_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def _days_until_deadline(deadline_str: Optional[str]) -> Optional[int]:
    if not deadline_str:
        return None
    try:
        dl = date.fromisoformat(deadline_str)
        delta = (dl - date.today()).days
        return delta
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


def _build_message_text(programs: list[dict], run_date: str) -> str:
    """카카오톡 텍스트 메시지 본문 생성"""
    urgent = [p for p in programs if (_days_until_deadline(p.get("deadline")) or 999) <= DEADLINE_URGENT_DAYS]
    normal = [p for p in programs if p not in urgent]

    lines = []
    lines.append(f"[StartupRadar] {run_date} 창업 지원 리포트")
    lines.append(f"총 {len(programs)}건 | 임박 {len(urgent)}건\n")

    if urgent:
        lines.append("━━ 🔴 마감 임박 ━━")
        for p in urgent[:3]:
            emoji = _type_emoji(p.get("type", ""))
            lines.append(f"{emoji} {p['title']}")
            lines.append(f"   {p.get('organization', '')} | {_format_deadline(p.get('deadline'))}")
            lines.append(f"   💰 {_format_amount(p.get('amount'))}")
            if p.get("apply_url"):
                lines.append(f"   🔗 {p['apply_url']}")
            lines.append("")

    if normal:
        lines.append("━━ 📋 이번 주 추천 ━━")
        for p in normal[:MAX_ITEMS_PER_REPORT - min(len(urgent), 3)]:
            emoji = _type_emoji(p.get("type", ""))
            score = p.get("relevance_score", 0)
            lines.append(f"{emoji} {p['title']} (적합도 {score}점)")
            lines.append(f"   {p.get('organization', '')} | {_format_deadline(p.get('deadline'))}")
            lines.append(f"   💰 {_format_amount(p.get('amount'))}")
            lines.append(f"   📝 {p.get('summary', '')[:60]}...")
            if p.get("apply_url"):
                lines.append(f"   🔗 {p['apply_url']}")
            lines.append("")

    lines.append("─────────────────")
    lines.append("자세한 내용은 각 링크에서 확인하세요.")
    lines.append("StartupRadar 자동 발송")

    return "\n".join(lines)


def _build_list_template(programs: list[dict], run_date: str) -> dict:
    """카카오 리스트형 템플릿 (더 보기 좋은 형태)"""
    items = []
    for p in programs[:5]:
        deadline_str = _format_deadline(p.get("deadline"))
        description = f"{p.get('organization', '')} | {deadline_str}"
        item = {
            "title": f"{_type_emoji(p.get('type', ''))} {p['title'][:40]}",
            "description": description[:50],
            "link": {
                "web_url": p.get("apply_url") or p.get("source_url", "https://www.k-startup.go.kr"),
                "mobile_web_url": p.get("apply_url") or p.get("source_url", "https://www.k-startup.go.kr"),
            },
        }
        items.append(item)

    template = {
        "object_type": "list",
        "header_title": f"[StartupRadar] {run_date} 창업 지원 {len(programs)}건",
        "header_link": {
            "web_url": "https://www.k-startup.go.kr",
            "mobile_web_url": "https://www.k-startup.go.kr",
        },
        "contents": items,
        "buttons": [
            {
                "title": "K-Startup 바로가기",
                "link": {
                    "web_url": "https://www.k-startup.go.kr",
                    "mobile_web_url": "https://www.k-startup.go.kr",
                },
            }
        ],
    }
    return template


def send_kakao_notification(programs: list[dict]) -> bool:
    """카카오 나에게 보내기 발송 (리스트 템플릿 → 실패 시 텍스트 폴백)"""
    if not programs:
        logger.info("발송할 프로그램 없음")
        return True

    run_date = datetime.now().strftime("%m/%d")
    headers = {
        "Authorization": f"Bearer {KAKAO_ACCESS_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # 1차 시도: 리스트 템플릿
    try:
        template = _build_list_template(programs, run_date)
        payload = {"template_object": json.dumps(template, ensure_ascii=False)}
        resp = requests.post(KAKAO_ME_URL, headers=headers, data=payload, timeout=10)

        if resp.status_code == 200:
            logger.info(f"카카오 리스트 메시지 발송 성공: {len(programs)}건")
            return True
        else:
            logger.warning(f"리스트 템플릿 실패 ({resp.status_code}), 텍스트로 폴백")

    except Exception as e:
        logger.warning(f"리스트 템플릿 예외: {e}, 텍스트로 폴백")

    # 2차 시도: 텍스트 메시지 (분할 발송 - 5건씩)
    text_body = _build_message_text(programs, run_date)
    chunks = _split_text(text_body, max_len=1900)

    all_ok = True
    for i, chunk in enumerate(chunks):
        try:
            template = {
                "object_type": "text",
                "text": chunk,
                "link": {
                    "web_url": "https://www.k-startup.go.kr",
                    "mobile_web_url": "https://www.k-startup.go.kr",
                },
            }
            payload = {"template_object": json.dumps(template, ensure_ascii=False)}
            resp = requests.post(KAKAO_ME_URL, headers=headers, data=payload, timeout=10)

            if resp.status_code == 200:
                logger.info(f"텍스트 메시지 {i+1}/{len(chunks)} 발송 성공")
            else:
                logger.error(f"텍스트 발송 실패: {resp.status_code} {resp.text}")
                all_ok = False

        except Exception as e:
            logger.error(f"텍스트 발송 예외: {e}")
            all_ok = False

    return all_ok


def _split_text(text: str, max_len: int = 1900) -> list[str]:
    """긴 텍스트를 카카오 길이 제한에 맞게 분할"""
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


def send_test_message() -> bool:
    """연동 테스트용 간단 메시지"""
    test_program = {
        "title": "StartupRadar 연동 테스트",
        "organization": "시스템 테스트",
        "type": "지원사업",
        "amount": "최대 1억원",
        "deadline": None,
        "apply_url": "https://www.k-startup.go.kr",
        "summary": "카카오톡 알림 연동이 정상 작동합니다. 이 메시지가 보이면 설정 완료!",
        "relevance_score": 100,
        "source_name": "테스트",
        "source_url": "https://www.k-startup.go.kr",
    }
    return send_kakao_notification([test_program])


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    print("카카오 연동 테스트 메시지 발송 중...")
    ok = send_test_message()
    print("✅ 성공!" if ok else "❌ 실패 - config.py의 KAKAO_ACCESS_TOKEN을 확인하세요")
