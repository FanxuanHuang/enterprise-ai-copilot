from app.services.enterprise_services import EmployeeService
from app.tools.schemas import GetEmployeeInfoArguments, ToolExecutionContext


def get_employee_info(
    arguments: GetEmployeeInfoArguments,
    context: ToolExecutionContext,
    employee_service: EmployeeService,
) -> dict[str, object]:
    actor = employee_service.require_employee(context.user_id)
    return employee_service.get_employee_info(
        actor=actor,
        employee_id=arguments.employee_id,
    )
