import tempfile
import unittest
from pathlib import Path

from app.db.database import Database
from evals.judge import JUDGE_SYSTEM_PROMPT, judge_case
from evals.models import (
    CaseEvaluation,
    EvalCase,
    EvalTrace,
    JudgeResult,
)
from evals.run_evals import load_dataset, select_cases
from evals.scorers import score_case, score_tool_selection, summarize


def make_case() -> EvalCase:
    return EvalCase.model_validate(
        {
            "id": "tool_case",
            "input": "查询 E1001",
            "expected": {
                "needs_retrieval": False,
                "expected_sources": [],
                "expected_tools": ["get_employee_info"],
                "expected_tool_arguments": {
                    "get_employee_info": {"employee_id": "E1001"}
                },
                "expected_task_outcome": "employee_lookup_success",
                "expected_result_fields": {
                    "employee_id": "E1001",
                    "department": "研发",
                },
                "forbidden_claims": ["财务"],
            },
        }
    )


def make_trace() -> EvalTrace:
    return EvalTrace(
        needs_retrieval=False,
        retrieval_query="",
        retrieved_chunks=[],
        sources=[],
        knowledge_sufficient=True,
        tool_calls=[
            {
                "tool_call_id": "call-1",
                "name": "get_employee_info",
                "arguments": '{"employee_id":"E1001"}',
            }
        ],
        tool_results=[
            {
                "tool_call_id": "call-1",
                "tool_name": "get_employee_info",
                "ok": True,
                "data": {"employee_id": "E1001", "department": "研发"},
                "error": None,
            }
        ],
        tool_iteration_count=1,
        revision_count=0,
        final_answer="E1001 属于研发部门。",
        latency_seconds=1.5,
    )


class EvaluationHarnessTests(unittest.IsolatedAsyncioTestCase):
    def test_dataset_schema_loads_and_case_selection_works(self):
        dataset = load_dataset()
        self.assertGreaterEqual(len(dataset.cases), 10)
        ids = {case.id for case in dataset.cases}
        self.assertEqual(len(ids), len(dataset.cases))
        selected = select_cases(
            dataset,
            case_id="rag_tool_create_trip",
            limit=None,
        )
        self.assertEqual([case.id for case in selected], ["rag_tool_create_trip"])
        self.assertEqual(
            selected[0].expected.required_tools,
            ["create_business_trip_application"],
        )
        self.assertEqual(
            selected[0].expected.allowed_extra_tools,
            ["get_employee_info"],
        )

    def test_tool_selection_allows_declared_read_only_extra(self):
        case_data = make_case().model_dump()
        case_data["expected"].update(
            {
                "required_tools": ["create_business_trip_application"],
                "allowed_extra_tools": ["get_employee_info"],
                "forbidden_tools": ["get_application_status"],
            }
        )
        case = EvalCase.model_validate(case_data)
        trace = make_trace()
        trace.tool_calls.append(
            {
                "tool_call_id": "call-2",
                "name": "create_business_trip_application",
                "arguments": '{"employee_id":"E1001","destination":"上海","days":3}',
            }
        )

        score = score_tool_selection(case, trace)

        self.assertTrue(score.passed)
        self.assertIn("allowed extras used=['get_employee_info']", score.details)

    def test_tool_selection_rejects_forbidden_and_wrong_order(self):
        case_data = make_case().model_dump()
        case_data["expected"].update(
            {
                "required_tools": ["get_employee_info"],
                "allowed_extra_tools": ["get_application_status"],
                "forbidden_tools": ["create_business_trip_application"],
                "tool_order": ["get_application_status", "get_employee_info"],
            }
        )
        case = EvalCase.model_validate(case_data)
        trace = make_trace()
        trace.tool_calls.append(
            {
                "tool_call_id": "call-2",
                "name": "create_business_trip_application",
                "arguments": "{}",
            }
        )

        score = score_tool_selection(case, trace)

        self.assertFalse(score.passed)
        self.assertIn("forbidden used=['create_business_trip_application']", score.details)
        self.assertIn("order matched=False", score.details)

    def test_deterministic_scorers_validate_tool_and_result_fields(self):
        case = make_case()
        trace = make_trace()
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Database(Path(temporary_directory) / "eval.db")
            database.initialize()
            scores = score_case(case, trace, database)

        self.assertTrue(scores["retrieval"].passed)
        self.assertTrue(scores["tool_selection"].passed)
        self.assertTrue(scores["tool_arguments"].passed)
        self.assertTrue(scores["task_completion"].passed)
        self.assertTrue(scores["guardrail"].passed)

    async def test_judge_uses_structured_output_with_required_evidence(self):
        class FakeService:
            def __init__(self):
                self.call = None

            async def generate_structured(self, **kwargs):
                self.call = kwargs
                return JudgeResult(
                    completeness_score=5,
                    grounding_score=5,
                    hallucination=False,
                    contradiction=False,
                    reason="All claims match the tool result.",
                )

        service = FakeService()
        result = await judge_case(make_case(), make_trace(), service=service)

        self.assertEqual(result.completeness_score, 5)
        self.assertIs(service.call["response_model"], JudgeResult)
        self.assertIn("only factual authorities", JUDGE_SYSTEM_PROMPT)
        self.assertIn("tool_results", service.call["user_prompt"])
        self.assertIn("final_answer", service.call["user_prompt"])

    def test_summary_metrics_are_calculated_separately(self):
        case = make_case()
        trace = make_trace()
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Database(Path(temporary_directory) / "eval.db")
            database.initialize()
            scores = score_case(case, trace, database)
        evaluation = CaseEvaluation(
            case_id=case.id,
            trace=trace,
            scores=scores,
            judge=JudgeResult(
                completeness_score=4,
                grounding_score=5,
                hallucination=False,
                contradiction=False,
                reason="Grounded.",
            ),
        )

        summary = summarize([case], [evaluation])

        self.assertEqual(summary.total_cases, 1)
        self.assertEqual(summary.tool_argument_accuracy, 1.0)
        self.assertEqual(summary.average_judge_completeness, 4.0)
        self.assertEqual(summary.average_judge_grounding, 5.0)
        self.assertEqual(summary.average_latency_seconds, 1.5)
        self.assertEqual(summary.max_latency_seconds, 1.5)


if __name__ == "__main__":
    unittest.main()
