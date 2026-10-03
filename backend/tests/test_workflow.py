import unittest
from unittest.mock import patch

from app.agents.nodes import AnalysisOutput, PlanOutput, ReviewOutput
from app.agents.workflow import invoke_workflow
from app.services.llm_service import AgentDecision


class WorkflowTests(unittest.TestCase):
    def _structured_response(self, review_results: list[bool]):
        def generate_structured(system_prompt, user_prompt, response_model):
            del system_prompt, user_prompt
            if response_model is AnalysisOutput:
                return AnalysisOutput(
                    goal="Handle the request",
                    desired_output="A clear recommendation",
                    constraints=["Be practical"],
                )
            if response_model is PlanOutput:
                return PlanOutput(
                    steps=[
                        {
                            "step_number": 1,
                            "action": "Assess the request",
                            "expected_result": "A justified decision",
                        }
                    ]
                )
            if response_model is ReviewOutput:
                passed = review_results.pop(0)
                return ReviewOutput(
                    passed=passed,
                    summary="Ready" if passed else "Needs improvement",
                    issues=[] if passed else ["Add detail"],
                    improvement_instructions=[] if passed else ["Add one example"],
                )
            raise AssertionError(f"Unexpected response model: {response_model}")

        return generate_structured

    def test_workflow_reaches_finalize_when_review_passes(self):
        text_responses = iter(["Final answer"])

        with (
            patch(
                "app.agents.nodes.llm_service.generate_structured",
                side_effect=self._structured_response([True]),
            ),
            patch(
                "app.agents.nodes.llm_service.generate_agent_decision",
                return_value=AgentDecision(content="Initial draft", tool_calls=[]),
            ) as generate_agent_decision,
            patch(
                "app.agents.nodes.llm_service.generate_text",
                side_effect=lambda **kwargs: next(text_responses),
            ) as generate_text,
        ):
            result = invoke_workflow("Test request")

        self.assertEqual(result["final_answer"], "Final answer")
        self.assertTrue(result["review_passed"])
        self.assertEqual(result["revision_count"], 0)
        self.assertEqual(generate_agent_decision.call_count, 1)
        self.assertEqual(generate_text.call_count, 1)

    def test_revision_loop_stops_at_guardrail(self):
        agent_responses = iter(["Initial draft", "Revision one", "Revision two"])

        with (
            patch(
                "app.agents.nodes.llm_service.generate_structured",
                side_effect=self._structured_response([False, False, False]),
            ),
            patch(
                "app.agents.nodes.llm_service.generate_agent_decision",
                side_effect=lambda **kwargs: AgentDecision(
                    content=next(agent_responses),
                    tool_calls=[],
                ),
            ) as generate_agent_decision,
            patch(
                "app.agents.nodes.llm_service.generate_text",
                return_value="Best final answer",
            ) as generate_text,
        ):
            result = invoke_workflow("Test request")

        self.assertEqual(result["final_answer"], "Best final answer")
        self.assertFalse(result["review_passed"])
        self.assertEqual(result["revision_count"], 2)
        self.assertEqual(generate_agent_decision.call_count, 3)
        self.assertEqual(generate_text.call_count, 1)


if __name__ == "__main__":
    unittest.main()
