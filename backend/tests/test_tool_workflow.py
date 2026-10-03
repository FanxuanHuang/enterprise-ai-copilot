import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.agents.nodes import AnalysisOutput, PlanOutput, ReviewOutput
from app.agents.workflow import invoke_workflow
from app.db.database import Database
from app.repositories.application_repository import ApplicationRepository
from app.services.knowledge_service import SearchResult
from app.services.llm_service import AgentDecision, LLMToolCall
from app.tools.registry import build_tool_registry
from app.tools.schemas import ToolResult


class ToolWorkflowTests(unittest.TestCase):
    @staticmethod
    def structured_response(needs_retrieval=False):
        def generate_structured(system_prompt, user_prompt, response_model):
            del system_prompt, user_prompt
            if response_model is AnalysisOutput:
                return AnalysisOutput(
                    goal="Complete the enterprise task",
                    desired_output="A verified result",
                    constraints=["Use tools for business data"],
                    needs_retrieval=needs_retrieval,
                    retrieval_query="公司 差旅政策 出差申请" if needs_retrieval else "",
                )
            if response_model is PlanOutput:
                return PlanOutput(
                    steps=[
                        {
                            "step_number": 1,
                            "action": "Retrieve facts and execute the task",
                            "expected_result": "A grounded result",
                        }
                    ]
                )
            if response_model is ReviewOutput:
                return ReviewOutput(
                    passed=True,
                    summary="Verified",
                    issues=[],
                    improvement_instructions=[],
                )
            raise AssertionError(f"Unexpected model: {response_model}")

        return generate_structured

    def test_tool_result_is_returned_to_agent_for_next_decision(self):
        decisions = []

        def decide(**kwargs):
            decisions.append(kwargs)
            if len(decisions) == 1:
                return AgentDecision(
                    content="",
                    tool_calls=[
                        LLMToolCall(
                            tool_call_id="call-employee",
                            name="get_employee_info",
                            arguments='{"employee_id":"E1001"}',
                        )
                    ],
                )
            self.assertEqual(kwargs["messages"][-1]["role"], "tool")
            self.assertIn("研发", kwargs["messages"][-1]["content"])
            return AgentDecision(
                content="员工 E1001 属于研发部门，职级为 P6。",
                tool_calls=[],
            )

        tool_result = ToolResult(
            tool_call_id="call-employee",
            tool_name="get_employee_info",
            ok=True,
            data={"employee_id": "E1001", "department": "研发", "level": "P6"},
        )
        with (
            patch(
                "app.agents.nodes.llm_service.generate_structured",
                side_effect=self.structured_response(),
            ),
            patch(
                "app.agents.nodes.llm_service.generate_agent_decision",
                side_effect=decide,
            ),
            patch(
                "app.agents.nodes.tool_registry.dispatch",
                return_value=tool_result,
            ) as dispatch,
            patch(
                "app.agents.nodes.llm_service.generate_text",
                return_value="员工 E1001 属于研发部门，职级为 P6。",
            ) as generate_text,
        ):
            state = invoke_workflow("查询员工 E1001 的部门和职级")

        dispatch.assert_called_once()
        self.assertEqual(state["tool_iteration_count"], 1)
        self.assertEqual(state["tool_results"][0]["data"]["department"], "研发")
        self.assertEqual(len(decisions), 2)
        self.assertIn("tool_results", generate_text.call_args.kwargs["user_prompt"])
        self.assertIn("研发", generate_text.call_args.kwargs["user_prompt"])

    def test_tool_loop_stops_at_configured_maximum(self):
        call_number = 0

        def decide(**kwargs):
            nonlocal call_number
            call_number += 1
            return AgentDecision(
                content="",
                tool_calls=[
                    LLMToolCall(
                        tool_call_id=f"call-{call_number}",
                        name="get_employee_info",
                        arguments=f'{{"employee_id":"E{call_number:04d}"}}',
                    )
                ],
            )

        with (
            patch(
                "app.agents.nodes.llm_service.generate_structured",
                side_effect=self.structured_response(),
            ),
            patch(
                "app.agents.nodes.llm_service.generate_agent_decision",
                side_effect=decide,
            ),
            patch(
                "app.agents.nodes.tool_registry.dispatch",
                side_effect=lambda **kwargs: ToolResult(
                    tool_call_id=kwargs["tool_call_id"],
                    tool_name=kwargs["tool_name"],
                    ok=True,
                    data={"employee_id": "E1001"},
                ),
            ) as dispatch,
            patch("app.agents.nodes.settings.max_tool_iterations", 2),
            patch(
                "app.agents.nodes.llm_service.generate_text",
                return_value="已达到工具执行安全上限。",
            ),
        ):
            state = invoke_workflow("不断查询")

        self.assertEqual(dispatch.call_count, 2)
        self.assertEqual(state["tool_iteration_count"], 2)
        self.assertTrue(state["tool_limit_reached"])
        self.assertIn("安全上限", state["draft"])

    def test_repeated_successful_tool_call_reuses_result(self):
        call_number = 0

        def decide(**kwargs):
            nonlocal call_number
            call_number += 1
            if call_number <= 2:
                return AgentDecision(
                    content="",
                    tool_calls=[
                        LLMToolCall(
                            tool_call_id=f"duplicate-{call_number}",
                            name="create_business_trip_application",
                            arguments=(
                                '{"employee_id":"E1001","destination":"上海",'
                                '"days":3,"reason":"客户会议"}'
                            ),
                        )
                    ],
                )
            return AgentDecision(content="申请已创建。", tool_calls=[])

        with (
            patch(
                "app.agents.nodes.llm_service.generate_structured",
                side_effect=self.structured_response(),
            ),
            patch(
                "app.agents.nodes.llm_service.generate_agent_decision",
                side_effect=decide,
            ),
            patch(
                "app.agents.nodes.tool_registry.dispatch",
                return_value=ToolResult(
                    tool_call_id="duplicate-1",
                    tool_name="create_business_trip_application",
                    ok=True,
                    data={"application_id": "TRIP-2026-002", "status": "审批中"},
                ),
            ) as dispatch,
            patch(
                "app.agents.nodes.llm_service.generate_text",
                return_value="申请已创建。",
            ),
        ):
            state = invoke_workflow("创建上海 3 天出差申请")

        dispatch.assert_called_once()
        self.assertEqual(state["tool_iteration_count"], 2)
        self.assertEqual(len(state["tool_results"]), 2)
        self.assertEqual(
            state["tool_results"][1]["data"]["application_id"],
            "TRIP-2026-002",
        )

    def test_rag_context_and_tool_execution_work_together(self):
        prompts = []

        def decide(**kwargs):
            prompts.append(kwargs["messages"])
            if len(prompts) == 1:
                self.assertIn("至少在出发前 3 个工作日", kwargs["messages"][0]["content"])
                return AgentDecision(
                    content="",
                    tool_calls=[
                        LLMToolCall(
                            tool_call_id="call-create",
                            name="create_business_trip_application",
                            arguments=(
                                '{"employee_id":"E1001","destination":"上海",'
                                '"days":3,"reason":"业务出差"}'
                            ),
                        )
                    ],
                )
            return AgentDecision(
                content="申请已创建，编号 TRIP-2026-002，并请遵守提前申请政策。",
                tool_calls=[],
            )

        search_result = SearchResult(
            content="员工应至少在出发前 3 个工作日通过内部 OA 提交出差申请。",
            source="travel_policy.md",
            section="出差申请与审批",
            score=0.92,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_database = Database(Path(temporary_directory) / "rag-tool.db")
            registry = build_tool_registry(test_database)
            with (
                patch(
                    "app.agents.nodes.llm_service.generate_structured",
                    side_effect=self.structured_response(needs_retrieval=True),
                ),
                patch(
                    "app.agents.nodes.knowledge_service.search",
                    return_value=[search_result],
                ),
                patch(
                    "app.agents.nodes.llm_service.generate_agent_decision",
                    side_effect=decide,
                ),
                patch("app.agents.nodes.tool_registry", registry),
                patch(
                    "app.agents.nodes.llm_service.generate_text",
                    return_value=(
                        "申请已创建，编号 TRIP-2026-002。\n\n"
                        "Sources:\n- travel_policy.md"
                    ),
                ),
            ):
                state = invoke_workflow(
                    "根据差旅政策，为 E1001 创建上海 3 天出差申请"
                )

            created = ApplicationRepository(test_database).get_by_id("TRIP-2026-002")
            self.assertIsNotNone(created)
            self.assertEqual(created.destination, "上海")

        self.assertEqual(state["sources"], ["travel_policy.md"])
        self.assertEqual(state["tool_results"][0]["data"]["status"], "审批中")
        self.assertEqual(state["tool_iteration_count"], 1)


if __name__ == "__main__":
    unittest.main()
