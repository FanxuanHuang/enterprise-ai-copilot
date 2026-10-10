from dataclasses import dataclass

from app.core.config import settings
from app.services.knowledge_service import SearchResult, knowledge_service
from evals.run_evals import load_dataset


THRESHOLDS = (0.50, 0.55, 0.60, 0.65)


@dataclass(frozen=True)
class ThresholdMetrics:
    source_recall: float
    insufficient_rejection: float
    task_completion: float
    guardrail_pass_rate: float


def _relevant_sources(
    results: list[SearchResult],
    threshold: float,
) -> set[str]:
    return {result.source for result in results if result.score >= threshold}


def scan_thresholds() -> dict[float, ThresholdMetrics]:
    cases = [case for case in load_dataset().cases if case.expected.needs_retrieval]
    results_by_case = {
        case.id: knowledge_service.search(case.input, settings.knowledge_top_k)
        for case in cases
    }

    print("Retrieval diagnostics (dataset input used as deterministic query)")
    print("---------------------------------------------------------------")
    print(f"configured threshold={settings.knowledge_min_score:.2f}")
    for case in cases:
        print(f"{case.id}: query={case.input}")
        for result in results_by_case[case.id]:
            summary = " ".join(result.content.split())[:120]
            print(
                f"  score={result.score:.4f} source={result.source} "
                f"section={result.section} chunk_index={result.chunk_index} "
                f"summary={summary}"
            )

    normal_cases = [
        case
        for case in cases
        if case.expected.expected_task_outcome != "knowledge_insufficient"
    ]
    insufficient_cases = [
        case
        for case in cases
        if case.expected.expected_task_outcome == "knowledge_insufficient"
    ]
    metrics: dict[float, ThresholdMetrics] = {}
    print("\nThreshold comparison")
    print("--------------------")
    for threshold in THRESHOLDS:
        recalled_sources = 0
        expected_sources = 0
        completed = 0
        for case in normal_cases:
            actual = _relevant_sources(results_by_case[case.id], threshold)
            expected = set(case.expected.expected_sources)
            recalled_sources += len(actual & expected)
            expected_sources += len(expected)
            completed += int(bool(actual) and expected.issubset(actual))

        rejected = sum(
            not _relevant_sources(results_by_case[case.id], threshold)
            for case in insufficient_cases
        )
        total_cases = len(normal_cases) + len(insufficient_cases)
        metrics[threshold] = ThresholdMetrics(
            source_recall=(
                recalled_sources / expected_sources if expected_sources else 1.0
            ),
            insufficient_rejection=(
                rejected / len(insufficient_cases) if insufficient_cases else 1.0
            ),
            task_completion=(completed + rejected) / total_cases,
            guardrail_pass_rate=(
                rejected / len(insufficient_cases) if insufficient_cases else 1.0
            ),
        )
        result = metrics[threshold]
        print(
            f"{threshold:.2f}: source_recall={result.source_recall:.1%} "
            f"insufficient_rejection={result.insufficient_rejection:.1%} "
            f"task_completion={result.task_completion:.1%} "
            f"guardrail={result.guardrail_pass_rate:.1%}"
        )
    return metrics


if __name__ == "__main__":
    scan_thresholds()
