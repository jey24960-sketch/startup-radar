"""
core/analyzer.py
Phase 2: raw_data를 받아 Claude API로 창업 지원 프로그램을 추출·분석.
청크 분할로 API 호출 횟수를 최소화합니다.
"""

import json
import logging
import re
import sys
import os
from datetime import date

import anthropic

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    CLUB_PROFILE,
    CLAUDE_MODEL,
    MAX_TOKENS,
    CHUNK_MAX_CHARS,
    MIN_RELEVANCE_SCORE,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """당신은 대학생 창업동아리를 위한 창업 지원 프로그램 분석 전문가입니다.
제공된 웹페이지 텍스트에서 현재 모집 중이거나 모집 예정인 창업 지원 프로그램만 추출하세요.

동아리 프로필:
{CLUB_PROFILE}

오늘 날짜: {TODAY}

추출 기준:
- 반드시 현재 모집 중(접수 기간 내) 또는 모집 예정(미래 일정)인 것만
- 이미 마감된 공고는 절대 포함하지 말 것
- 예비창업팀, 아이디어 단계도 지원 가능한 것 우선
- 사업자등록 필수 조건이면 relevance_score 20 이하로
- 나이 제한이 있으면 대학생(20대) 해당 여부 명확히 판단

반드시 JSON 배열만 응답하세요. 다른 텍스트 없이.
공고가 없으면 빈 배열 []"""

_USER_PROMPT_TEMPLATE = """다음 웹페이지 텍스트들에서 창업 지원 프로그램을 추출해주세요:

{sources_block}

JSON 형식:
[
  {{
    "title": "프로그램 정식 명칭",
    "organization": "주관기관명",
    "source": "수집한 소스명",
    "type": "지원사업|경진대회|액셀러레이터|보조금|대학지원|투자연계",
    "target": "지원 대상 (나이, 팀 구성, 단계 등)",
    "amount": "지원금액 또는 주요 혜택 (없으면 null)",
    "deadline": "YYYY-MM-DD (모르면 null)",
    "apply_url": "신청 또는 공고 URL",
    "summary": "이 프로그램이 동아리에 왜 유용한지 2문장으로",
    "relevance_score": 0,
    "relevance_reason": "점수 판단 근거 1문장",
    "stage_fit": "팀빌딩|아이디어|MVP|초기매출 중 해당하는 것"
  }}
]"""


