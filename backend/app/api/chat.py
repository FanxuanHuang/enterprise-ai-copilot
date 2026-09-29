from fastapi import APIRouter, HTTPException, status

from app.agents.workflow import WorkflowExecutionError, run_workflow
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.llm_service import LLMServiceError

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        answer = run_workflow(request.message)
    except (LLMServiceError, WorkflowExecutionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return ChatResponse(answer=answer)
