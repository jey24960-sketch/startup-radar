"""
core/crawler.py
Phase 1: requests + BeautifulSoup4 기반 크롤러.
Claude API 호출 없음. 각 소스에서 텍스트를 수집해 raw_data dict로 반환.
"""

import time
import logging
import sys
import os

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import SOURCES, CRAWL_DELAY_SECONDS

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_NOISE_TAGS = ["nav", "header", "footer", "script", "style", "noscript", "aside", "iframe"]
_CONTENT_TAGS = ["h1", "h2", "h3", "h4", "p", "li", "td", "th", "a", "span", "div"]
_MAX_TEXT_CHARS = 3000


def _fetch_text(source_name: str, url: str) -> str:
    """
    URL에서 HTML을 가져와 노이즈를 제거하고 관련 텍스트를 추출합니다.
    실패 시 예외를 발생시킵니다.
    """
    resp = requests.get(url, headers=_HEADERS, timeout=10, allow_redirects=True)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"

    soup = BeautifulSoup(resp.text, "lxml")

    # 노이즈 태그 제거
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    # 텍스트 추출: 공고/모집/지원/사업 관련 태그 우선
    lines = []
    for tag in soup.find_all(_CONTENT_TAGS):
        text = tag.get_text(separator=" ", strip=True)
        if text and len(text) > 5:
            lines.append(text)

    # 중복 라인 제거 (순서 유지)
    seen_lines: set = set()
    unique_lines = []
    for line in lines:
        if line not in seen_lines:
            seen_lines.add(line)
            unique_lines.append(line)

    full_text = "\n".join(unique_lines)
    return full_text[:_MAX_TEXT_CHARS]


def crawl_all() -> tuple[dict, list]:
    """
    모든 소스를 순서대로 크롤링합니다.

    Returns:
        raw_data: {"소스명": "수집된 텍스트", ...}  (성공한 소스)
        failed_sources: ["소스명", ...]              (실패한 소스)
    """
    raw_data: dict[str, str] = {}
    failed_sources: list[str] = []

    total = len(SOURCES)
    logger.info(f"크롤링 시작: 총 {total}개 소스")

    for i, (name, url) in enumerate(SOURCES.items(), 1):
        logger.info(f"[{i}/{total}] 수집 시작: {name}")
        try:
            text = _fetch_text(name, url)
            if text.strip():
                raw_data[name] = text
                logger.info(f"[{i}/{total}] {name}: {len(text)}자 수집 완료")
            else:
                logger.warning(f"[{i}/{total}] {name}: 텍스트 없음 (빈 페이지)")
                failed_sources.append(name)
        except requests.exceptions.Timeout:
            logger.warning(f"[{i}/{total}] {name}: 타임아웃 (10초 초과)")
            failed_sources.append(name)
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"[{i}/{total}] {name}: 연결 오류 - {e}")
            failed_sources.append(name)
        except requests.exceptions.HTTPError as e:
            logger.warning(f"[{i}/{total}] {name}: HTTP 오류 - {e}")
            failed_sources.append(name)
        except Exception as e:
            logger.warning(f"[{i}/{total}] {name}: 수집 실패 - {e}")
            failed_sources.append(name)

        # 소스 간 딜레이 (마지막 소스 제외)
        if i < total:
            time.sleep(CRAWL_DELAY_SECONDS)

    logger.info(
        f"크롤링 완료: 성공 {len(raw_data)}개 / 실패 {len(failed_sources)}개"
    )
    if failed_sources:
        logger.info(f"실패 소스: {', '.join(failed_sources)}")

    return raw_data, failed_sources
