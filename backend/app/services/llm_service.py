import json
from typing import TypeVar

from openai import APIError, OpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import settings


class LLMServiceError(Exception):
    pass


StructuredResponse = TypeVar("StructuredResponse", bound=BaseModel)


class LLMService:
    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )

    def _create_completion(
        self,
        messages: list[dict[str, str]],
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

            response = self.client.chat.completions.create(**request_options)
        except APIError as exc:
            raise LLMServiceError("DeepSeek API request failed.") from exc
        except Exception as exc:
            raise LLMServiceError("Unexpected error while calling the LLM.") from exc

        answer = response.choices[0].message.content
        if not answer:
            raise LLMServiceError("DeepSeek returned an empty response.")

        return answer

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        return self._create_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

    def generate_structured(
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
        content = self._create_completion(
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

    def generate_answer(self, message: str) -> str:
        """Keep the V1 service method available for simple direct calls."""
        return self.generate_text(
            "You are a helpful enterprise AI copilot.",
            message,
        )


llm_service = LLMService()
