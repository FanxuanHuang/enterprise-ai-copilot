from typing import Any, NotRequired, TypedDict


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
    chunk_index: int


class UserContext(TypedDict):
    user_id: str


class AgentToolCall(TypedDict):
    tool_call_id: str
    name: str
    arguments: str


class AgentToolResult(TypedDict):
    tool_call_id: str
    tool_name: str
    ok: bool
    data: dict[str, Any] | None
    error: dict[str, str] | None


class AgentStep(TypedDict):
    step_type: str
    summary: str


class AgentState(TypedDict):
    user_input: str
    revision_count: int
    tool_iteration_count: int
    request_id: str
    session_id: str
    user_context: UserContext
    conversation_history: list[dict[str, str]]
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
    agent_messages: NotRequired[list[dict[str, Any]]]
    current_tool_calls: NotRequired[list[AgentToolCall]]
    tool_calls: NotRequired[list[AgentToolCall]]
    tool_results: NotRequired[list[AgentToolResult]]
    agent_steps: NotRequired[list[AgentStep]]
    tool_limit_reached: NotRequired[bool]
