from datetime import datetime

from app.db.database import Database
from app.db.models import Application


class ApplicationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_by_id(self, application_id: str) -> Application | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT application_id, employee_id, application_type,
                       destination, days, reason, status, created_at
                FROM applications
                WHERE application_id = ?
                """,
                (application_id,),
            ).fetchone()
        return Application(**dict(row)) if row else None

    def create_business_trip(
        self,
        *,
        employee_id: str,
        destination: str,
        days: int,
        reason: str,
    ) -> Application:
        year = datetime.now().year
        prefix = f"TRIP-{year}-"
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT application_id
                FROM applications
                WHERE application_id LIKE ?
                """,
                (f"{prefix}%",),
            ).fetchall()
            sequence = max(
                (
                    int(row["application_id"].removeprefix(prefix))
                    for row in rows
                    if row["application_id"].removeprefix(prefix).isdigit()
                ),
                default=0,
            ) + 1
            application_id = f"{prefix}{sequence:03d}"
            connection.execute(
                """
                INSERT INTO applications
                    (application_id, employee_id, application_type,
                     destination, days, reason, status)
                VALUES (?, ?, 'business_trip', ?, ?, ?, '审批中')
                """,
                (application_id, employee_id, destination, days, reason),
            )
            row = connection.execute(
                """
                SELECT application_id, employee_id, application_type,
                       destination, days, reason, status, created_at
                FROM applications
                WHERE application_id = ?
                """,
                (application_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Created application could not be loaded.")
        return Application(**dict(row))
