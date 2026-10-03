from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetEmployeeInfoArguments(ToolArguments):
    employee_id: str = Field(min_length=1, max_length=32)


class GetApplicationStatusArguments(ToolArguments):
    application_id: str = Field(min_length=1, max_length=64)


class CreateBusinessTripArguments(ToolArguments):
    employee_id: str = Field(min_length=1, max_length=32)
    destination: str = Field(min_length=1, max_length=100)
    days: int = Field(ge=1, le=365)
    reason: str = Field(
        default="业务出差（用户未提供具体事由）",
        min_length=1,
        max_length=500,
    )


@dataclass(frozen=True)
class ToolExecutionContext:
    user_id: str
    request_id: str


class ToolError(BaseModel):
    code: str
    message: str


class ToolResult(BaseModel):
    tool_call_id: str
    tool_name: str
    ok: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None
