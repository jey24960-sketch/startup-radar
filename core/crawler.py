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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_NOISE_TAGS = ["nav", "header", "footer", "script", "style", "noscript", "aside", "iframe"]
_CONTENT_TAGS = ["h1", "h2", "h3", "h4", "p", "li", "td", "th", "a", "span", "div"]
_MAX_TEXT_CHARS = 3000
_TIMEOUT = 10
_RETRY_WAIT = 3


def _parse_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    lines = []
    seen_lines: set = set()
    for tag in soup.find_all(_CONTENT_TAGS):
        text = tag.get_text(separator=" ", strip=True)
        if text and len(text) > 5 and text not in seen_lines:
            seen_lines.add(text)
            lines.append(text)

    return "\n".join(lines)[:_MAX_TEXT_CHARS]


def _fetch_text(session: requests.Session, source_name: str, url: str) -> str:
    """
    Session으로 URL을 가져와 텍스트를 추출합니다.
    403 / ConnectionError 시 3초 대기 후 1회 재시도.
    """
    for attempt in range(2):
        try:
            resp = session.get(url, timeout=_TIMEOUT, allow_redirects=True)
            if resp.status_code == 403:
                if attempt == 0:
                    logger.warning(f"{source_name}: 403 봇 차단 — {_RETRY_WAIT}초 후 재시도")
                    time.sleep(_RETRY_WAIT)
                    continue
                raise requests.exceptions.HTTPError(
                    f"403 Client Error: Forbidden for url: {url}"
                )
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return _parse_html(resp.text)

        except requests.exceptions.ConnectionError as e:
            if attempt == 0:
                logger.warning(f"{source_name}: 연결 오류 — {_RETRY_WAIT}초 후 재시도 ({str(e)[:80]})")
                time.sleep(_RETRY_WAIT)
                continue
            raise

    return ""  # 도달하지 않음


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

    session = requests.Session()
    session.headers.update(_HEADERS)

    for i, (name, url) in enumerate(SOURCES.items(), 1):
        logger.info(f"[{i}/{total}] 수집 시작: {name}")
        try:
            text = _fetch_text(session, name, url)
            if text.strip():
                raw_data[name] = text
                logger.info(f"[{i}/{total}] {name}: {len(text)}자 수집 완료")
            else:
                logger.warning(f"[{i}/{total}] {name}: 텍스트 없음 (빈 페이지)")
                failed_sources.append(name)

        except requests.exceptions.Timeout:
            logger.warning(f"[{i}/{total}] {name}: 타임아웃 ({_TIMEOUT}초)")
            failed_sources.append(name)
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"[{i}/{total}] {name}: 연결 오류 - {str(e)[:120]}")
            failed_sources.append(name)
        except requests.exceptions.HTTPError as e:
            status = getattr(e.response, "status_code", None) if hasattr(e, "response") else None
            if status == 403 or "403" in str(e):
                logger.warning(f"[{i}/{total}] {name}: 403 봇 차단")
            else:
                logger.warning(f"[{i}/{total}] {name}: HTTP 오류 - {e}")
            failed_sources.append(name)
        except Exception as e:
            logger.warning(f"[{i}/{total}] {name}: 기타 오류 - {type(e).__name__}: {str(e)[:120]}")
            failed_sources.append(name)

        if i < total:
            time.sleep(CRAWL_DELAY_SECONDS)

    logger.info(f"크롤링 완료: 성공 {len(raw_data)}개 / 실패 {len(failed_sources)}개")
    if failed_sources:
        logger.info(f"실패 소스: {', '.join(failed_sources)}")

    return raw_data, failed_sources
