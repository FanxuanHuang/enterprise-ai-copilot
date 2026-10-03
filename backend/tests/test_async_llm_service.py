import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import settings
from app.services.llm_service import LLMService


class AsyncLLMServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_llm_waits_can_progress_concurrently(self):
        active_requests = 0
        max_active_requests = 0
        both_requests_started = asyncio.Event()

        async def create(**request_options):
            nonlocal active_requests, max_active_requests
            self.assertIn("messages", request_options)
            active_requests += 1
            max_active_requests = max(max_active_requests, active_requests)
            if active_requests == 2:
                both_requests_started.set()
            await asyncio.wait_for(both_requests_started.wait(), timeout=1)
            active_requests -= 1
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="async response")
                    )
                ]
            )

        with patch.object(settings, "deepseek_api_key", "test-key"):
            service = LLMService()
            service.client = SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(create=create),
                )
            )
            answers = await asyncio.gather(
                service.generate_text("system", "first"),
                service.generate_text("system", "second"),
            )

        self.assertEqual(answers, ["async response", "async response"])
        self.assertEqual(max_active_requests, 2)


if __name__ == "__main__":
    unittest.main()
