"""
Leave Management Service - RBAC Permissions Module.

Defines role-based access control (RBAC) logic for leave management operations.
Integrates with Asgardeo groups and roles extracted from JWT tokens.

Group Hierarchy:
- Employees: Can manage their own leaves
- Team-Managers: Can view and approve team member leaves
- HR-Managers: Can view and approve any leave, access reports
- HR-Administrators: Full access to all leave operations
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.core.logging import get_logger
from app.core.security import TokenData, get_current_user

logger = get_logger(__name__)

# Define Asgardeo group names (case-sensitive)
GROUP_EMPLOYEES = "Employees"
GROUP_TEAM_MANAGERS = "Team-Managers"
GROUP_HR_MANAGERS = "HR-Managers"
GROUP_HR_ADMINISTRATORS = "HR-Administrators"

# Manager and HR groups for quick checks
MANAGER_GROUPS = {GROUP_TEAM_MANAGERS, GROUP_HR_MANAGERS, GROUP_HR_ADMINISTRATORS}
HR_GROUPS = {GROUP_HR_MANAGERS, GROUP_HR_ADMINISTRATORS}
ADMIN_GROUPS = {GROUP_HR_ADMINISTRATORS}


def is_employee(user: TokenData) -> bool:
    """
    Check if user is an employee (has Employees group).
    All users should have this as the base group.

    Args:
        user: Authenticated user token data

    Returns:
        True if user is in Employees group
    """
    return GROUP_EMPLOYEES in user.groups


def is_manager(user: TokenData) -> bool:
    """
    Check if user is a manager (Team-Manager, HR-Manager, or HR-Administrator).

    Args:
        user: Authenticated user token data

    Returns:
        True if user is in any manager group
    """
    return bool(MANAGER_GROUPS & set(user.groups))


def is_hr(user: TokenData) -> bool:
    """
    Check if user is HR staff (HR-Manager or HR-Administrator).

    Args:
        user: Authenticated user token data

    Returns:
        True if user is in HR groups
    """
    return bool(HR_GROUPS & set(user.groups))


def is_hr_admin(user: TokenData) -> bool:
    """
    Check if user is HR Administrator.

    Args:
        user: Authenticated user token data

    Returns:
        True if user is HR Administrator
    """
    return GROUP_HR_ADMINISTRATORS in user.groups


def is_team_manager(user: TokenData) -> bool:
    """
    Check if user is a Team Manager.

    Args:
        user: Authenticated user token data

    Returns:
        True if user is Team Manager
    """
    return GROUP_TEAM_MANAGERS in user.groups


def can_approve_leave(user: TokenData) -> bool:
    """
    Check if user has permission to approve leave requests.
    Managers and HR can approve leaves.

    Args:
        user: Authenticated user token data

    Returns:
        True if user can approve leaves
    """
    return is_manager(user)


def can_view_all_leaves(user: TokenData) -> bool:
    """
    Check if user can view all leave requests.
    HR staff can view all leaves.

    Args:
        user: Authenticated user token data

    Returns:
        True if user can view all leaves
    """
    return is_hr(user)


def can_manage_leave_balances(user: TokenData) -> bool:
    """
    Check if user can manage leave balances.
    Only HR Administrators can manage balances.

    Args:
        user: Authenticated user token data

    Returns:
        True if user can manage leave balances
    """
    return is_hr_admin(user)


def require_employee(
    user: Annotated[TokenData, Depends(get_current_user)],
) -> TokenData:
    """
    Dependency that requires the user to be an employee.

    Args:
        user: Authenticated user token data

    Returns:
        TokenData if user is employee

    Raises:
        HTTPException: 403 if user is not an employee
    """
    if not is_employee(user):
        logger.warning(f"Access denied: User {user.email} is not an employee")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employee access required",
        )
    return user


def require_manager(user: Annotated[TokenData, Depends(get_current_user)]) -> TokenData:
    """
    Dependency that requires the user to be a manager.

    Args:
        user: Authenticated user token data

    Returns:
        TokenData if user is manager

    Raises:
        HTTPException: 403 if user is not a manager
    """
    if not is_manager(user):
        logger.warning(f"Access denied: User {user.email} is not a manager")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager access required",
        )
    return user


def require_hr(user: Annotated[TokenData, Depends(get_current_user)]) -> TokenData:
    """
    Dependency that requires the user to be HR staff.

    Args:
        user: Authenticated user token data

    Returns:
        TokenData if user is HR

    Raises:
        HTTPException: 403 if user is not HR
    """
    if not is_hr(user):
        logger.warning(f"Access denied: User {user.email} is not HR")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HR access required",
        )
    return user


def require_hr_admin(
    user: Annotated[TokenData, Depends(get_current_user)],
) -> TokenData:
    """
    Dependency that requires the user to be HR Administrator.

    Args:
        user: Authenticated user token data

    Returns:
        TokenData if user is HR Administrator

    Raises:
        HTTPException: 403 if user is not HR Administrator
    """
    if not is_hr_admin(user):
        logger.warning(f"Access denied: User {user.email} is not HR Administrator")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HR Administrator access required",
        )
    return user


def can_access_leave(
    user: TokenData, leave_employee_id: int, applicant_employee_id: int
) -> bool:
    """
    Check if user can access a specific leave record.

    Rules:
    - Employees can only access their own leaves
    - HR can access any leave
    - Team Managers can access their team members' leaves (requires manager check)

    Args:
        user: Authenticated user token data
        leave_employee_id: Employee ID associated with the leave record
        applicant_employee_id: Employee ID of the authenticated user

    Returns:
        True if user can access the leave
    """
    # HR can access any leave
    if is_hr(user):
        return True

    # User can access their own leaves
    if leave_employee_id == applicant_employee_id:
        return True

    # Team managers can access their team members' leaves
    # (In real implementation, you'd check manager-employee relationship in DB)
    if is_team_manager(user):
        # TODO: Implement actual team membership check via Employee Service
        # For now, team managers can see all leaves (simplified)
        logger.info(
            f"Team Manager {user.email} accessing leave for employee {leave_employee_id}"
        )
        return True

    return False


def can_approve_specific_leave(
    user: TokenData, leave_employee_id: int, approver_employee_id: int
) -> bool:
    """
    Check if user can approve a specific leave request.

    Rules:
    - HR can approve any leave
    - Team Managers can approve their team members' leaves
    - Users cannot approve their own leaves

    Args:
        user: Authenticated user token data
        leave_employee_id: Employee ID who requested the leave
        approver_employee_id: Employee ID of the approver

    Returns:
        True if user can approve the leave
    """
    # Users cannot approve their own leaves
    if leave_employee_id == approver_employee_id:
        logger.warning(
            f"Self-approval attempt: User {user.email} tried to approve own leave"
        )
        return False

    # HR can approve any leave
    if is_hr(user):
        return True

    # Team managers can approve team members' leaves
    if is_team_manager(user):
        # TODO: Implement actual team membership check via Employee Service
        # For now, team managers can approve any leave except their own
        logger.info(
            f"Team Manager {user.email} approving leave for employee {leave_employee_id}"
        )
        return True

    return False


def log_authorization_check(
    user: TokenData, action: str, resource: str, allowed: bool
) -> None:
    """
    Log authorization check results for audit purposes.

    Args:
        user: Authenticated user token data
        action: Action being performed (e.g., "approve_leave", "view_leave")
        resource: Resource being accessed (e.g., "leave:123")
        allowed: Whether access was allowed
    """
    status_str = "ALLOWED" if allowed else "DENIED"
    logger.info(
        f"Authorization {status_str}: user={user.email}, "
        f"action={action}, resource={resource}, groups={user.groups}"
    )
