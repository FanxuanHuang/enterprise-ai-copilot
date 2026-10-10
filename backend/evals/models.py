from typing import Any, Literal

from pydantic import BaseModel, Field


TaskOutcome = Literal[
    "answer_from_retrieval",
    "employee_lookup_success",
    "application_lookup_success",
    "application_created",
    "tool_error",
    "knowledge_insufficient",
]


class EvalExpected(BaseModel):
    needs_retrieval: bool
    expected_sources: list[str] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    required_tools: list[str] | None = None
    allowed_extra_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    tool_order: list[str] | None = None
    expected_tool_arguments: dict[str, dict[str, Any]] = Field(default_factory=dict)
    expected_task_outcome: TaskOutcome
    forbidden_claims: list[str] = Field(default_factory=list)
    expected_result_fields: dict[str, Any] = Field(default_factory=dict)
    expected_error_code: str | None = None


class EvalCase(BaseModel):
    id: str = Field(min_length=1)
    input: str = Field(min_length=1)
    user_id: str = "E1001"
    expected: EvalExpected


class EvalDataset(BaseModel):
    cases: list[EvalCase] = Field(min_length=1)


class EvalTrace(BaseModel):
    needs_retrieval: bool
    retrieval_query: str
    retrieved_chunks: list[dict[str, Any]]
    sources: list[str]
    knowledge_sufficient: bool
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    tool_iteration_count: int
    revision_count: int
    final_answer: str
    latency_seconds: float = Field(ge=0)


class ScoreResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    details: str


class JudgeResult(BaseModel):
    completeness_score: int = Field(ge=0, le=5)
    grounding_score: int = Field(ge=0, le=5)
    hallucination: bool
    contradiction: bool
    reason: str


class CaseEvaluation(BaseModel):
    case_id: str
    trace: EvalTrace
    scores: dict[str, ScoreResult]
    judge: JudgeResult | None = None
    judge_error: str | None = None


class EvaluationSummary(BaseModel):
    total_cases: int
    retrieval_accuracy: float
    tool_selection_accuracy: float
    tool_argument_accuracy: float | None
    task_completion_rate: float
    guardrail_pass_rate: float | None
    hallucination_rate: float | None
    average_judge_completeness: float | None
    average_judge_grounding: float | None
    average_latency_seconds: float
    max_latency_seconds: float
