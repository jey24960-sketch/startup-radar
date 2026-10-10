"""Offline regressions for the bounded comparison's qualification safeguards."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from radar.eligibility import evaluate
from radar.models import Evidence, Program, Requirement, TeamProfile
from tools import evaluate_models as evaluator


@pytest.fixture(scope="module")
def cases():
    rows, _ = evaluator.load_cases(Path(__file__).resolve().parents[1])
    return {row["id"]: row for row in rows}


def program(case, **changes):
    return Program(title="Evaluation", organization="Test source",
                   official_url=case["url"], **changes)


def supported_rule(case, key, operator, value):
    return Requirement(
        key=key, operator=operator, value=value, mandatory=True, certain=True,
        evidence=[Evidence(source_id="official", text=case["text"], method="LLM",
                           confidence=1, verified=True)],
    )


def score(case, result):
    return evaluator.grade(case, result, evaluate, TeamProfile)


def row(grade, status="SUCCESS"):
    return {"status": status, "score": grade, "latency_ms": 0, "metrics": {}}


def passing_summary(cases):
    case = cases["positive-independent-founder-age"]
    result = program(case, evidence_complete=True,
                     requirements=[supported_rule(case, "founder_age", "LTE", 39)])
    grade = score(case, result)
    assert grade["passed"]
    return evaluator.summarize([row(grade)], 1)


def test_all_unknown_cannot_qualify_despite_passing_negative_probes(cases):
    rows = [row(score(case, program(case))) for case in cases.values()]
    summary = evaluator.summarize(rows, len(cases))

    assert summary["successful_extractions"] == len(cases)
    assert summary["critical_failure_count"] == 0
    assert summary["passed_case_runs"] > 0
    assert summary["positive_facts_expected"] > 0
    assert summary["positive_facts_correct"] == 0
    assert summary["missed_positive_facts"] == summary["positive_facts_expected"]
    result = evaluator.decision({"haiku": summary, "sonnet": summary}, complete=True)
    assert result["bounded_candidate"] is None


def test_age_control_catches_hidden_lower_bound(cases):
    case = cases["positive-independent-founder-age"]
    result = program(case, evidence_complete=True,
                     requirements=[supported_rule(case, "founder_age", "RANGE", [20, 39])])

    # This wrong rule passed the previous 20/39/40 probe set.
    for age, expected in [(20, "ELIGIBLE"), (39, "ELIGIBLE"), (40, "INELIGIBLE")]:
        assert evaluate(TeamProfile(founder_age=age), result.requirements, True).status == expected

    grade = score(case, result)
    assert not grade["passed"]
    assert grade["positive_expected"] == 121
    assert grade["positive_correct"] == 101
    assert len(grade["critical_failures"]) == 20
    assert "INCORRECT_CONFIRMED_ELIGIBILITY:19" in grade["critical_failures"]


def test_verbatim_quote_does_not_validate_unlabelled_hard_rule(cases):
    case = cases["product-stage-checkbox-is-not-a-restriction"]
    unsupported = supported_rule(case, "business_status", "EQ", "CORPORATION")
    result = program(case, requirements=[unsupported])

    assert unsupported.key not in case["expect"]["forbidden_hard_keys"]
    assert unsupported.evidence[0].verified
    grade = score(case, result)
    assert not grade["passed"]
    assert grade["critical_failures"] == ["UNREVIEWED_HARD_REQUIREMENT:business_status"]


@pytest.mark.parametrize("defect", ["interrupted", "missing_case", "failed_extraction"])
def test_decision_refuses_incomplete_or_failed_comparison(cases, defect):
    summary = passing_summary(cases)
    complete = defect != "interrupted"
    if defect == "missing_case":
        summary["planned_case_runs"] += 1
    elif defect == "failed_extraction":
        summary["failed_extractions"] = 1
    result = evaluator.decision({"haiku": summary, "sonnet": summary}, complete)
    assert result["bounded_candidate"] is None
    assert result["general_quality_equivalence_claim"] is False
    assert result["automatic_deployment"] is False


def test_bounded_pass_prefers_haiku_without_claiming_general_equivalence(cases):
    summary = passing_summary(cases)
    result = evaluator.decision({"haiku": summary, "sonnet": summary}, complete=True)
    assert result["bounded_candidate"] == "haiku"
    assert result["general_quality_equivalence_claim"] is False
    assert result["automatic_deployment"] is False


@pytest.mark.parametrize("first_request_fails", [False, True])
def test_shared_budget_counts_failed_attempts_and_blocks_extra_calls(first_request_fails):
    calls = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            if first_request_fails and len(calls) == 1:
                raise RuntimeError("Simulated provider failure")
            return "response"

    provider = SimpleNamespace(messages=FakeMessages())
    budget = evaluator.Budget(2)
    haiku = evaluator.BudgetClient(provider, budget)
    sonnet = evaluator.BudgetClient(provider, budget)
    if first_request_fails:
        with pytest.raises(RuntimeError, match="Simulated provider failure"):
            haiku.messages.create(model="haiku")
    else:
        assert haiku.messages.create(model="haiku") == "response"
    assert sonnet.messages.create(model="sonnet") == "response"

    with pytest.raises(evaluator.RequestBudgetExceeded):
        haiku.messages.create(model="haiku", attempt="retry")
    assert budget.used == 2
    assert calls == [{"model": "haiku"}, {"model": "sonnet"}]
