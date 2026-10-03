import tempfile
import unittest
from pathlib import Path

from app.db.database import Database
from app.repositories.application_repository import ApplicationRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.employee_repository import EmployeeRepository
from app.services.conversation_service import (
    ConversationAccessError,
    ConversationService,
)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(
            Path(self.temporary_directory.name) / "enterprise-test.db"
        )
        self.database.initialize()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_initialization_seeds_demo_records(self):
        employee = EmployeeRepository(self.database).get_by_id("E1001")
        application = ApplicationRepository(self.database).get_by_id(
            "TRIP-2026-001"
        )

        self.assertIsNotNone(employee)
        self.assertEqual(employee.department, "研发")
        self.assertEqual(employee.level, "P6")
        self.assertIsNotNone(application)
        self.assertEqual(application.status, "审批中")

    def test_application_and_conversation_round_trip(self):
        application = ApplicationRepository(self.database).create_business_trip(
            employee_id="E1001",
            destination="上海",
            days=3,
            reason="客户会议",
        )
        self.assertEqual(application.destination, "上海")
        self.assertEqual(application.days, 3)

        repository = ConversationRepository(self.database)
        repository.add_message(
            session_id="session-1",
            user_id="E1001",
            role="user",
            content="你好",
        )
        repository.add_message(
            session_id="session-1",
            user_id="E1001",
            role="assistant",
            content="你好，有什么可以帮助你的？",
        )
        messages = repository.list_recent_messages("session-1")
        self.assertEqual([message.role for message in messages], ["user", "assistant"])

    def test_session_history_cannot_be_read_by_another_user(self):
        service = ConversationService(self.database)
        service.add_message(
            session_id="private-session",
            user_id="E1001",
            role="user",
            content="private message",
        )

        with self.assertRaises(ConversationAccessError):
            service.get_history("private-session", user_id="M1001")


if __name__ == "__main__":
    unittest.main()
