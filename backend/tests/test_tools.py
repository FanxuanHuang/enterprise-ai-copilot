import json
import tempfile
import unittest
from pathlib import Path

from app.db.database import Database
from app.tools.registry import build_tool_registry
from app.tools.schemas import ToolExecutionContext


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "tools.db")
        self.registry = build_tool_registry(self.database)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def dispatch(self, name, arguments, user_id="E1001"):
        return self.registry.dispatch(
            tool_call_id="call-1",
            tool_name=name,
            arguments_json=json.dumps(arguments, ensure_ascii=False),
            context=ToolExecutionContext(user_id=user_id, request_id="request-1"),
        )

    def test_tool_schemas_are_openai_compatible(self):
        schemas = self.registry.schemas()
        names = {schema["function"]["name"] for schema in schemas}
        self.assertEqual(
            names,
            {
                "get_employee_info",
                "get_application_status",
                "create_business_trip_application",
            },
        )
        self.assertTrue(
            all(schema["function"]["parameters"]["type"] == "object" for schema in schemas)
        )

    def test_dispatcher_passes_arguments_and_persists_application(self):
        result = self.dispatch(
            "create_business_trip_application",
            {
                "employee_id": "E1001",
                "destination": "上海",
                "days": 3,
                "reason": "客户会议",
            },
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.data["destination"], "上海")

        status = self.dispatch(
            "get_application_status",
            {"application_id": result.data["application_id"]},
        )
        self.assertTrue(status.ok)
        self.assertEqual(status.data["status"], "审批中")

    def test_not_found_invalid_arguments_and_permissions_are_structured(self):
        missing = self.dispatch(
            "get_employee_info",
            {"employee_id": "E9999"},
        )
        invalid = self.dispatch(
            "create_business_trip_application",
            {"employee_id": "E1001", "destination": "上海", "days": 0},
        )
        denied = self.dispatch(
            "get_employee_info",
            {"employee_id": "M1001"},
        )
        manager = self.dispatch(
            "get_employee_info",
            {"employee_id": "E1001"},
            user_id="M1001",
        )

        self.assertEqual(missing.error.code, "employee_not_found")
        self.assertEqual(invalid.error.code, "invalid_arguments")
        self.assertEqual(denied.error.code, "permission_denied")
        self.assertTrue(manager.ok)


if __name__ == "__main__":
    unittest.main()
