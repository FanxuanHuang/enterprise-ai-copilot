import asyncio
from typing import Literal, cast
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.nodes import (
    agent_decide_node,
    analyze_node,
    finalize_node,
    knowledge_retrieval_node,
    plan_node,
    prepare_revision_node,
    review_node,
    tool_execution_node,
)
from app.agents.state import AgentState
from app.core.config import settings
from app.core.observability import reset_request_id, set_request_id
from app.db.database import database
from app.services.llm_service import LLMServiceError
from app.services.knowledge_service import KnowledgeServiceError


class WorkflowExecutionError(Exception):
    pass


def route_after_agent(state: AgentState) -> Literal["tool_execution", "review"]:
    if state.get("current_tool_calls"):
        return "tool_execution"
    return "review"


def route_after_review(
    state: AgentState,
) -> Literal["prepare_revision", "finalize"]:
    if state["review_passed"]:
        return "finalize"

    # Guardrail: stop revising after the configured number of retry executions.
    if state["revision_count"] >= settings.max_revision_count:
        return "finalize"

    return "prepare_revision"


def build_workflow() -> CompiledStateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("analyze", analyze_node)
    graph.add_node("plan", plan_node)
    graph.add_node("knowledge_retrieval", knowledge_retrieval_node)
    graph.add_node("agent_decide", agent_decide_node)
    graph.add_node("tool_execution", tool_execution_node)
    graph.add_node("review", review_node)
    graph.add_node("prepare_revision", prepare_revision_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "plan")
    graph.add_edge("plan", "knowledge_retrieval")
    graph.add_edge("knowledge_retrieval", "agent_decide")
    graph.add_conditional_edges(
        "agent_decide",
        route_after_agent,
        {
            "tool_execution": "tool_execution",
            "review": "review",
        },
    )
    graph.add_edge("tool_execution", "agent_decide")
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {
            "prepare_revision": "prepare_revision",
            "finalize": "finalize",
        },
    )
    graph.add_edge("prepare_revision", "agent_decide")
    graph.add_edge("finalize", END)

    return graph.compile()


workflow = build_workflow()


async def invoke_workflow(
    user_input: str,
    *,
    session_id: str | None = None,
    user_id: str = "E1001",
    request_id: str | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> AgentState:
    resolved_request_id = request_id or str(uuid4())
    initial_state: AgentState = {
        "user_input": user_input,
        "revision_count": 0,
        "tool_iteration_count": 0,
        "request_id": resolved_request_id,
        "session_id": session_id or str(uuid4()),
        "user_context": {"user_id": user_id},
        "conversation_history": conversation_history or [],
    }
    token = set_request_id(resolved_request_id)
    try:
        await asyncio.to_thread(database.initialize)
        return cast(AgentState, await workflow.ainvoke(initial_state))
    except LLMServiceError:
        raise
    except KnowledgeServiceError as exc:
        raise WorkflowExecutionError(str(exc)) from exc
    except Exception as exc:
        raise WorkflowExecutionError("The agent workflow failed.") from exc
    finally:
        reset_request_id(token)


async def run_workflow(
    user_input: str,
    *,
    session_id: str | None = None,
    user_id: str = "E1001",
    request_id: str | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> str:
    result = await invoke_workflow(
        user_input,
        session_id=session_id,
        user_id=user_id,
        request_id=request_id,
        conversation_history=conversation_history,
    )
    final_answer = result.get("final_answer")
    if not final_answer:
        raise WorkflowExecutionError("The agent workflow returned no final answer.")
    return final_answer
