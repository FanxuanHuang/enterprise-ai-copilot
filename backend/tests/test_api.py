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
        with patch(
            "app.api.chat.run_workflow",
            return_value="Workflow answer",
        ) as run_workflow:
            response = self.client.post(
                "/api/chat",
                json={"message": "Analyze this request"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"answer": "Workflow answer"})
        run_workflow.assert_called_once_with("Analyze this request")


if __name__ == "__main__":
    unittest.main()
