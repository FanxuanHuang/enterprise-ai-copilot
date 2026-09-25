from openai import APIError, OpenAI

from app.core.config import settings


class LLMServiceError(Exception):
    pass


class LLMService:
    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )

    def generate_answer(self, message: str) -> str:
        if not settings.deepseek_api_key:
            raise LLMServiceError("DEEPSEEK_API_KEY is not configured.")

        try:
            response = self.client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful enterprise AI copilot.",
                    },
                    {"role": "user", "content": message},
                ],
            )
        except APIError as exc:
            raise LLMServiceError("DeepSeek API request failed.") from exc
        except Exception as exc:
            raise LLMServiceError("Unexpected error while calling the LLM.") from exc

        answer = response.choices[0].message.content
        if not answer:
            raise LLMServiceError("DeepSeek returned an empty response.")

        return answer


llm_service = LLMService()

