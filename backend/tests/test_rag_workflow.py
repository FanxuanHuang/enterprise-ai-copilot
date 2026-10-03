import unittest
from unittest.mock import patch

from app.agents.nodes import AnalysisOutput, PlanOutput, ReviewOutput
from app.agents.workflow import invoke_workflow
from app.services.knowledge_service import SearchResult
from app.services.llm_service import AgentDecision


class RagWorkflowTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    async def _structured_response(system_prompt, user_prompt, response_model):
        del system_prompt, user_prompt
        if response_model is AnalysisOutput:
            return AnalysisOutput(
                goal="Answer the remote-work policy question",
                desired_output="A grounded answer",
                constraints=["Use enterprise knowledge"],
                needs_retrieval=True,
                retrieval_query="新员工 远程办公 申请资格 入职时间",
            )
        if response_model is PlanOutput:
            return PlanOutput(
                steps=[
                    {
                        "step_number": 1,
                        "action": "Use the retrieved policy",
                        "expected_result": "A grounded policy answer",
                    }
                ]
            )
        if response_model is ReviewOutput:
            return ReviewOutput(
                passed=True,
                summary="Grounded",
                issues=[],
                improvement_instructions=[],
            )
        raise AssertionError(f"Unexpected response model: {response_model}")

    async def test_workflow_passes_retrieved_context_to_execute(self):
        text_prompts: list[str] = []

        async def generate_agent_decision(
            system_prompt,
            messages,
            tools,
            allow_tools,
        ):
            del system_prompt, tools, allow_tools
            text_prompts.append(messages[0]["content"])
            return AgentDecision(
                content="新员工入职满 90 个自然日后可以申请。",
                tool_calls=[],
            )

        result = SearchResult(
            content="新员工完成入职满 90 个自然日后，才可以申请常规远程办公。",
            source="remote_work_policy.md",
            section="申请资格",
            score=0.91,
        )
        with (
            patch(
                "app.agents.nodes.llm_service.generate_structured",
                side_effect=self._structured_response,
            ),
            patch(
                "app.agents.nodes.llm_service.generate_agent_decision",
                side_effect=generate_agent_decision,
            ),
            patch(
                "app.agents.nodes.llm_service.generate_text",
                return_value="新员工入职满 90 个自然日后可以申请。",
            ),
            patch(
                "app.agents.nodes.knowledge_service.search",
                return_value=[result],
            ) as search,
        ):
            state = await invoke_workflow("新员工多久可以申请远程办公？")

        search.assert_called_once_with("新员工 远程办公 申请资格 入职时间", 3)
        self.assertIn("满 90 个自然日", text_prompts[0])
        self.assertEqual(state["sources"], ["remote_work_policy.md"])
        self.assertIn("Sources:\n- remote_work_policy.md", state["final_answer"])

    async def test_insufficient_knowledge_returns_guarded_answer_without_generation(self):
        weak_result = SearchResult(
            content="无关内容",
            source="travel_policy.md",
            section="交通标准",
            score=0.1,
        )
        with (
            patch(
                "app.agents.nodes.llm_service.generate_structured",
                side_effect=self._structured_response,
            ),
            patch(
                "app.agents.nodes.llm_service.generate_agent_decision"
            ) as generate_agent_decision,
            patch("app.agents.nodes.llm_service.generate_text") as generate_text,
            patch(
                "app.agents.nodes.knowledge_service.search",
                return_value=[weak_result],
            ),
        ):
            state = await invoke_workflow("公司的宠物保险政策是什么？")

        generate_text.assert_not_called()
        generate_agent_decision.assert_not_called()
        self.assertFalse(state["knowledge_sufficient"])
        self.assertEqual(state["sources"], [])
        self.assertIn("没有找到足够依据", state["final_answer"])


if __name__ == "__main__":
    unittest.main()