def _build_chunks(raw_data: dict[str, str]) -> list[dict[str, str]]:
    """
    소스 텍스트를 CHUNK_MAX_CHARS 기준으로 청크로 분할합니다.
    각 청크는 {"소스명": "텍스트"} dict입니다.
    """
    chunks: list[dict[str, str]] = []
    current_chunk: dict[str, str] = {}
    current_size = 0

    for name, text in raw_data.items():
        entry_size = len(name) + len(text) + 10  # 구분자 여유분

        # 현재 청크가 가득 찼고 이미 내용이 있으면 새 청크 시작
        if current_size + entry_size > CHUNK_MAX_CHARS and current_chunk:
            chunks.append(current_chunk)
            current_chunk = {}
            current_size = 0

        current_chunk[name] = text
        current_size += entry_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _call_claude(client: anthropic.Anthropic, chunk: dict[str, str]) -> list[dict]:
    """
    단일 청크를 Claude API로 분석합니다.
    JSON 파싱 실패 시 빈 리스트를 반환합니다.
    """
    today = date.today().strftime("%Y-%m-%d")
    system = _SYSTEM_PROMPT.format(
        CLUB_PROFILE=CLUB_PROFILE.strip(),
        TODAY=today,
    )

    # 소스 블록 구성
    parts = []
    for name, text in chunk.items():
        parts.append(f"{name}:\n{text}")
    sources_block = "\n\n---\n\n".join(parts)

    user_msg = _USER_PROMPT_TEMPLATE.format(sources_block=sources_block)

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        if not response.content:
            logger.error("Claude 응답 content가 비어있음")
            return []
        raw_text = response.content[0].text.strip()

        # JSON 블록 추출 (```json ... ``` 감싸인 경우 처리)
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            raw_text = "\n".join(
                line for line in lines
                if not line.startswith("```")
            ).strip()

        # 1차: 중첩 배열을 고려한 브라켓 카운팅으로 완전한 JSON 배열 추출
        start = raw_text.find("[")
        if start == -1:
            logger.warning("청크 파싱 실패: JSON 배열을 찾을 수 없음")
            return []
        bracket_count = 0
        end = start
        for i, ch in enumerate(raw_text[start:], start):
            if ch == "[":
                bracket_count += 1
            elif ch == "]":
                bracket_count -= 1
            if bracket_count == 0:
                end = i
                break
        else:
            # 배열이 잘린 경우 복구 시도
            end = None

        try:
            if end is not None:
                programs = json.loads(raw_text[start:end + 1])
            else:
                # 2차: 응답이 중간에 잘린 경우 마지막 완전한 } 까지만 복구
                last_brace = raw_text.rfind("}")
                if last_brace == -1:
                    raise json.JSONDecodeError("복구 불가", raw_text, 0)
                recovered = raw_text[start:last_brace + 1] + "]"
                programs = json.loads(recovered)
                logger.warning("응답 잘림 감지 — 부분 복구 후 파싱 성공")

        if not isinstance(programs, list):
            logger.warning("Claude 응답이 리스트가 아님, 빈 리스트로 처리")
            return []
        return programs

    except json.JSONDecodeError as e:
        logger.warning(f"청크 파싱 실패: {e}")
        return []
    except anthropic.APIError as e:
        logger.error(f"Claude API 오류: {e}")
        return []
    except Exception as e:
        logger.error(f"분석 중 예외 발생: {e}")
        return []


def analyze(raw_data: dict[str, str], api_key: str) -> tuple[list[dict], bool]:
    """
    raw_data를 청크로 분할해 Claude API로 분석합니다.

    Args:
        raw_data: {"소스명": "텍스트", ...}
        api_key: Anthropic API 키

    Returns:
        programs: 관련성 60점 이상, 중복 제거, 점수 내림차순 정렬된 공고 목록
        analysis_failed: 모든 청크 실패 시 True
    """
    if not raw_data:
        logger.warning("raw_data가 비어있음, 분석 건너뜀")
        return [], True

    client = anthropic.Anthropic(api_key=api_key)
    chunks = _build_chunks(raw_data)
    logger.info(f"분석 시작: {len(raw_data)}개 소스 → {len(chunks)}개 청크")

    all_programs: list[dict] = []
    success_count = 0

    for i, chunk in enumerate(chunks, 1):
        source_names = list(chunk.keys())
        logger.info(f"[{i}/{len(chunks)}] 청크 분석: {source_names}")
        programs = _call_claude(client, chunk)
        if programs is not None:
            all_programs.extend(programs)
            success_count += 1
            logger.info(f"[{i}/{len(chunks)}] {len(programs)}건 추출")

    analysis_failed = success_count == 0

    # 중복 제거 (title + organization 기준, 높은 점수 우선)
    seen_keys: set = set()
    unique_programs: list[dict] = []
    for p in sorted(all_programs, key=lambda x: x.get("relevance_score", 0), reverse=True):
        key = f"{p.get('title', '')}|{p.get('organization', '')}".lower()
        if key not in seen_keys:
            seen_keys.add(key)
            unique_programs.append(p)

    # MIN_RELEVANCE_SCORE 미만 필터링
    filtered = [
        p for p in unique_programs
        if p.get("relevance_score", 0) >= MIN_RELEVANCE_SCORE
    ]

    logger.info(
        f"분석 완료: 전체 {len(all_programs)}건 → "
        f"중복 제거 후 {len(unique_programs)}건 → "
        f"점수 필터 후 {len(filtered)}건"
    )

    return filtered, analysis_failed
