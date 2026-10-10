import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path

from app.agents.state import AgentState
from app.agents.workflow import invoke_workflow
from app.core.config import settings
from app.db.database import Database
from evals.judge import judge_case
from evals.models import (
    CaseEvaluation,
    EvalCase,
    EvalDataset,
    EvaluationSummary,
    EvalTrace,
    ScoreResult,
)
from evals.scorers import score_case, summarize


DATASET_PATH = Path(__file__).with_name("dataset.json")


def load_dataset(path: Path = DATASET_PATH) -> EvalDataset:
    return EvalDataset.model_validate_json(path.read_text(encoding="utf-8"))


def build_trace(state: AgentState, latency_seconds: float) -> EvalTrace:
    return EvalTrace(
        needs_retrieval=state.get("needs_retrieval", False),
        retrieval_query=state.get("retrieval_query", ""),
        retrieved_chunks=list(state.get("retrieved_chunks", [])),
        sources=list(state.get("sources", [])),
        knowledge_sufficient=state.get("knowledge_sufficient", True),
        tool_calls=list(state.get("tool_calls", [])),
        tool_results=list(state.get("tool_results", [])),
        tool_iteration_count=state.get("tool_iteration_count", 0),
        revision_count=state.get("revision_count", 0),
        final_answer=state.get("final_answer", ""),
        latency_seconds=latency_seconds,
    )


def _failed_evaluation(
    case: EvalCase,
    latency_seconds: float,
    error: Exception,
) -> CaseEvaluation:
    trace = EvalTrace(
        needs_retrieval=False,
        retrieval_query="",
        retrieved_chunks=[],
        sources=[],
        knowledge_sufficient=False,
        tool_calls=[],
        tool_results=[],
        tool_iteration_count=0,
        revision_count=0,
        final_answer="",
        latency_seconds=latency_seconds,
    )
    failure = ScoreResult(
        score=0.0,
        passed=False,
        details=f"workflow error: {type(error).__name__}: {error}",
    )
    return CaseEvaluation(
        case_id=case.id,
        trace=trace,
        scores={
            "retrieval": failure,
            "tool_selection": failure,
            "tool_arguments": failure,
            "task_completion": failure,
            "guardrail": failure,
        },
    )


async def evaluate_case(case: EvalCase, *, use_judge: bool) -> CaseEvaluation:
    with tempfile.TemporaryDirectory(prefix=f"agent-eval-{case.id}-") as temp_dir:
        database = Database(Path(temp_dir) / "eval.db")
        started = time.perf_counter()
        try:
            state = await invoke_workflow(
                case.input,
                user_id=case.user_id,
                request_id=f"eval-{case.id}",
                session_id=f"eval-{case.id}",
                target_database=database,
            )
        except Exception as exc:
            return _failed_evaluation(
                case,
                time.perf_counter() - started,
                exc,
            )

        trace = build_trace(state, time.perf_counter() - started)
        scores = score_case(case, trace, database)
        judge = None
        judge_error = None
        if use_judge:
            try:
                judge = await judge_case(case, trace)
            except Exception as exc:
                judge_error = f"{type(exc).__name__}: {exc}"
        return CaseEvaluation(
            case_id=case.id,
            trace=trace,
            scores=scores,
            judge=judge,
            judge_error=judge_error,
        )


def select_cases(
    dataset: EvalDataset,
    *,
    case_id: str | None,
    limit: int | None,
) -> list[EvalCase]:
    cases = dataset.cases
    if case_id:
        cases = [case for case in cases if case.id == case_id]
        if not cases:
            available = ", ".join(case.id for case in dataset.cases)
            raise ValueError(f"Unknown case {case_id!r}. Available: {available}")
    if limit is not None:
        cases = cases[:limit]
    return cases


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def print_case_result(result: CaseEvaluation) -> None:
    score_text = ", ".join(
        f"{name}={score.score:.2f}" for name, score in result.scores.items()
    )
    judge_text = ""
    if result.judge:
        judge_text = (
            f", judge={result.judge.completeness_score}/"
            f"{result.judge.grounding_score}, "
            f"hallucination={result.judge.hallucination}, "
            f"contradiction={result.judge.contradiction}"
        )
    print(
        f"[{result.case_id}] {score_text}{judge_text}, "
        f"latency={result.trace.latency_seconds:.2f}s"
    )
    if result.trace.needs_retrieval:
        chunks = [
            (
                f"{chunk.get('source')}#{chunk.get('chunk_index', '?')}"
                f"/{chunk.get('section')}({chunk.get('score')})"
            )
            for chunk in result.trace.retrieved_chunks
        ]
        print(
            f"  retrieval: query={result.trace.retrieval_query!r}; "
            f"threshold={settings.knowledge_min_score}; chunks={chunks}"
        )
    for name, score in result.scores.items():
        if not score.passed:
            print(f"  {name}: {score.details}")
    if result.judge_error:
        print(f"  judge error: {result.judge_error}")


def print_summary(summary: EvaluationSummary) -> None:
    hallucination = (
        _percent(summary.hallucination_rate)
        if summary.hallucination_rate is not None
        else "N/A (--no-judge)"
    )
    completeness = (
        f"{summary.average_judge_completeness:.2f}/5"
        if summary.average_judge_completeness is not None
        else "N/A (--no-judge)"
    )
    grounding = (
        f"{summary.average_judge_grounding:.2f}/5"
        if summary.average_judge_grounding is not None
        else "N/A (--no-judge)"
    )
    print("\nEvaluation Summary")
    print("------------------")
    print(f"Cases: {summary.total_cases}")
    print(f"Retrieval Accuracy: {_percent(summary.retrieval_accuracy)}")
    print(f"Tool Selection: {_percent(summary.tool_selection_accuracy)}")
    tool_arguments = (
        _percent(summary.tool_argument_accuracy)
        if summary.tool_argument_accuracy is not None
        else "N/A (no tool cases)"
    )
    guardrails = (
        _percent(summary.guardrail_pass_rate)
        if summary.guardrail_pass_rate is not None
        else "N/A (no guardrail cases)"
    )
    print(f"Tool Argument Accuracy: {tool_arguments}")
    print(f"Task Completion: {_percent(summary.task_completion_rate)}")
    print(f"Guardrail Pass Rate: {guardrails}")
    print(f"Hallucination Rate: {hallucination}")
    print(f"Avg Completeness: {completeness}")
    print(f"Avg Grounding: {grounding}")
    print(f"Avg Latency: {summary.average_latency_seconds:.2f}s")
    print(f"Max Latency: {summary.max_latency_seconds:.2f}s")


async def run(args: argparse.Namespace) -> EvaluationSummary:
    dataset = load_dataset()
    cases = select_cases(dataset, case_id=args.case, limit=args.limit)
    evaluations = []
    for case in cases:
        result = await evaluate_case(case, use_judge=not args.no_judge)
        evaluations.append(result)
        print_case_result(result)
    summary = summarize(cases, evaluations)
    print_summary(summary)
    return summary


def parse_args() -> argparse.Namespace:
    def positive_int(value: str) -> int:
        parsed = int(value)
        if parsed < 1:
            raise argparse.ArgumentTypeError("must be at least 1")
        return parsed

    parser = argparse.ArgumentParser(
        description="Run the Enterprise AI Copilot agent evaluation dataset."
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip the additional DeepSeek LLM-as-a-Judge call.",
    )
    parser.add_argument("--case", help="Run one case by exact case id.")
    parser.add_argument("--limit", type=positive_int)
    return parser.parse_args()


def main() -> None:
    try:
        asyncio.run(run(parse_args()))
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
