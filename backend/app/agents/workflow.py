from typing import Literal, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.nodes import (
    analyze_node,
    execute_node,
    finalize_node,
    knowledge_retrieval_node,
    plan_node,
    review_node,
)
from app.agents.state import AgentState
from app.core.config import settings
from app.services.llm_service import LLMServiceError
from app.services.knowledge_service import KnowledgeServiceError


class WorkflowExecutionError(Exception):
    pass


def route_after_review(state: AgentState) -> Literal["execute", "finalize"]:
    if state["review_passed"]:
        return "finalize"

    # Guardrail: stop revising after the configured number of retry executions.
    if state["revision_count"] >= settings.max_revision_count:
        return "finalize"

    return "execute"


def build_workflow() -> CompiledStateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("analyze", analyze_node)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("knowledge_retrieval", knowledge_retrieval_node)
    graph.add_node("review", review_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "plan")
    graph.add_edge("plan", "knowledge_retrieval")
    graph.add_edge("knowledge_retrieval", "execute")
    graph.add_edge("execute", "review")
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {
            "execute": "execute",
            "finalize": "finalize",
        },
    )
    graph.add_edge("finalize", END)

    return graph.compile()


workflow = build_workflow()


def invoke_workflow(user_input: str) -> AgentState:
    initial_state: AgentState = {
        "user_input": user_input,
        "revision_count": 0,
    }
    try:
        return cast(AgentState, workflow.invoke(initial_state))
    except LLMServiceError:
        raise
    except KnowledgeServiceError as exc:
        raise WorkflowExecutionError(str(exc)) from exc
    except Exception as exc:
        raise WorkflowExecutionError("The agent workflow failed.") from exc


def run_workflow(user_input: str) -> str:
    result = invoke_workflow(user_input)
    final_answer = result.get("final_answer")
    if not final_answer:
        raise WorkflowExecutionError("The agent workflow returned no final answer.")
    return final_answer
