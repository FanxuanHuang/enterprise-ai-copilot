import asyncio
import sqlite3
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status

from app.agents.workflow import WorkflowExecutionError, run_workflow
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.llm_service import LLMServiceError
from app.services.conversation_service import (
    ConversationAccessError,
    conversation_service,
)

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    session_id = payload.session_id or str(uuid4())
    request_id = getattr(request.state, "request_id", str(uuid4()))
    try:
        history = await asyncio.to_thread(
            conversation_service.get_history,
            session_id,
            user_id=payload.user_id,
        )
        await asyncio.to_thread(
            conversation_service.add_message,
            session_id=session_id,
            user_id=payload.user_id,
            role="user",
            content=payload.message,
        )
        answer = await run_workflow(
            payload.message,
            session_id=session_id,
            user_id=payload.user_id,
            request_id=request_id,
            conversation_history=history,
        )
        await asyncio.to_thread(
            conversation_service.add_message,
            session_id=session_id,
            user_id=payload.user_id,
            role="assistant",
            content=answer,
        )
    except (LLMServiceError, WorkflowExecutionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversation persistence is temporarily unavailable.",
        ) from exc
    except ConversationAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    return ChatResponse(answer=answer)
