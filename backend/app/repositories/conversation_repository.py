from app.db.database import Database
from app.db.models import ConversationMessage


class ConversationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add_message(
        self,
        *,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations (session_id, user_id)
                VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, user_id),
            )
            connection.execute(
                """
                INSERT INTO messages (session_id, role, content)
                VALUES (?, ?, ?)
                """,
                (session_id, role, content),
            )

    def get_user_id(self, session_id: str) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT user_id FROM conversations WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row["user_id"] if row else None

    def list_recent_messages(
        self,
        session_id: str,
        *,
        limit: int = 10,
    ) -> list[ConversationMessage]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, created_at
                FROM (
                    SELECT id, role, content, created_at
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
                """,
                (session_id, limit),
            ).fetchall()
        return [ConversationMessage(**dict(row)) for row in rows]
