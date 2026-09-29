from typing import NotRequired, TypedDict


class TaskAnalysis(TypedDict):
    goal: str
    desired_output: str
    constraints: list[str]


class PlanStep(TypedDict):
    step_number: int
    action: str
    expected_result: str


class ReviewResult(TypedDict):
    summary: str
    issues: list[str]
    improvement_instructions: list[str]


class RetrievedChunk(TypedDict):
    content: str
    source: str
    section: str
    score: float


class AgentState(TypedDict):
    user_input: str
    revision_count: int
    needs_retrieval: NotRequired[bool]
    retrieval_query: NotRequired[str]
    analysis: NotRequired[TaskAnalysis]
    plan: NotRequired[list[PlanStep]]
    draft: NotRequired[str]
    review_result: NotRequired[ReviewResult]
    review_passed: NotRequired[bool]
    final_answer: NotRequired[str]
    retrieved_chunks: NotRequired[list[RetrievedChunk]]
    knowledge_context: NotRequired[str]
    knowledge_sufficient: NotRequired[bool]
    sources: NotRequired[list[str]]
