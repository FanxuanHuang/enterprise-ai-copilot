import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agents.state import AgentState, PlanStep, ReviewResult, TaskAnalysis
from app.core.config import settings
from app.core.observability import log_latency
from app.services.knowledge_service import knowledge_service
from app.services.llm_service import llm_service
from app.tools.registry import tool_registry
from app.tools.schemas import ToolExecutionContext, ToolResult


BASE_SYSTEM_PROMPT = "You are a helpful enterprise AI copilot."
logger = logging.getLogger(__name__)


class AnalysisOutput(BaseModel):
    goal: str = Field(description="The user's real goal")
    desired_output: str = Field(description="The result the user expects")
    constraints: list[str] = Field(
        description="Important explicit or implicit constraints"
    )
    needs_retrieval: bool = Field(
        default=False,
        description=(
            "Whether answering requires company-specific policies, processes, "
            "handbook rules, or internal FAQ facts"
        ),
    )
    retrieval_query: str = Field(
        default="",
        description=(
            "A concise standalone knowledge-base search query; empty when "
            "retrieval is not needed"
        ),
    )


class PlanStepOutput(BaseModel):
    step_number: int
    action: str
    expected_result: str


class PlanOutput(BaseModel):
    steps: list[PlanStepOutput] = Field(min_length=1)


class ReviewOutput(BaseModel):
    passed: bool = Field(
        description="True only when the draft adequately satisfies the request"
    )
    summary: str
    issues: list[str]
    improvement_instructions: list[str]


def analyze_node(state: AgentState) -> dict[str, object]:
    logger.info("request_id=%s stage=analyze", state["request_id"])
    system_prompt = (
        f"{BASE_SYSTEM_PROMPT} Analyze the user's enterprise task. "
        "Identify the real goal, expected deliverable, and key constraints. "
        "Set needs_retrieval=true only when the answer depends on this "
        "company's internal policies, procedures, handbook, or FAQ. For those "
        "requests, produce a concise standalone retrieval_query in the user's "
        "language. Employee records, application records, application status, "
        "and requests to create business applications use enterprise tools, "
        "not document retrieval, so set needs_retrieval=false for those tasks. "
        "For a combined request that explicitly needs both a policy and a "
        "business operation, set needs_retrieval=true so policy context can be "
        "retrieved before the agent calls a tool. General writing, reasoning, "
        "and public-knowledge tasks do not need enterprise retrieval. "
        "Do not solve the task yet. Respond in JSON."
    )
    result = llm_service.generate_structured(
        system_prompt=system_prompt,
        user_prompt=state["user_input"],
        response_model=AnalysisOutput,
    )
    analysis: TaskAnalysis = {
        "goal": result.goal,
        "desired_output": result.desired_output,
        "constraints": result.constraints,
    }
    retrieval_query = (
        result.retrieval_query.strip() or state["user_input"]
        if result.needs_retrieval
        else ""
    )
    return {
        "analysis": analysis,
        "needs_retrieval": result.needs_retrieval,
        "retrieval_query": retrieval_query,
    }


def plan_node(state: AgentState) -> dict[str, list[PlanStep]]:
    logger.info("request_id=%s stage=plan", state["request_id"])
    system_prompt = (
        f"{BASE_SYSTEM_PROMPT} Create a concise, actionable execution plan "
        "from the supplied task analysis. Do not write the final answer. "
        "Respond in JSON."
    )
    result = llm_service.generate_structured(
        system_prompt=system_prompt,
        user_prompt=json.dumps(state["analysis"], ensure_ascii=False),
        response_model=PlanOutput,
    )
    plan: list[PlanStep] = [step.model_dump() for step in result.steps]
    return {"plan": plan}


