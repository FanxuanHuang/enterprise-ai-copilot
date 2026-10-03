import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import ValidationError

from app.db.database import Database, database
from app.repositories.application_repository import ApplicationRepository
from app.repositories.employee_repository import EmployeeRepository
from app.services.enterprise_services import (
    ApplicationService,
    EmployeeService,
    EnterpriseServiceError,
)
from app.tools.application_tools import (
    create_business_trip_application,
    get_application_status,
)
from app.tools.employee_tools import get_employee_info
from app.tools.schemas import (
    CreateBusinessTripArguments,
    GetApplicationStatusArguments,
    GetEmployeeInfoArguments,
    ToolArguments,
    ToolError,
    ToolExecutionContext,
    ToolResult,
)


logger = logging.getLogger(__name__)
ToolHandler = Callable[[ToolArguments, ToolExecutionContext], dict[str, object]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments_model: type[ToolArguments]
    handler: ToolHandler

    def api_schema(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments_model.model_json_schema(),
            },
        }


class ToolRegistry:
    def __init__(
        self,
        definitions: list[ToolDefinition],
        target_database: Database,
    ) -> None:
        self._definitions = {definition.name: definition for definition in definitions}
        self.database = target_database

    def schemas(self) -> list[dict[str, object]]:
        return [definition.api_schema() for definition in self._definitions.values()]

    def dispatch(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        arguments_json: str,
        context: ToolExecutionContext,
    ) -> ToolResult:
        definition = self._definitions.get(tool_name)
        if definition is None:
            return self._error(
                tool_call_id,
                tool_name,
                "unknown_tool",
                f"Tool {tool_name} is not registered.",
            )

        try:
            raw_arguments = json.loads(arguments_json)
            arguments = definition.arguments_model.model_validate(raw_arguments)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning(
                "request_id=%s tool=%s status=invalid_arguments error=%s",
                context.request_id,
                tool_name,
                type(exc).__name__,
            )
            return self._error(
                tool_call_id,
                tool_name,
                "invalid_arguments",
                "Tool arguments did not match the required schema.",
            )

        try:
            self.database.initialize()
            started = time.perf_counter()
            data = definition.handler(arguments, context)
            logger.info(
                "request_id=%s event=tool_execution tool=%s input_keys=%s "
                "status=success latency_ms=%.2f",
                context.request_id,
                tool_name,
                sorted(raw_arguments),
                (time.perf_counter() - started) * 1000,
            )
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                ok=True,
                data=data,
            )
        except EnterpriseServiceError as exc:
            logger.info(
                "request_id=%s event=tool_execution tool=%s "
                "status=business_error error_code=%s",
                context.request_id,
                tool_name,
                exc.code,
            )
            return self._error(
                tool_call_id,
                tool_name,
                exc.code,
                exc.message,
            )
        except sqlite3.Error:
            logger.exception(
                "request_id=%s event=tool_execution tool=%s status=database_error",
                context.request_id,
                tool_name,
            )
            return self._error(
                tool_call_id,
                tool_name,
                "database_error",
                "The enterprise database operation failed.",
            )
        except Exception:
            logger.exception(
                "request_id=%s event=tool_execution tool=%s status=unexpected_error",
                context.request_id,
                tool_name,
            )
            return self._error(
                tool_call_id,
                tool_name,
                "tool_execution_error",
                "The tool could not complete the operation.",
            )

    @staticmethod
    def _error(
        tool_call_id: str,
        tool_name: str,
        code: str,
        message: str,
    ) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            ok=False,
            error=ToolError(code=code, message=message),
        )


def build_tool_registry(target_database: Database = database) -> ToolRegistry:
    employee_service = EmployeeService(EmployeeRepository(target_database))
    application_service = ApplicationService(
        ApplicationRepository(target_database),
        employee_service,
    )
    return ToolRegistry(
        [
            ToolDefinition(
                name="get_employee_info",
                description=(
                    "Get an employee's department, level, and role from the "
                    "enterprise employee database."
                ),
                arguments_model=GetEmployeeInfoArguments,
                handler=lambda arguments, context: get_employee_info(
                    arguments,
                    context,
                    employee_service,
                ),
            ),
            ToolDefinition(
                name="get_application_status",
                description=(
                    "Get the current status and details of an enterprise "
                    "application by application ID."
                ),
                arguments_model=GetApplicationStatusArguments,
                handler=lambda arguments, context: get_application_status(
                    arguments,
                    context,
                    application_service,
                    employee_service,
                ),
            ),
            ToolDefinition(
                name="create_business_trip_application",
                description=(
                    "Create and persist a business-trip application. Use this "
                    "only when the user explicitly asks to create one."
                ),
                arguments_model=CreateBusinessTripArguments,
                handler=lambda arguments, context: create_business_trip_application(
                    arguments,
                    context,
                    application_service,
                    employee_service,
                ),
            ),
        ],
        target_database,
    )


tool_registry = build_tool_registry()
