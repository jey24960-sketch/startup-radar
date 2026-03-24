"""
core/crawler.py
Claude API의 web_search 툴을 활용해 각 소스에서 창업 지원 정보를 수집·분석합니다.
"""

import json
import time
import logging
from datetime import datetime
from typing import Optional
import anthropic
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    MAX_TOKENS,
    CLUB_PROFILE,
    SOURCES,
    MIN_RELEVANCE_SCORE,
    CRAWL_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


EXTRACT_SYSTEM_PROMPT = """당신은 대학생 창업동아리를 위한 지원 프로그램 전문 분석가입니다.
주어진 웹페이지 내용이나 검색 결과에서 창업 지원 프로그램 정보를 추출하고,
동아리 프로필과의 적합도를 정확히 평가해야 합니다.

반드시 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.
한국어로 작성하세요."""


def build_extract_prompt(source: dict, club_profile: str) -> str:
    today = datetime.now().strftime("%Y년 %m월 %d일")
    return f"""오늘 날짜: {today}

다음 사이트에서 현재 모집 중이거나 곧 모집 예정인 창업 지원 프로그램을 찾아주세요.

대상 사이트: {source['name']}
URL: {source['url']}
분류: {source['type']}

동아리 프로필:
{club_profile}

위 사이트를 검색하거나 직접 접근해서, 현재 공고 중인 프로그램 목록을 추출해주세요.

다음 JSON 형식으로 응답하세요 (배열 형태):
[
  {{
    "title": "프로그램명",
    "organization": "주관기관명",
    "type": "지원사업|경진대회|액셀러레이터|보조금|대학지원",
    "target": "지원 대상 요약 (예: 예비창업자, 7년 이내 창업팀 등)",
    "amount": "지원금액 또는 혜택 요약 (모르면 null)",
    "deadline": "마감일 (YYYY-MM-DD 형식, 모르면 null)",
    "apply_url": "신청 URL",
    "summary": "프로그램 핵심 내용 3줄 요약",
    "relevance_score": 0~100,
    "relevance_reason": "적합도 판단 이유 (1~2문장)",
    "tags": ["태그1", "태그2"]
  }}
]

적합도(relevance_score) 기준:
- 80~100: 강력 추천 (팀 단계·조건 완벽 부합)
- 60~79: 추천 (대부분 조건 부합)
- 40~59: 검토 가능 (일부 조건 불일치)
- 0~39: 부적합 (사업자 등록 필수, 이미 마감 등)

현재 모집 중인 공고가 없으면 빈 배열 []을 반환하세요.
"""


def fetch_programs_from_source(source: dict) -> tuple[list[dict], bool]:
    """단일 소스에서 Claude 웹검색으로 프로그램 수집.
    반환: (programs, success) — 오류 시 ([], False)
    """
    logger.info(f"수집 시작: {source['name']}")

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=MAX_TOKENS,
                system=EXTRACT_SYSTEM_PROMPT,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[
                    {
                        "role": "user",
                        "content": build_extract_prompt(source, CLUB_PROFILE),
                    }
                ],
            )

            raw_text = ""
            for block in response.content:
                if block.type == "text":
                    raw_text += block.text

            if not raw_text.strip():
                logger.warning(f"{source['name']}: AI 응답 없음")
                return [], False

            # JSON 파싱
            clean = raw_text.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
                clean = clean.strip()

            programs = json.loads(clean)

            # 적합도 필터링
            filtered = [p for p in programs if p.get("relevance_score", 0) >= MIN_RELEVANCE_SCORE]

            # source 정보 주입
            for p in filtered:
                p["source_name"] = source["name"]
                p["source_url"] = source["url"]
                p["collected_at"] = datetime.now().isoformat()

            logger.info(f"{source['name']}: {len(filtered)}건 수집 (전체 {len(programs)}건 중)")
            return filtered, True

        except json.JSONDecodeError as e:
            logger.error(f"{source['name']}: JSON 파싱 실패 - {e}")
            return [], False
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                logger.warning(f"{source['name']}: 429 rate limit, 15초 대기 후 재시도 ({attempt + 1}/2)")
                time.sleep(15)
                continue
            logger.error(f"{source['name']}: 수집 실패 - {e}")
            return [], False

    return [], False


def crawl_all_sources(delay_seconds: float = CRAWL_DELAY_SECONDS) -> tuple[list[dict], list[str]]:
    """모든 소스 순차 수집 (Rate limit 방지 딜레이 포함).
    반환: (all_programs, failed_source_names)
    """
    all_programs = []
    failed_sources = []
    total_sources = sum(len(v) for v in SOURCES.values())
    processed = 0

    for category, sources in SOURCES.items():
        logger.info(f"\n{'='*40}")
        logger.info(f"카테고리: {category} ({len(sources)}개 소스)")
        logger.info(f"{'='*40}")

        for source in sources:
            programs, success = fetch_programs_from_source(source)
            all_programs.extend(programs)
            if not success:
                failed_sources.append(source["name"])
            processed += 1
            logger.info(f"진행: {processed}/{total_sources}")

            if processed < total_sources:
                time.sleep(delay_seconds)

    # 적합도 내림차순 정렬
    all_programs.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    logger.info(f"\n수집 완료: 총 {len(all_programs)}건 | 실패 소스: {len(failed_sources)}개")
    return all_programs, failed_sources


def crawl_category(category_name: str, delay_seconds: float = 1.5) -> tuple[list[dict], list[str]]:
    """특정 카테고리만 수집 (테스트용).
    반환: (programs, failed_source_names)
    """
    sources = SOURCES.get(category_name, [])
    if not sources:
        logger.error(f"카테고리 없음: {category_name}")
        return [], []

    all_programs = []
    failed_sources = []
    for i, source in enumerate(sources):
        programs, success = fetch_programs_from_source(source)
        all_programs.extend(programs)
        if not success:
            failed_sources.append(source["name"])
        if i < len(sources) - 1:
            time.sleep(delay_seconds)

    all_programs.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return all_programs, failed_sources


if __name__ == "__main__":
    # 빠른 테스트: 정부·공공 첫 번째 소스만
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    test_source = SOURCES["정부·공공"][0]
    result = fetch_programs_from_source(test_source)
    print(json.dumps(result, ensure_ascii=False, indent=2))