def knowledge_retrieval_node(state: AgentState) -> dict[str, object]:
    logger.info(
        "request_id=%s stage=knowledge_retrieval",
        state["request_id"],
    )
    if not state.get("needs_retrieval", False):
        logger.info("Knowledge retrieval skipped: not an enterprise knowledge query")
        return {
            "retrieved_chunks": [],
            "knowledge_context": "",
            "knowledge_sufficient": True,
            "sources": [],
        }

    retrieval_query = state.get("retrieval_query") or state["user_input"]
    with log_latency(logger, event="knowledge_retrieval"):
        results = knowledge_service.search(retrieval_query, settings.knowledge_top_k)
    retrieved_chunks = [
        {
            "content": result.content,
            "source": result.source,
            "section": result.section,
            "score": round(result.score, 4),
        }
        for result in results
    ]
    relevant_results = [
        result
        for result in results
        if result.score >= settings.knowledge_min_score
    ]
    knowledge_sufficient = bool(relevant_results)
    knowledge_context = ""
    sources: list[str] = []
    if knowledge_sufficient:
        knowledge_context = "\n\n".join(
            (
                f"[Source: {result.source}; Section: {result.section}; "
                f"Score: {result.score:.4f}]\n{result.content}"
            )
            for result in relevant_results
        )
        sources = list(dict.fromkeys(result.source for result in relevant_results))

    logger.info(
        "request_id=%s retrieval_query=%s",
        state["request_id"],
        retrieval_query,
    )
    logger.info(
        "request_id=%s retrieved_chunks=%d sources=%s sufficient=%s",
        state["request_id"],
        len(results),
        [result.source for result in results],
        knowledge_sufficient,
    )
    return {
        "retrieved_chunks": retrieved_chunks,
        "knowledge_context": knowledge_context,
        "knowledge_sufficient": knowledge_sufficient,
        "sources": sources,
    }


def _initial_agent_messages(state: AgentState) -> list[dict[str, Any]]:
    context = {
        "user_input": state["user_input"],
        "analysis": state["analysis"],
        "plan": state["plan"],
        "enterprise_knowledge": state.get("knowledge_context", ""),
        "knowledge_sufficient": state.get("knowledge_sufficient", True),
        "current_user": state["user_context"],
        "recent_conversation_history": state["conversation_history"],
    }
    return [
        {
            "role": "user",
            "content": json.dumps(context, ensure_ascii=False),
        }
    ]


def agent_decide_node(state: AgentState) -> dict[str, object]:
    logger.info(
        "request_id=%s stage=agent_decide tool_iteration_count=%d "
        "revision_count=%d",
        state["request_id"],
        state["tool_iteration_count"],
        state["revision_count"],
    )
    if state.get("needs_retrieval") and not state.get("knowledge_sufficient", False):
        return {
            "draft": (
                "企业知识库中没有找到足够依据来回答这个内部政策问题。"
                "请联系相应的 HR、财务或内部流程负责人确认。"
            ),
            "current_tool_calls": [],
            "agent_steps": [
                *state.get("agent_steps", []),
                {
                    "step_type": "agent_decision",
                    "summary": "Stopped because enterprise knowledge was insufficient.",
                },
            ],
        }

    messages = list(state.get("agent_messages") or _initial_agent_messages(state))
    allow_tools = state["tool_iteration_count"] < settings.max_tool_iterations
    system_prompt = (
        f"{BASE_SYSTEM_PROMPT} Act as the execution agent. Use enterprise "
        "knowledge only for company policies and documents. Use tools for live "
        "business data and business operations. Never claim that an operation "
        "succeeded unless a successful tool result proves it. Only call a tool "
        "when it is necessary, never invent tool names or arguments, and do not "
        "repeat a successful operation. Prefer one tool call at a time when a "
        "later decision depends on its result. The Python application enforces "
        "permissions and executes all tools. When no more tools are needed, "
        "produce a complete draft without a Sources section. Do not invent "
        "dates, costs, budgets, statuses, identifiers, or other business-record "
        "fields that are absent from successful tool results."
    )
    decision = llm_service.generate_agent_decision(
        system_prompt=system_prompt,
        messages=messages,
        tools=tool_registry.schemas(),
        allow_tools=allow_tools,
    )
    current_tool_calls = [
        {
            "tool_call_id": tool_call.tool_call_id,
            "name": tool_call.name,
            "arguments": tool_call.arguments,
        }
        for tool_call in decision.tool_calls
    ]

    if current_tool_calls and allow_tools:
        messages.append(
            {
                "role": "assistant",
                "content": decision.content or None,
                "tool_calls": [
                    {
                        "id": tool_call["tool_call_id"],
                        "type": "function",
                        "function": {
                            "name": tool_call["name"],
                            "arguments": tool_call["arguments"],
                        },
                    }
                    for tool_call in current_tool_calls
                ],
            }
        )
        return {
            "agent_messages": messages,
            "current_tool_calls": current_tool_calls,
            "tool_calls": [*state.get("tool_calls", []), *current_tool_calls],
            "agent_steps": [
                *state.get("agent_steps", []),
                {
                    "step_type": "agent_decision",
                    "summary": "Requested tools: "
                    + ", ".join(call["name"] for call in current_tool_calls),
                },
            ],
        }

    tool_limit_reached = bool(current_tool_calls and not allow_tools)
    draft = decision.content.strip()
    if not draft:
        draft = (
            "工具执行次数已达到安全上限，无法继续执行新的企业操作。"
            "请缩小请求范围后重试。"
        )
    messages.append({"role": "assistant", "content": draft})
    return {
        "draft": draft,
        "agent_messages": messages,
        "current_tool_calls": [],
        "tool_limit_reached": tool_limit_reached,
        "agent_steps": [
            *state.get("agent_steps", []),
            {
                "step_type": "agent_decision",
                "summary": (
                    "Tool limit reached; produced a safe draft."
                    if tool_limit_reached
                    else "Produced a draft without another tool call."
                ),
            },
        ],
    }


