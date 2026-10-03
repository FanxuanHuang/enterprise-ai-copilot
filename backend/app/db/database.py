import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.core.config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    department TEXT NOT NULL,
    level TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('employee', 'manager', 'admin')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS applications (
    application_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    application_type TEXT NOT NULL,
    destination TEXT NOT NULL,
    days INTEGER NOT NULL CHECK (days > 0),
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES conversations(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_applications_employee_id
ON applications(employee_id);

CREATE INDEX IF NOT EXISTS idx_messages_session_id
ON messages(session_id, id);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialized = False
        self._initialize_lock = threading.Lock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as connection:
                connection.executescript(SCHEMA)
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO employees
                        (employee_id, name, department, level, role)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        ("E1001", "张明", "研发", "P6", "employee"),
                        ("M1001", "李静", "研发", "M2", "manager"),
                        ("A1001", "王晨", "企业系统", "P8", "admin"),
                    ],
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO applications
                        (application_id, employee_id, application_type,
                         destination, days, reason, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "TRIP-2026-001",
                        "E1001",
                        "business_trip",
                        "北京",
                        2,
                        "客户项目沟通",
                        "审批中",
                    ),
                )
            self._initialized = True


database = Database(settings.database_path)
