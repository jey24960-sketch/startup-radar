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
from core.clock import today as business_today
from core.results import AnalysisResult, Failure

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


def _validate_programs(value):
    if not isinstance(value, list):
        raise ValueError("Expected an array")
    for program in value:
        if not isinstance(program, dict):
            raise ValueError("Program must be an object")
        for key in ("title", "organization", "source", "summary"):
            if not isinstance(program.get(key), str):
                raise ValueError(f"Invalid {key}")
        score = program.get("relevance_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
            raise ValueError("Invalid relevance_score")
        for key in ("amount", "apply_url", "deadline"):
            if program.get(key) is not None and not isinstance(program[key], str):
                raise ValueError(f"Invalid {key}")
        if program.get("deadline"):
            date.fromisoformat(program["deadline"])
    return value


def _call_claude(client, chunk) -> AnalysisResult:
    system = _SYSTEM_PROMPT.format(CLUB_PROFILE=CLUB_PROFILE.strip(), TODAY=business_today().isoformat())
    block = "\n\n---\n\n".join(f"{name}:\n{text}" for name, text in chunk.items())
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": _USER_PROMPT_TEMPLATE.format(sources_block=block)}],
        )
        if getattr(response, "stop_reason", None) == "max_tokens":
            return AnalysisResult(failures=[Failure("TRUNCATED", "Model output exceeded limit", list(chunk))])
        blocks = [part.text for part in response.content if getattr(part, "type", "text") == "text"]
        if not blocks:
            return AnalysisResult(failures=[Failure("EMPTY_RESPONSE", "No text response", list(chunk))])
        raw = "\n".join(blocks).strip()
        if raw.startswith("```") and raw.endswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        programs = _validate_programs(json.loads(raw))
        programs = [p for p in programs if not p.get("deadline") or date.fromisoformat(p["deadline"]) >= business_today()]
        return AnalysisResult(programs=programs, successful_chunks=1)
    except json.JSONDecodeError:
        return AnalysisResult(failures=[Failure("JSON", "Malformed model JSON", list(chunk))])
    except ValueError as error:
        return AnalysisResult(failures=[Failure("SCHEMA", str(error), list(chunk))])
    except anthropic.APIError as error:
        return AnalysisResult(failures=[Failure(type(error).__name__, "AI request failed", list(chunk))])
    except Exception as error:
        return AnalysisResult(failures=[Failure(type(error).__name__, "Unexpected analysis failure", list(chunk))])


def analyze(raw_data: dict[str, str], api_key: str) -> AnalysisResult:
    if not raw_data:
        return AnalysisResult(failures=[Failure("NO_INPUT", "No acquired source text")])
    client = anthropic.Anthropic(api_key=api_key)
    result = AnalysisResult()
    for chunk in _build_chunks(raw_data):
        outcome = _call_claude(client, chunk)
        result.programs.extend(outcome.programs)
        result.failures.extend(outcome.failures)
        result.successful_chunks += outcome.successful_chunks
    unique = {}
    for program in sorted(result.programs, key=lambda p: p["relevance_score"], reverse=True):
        key = (program["title"].casefold(), program["organization"].casefold())
        if program["relevance_score"] >= MIN_RELEVANCE_SCORE:
            unique.setdefault(key, program)
    result.programs = list(unique.values())
    for failure in result.failures:
        logger.error("Analysis failure %s for %s: %s", failure.kind, failure.sources, failure.message)
    return result