def tool_execution_node(state: AgentState) -> dict[str, object]:
    next_iteration = state["tool_iteration_count"] + 1
    logger.info(
        "request_id=%s stage=tool_execution tool_iteration_count=%d "
        "revision_count=%d",
        state["request_id"],
        next_iteration,
        state["revision_count"],
    )
    context = ToolExecutionContext(
        user_id=state["user_context"]["user_id"],
        request_id=state["request_id"],
    )
    current_tool_calls = state.get("current_tool_calls", [])
    prior_tool_calls = state.get("tool_calls", [])[: -len(current_tool_calls)]
    prior_results = {
        result["tool_call_id"]: result for result in state.get("tool_results", [])
    }

    def signature(tool_call: dict[str, str]) -> tuple[str, str]:
        try:
            normalized_arguments = json.dumps(
                json.loads(tool_call["arguments"]),
                ensure_ascii=False,
                sort_keys=True,
            )
        except json.JSONDecodeError:
            normalized_arguments = tool_call["arguments"]
        return tool_call["name"], normalized_arguments

    successful_results_by_signature = {
        signature(tool_call): prior_results[tool_call["tool_call_id"]]
        for tool_call in prior_tool_calls
        if tool_call["tool_call_id"] in prior_results
        and prior_results[tool_call["tool_call_id"]]["ok"]
    }
    results = []
    for tool_call in current_tool_calls:
        previous_result = successful_results_by_signature.get(signature(tool_call))
        if previous_result is not None:
            logger.info(
                "request_id=%s tool=%s status=reused_successful_result",
                state["request_id"],
                tool_call["name"],
            )
            result = ToolResult(
                tool_call_id=tool_call["tool_call_id"],
                tool_name=tool_call["name"],
                ok=True,
                data=previous_result["data"],
            )
        else:
            result = tool_registry.dispatch(
                tool_call_id=tool_call["tool_call_id"],
                tool_name=tool_call["name"],
                arguments_json=tool_call["arguments"],
                context=context,
            )
        results.append(result)
        if result.ok:
            successful_results_by_signature[signature(tool_call)] = result.model_dump(
                mode="json"
            )
    result_dicts = [result.model_dump(mode="json") for result in results]
    messages = list(state.get("agent_messages", []))
    messages.extend(
        {
            "role": "tool",
            "tool_call_id": result.tool_call_id,
            "content": result.model_dump_json(),
        }
        for result in results
    )
    return {
        "agent_messages": messages,
        "current_tool_calls": [],
        "tool_results": [*state.get("tool_results", []), *result_dicts],
        "tool_iteration_count": next_iteration,
        "agent_steps": [
            *state.get("agent_steps", []),
            *(
                {
                    "step_type": "tool_result",
                    "summary": (
                        f"{result.tool_name}: "
                        f"{'success' if result.ok else result.error.code}"
                    ),
                }
                for result in results
            ),
        ],
    }


