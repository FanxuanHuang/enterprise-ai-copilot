import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_chat_keeps_v1_api_contract(self):
        with (
            patch(
                "app.api.chat.run_workflow",
                return_value="Workflow answer",
            ) as run_workflow,
            patch(
                "app.api.chat.conversation_service.get_history",
                return_value=[],
            ) as get_history,
            patch("app.api.chat.conversation_service.add_message") as add_message,
        ):
            response = self.client.post(
                "/api/chat",
                json={"message": "Analyze this request"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"answer": "Workflow answer"})
        self.assertEqual(run_workflow.call_args.args, ("Analyze this request",))
        self.assertEqual(run_workflow.call_args.kwargs["user_id"], "E1001")
        self.assertEqual(run_workflow.call_args.kwargs["conversation_history"], [])
        self.assertEqual(get_history.call_args.kwargs["user_id"], "E1001")
        self.assertEqual(add_message.call_count, 2)


if __name__ == "__main__":
    unittest.main()
