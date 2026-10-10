import json
from statistics import mean
from typing import Any, Iterable

from app.db.database import Database
from app.repositories.application_repository import ApplicationRepository
from evals.models import (
    CaseEvaluation,
    EvalCase,
    EvaluationSummary,
    EvalTrace,
    ScoreResult,
)


def _result(score: float, details: str) -> ScoreResult:
    return ScoreResult(score=score, passed=score == 1.0, details=details)


def score_retrieval(case: EvalCase, trace: EvalTrace) -> ScoreResult:
    expected = case.expected
    trigger_matches = trace.needs_retrieval == expected.needs_retrieval
    if not expected.needs_retrieval:
        return _result(
            float(trigger_matches),
            f"expected trigger=False, actual={trace.needs_retrieval}",
        )

    expected_sources = set(expected.expected_sources)
    actual_sources = set(trace.sources) | {
        str(chunk.get("source", "")) for chunk in trace.retrieved_chunks
    }
    chunk_details = [
        (
            f"{chunk.get('source')}#{chunk.get('chunk_index', '?')}"
            f"/{chunk.get('section')}({chunk.get('score')})"
        )
        for chunk in trace.retrieved_chunks
    ]
    if not expected_sources:
        source_recall = 1.0
    else:
        source_recall = len(expected_sources & actual_sources) / len(expected_sources)
    score = (float(trigger_matches) + source_recall) / 2
    return _result(
        score,
        "trigger match="
        f"{trigger_matches}; source recall={source_recall:.2f}; "
        f"actual sources={sorted(actual_sources)}; chunks={chunk_details}",
    )


def score_tool_selection(case: EvalCase, trace: EvalTrace) -> ScoreResult:
    actual = [str(call.get("name", "")) for call in trace.tool_calls]
    expected = case.expected
    if expected.required_tools is None:
        # Backward compatibility: the old field keeps its original strict behavior.
        matches = actual == expected.expected_tools
        return _result(
            float(matches),
            f"legacy expected tools={expected.expected_tools}; actual={actual}",
        )

    required = expected.required_tools
    allowed_extras = expected.allowed_extra_tools
    forbidden = expected.forbidden_tools
    order = expected.tool_order

    missing = [tool for tool in required if tool not in actual]
    allowed_hits = [tool for tool in actual if tool in allowed_extras]
    forbidden_hits = [tool for tool in actual if tool in forbidden]
    declared = set(required) | set(allowed_extras) | set(forbidden)
    unexpected = [tool for tool in actual if tool not in declared]
    unexpected.extend(
        f"{tool} (duplicate)"
        for tool in sorted(set(actual))
        if tool not in allowed_extras and actual.count(tool) > required.count(tool)
    )

    order_matches = True
    if order is not None:
        cursor = 0
        for tool in actual:
            if cursor < len(order) and tool == order[cursor]:
                cursor += 1
        order_matches = cursor == len(order)

    matches = not missing and not forbidden_hits and not unexpected and order_matches
    return _result(
        float(matches),
        f"required={required}; missing={missing}; allowed extras used={allowed_hits}; "
        f"forbidden used={forbidden_hits}; unexpected={unexpected}; "
        f"order={order}; order matched={order_matches}; actual={actual}",
    )


def score_tool_arguments(case: EvalCase, trace: EvalTrace) -> ScoreResult:
    expected_by_tool = case.expected.expected_tool_arguments
    if not expected_by_tool:
        return _result(
            float(not trace.tool_calls),
            "no tool arguments expected"
            if not trace.tool_calls
            else "unexpected tool calls supplied arguments",
        )

    actual_by_tool: dict[str, list[dict[str, Any]]] = {}
    invalid_tools: list[str] = []
    for call in trace.tool_calls:
        name = str(call.get("name", ""))
        try:
            arguments = json.loads(str(call.get("arguments", "{}")))
        except (json.JSONDecodeError, TypeError):
            invalid_tools.append(name)
            continue
        if isinstance(arguments, dict):
            actual_by_tool.setdefault(name, []).append(arguments)
        else:
            invalid_tools.append(name)

    field_checks: list[bool] = []
    details: list[str] = []
    for tool_name, expected_arguments in expected_by_tool.items():
        candidates = actual_by_tool.get(tool_name, [])
        actual = candidates[0] if candidates else {}
        for key, expected_value in expected_arguments.items():
            matched = actual.get(key) == expected_value
            field_checks.append(matched)
            details.append(
                f"{tool_name}.{key}: expected={expected_value!r}, "
                f"actual={actual.get(key)!r}"
            )

    score = sum(field_checks) / len(field_checks) if field_checks else 1.0
    if invalid_tools:
        details.append(f"invalid JSON arguments for={invalid_tools}")
        score = 0.0
    return _result(score, "; ".join(details))


def _successful_data(trace: EvalTrace, tool_name: str) -> dict[str, Any] | None:
    for result in trace.tool_results:
        if result.get("tool_name") == tool_name and result.get("ok"):
            data = result.get("data")
            if isinstance(data, dict):
                return data
    return None