def prepare_revision_node(state: AgentState) -> dict[str, object]:
    revision_count = state["revision_count"] + 1
    logger.info(
        "request_id=%s stage=prepare_revision revision_count=%d",
        state["request_id"],
        revision_count,
    )
    messages = list(state.get("agent_messages", []))
    messages.append(
        {
            "role": "user",
            "content": json.dumps(
                {
                    "instruction": "Revise the draft using this review feedback.",
                    "review_feedback": state["review_result"],
                },
                ensure_ascii=False,
            ),
        }
    )
    return {
        "revision_count": revision_count,
        "agent_messages": messages,
        "current_tool_calls": [],
    }


def review_node(state: AgentState) -> dict[str, object]:
    logger.info(
        "request_id=%s stage=review tool_iteration_count=%d revision_count=%d",
        state["request_id"],
        state["tool_iteration_count"],
        state["revision_count"],
    )
    review_context = {
        "user_input": state["user_input"],
        "analysis": state["analysis"],
        "plan": state["plan"],
        "draft": state["draft"],
        "enterprise_knowledge": state.get("knowledge_context", ""),
        "tool_results": state.get("tool_results", []),
    }
    system_prompt = (
        f"{BASE_SYSTEM_PROMPT} Review the draft against the original request. "
        "Check whether it answers the core question, includes key steps, is "
        "logically clear, and has no obvious incomplete content. Be strict but "
        "practical. If enterprise knowledge is present, reject any internal "
        "policy claim that is not supported by that knowledge. Reject claims "
        "that a business operation succeeded unless supported by a successful "
        "tool result. Reject any date, cost, budget, status, identifier, or "
        "other business-record field that is absent from the tool results. "
        "Respond in JSON."
    )
    result = llm_service.generate_structured(
        system_prompt=system_prompt,
        user_prompt=json.dumps(review_context, ensure_ascii=False),
        response_model=ReviewOutput,
    )
    review_result: ReviewResult = {
        "summary": result.summary,
        "issues": result.issues,
        "improvement_instructions": result.improvement_instructions,
    }
    return {
        "review_result": review_result,
        "review_passed": result.passed,
    }


def finalize_node(state: AgentState) -> dict[str, str]:
    logger.info(
        "request_id=%s stage=finalize tool_iteration_count=%d revision_count=%d",
        state["request_id"],
        state["tool_iteration_count"],
        state["revision_count"],
    )
    if state.get("needs_retrieval") and not state.get("knowledge_sufficient", False):
        return {"final_answer": state["draft"]}

    system_prompt = (
        f"{BASE_SYSTEM_PROMPT} Convert the approved or best available draft "
        "into the final user-facing answer. Preserve useful detail, remove "
        "workflow meta-commentary, and return only the final answer. Treat the "
        "supplied enterprise knowledge as the only authority for company policy "
        "and successful tool results as the only authority for business-record "
        "fields and operation outcomes. Remove any unsupported date, cost, "
        "budget, status, identifier, or other record field from the draft. Do "
        "not add or modify source citations."
    )
    final_answer = llm_service.generate_text(
        system_prompt=system_prompt,
        user_prompt=json.dumps(
            {
                "user_input": state["user_input"],
                "draft": state["draft"],
                "enterprise_knowledge": state.get("knowledge_context", ""),
                "tool_results": state.get("tool_results", []),
                "review_result": state.get("review_result"),
                "review_passed": state.get("review_passed", False),
            },
            ensure_ascii=False,
        ),
    )
    sources = state.get("sources", [])
    if sources:
        source_list = "\n".join(f"- {source}" for source in sources)
        final_answer = f"{final_answer.rstrip()}\n\nSources:\n{source_list}"
    return {"final_answer": final_answer}
