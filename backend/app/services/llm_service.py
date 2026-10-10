import json
import logging
from dataclasses import dataclass
from typing import Any, TypeVar

from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import settings


logger = logging.getLogger(__name__)


class LLMServiceError(Exception):
    pass


StructuredResponse = TypeVar("StructuredResponse", bound=BaseModel)


@dataclass(frozen=True)
class LLMToolCall:
    tool_call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class AgentDecision:
    content: str
    tool_calls: list[LLMToolCall]


class LLMService:
    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=settings.deepseek_timeout_seconds,
            max_retries=settings.deepseek_max_retries,
        )

    async def _create_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        response_format: dict[str, str] | None = None,
    ) -> str:
        if not settings.deepseek_api_key:
            raise LLMServiceError("DEEPSEEK_API_KEY is not configured.")

        try:
            request_options = {
                "model": settings.deepseek_model,
                "messages": messages,
            }
            if response_format is not None:
                request_options["response_format"] = response_format

            response = await self.client.chat.completions.create(**request_options)
        except APIError as exc:
            logger.warning(
                "DeepSeek API request failed: error_type=%s",
                type(exc).__name__,
            )
            raise LLMServiceError("DeepSeek API request failed.") from exc
        except Exception as exc:
            logger.exception(
                "Unexpected DeepSeek request error: error_type=%s",
                type(exc).__name__,
            )
            raise LLMServiceError("Unexpected error while calling the LLM.") from exc

        answer = response.choices[0].message.content
        if not answer:
            raise LLMServiceError("DeepSeek returned an empty response.")

        return answer

    async def generate_agent_decision(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, object]],
        allow_tools: bool,
    ) -> AgentDecision:
        if not settings.deepseek_api_key:
            raise LLMServiceError("DEEPSEEK_API_KEY is not configured.")

        request_options: dict[str, Any] = {
            "model": settings.deepseek_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                *messages,
            ],
            "tools": tools,
            "tool_choice": "auto" if allow_tools else "none",
        }
        try:
            response = await self.client.chat.completions.create(**request_options)
        except APIError as exc:
            logger.warning(
                "DeepSeek agent request failed: error_type=%s",
                type(exc).__name__,
            )
            raise LLMServiceError("DeepSeek API request failed.") from exc
        except Exception as exc:
            logger.exception(
                "Unexpected DeepSeek agent error: error_type=%s",
                type(exc).__name__,
            )
            raise LLMServiceError(
                "Unexpected error while calling the LLM agent."
            ) from exc

        message = response.choices[0].message
        tool_calls = [
            LLMToolCall(
                tool_call_id=tool_call.id,
                name=tool_call.function.name,
                arguments=tool_call.function.arguments,
            )
            for tool_call in (message.tool_calls or [])
        ]
        content = message.content or ""
        if not content and not tool_calls:
            raise LLMServiceError("DeepSeek returned an empty agent decision.")
        return AgentDecision(content=content, tool_calls=tool_calls)

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        return await self._create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredResponse],
    ) -> StructuredResponse:
        schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        json_prompt = (
            f"{user_prompt}\n\n"
            "Return only one valid JSON object matching this JSON schema:\n"
            f"{schema}"
        )
        content = await self._create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json_prompt},
            ],
            response_format={"type": "json_object"},
        )

        try:
            return response_model.model_validate_json(content)
        except ValidationError as exc:
            raise LLMServiceError(
                "DeepSeek returned an invalid structured response."
            ) from exc

    async def generate_answer(self, message: str) -> str:
        """Keep the V1 service method available for simple direct calls."""
        return await self.generate_text(
            "You are a helpful enterprise AI copilot.",
            message,
        )


llm_service = LLMService()
