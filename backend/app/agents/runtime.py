from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.tools.registry import ToolRegistry


_tool_registry_override: ContextVar["ToolRegistry | None"] = ContextVar(
    "workflow_tool_registry_override",
    default=None,
)


def set_runtime_overrides(
    tool_registry: "ToolRegistry",
) -> Token["ToolRegistry | None"]:
    return _tool_registry_override.set(tool_registry)


def reset_runtime_overrides(
    token: Token["ToolRegistry | None"],
) -> None:
    _tool_registry_override.reset(token)


def get_tool_registry(default: "ToolRegistry") -> "ToolRegistry":
    return _tool_registry_override.get() or default
