import json
from typing import Protocol

from pydantic import BaseModel

from app.services.llm_service import llm_service
from evals.models import EvalCase, EvalTrace, JudgeResult


JUDGE_SYSTEM_PROMPT = """You are an evaluator, not an execution agent.
Evaluate only the quality of the supplied final answer. Do not call tools, execute the
request, or propose new business actions. The supplied RAG evidence and Tool Results
are the only factual authorities for company policy and enterprise records. Do not use
general knowledge to fill missing company facts.

Score only:
1. completeness: whether the answer fully addresses the user's actual request (0-5)
2. grounding: whether material claims are supported by RAG evidence or Tool Results (0-5)
3. hallucination: true if the answer invents any unsupported date, amount, budget,
   status, application_id, employee data, or policy fact
4. contradiction: true if the answer conflicts with RAG evidence or Tool Results

Return a concise reason and only the requested structured JSON."""


class _StructuredLLM(Protocol):
    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel: ...


async def judge_case(
    case: EvalCase,
    trace: EvalTrace,
    *,
    service: _StructuredLLM = llm_service,
) -> JudgeResult:
    payload = {
        "user_request": case.input,
        "rag_evidence": trace.retrieved_chunks,
        "tool_results": trace.tool_results,
        "final_answer": trace.final_answer,
    }
    result = await service.generate_structured(
        system_prompt=JUDGE_SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        response_model=JudgeResult,
    )
    return JudgeResult.model_validate(result)
