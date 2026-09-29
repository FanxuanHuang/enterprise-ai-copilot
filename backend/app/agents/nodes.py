import json
import logging

from pydantic import BaseModel, Field

from app.agents.state import AgentState, PlanStep, ReviewResult, TaskAnalysis
from app.core.config import settings
from app.services.knowledge_service import knowledge_service
from app.services.llm_service import llm_service


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
    logger.info("Workflow stage: analyze")
    system_prompt = (
        f"{BASE_SYSTEM_PROMPT} Analyze the user's enterprise task. "
        "Identify the real goal, expected deliverable, and key constraints. "
        "Set needs_retrieval=true only when the answer depends on this "
        "company's internal policies, procedures, handbook, or FAQ. For those "
        "requests, produce a concise standalone retrieval_query in the user's "
        "language. General writing, reasoning, and public-knowledge tasks do "
        "not need enterprise retrieval. "
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
    logger.info("Workflow stage: plan")
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
    logger.info("Workflow stage: knowledge_retrieval")
    if not state.get("needs_retrieval", False):
        logger.info("Knowledge retrieval skipped: not an enterprise knowledge query")
        return {
            "retrieved_chunks": [],
            "knowledge_context": "",
            "knowledge_sufficient": True,
            "sources": [],
        }

    retrieval_query = state.get("retrieval_query") or state["user_input"]
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

    logger.info("Retrieval query: %s", retrieval_query)
    logger.info(
        "Retrieved chunks: count=%d sources=%s sufficient=%s",
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


def execute_node(state: AgentState) -> dict[str, object]:
    logger.info("Workflow stage: execute")
    review_result = state.get("review_result")
    is_revision = review_result is not None and not state.get("review_passed", False)
    revision_count = state["revision_count"] + 1 if is_revision else 0

    if state.get("needs_retrieval") and not state.get("knowledge_sufficient", False):
        return {
            "draft": (
                "企业知识库中没有找到足够依据来回答这个内部政策问题。"
                "请联系相应的 HR、财务或内部流程负责人确认。"
            ),
            "revision_count": revision_count,
        }

    context = {
        "user_input": state["user_input"],
        "analysis": state["analysis"],
        "plan": state["plan"],
        "previous_draft": state.get("draft") if is_revision else None,
        "review_feedback": review_result if is_revision else None,
        "enterprise_knowledge": state.get("knowledge_context", ""),
    }
    system_prompt = (
        f"{BASE_SYSTEM_PROMPT} Produce a complete draft for the user. "
        "Follow the analysis and plan. If review feedback is present, revise "
        "the previous draft to address every issue. When enterprise knowledge "
        "is provided, treat it as the only authoritative source for internal "
        "company facts and policies. Never invent, infer, or supplement company "
        "policy from general knowledge. If the supplied knowledge does not "
        "support a requested policy claim, explicitly say the knowledge base "
        "does not provide enough information. Return only the draft and do not "
        "add a Sources section."
    )
    draft = llm_service.generate_text(
        system_prompt=system_prompt,
        user_prompt=json.dumps(context, ensure_ascii=False),
    )
    return {"draft": draft, "revision_count": revision_count}


def review_node(state: AgentState) -> dict[str, object]:
    logger.info("Workflow stage: review")
    review_context = {
        "user_input": state["user_input"],
        "analysis": state["analysis"],
        "plan": state["plan"],
        "draft": state["draft"],
        "enterprise_knowledge": state.get("knowledge_context", ""),
    }
    system_prompt = (
        f"{BASE_SYSTEM_PROMPT} Review the draft against the original request. "
        "Check whether it answers the core question, includes key steps, is "
        "logically clear, and has no obvious incomplete content. Be strict but "
        "practical. If enterprise knowledge is present, reject any internal "
        "policy claim that is not supported by that knowledge. Respond in JSON."
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
    logger.info("Workflow stage: finalize")
    if state.get("needs_retrieval") and not state.get("knowledge_sufficient", False):
        return {"final_answer": state["draft"]}

    system_prompt = (
        f"{BASE_SYSTEM_PROMPT} Convert the approved or best available draft "
        "into the final user-facing answer. Preserve useful detail, remove "
        "workflow meta-commentary, and return only the final answer. Do not add "
        "or modify source citations."
    )
    final_answer = llm_service.generate_text(
        system_prompt=system_prompt,
        user_prompt=state["draft"],
    )
    sources = state.get("sources", [])
    if sources:
        source_list = "\n".join(f"- {source}" for source in sources)
        final_answer = f"{final_answer.rstrip()}\n\nSources:\n{source_list}"
    return {"final_answer": final_answer}
