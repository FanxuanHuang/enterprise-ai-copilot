from dataclasses import dataclass


@dataclass(frozen=True)
class Employee:
    employee_id: str
    name: str
    department: str
    level: str
    role: str


@dataclass(frozen=True)
class Application:
    application_id: str
    employee_id: str
    application_type: str
    destination: str
    days: int
    reason: str
    status: str
    created_at: str


@dataclass(frozen=True)
class ConversationMessage:
    role: str
    content: str
    created_at: str
