from app.services.enterprise_services import ApplicationService, EmployeeService
from app.tools.schemas import (
    CreateBusinessTripArguments,
    GetApplicationStatusArguments,
    ToolExecutionContext,
)


def get_application_status(
    arguments: GetApplicationStatusArguments,
    context: ToolExecutionContext,
    application_service: ApplicationService,
    employee_service: EmployeeService,
) -> dict[str, object]:
    actor = employee_service.require_employee(context.user_id)
    return application_service.get_application_status(
        actor=actor,
        application_id=arguments.application_id,
    )


def create_business_trip_application(
    arguments: CreateBusinessTripArguments,
    context: ToolExecutionContext,
    application_service: ApplicationService,
    employee_service: EmployeeService,
) -> dict[str, object]:
    actor = employee_service.require_employee(context.user_id)
    return application_service.create_business_trip_application(
        actor=actor,
        employee_id=arguments.employee_id,
        destination=arguments.destination,
        days=arguments.days,
        reason=arguments.reason,
    )
