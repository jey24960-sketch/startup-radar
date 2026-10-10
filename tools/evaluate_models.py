"""Bounded paired extraction check; no database, recrawl, publication or delivery.

Run with the startup-radar Python environment and --repo PATH. The 10 existing
official excerpts are semantic safety probes, not complete notice ground truth.
Five explicitly synthetic positive controls prevent a vacuous all-unknown pass.
No provider call is made by --list-cases. Live calls require ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time


VERSION = "bounded-extraction-pair-1"
MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"}
LIMITATIONS = [
    "This checks the deployed extractor plus its guards, not unguarded model accuracy.",
    "Ten short official excerpts and five synthetic controls do not represent full notices.",
    "No scanned document, long attachment, live source coverage or production traffic is evaluated.",
    "Assertions are bounded semantic checks, not exhaustive correctness labels.",
    "A bounded candidate is not a claim of general quality equivalence or a deployment approval.",
    "Token and latency measurements are recorded; prices and monetary cost are not assumed.",
]


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def expectation(**updates):
    result = {
        "must_not_certify": True,
        "forbidden_hard_keys": [],
        "allowed_hard_keys": [],
        "allowed_start": None,
        "allowed_end": None,
        "deadline_type": "UNKNOWN",
        "required_facts": [],
        "eligibility_probes": [],
    }
    result.update(updates)
    return result


def load_cases(repo):
    path = repo / "tests" / "fixtures" / "extraction_golden.json"
    corpus = json.loads(path.read_text(encoding="utf-8"))
    rules = {
        "founder-age-is-tiebreaker": expectation(forbidden_hard_keys=["founder_age"]),
        "student-status-has-graduate-alternatives": expectation(forbidden_hard_keys=["student_status"]),
        "compound-business-age-branch": expectation(forbidden_hard_keys=["business_age_months"]),
        "facility-region-is-not-team-region": expectation(forbidden_hard_keys=["region"]),
        "product-stage-checkbox-is-not-a-restriction": expectation(forbidden_hard_keys=["product_stage"]),
        "future-registration-is-not-current-status": expectation(forbidden_hard_keys=["business_status", "region"]),
        "prior-support-needs-controlled-response": expectation(forbidden_hard_keys=["prior_support_restrictions"]),
        "precise-application-cutoff": expectation(
            allowed_start={"at": "2026-09-09T00:00:00+09:00", "precision": "DATE"},
            allowed_end={"at": "2026-09-30T18:00:00+09:00", "precision": "DATETIME"},
            deadline_type="FIXED_DATE", required_facts=["end", "deadline_type"]),
        "event-time-is-not-deadline": expectation(),
        "rolling-source-phrase": expectation(deadline_type="ROLLING", required_facts=["deadline_type"]),
    }
    official = {row["id"]: row for row in corpus["cases"]}
    if set(official) != set(rules):
        raise ValueError("CORPUS_IDS_CHANGED")
    cases = []
    for case_id, expected in rules.items():
        source = official[case_id]
        cases.append({"id": case_id, "kind": "official_excerpt", "url": source["url"],
                      "text": source["text"], "tags": source.get("tags", []), "expect": expected})
    controls = [
        ("positive-independent-founder-age",
         "신청자격(전체): 대표자 나이가 만 39세 이하인 사람만 신청 가능. 추가 자격 제한 없음.",
         expectation(must_not_certify=False, allowed_hard_keys=["founder_age"], eligibility_probes=[
             {"profile": {"founder_age": age}, "status": "ELIGIBLE" if age <= 39 else "INELIGIBLE"}
             for age in range(121)])),
        ("positive-explicit-resident-region",
         "신청자격(전체): 서울 거주자만 신청 가능. 추가 자격 제한 없음.",
         expectation(must_not_certify=False, allowed_hard_keys=["region"], eligibility_probes=[
             {"profile": {"region": "서울"}, "status": "ELIGIBLE"},
             {"profile": {"region": "부산"}, "status": "INELIGIBLE"}])),
        ("positive-registered-business-alternatives",
         "신청자격(전체): 신청일 현재 사업자등록을 완료한 개인사업자 또는 법인만 지원 가능. 추가 자격 제한 없음.",
         expectation(must_not_certify=False, allowed_hard_keys=["business_status"], eligibility_probes=[
             {"profile": {"business_status": "SOLE_PROPRIETOR"}, "status": "ELIGIBLE"},
             {"profile": {"business_status": "CORPORATION"}, "status": "ELIGIBLE"},
             {"profile": {"business_status": "PRE_BUSINESS"}, "status": "INELIGIBLE"}])),
        ("positive-explicit-cutoff-time",
         "신청자격(전체): 누구나 신청 가능합니다. 추가 자격 제한 없음.\n접수 마감: 2026. 9. 30.(수) 오전 11시까지.",
         expectation(must_not_certify=False,
                     allowed_end={"at": "2026-09-30T11:00:00+09:00", "precision": "DATETIME"},
                     deadline_type="FIXED_DATE", required_facts=["end", "deadline_type"],
                     eligibility_probes=[{"profile": {}, "status": "ELIGIBLE"}])),
        ("positive-date-only-and-free-education",
         "신청자격(전체): 누구나 신청 가능합니다. 추가 자격 제한 없음.\n접수 마감: 2026년 9월 30일까지.\n지원내용: 무료 창업 교육.",
         expectation(must_not_certify=False,
                     allowed_end={"at": "2026-09-30T23:59:59.999999+09:00", "precision": "DATE"},
                     deadline_type="FIXED_DATE", required_facts=["end", "deadline_type", "benefit"],
                     benefit_terms=["무료", "교육"],
                     eligibility_probes=[{"profile": {}, "status": "ELIGIBLE"}])),
    ]
    for case_id, text, expected in controls:
        cases.append({"id": case_id, "kind": "synthetic_positive_control",
                      "url": "https://example.invalid/model-eval/" + case_id,
                      "text": text, "tags": ["synthetic", "positive_control"], "expect": expected})
    return cases, {"version": corpus.get("version"), "reviewed_at": corpus.get("reviewed_at"),
                   "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def grade(case, program, evaluate, TeamProfile):
    expected = case["expect"]
    critical, checks = [], []
    if expected["must_not_certify"] and program.evidence_complete:
        critical.append("INCOMPLETE_EXCERPT_CERTIFIED")
    for rule in program.requirements:
        if not (rule.mandatory and rule.certain):
            continue
        if rule.key in expected["forbidden_hard_keys"]:
            critical.append("UNSUPPORTED_HARD_REQUIREMENT:" + rule.key)
        elif rule.key not in expected["allowed_hard_keys"]:
            critical.append("UNREVIEWED_HARD_REQUIREMENT:" + rule.key)
        if not any(item.verified for item in rule.evidence):
            critical.append("UNGROUNDED_HARD_REQUIREMENT:" + rule.key)
    for which in ("start", "end"):
        actual = getattr(program, "application_" + which + "_at")
        precision = getattr(program, "application_" + which + "_precision")
        allowed = expected["allowed_" + which]
        correct = bool(actual and allowed and actual == datetime.fromisoformat(allowed["at"])
                       and precision == allowed["precision"])
        if actual is not None and not correct:
            critical.append("INCORRECT_APPLICATION_" + which.upper())
        if which in expected["required_facts"]:
            checks.append({"fact": which, "passed": correct})
    if program.deadline_type not in (expected["deadline_type"], "UNKNOWN"):
        critical.append("INCORRECT_DEADLINE_TYPE")
    if "deadline_type" in expected["required_facts"]:
        checks.append({"fact": "deadline_type", "passed": program.deadline_type == expected["deadline_type"]})
    if "benefit" in expected["required_facts"]:
        summary = program.benefit_summary or ""
        checks.append({"fact": "benefit", "passed": all(term in summary for term in expected["benefit_terms"])})
    for index, probe in enumerate(expected["eligibility_probes"]):
        actual = str(evaluate(TeamProfile.model_validate(probe["profile"]), program.requirements,
                              program.evidence_complete, as_of=date(2026, 9, 14)).status)
        wanted = probe["status"]
        checks.append({"fact": "eligibility_probe_" + str(index), "passed": actual == wanted,
                       "expected": wanted, "actual": actual})
        if actual != wanted and actual in ("ELIGIBLE", "INELIGIBLE"):
            critical.append("INCORRECT_CONFIRMED_ELIGIBILITY:" + str(index))
    missed = [check["fact"] for check in checks if not check["passed"]]
    return {"critical_failures": sorted(set(critical)), "positive_checks": checks,
            "positive_expected": len(checks), "positive_correct": len(checks) - len(missed),
            "missed_positive_facts": missed, "passed": not critical and not missed}


def expected_count(case):
    return len(case["expect"]["required_facts"]) + len(case["expect"]["eligibility_probes"])


def safe_kind(error):
    kind = getattr(error, "kind", "")
    return kind if isinstance(kind, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", kind) else "LOCAL_EXTRACTION_ERROR"


class RequestBudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, limit):
        self.limit, self.used = limit, 0


class BudgetMessages:
    def __init__(self, messages, budget):
        self.messages, self.budget = messages, budget

    def create(self, **kwargs):
        if self.budget.used >= self.budget.limit:
            raise RequestBudgetExceeded()
        self.budget.used += 1
        return self.messages.create(**kwargs)


class BudgetClient:
    def __init__(self, client, budget):
        self.messages = BudgetMessages(client.messages, budget)


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize(rows, total):
    success = [row for row in rows if row["status"] == "SUCCESS"]
    correct = sum(row["score"]["positive_correct"] for row in rows)
    expected = sum(row["score"]["positive_expected"] for row in rows)
    return {
        "planned_case_runs": total, "completed_case_runs": len(rows), "successful_extractions": len(success),
        "failed_extractions": len(rows) - len(success),
        "passed_case_runs": sum(row["score"]["passed"] for row in rows),
        "critical_failure_count": sum(len(row["score"]["critical_failures"]) for row in rows),
        "positive_facts_expected": expected, "positive_facts_correct": correct,
        "missed_positive_facts": expected - correct,
        "positive_recall": correct / expected if expected else None,
        "median_latency_ms": statistics.median(row["latency_ms"] for row in rows) if rows else None,
        "usage": {field: sum(row.get("metrics", {}).get(field, 0) for row in rows)
                  for field in ("request_count", "successful_calls", "failed_calls", "retry_calls", "input_tokens",
                                "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "usage_unknown_calls")},
        "returned_models": sorted({request["model"] for row in rows
                                   for request in row.get("metrics", {}).get("requests", []) if request.get("model")}),
    }


def decision(summaries, complete):
    def qualified(summary):
        return (complete and summary["completed_case_runs"] == summary["planned_case_runs"]
                and summary["failed_extractions"] == 0 and summary["critical_failure_count"] == 0
                and summary["missed_positive_facts"] == 0)
    haiku, sonnet = summaries["haiku"], summaries["sonnet"]
    haiku_not_worse = (haiku["passed_case_runs"] >= sonnet["passed_case_runs"]
                       and haiku["positive_facts_correct"] >= sonnet["positive_facts_correct"]
                       and haiku["failed_extractions"] <= sonnet["failed_extractions"]
                       and haiku["critical_failure_count"] <= sonnet["critical_failure_count"])
    if qualified(haiku) and haiku_not_worse:
        candidate, reason = "haiku", "HAIKU_PASSES_ALL_BOUNDED_ASSERTIONS_AND_IS_NOT_WORSE_ON_THIS_SET"
    elif qualified(sonnet):
        candidate, reason = "sonnet", "ONLY_SONNET_PASSES_ALL_BOUNDED_ASSERTIONS"
    else:
        candidate, reason = None, "NO_CANDIDATE_PASSES_ALL_BOUNDED_ASSERTIONS_OR_RUN_INCOMPLETE"
    return {"bounded_candidate": candidate, "reason_code": reason,
            "general_quality_equivalence_claim": False, "automatic_deployment": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="StartupRadar checkout to import and inspect")
    parser.add_argument("--output", type=Path, help="JSON report destination; required for live evaluation")
    parser.add_argument("--list-cases", action="store_true", help="Print frozen evidence and expectations; no API calls")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-api-requests", type=int, default=60, help="Hard shared provider-request cap, including retries (maximum 120)")
    parser.add_argument("--haiku-model", default=MODELS["haiku"])
    parser.add_argument("--sonnet-model", default=MODELS["sonnet"])
    args = parser.parse_args(argv)
    if not 1 <= args.repeats <= 4 or not 1 <= args.max_api_requests <= 120:
        parser.error("repeats must be 1..4 and max-api-requests must be 1..120")
    if args.haiku_model == args.sonnet_model:
        parser.error("The paired model IDs must differ")
    repo = args.repo.resolve()
    try:
        cases, corpus = load_cases(repo)
    except Exception:
        print(json.dumps({"status": "FAILED", "reason_code": "CORPUS_UNAVAILABLE_OR_CHANGED"}))
        return 2
    manifest = {"evaluator_version": VERSION, "corpus": corpus, "cases": cases}
    corpus_hash = digest(manifest)
    if args.list_cases:
        print(json.dumps({**manifest, "manifest_sha256": corpus_hash, "model_calls": 0}, indent=2))
        return 0
    if args.output is None:
        parser.error("--output is required for live evaluation")
    output = args.output.resolve()
    models = {"haiku": args.haiku_model, "sonnet": args.sonnet_model}
    report = {"evaluator_version": VERSION, "status": "PRECHECK", "started_at": stamp(),
              "models": models, "repo": str(repo), "manifest": manifest, "manifest_sha256": corpus_hash,
              "repeats": args.repeats, "max_api_requests": args.max_api_requests,
              "limitations": LIMITATIONS, "runs": [], "general_quality_equivalence_claim": False}
    def fail(code):
        report.update(status="FAILED", reason_code=code, finished_at=stamp())
        save(output, report)
        print(json.dumps({"status": "FAILED", "reason_code": code, "output": str(output)}))
        return 2
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return fail("ANTHROPIC_API_KEY_MISSING")
    sys.path.insert(0, str(repo))
    try:
        import anthropic
        from radar.adapters.base import AcquiredDetail
        from radar.ai_requests import MAX_REQUESTS, REQUEST_TIMEOUT
        from radar.eligibility import evaluate
        from radar.extraction import RequirementExtractor
        from radar.models import Program, TeamProfile
    except Exception:
        return fail("REPOSITORY_RUNTIME_IMPORT_FAILED")
    worst_case = len(cases) * len(models) * args.repeats * MAX_REQUESTS
    report["planned_extractions"] = len(cases) * len(models) * args.repeats
    report["worst_case_api_requests"] = worst_case
    if worst_case > args.max_api_requests:
        return fail("PLANNED_REQUESTS_EXCEED_CAP")
    report["extractor_contract_version"] = RequirementExtractor.version
    try:
        provider = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=0, timeout=REQUEST_TIMEOUT)
    except Exception:
        return fail("PROVIDER_CLIENT_INITIALIZATION_FAILED")
    budget = Budget(args.max_api_requests)
    client = BudgetClient(provider, budget)
    report["status"] = "RUNNING"
    save(output, report)
    stopped = None
    try:
        for repetition in range(1, args.repeats + 1):
            for case_index, case in enumerate(cases):
                # Alternate order to reduce order-dependent latency/provider effects.
                order = list(models) if (case_index + repetition) % 2 else list(reversed(models))
                for label in order:
                    extractor = RequirementExtractor(client=client, model=models[label])
                    program = Program(title="Extraction evaluation notice", organization="Evaluation source", official_url=case["url"])
                    detail = AcquiredDetail(case["url"], case["text"], program.title)
                    started = time.monotonic()
                    row = {"model_label": label, "requested_model": models[label], "case_id": case["id"],
                           "case_kind": case["kind"], "repetition": repetition}
                    try:
                        normalized = extractor.extract(program, detail, [], "official")
                        row.update(status="SUCCESS", normalized=normalized.model_dump(mode="json"),
                                   score=grade(case, normalized, evaluate, TeamProfile))
                    except Exception as error:
                        reason = "REQUEST_BUDGET_EXHAUSTED" if isinstance(error, RequestBudgetExceeded) else safe_kind(error)
                        row.update(status="FAILED", reason_code=reason, normalized=None,
                                   score={"critical_failures": [], "positive_checks": [],
                                          "positive_expected": expected_count(case), "positive_correct": 0,
                                          "missed_positive_facts": ["EXTRACTION_FAILED"] if expected_count(case) else [],
                                          "passed": False})
                        if reason in ("AI_CREDENTIALS", "AI_REQUEST", "AI_TIMEOUT", "AI_CONNECTION",
                                      "AI_RATE_LIMIT", "AI_SERVER", "REQUEST_BUDGET_EXHAUSTED", "LOCAL_EXTRACTION_ERROR"):
                            stopped = reason
                    row.update(latency_ms=round((time.monotonic() - started) * 1000),
                               metrics=getattr(extractor, "metrics", {}),
                               review_flags=getattr(extractor, "review_flags", []))
                    report["runs"].append(row)
                    report["actual_api_requests"] = budget.used
                    save(output, report)
                    print(json.dumps({key: row[key] for key in ("model_label", "case_id", "repetition", "status")}), flush=True)
                    if stopped:
                        break
                if stopped:
                    break
            if stopped:
                break
    except KeyboardInterrupt:
        stopped = "INTERRUPTED"
    finally:
        provider.close()
    total = len(cases) * args.repeats
    summaries = {label: summarize([row for row in report["runs"] if row["model_label"] == label], total) for label in models}
    complete = len(report["runs"]) == report["planned_extractions"] and stopped is None
    report.update(status="COMPLETED" if complete else "INCOMPLETE", reason_code=stopped,
                  finished_at=stamp(), actual_api_requests=budget.used, summaries=summaries,
                  comparison=decision(summaries, complete))
    save(output, report)
    print(json.dumps({"status": report["status"], "output": str(output), "actual_api_requests": budget.used,
                      "comparison": report["comparison"]}, ensure_ascii=False))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
