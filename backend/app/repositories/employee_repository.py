from app.db.database import Database
from app.db.models import Employee


class EmployeeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_by_id(self, employee_id: str) -> Employee | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT employee_id, name, department, level, role
                FROM employees
                WHERE employee_id = ?
                """,
                (employee_id,),
            ).fetchone()
        return Employee(**dict(row)) if row else None
