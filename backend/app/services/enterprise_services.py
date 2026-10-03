from dataclasses import asdict

from app.db.models import Application, Employee
from app.repositories.application_repository import ApplicationRepository
from app.repositories.employee_repository import EmployeeRepository


class EnterpriseServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class EmployeeService:
    def __init__(self, repository: EmployeeRepository) -> None:
        self.repository = repository

    def require_employee(self, employee_id: str) -> Employee:
        employee = self.repository.get_by_id(employee_id)
        if employee is None:
            raise EnterpriseServiceError(
                "employee_not_found",
                f"Employee {employee_id} does not exist.",
            )
        return employee

    def get_employee_info(
        self,
        *,
        actor: Employee,
        employee_id: str,
    ) -> dict[str, object]:
        employee = self.require_employee(employee_id)
        if actor.role == "employee" and actor.employee_id != employee_id:
            raise EnterpriseServiceError(
                "permission_denied",
                "Employees may only query their own employee record.",
            )
        return asdict(employee)


class ApplicationService:
    def __init__(
        self,
        repository: ApplicationRepository,
        employee_service: EmployeeService,
    ) -> None:
        self.repository = repository
        self.employee_service = employee_service

    @staticmethod
    def _check_employee_access(actor: Employee, employee_id: str) -> None:
        if actor.role == "employee" and actor.employee_id != employee_id:
            raise EnterpriseServiceError(
                "permission_denied",
                "Employees may only access their own applications.",
            )

    def get_application_status(
        self,
        *,
        actor: Employee,
        application_id: str,
    ) -> dict[str, object]:
        application = self.repository.get_by_id(application_id)
        if application is None:
            raise EnterpriseServiceError(
                "application_not_found",
                f"Application {application_id} does not exist.",
            )
        self._check_employee_access(actor, application.employee_id)
        return self._application_result(application)

    def create_business_trip_application(
        self,
        *,
        actor: Employee,
        employee_id: str,
        destination: str,
        days: int,
        reason: str,
    ) -> dict[str, object]:
        self.employee_service.require_employee(employee_id)
        self._check_employee_access(actor, employee_id)
        application = self.repository.create_business_trip(
            employee_id=employee_id,
            destination=destination,
            days=days,
            reason=reason,
        )
        return self._application_result(application)

    @staticmethod
    def _application_result(application: Application) -> dict[str, object]:
        return {
            "application_id": application.application_id,
            "employee_id": application.employee_id,
            "application_type": application.application_type,
            "destination": application.destination,
            "days": application.days,
            "reason": application.reason,
            "status": application.status,
            "created_at": application.created_at,
        }