def _fields_match(data: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(data.get(key) == value for key, value in expected.items())


def score_task_completion(
    case: EvalCase,
    trace: EvalTrace,
    database: Database,
) -> ScoreResult:
    expected = case.expected
    outcome = expected.expected_task_outcome
    fields = expected.expected_result_fields

    if outcome == "answer_from_retrieval":
        passed = (
            trace.needs_retrieval
            and trace.knowledge_sufficient
            and bool(trace.final_answer.strip())
            and set(expected.expected_sources).issubset(trace.sources)
        )
        return _result(float(passed), "grounded retrieval answer completed")

    if outcome == "knowledge_insufficient":
        passed = (
            trace.needs_retrieval
            and not trace.knowledge_sufficient
            and bool(trace.final_answer.strip())
        )
        return _result(float(passed), "workflow stopped on insufficient knowledge")

    if outcome == "tool_error":
        actual_codes = [
            result.get("error", {}).get("code")
            for result in trace.tool_results
            if isinstance(result.get("error"), dict)
        ]
        passed = expected.expected_error_code in actual_codes
        return _result(
            float(passed),
            f"expected error={expected.expected_error_code}; actual={actual_codes}",
        )

    tool_name = {
        "employee_lookup_success": "get_employee_info",
        "application_lookup_success": "get_application_status",
        "application_created": "create_business_trip_application",
    }[outcome]
    data = _successful_data(trace, tool_name)
    if data is None or not _fields_match(data, fields):
        return _result(0.0, f"successful {tool_name} result did not match {fields}")

    if outcome != "application_created":
        return _result(1.0, f"verified successful {tool_name} result fields")

    application_id = data.get("application_id")
    application = (
        ApplicationRepository(database).get_by_id(str(application_id))
        if application_id
        else None
    )
    persisted = application is not None and _fields_match(
        {
            "employee_id": application.employee_id,
            "destination": application.destination,
            "days": application.days,
            "status": application.status,
        },
        fields,
    )
    return _result(
        float(persisted),
        f"created application persisted in isolated DB: {application_id}",
    )


def score_guardrail(case: EvalCase, trace: EvalTrace) -> ScoreResult:
    answer_lower = trace.final_answer.casefold()
    forbidden_hits = [
        claim
        for claim in case.expected.forbidden_claims
        if claim.casefold() in answer_lower
    ]
    checks = [not forbidden_hits]
    details = [f"forbidden claim hits={forbidden_hits}"]

    if case.expected.expected_error_code:
        error_codes = [
            result.get("error", {}).get("code")
            for result in trace.tool_results
            if isinstance(result.get("error"), dict)
        ]
        checks.append(case.expected.expected_error_code in error_codes)
        details.append(f"tool error codes={error_codes}")

    if case.expected.expected_task_outcome == "knowledge_insufficient":
        checks.append(not trace.knowledge_sufficient)
        details.append(f"knowledge_sufficient={trace.knowledge_sufficient}")

    passed = all(checks)
    return _result(float(passed), "; ".join(details))


def score_case(
    case: EvalCase,
    trace: EvalTrace,
    database: Database,
) -> dict[str, ScoreResult]:
    return {
        "retrieval": score_retrieval(case, trace),
        "tool_selection": score_tool_selection(case, trace),
        "tool_arguments": score_tool_arguments(case, trace),
        "task_completion": score_task_completion(case, trace, database),
        "guardrail": score_guardrail(case, trace),
    }


def _average(values: Iterable[float]) -> float:
    materialized = list(values)
    return mean(materialized) if materialized else 0.0


def summarize(
    cases: list[EvalCase],
    evaluations: list[CaseEvaluation],
) -> EvaluationSummary:
    by_id = {case.id: case for case in cases}
    tool_evaluations = [
        result
        for result in evaluations
        if (
            by_id[result.case_id].expected.required_tools
            if by_id[result.case_id].expected.required_tools is not None
            else by_id[result.case_id].expected.expected_tools
        )
    ]
    guardrail_evaluations = [
        result
        for result in evaluations
        if by_id[result.case_id].expected.expected_error_code
        or by_id[result.case_id].expected.expected_task_outcome
        == "knowledge_insufficient"
        or by_id[result.case_id].expected.forbidden_claims
    ]
    judged = [result.judge for result in evaluations if result.judge is not None]
    return EvaluationSummary(
        total_cases=len(evaluations),
        retrieval_accuracy=_average(
            result.scores["retrieval"].score for result in evaluations
        ),
        tool_selection_accuracy=_average(
            result.scores["tool_selection"].score for result in evaluations
        ),
        tool_argument_accuracy=(
            _average(
                result.scores["tool_arguments"].score
                for result in tool_evaluations
            )
            if tool_evaluations
            else None
        ),
        task_completion_rate=_average(
            result.scores["task_completion"].score for result in evaluations
        ),
        guardrail_pass_rate=(
            _average(
                result.scores["guardrail"].score
                for result in guardrail_evaluations
            )
            if guardrail_evaluations
            else None
        ),
        hallucination_rate=(
            _average(float(result.hallucination) for result in judged)
            if judged
            else None
        ),
        average_judge_completeness=(
            _average(result.completeness_score for result in judged)
            if judged
            else None
        ),
        average_judge_grounding=(
            _average(result.grounding_score for result in judged)
            if judged
            else None
        ),
        average_latency_seconds=_average(
            result.trace.latency_seconds for result in evaluations
        ),
        max_latency_seconds=max(
            (result.trace.latency_seconds for result in evaluations),
            default=0.0,
        ),
    )
