from app.db.database import Database, database
from app.repositories.conversation_repository import ConversationRepository


class ConversationAccessError(Exception):
    pass


class ConversationService:
    def __init__(self, target_database: Database = database) -> None:
        self.database = target_database
        self.repository = ConversationRepository(target_database)

    def add_message(
        self,
        *,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
    ) -> None:
        self.database.initialize()
        self._check_session_access(session_id, user_id)
        self.repository.add_message(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
        )

    def get_history(
        self,
        session_id: str,
        *,
        user_id: str,
        limit: int = 10,
    ) -> list[dict[str, str]]:
        self.database.initialize()
        self._check_session_access(session_id, user_id)
        return [
            {"role": message.role, "content": message.content}
            for message in self.repository.list_recent_messages(
                session_id,
                limit=limit,
            )
        ]

    def _check_session_access(self, session_id: str, user_id: str) -> None:
        owner_id = self.repository.get_user_id(session_id)
        if owner_id is not None and owner_id != user_id:
            raise ConversationAccessError(
                "The session belongs to a different user."
            )


conversation_service = ConversationService()
