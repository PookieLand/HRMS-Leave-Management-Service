"""
Leave Management Service - Leave Routes with RBAC Integration.

Implements comprehensive leave management endpoints with role-based access control:
- Self-service endpoints for employees
- Manager approval workflows
- HR dashboard and reporting
- Integration with Employee Service for user lookup
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import func, select

from app.api.dependencies import SessionDep
from app.core.events import (
    EventEnvelope,
    EventMetadata,
    EventType,
    LeaveApprovedEvent,
    LeaveCancelledEvent,
    LeaveRejectedEvent,
    LeaveRequestedEvent,
)
from app.core.kafka import publish_event
from app.core.logging import get_logger
from app.core.permissions import (
    can_access_leave,
    can_approve_specific_leave,
    is_hr,
    is_manager,
    log_authorization_check,
    require_employee,
    require_hr,
    require_manager,
)
from app.core.security import TokenData, get_current_user
from app.models.leave import Leave, LeaveStatus, LeaveType
from app.schemas.leave import (
    LeaveApproveRequest,
    LeaveCreate,
    LeaveCreateSelf,
    LeavePublic,
    LeavePublicEnriched,
    LeaveRejectRequest,
    LeaveStatusUpdate,
    LeaveSummary,
)
from app.services.employee_service import (
    get_employee_by_email,
    get_employee_by_id,
    get_employee_manager,
    get_employee_name,
    is_manager_of,
    list_team_members,
    verify_employee_exists,
)

logger = get_logger(__name__)

# Create router with prefix and tags for better organization
router = APIRouter(
    prefix="/leaves",
    tags=["leaves"],
    responses={404: {"description": "Leave not found"}},
)


# ============================================================================
# SELF-SERVICE ENDPOINTS (Employee Access)
# ============================================================================


@router.post("/me", response_model=LeavePublic, status_code=201)
async def create_leave_self_service(
    leave: LeaveCreateSelf,
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(require_employee)],
):
    """
    Create a new leave request (Self-Service).

    Employee applies for their own leave. The employee_id is automatically
    determined from the JWT token email claim.

    **Access**: Employees (all authenticated users)

    **Business Rules**:
    - start_date must be before end_date
    - Employee record must exist in Employee Service
    - Leave request is created with PENDING status
    """
    logger.info(f"Self-service leave creation by user: {current_user.email}")

    # Get employee ID from JWT email
    employee = get_employee_by_email(current_user.email)
    if not employee:
        logger.error(f"Employee record not found for user email: {current_user.email}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee record not found. Please contact HR.",
        )

    employee_id = employee.get("id")
    logger.info(f"Creating leave for employee {employee_id} ({current_user.email})")

    # Validate dates
    if leave.start_date >= leave.end_date:
        logger.warning(f"Invalid date range: {leave.start_date} >= {leave.end_date}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be before end_date",
        )

    # Validate dates are not in the past
    if leave.start_date.date() < datetime.now(timezone.utc).date():
        logger.warning(f"Leave start date is in the past: {leave.start_date}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot apply for leave with past dates",
        )

    # Create leave record
    db_leave = Leave(
        employee_id=employee_id,
        leave_type=leave.leave_type,
        start_date=leave.start_date,
        end_date=leave.end_date,
        reason=leave.reason,
        status=LeaveStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    session.add(db_leave)
    session.commit()
    session.refresh(db_leave)

    # Publish leave requested event
    try:
        event = EventEnvelope(
            event_type=EventType.LEAVE_REQUESTED,
            data={
                "leave_id": db_leave.id,
                "employee_id": db_leave.employee_id,
                "leave_type": db_leave.leave_type.value,
                "start_date": db_leave.start_date.isoformat(),
                "end_date": db_leave.end_date.isoformat(),
                "reason": db_leave.reason,
            },
            metadata=EventMetadata(user_id=current_user.sub),
        )
        await publish_event("leave-events", event)
        logger.info(f"Published leave requested event for: {db_leave.id}")
    except Exception as e:
        logger.warning(f"Failed to publish leave requested event: {e}")

    logger.info(
        f"Leave created successfully: ID={db_leave.id}, "
        f"employee={employee_id}, type={leave.leave_type.value}"
    )

    return db_leave


@router.get("/me", response_model=list[LeavePublicEnriched])
def get_my_leaves(
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(require_employee)],
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 100,
    status: str | None = None,
    leave_type: str | None = None,
):
    """
    Get my leave requests (Self-Service).

    Retrieve all leave requests for the authenticated employee.

    **Access**: Employees (all authenticated users)

    **Query Parameters**:
    - status: Filter by leave status (pending, approved, rejected, cancelled)
    - leave_type: Filter by leave type (sick, casual, annual, etc.)
    - offset: Pagination offset
    - limit: Maximum number of records (max 100)
    """
    logger.info(f"Fetching leaves for user: {current_user.email}")

    # Get employee ID from JWT email
    employee = get_employee_by_email(current_user.email)
    if not employee:
        logger.error(f"Employee record not found for user email: {current_user.email}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee record not found. Please contact HR.",
        )

    employee_id = employee.get("id")

    # Build query
    query = select(Leave).where(Leave.employee_id == employee_id)

    # Apply status filter
    if status:
        try:
            status_enum = LeaveStatus(status)
            query = query.where(Leave.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join([s.value for s in LeaveStatus])}",
            )

    # Apply leave type filter
    if leave_type:
        try:
            type_enum = LeaveType(leave_type)
            query = query.where(Leave.leave_type == type_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid leave type. Must be one of: {', '.join([t.value for t in LeaveType])}",
            )

    # Execute query with pagination
    leaves = session.exec(query.offset(offset).limit(limit)).all()

    logger.info(f"Retrieved {len(leaves)} leave(s) for employee {employee_id}")

    # Enrich with approver names
    enriched_leaves = []
    for leave in leaves:
        leave_dict = leave.model_dump()
        if leave.approved_by:
            approver_name = get_employee_name(leave.approved_by)
            leave_dict["approver_name"] = approver_name

        # Calculate days count
        days_count = (leave.end_date - leave.start_date).days + 1
        leave_dict["days_count"] = days_count

        enriched_leaves.append(LeavePublicEnriched(**leave_dict))

    return enriched_leaves


@router.delete("/me/{leave_id}")
async def cancel_my_leave(
    leave_id: int,
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(require_employee)],
):
    """
    Cancel my leave request (Self-Service).

    Employees can cancel their own PENDING or APPROVED leave requests.

    **Access**: Employees (all authenticated users, own leaves only)

    **Business Rules**:
    - Can only cancel own leaves
    - Can only cancel PENDING or APPROVED leaves
    - Cannot cancel REJECTED or already CANCELLED leaves
    """
    logger.info(f"User {current_user.email} attempting to cancel leave {leave_id}")

    # Get employee ID
    employee = get_employee_by_email(current_user.email)
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee record not found",
        )

    employee_id = employee.get("id")

    # Get leave record
    leave = session.get(Leave, leave_id)
    if not leave:
        logger.warning(f"Leave {leave_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave not found",
        )

    # Check ownership
    if leave.employee_id != employee_id:
        logger.warning(
            f"User {current_user.email} attempted to cancel leave belonging to employee {leave.employee_id}"
        )
        log_authorization_check(
            current_user, "cancel_leave", f"leave:{leave_id}", False
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only cancel your own leave requests",
        )

    # Check if leave can be cancelled
    if leave.status in [LeaveStatus.CANCELLED, LeaveStatus.REJECTED]:
        logger.warning(f"Cannot cancel leave with status {leave.status.value}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel a leave with status {leave.status.value}",
        )

    # Cancel the leave
    leave.status = LeaveStatus.CANCELLED
    leave.updated_at = datetime.now(timezone.utc)

    session.add(leave)
    session.commit()

    # Publish leave cancelled event
    try:
        event = EventEnvelope(
            event_type=EventType.LEAVE_CANCELLED,
            data={
                "leave_id": leave.id,
                "employee_id": leave.employee_id,
                "cancelled_by": employee_id,
                "cancellation_date": datetime.now(timezone.utc).isoformat(),
            },
            metadata=EventMetadata(user_id=current_user.sub),
        )
        await publish_event("leave-events", event)
        logger.info(f"Published leave cancelled event for: {leave.id}")
    except Exception as e:
        logger.warning(f"Failed to publish leave cancelled event: {e}")

    logger.info(f"Leave {leave_id} cancelled by employee {employee_id}")
    log_authorization_check(current_user, "cancel_leave", f"leave:{leave_id}", True)

    return {"ok": True, "message": "Leave cancelled successfully"}


# ============================================================================
# MANAGER & HR ENDPOINTS (Approval Workflows)
# ============================================================================


@router.get("/pending", response_model=list[LeavePublicEnriched])
def get_pending_leaves(
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(require_manager)],
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 100,
):
    """
    Get pending leave requests for approval.

    **Access**: Managers (Team-Managers, HR-Managers, HR-Administrators)

    **Behavior**:
    - Team-Managers: See pending leaves from their team members
    - HR-Managers & HR-Administrators: See all pending leaves

    **Returns**: List of pending leave requests with employee names
    """
    logger.info(f"Manager {current_user.email} fetching pending leaves")

    # Get employee ID
    employee = get_employee_by_email(current_user.email)
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee record not found",
        )

    manager_employee_id = employee.get("id")

    # Build base query for pending leaves
    query = select(Leave).where(Leave.status == LeaveStatus.PENDING)

    # If Team Manager (not HR), filter to team members only
    if not is_hr(current_user):
        # Get team member IDs
        team_members = list_team_members(manager_employee_id)
        team_member_ids = [tm.get("id") for tm in team_members]

        if not team_member_ids:
            logger.info(f"Team Manager {current_user.email} has no team members")
            return []

        query = query.where(Leave.employee_id.in_(team_member_ids))

    # Execute query
    leaves = session.exec(query.offset(offset).limit(limit)).all()

    logger.info(f"Retrieved {len(leaves)} pending leave(s)")

    # Enrich with employee names
    enriched_leaves = []
    for leave in leaves:
        leave_dict = leave.model_dump()
        employee_name = get_employee_name(leave.employee_id)
        leave_dict["employee_name"] = employee_name

        # Calculate days count
        days_count = (leave.end_date - leave.start_date).days + 1
        leave_dict["days_count"] = days_count

        enriched_leaves.append(LeavePublicEnriched(**leave_dict))

    return enriched_leaves


@router.post("/{leave_id}/approve", response_model=LeavePublic)
async def approve_leave(
    leave_id: int,
    request: LeaveApproveRequest,
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(require_manager)],
):
    """
    Approve a leave request.

    **Access**: Managers (Team-Managers, HR-Managers, HR-Administrators)

    **Business Rules**:
    - Can only approve PENDING leaves
    - Team-Managers can only approve their team members' leaves
    - HR can approve any leave
    - Cannot approve own leave
    """
    logger.info(f"Manager {current_user.email} attempting to approve leave {leave_id}")

    # Get approver employee ID
    approver_employee = get_employee_by_email(current_user.email)
    if not approver_employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approver employee record not found",
        )

    approver_id = approver_employee.get("id")

    # Get leave record
    leave = session.get(Leave, leave_id)
    if not leave:
        logger.warning(f"Leave {leave_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave not found",
        )

    # Check if leave is in PENDING status
    if leave.status != LeaveStatus.PENDING:
        logger.warning(f"Cannot approve leave with status {leave.status.value}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Can only approve PENDING leaves. Current status: {leave.status.value}",
        )

    # Check authorization
    if not can_approve_specific_leave(current_user, leave.employee_id, approver_id):
        logger.warning(
            f"Manager {current_user.email} not authorized to approve leave {leave_id}"
        )
        log_authorization_check(
            current_user, "approve_leave", f"leave:{leave_id}", False
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to approve this leave request",
        )

    # Approve the leave
    leave.status = LeaveStatus.APPROVED
    leave.approved_by = approver_id
    leave.updated_at = datetime.now(timezone.utc)

    session.add(leave)
    session.commit()
    session.refresh(leave)

    # Publish leave approved event
    try:
        event = EventEnvelope(
            event_type=EventType.LEAVE_APPROVED,
            data={
                "leave_id": leave.id,
                "employee_id": leave.employee_id,
                "approved_by": leave.approved_by,
                "approval_date": datetime.now(timezone.utc).isoformat(),
            },
            metadata=EventMetadata(user_id=current_user.sub),
        )
        await publish_event("leave-events", event)
        logger.info(f"Published leave approved event for: {leave.id}")
    except Exception as e:
        logger.warning(f"Failed to publish leave approved event: {e}")

    logger.info(
        f"Leave {leave_id} approved by {current_user.email} (employee_id={approver_id})"
    )
    log_authorization_check(current_user, "approve_leave", f"leave:{leave_id}", True)

    return leave


@router.post("/{leave_id}/reject", response_model=LeavePublic)
async def reject_leave(
    leave_id: int,
    request: LeaveRejectRequest,
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(require_manager)],
):
    """
    Reject a leave request.

    **Access**: Managers (Team-Managers, HR-Managers, HR-Administrators)

    **Business Rules**:
    - Can only reject PENDING leaves
    - Team-Managers can only reject their team members' leaves
    - HR can reject any leave
    - Rejection reason is mandatory
    """
    logger.info(f"Manager {current_user.email} attempting to reject leave {leave_id}")

    # Get approver employee ID
    approver_employee = get_employee_by_email(current_user.email)
    if not approver_employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approver employee record not found",
        )

    approver_id = approver_employee.get("id")

    # Get leave record
    leave = session.get(Leave, leave_id)
    if not leave:
        logger.warning(f"Leave {leave_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave not found",
        )

    # Check if leave is in PENDING status
    if leave.status != LeaveStatus.PENDING:
        logger.warning(f"Cannot reject leave with status {leave.status.value}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Can only reject PENDING leaves. Current status: {leave.status.value}",
        )

    # Check authorization
    if not can_approve_specific_leave(current_user, leave.employee_id, approver_id):
        logger.warning(
            f"Manager {current_user.email} not authorized to reject leave {leave_id}"
        )
        log_authorization_check(
            current_user, "reject_leave", f"leave:{leave_id}", False
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to reject this leave request",
        )

    # Reject the leave
    leave.status = LeaveStatus.REJECTED
    leave.approved_by = approver_id
    leave.rejection_reason = request.rejection_reason
    leave.updated_at = datetime.now(timezone.utc)

    session.add(leave)
    session.commit()
    session.refresh(leave)

    # Publish leave rejected event
    try:
        event = EventEnvelope(
            event_type=EventType.LEAVE_REJECTED,
            data={
                "leave_id": leave.id,
                "employee_id": leave.employee_id,
                "rejected_by": leave.approved_by,
                "rejection_reason": leave.rejection_reason,
                "rejection_date": datetime.now(timezone.utc).isoformat(),
            },
            metadata=EventMetadata(user_id=current_user.sub),
        )
        await publish_event("leave-events", event)
        logger.info(f"Published leave rejected event for: {leave.id}")
    except Exception as e:
        logger.warning(f"Failed to publish leave rejected event: {e}")

    logger.info(
        f"Leave {leave_id} rejected by {current_user.email} (employee_id={approver_id})"
    )
    log_authorization_check(current_user, "reject_leave", f"leave:{leave_id}", True)

    return leave


# ============================================================================
# HR DASHBOARD & REPORTING ENDPOINTS
# ============================================================================


@router.get("/dashboard/summary", response_model=LeaveSummary)
def get_leave_dashboard_summary(
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(require_hr)],
):
    """
    Get leave statistics summary for HR dashboard.

    **Access**: HR (HR-Managers, HR-Administrators)

    **Returns**: Summary counts of leaves by status
    """
    logger.info(f"HR user {current_user.email} fetching dashboard summary")

    # Get counts by status
    total_leaves = session.exec(select(func.count(Leave.id))).one()

    pending_leaves = session.exec(
        select(func.count(Leave.id)).where(Leave.status == LeaveStatus.PENDING)
    ).one()

    approved_leaves = session.exec(
        select(func.count(Leave.id)).where(Leave.status == LeaveStatus.APPROVED)
    ).one()

    rejected_leaves = session.exec(
        select(func.count(Leave.id)).where(Leave.status == LeaveStatus.REJECTED)
    ).one()

    cancelled_leaves = session.exec(
        select(func.count(Leave.id)).where(Leave.status == LeaveStatus.CANCELLED)
    ).one()

    summary = LeaveSummary(
        total_leaves=total_leaves or 0,
        pending_leaves=pending_leaves or 0,
        approved_leaves=approved_leaves or 0,
        rejected_leaves=rejected_leaves or 0,
        cancelled_leaves=cancelled_leaves or 0,
    )

    logger.info(f"Dashboard summary: {summary.model_dump()}")

    return summary


@router.get("/all", response_model=list[LeavePublicEnriched])
def list_all_leaves(
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(require_hr)],
    offset: int = 0,
    limit: Annotated[int, Query(le=200)] = 100,
    status: str | None = None,
    leave_type: str | None = None,
):
    """
    List all leave requests (HR access).

    **Access**: HR (HR-Managers, HR-Administrators)

    **Query Parameters**:
    - status: Filter by leave status
    - leave_type: Filter by leave type
    - offset: Pagination offset
    - limit: Maximum number of records (max 200 for HR)
    """
    logger.info(f"HR user {current_user.email} listing all leaves")

    # Build query
    query = select(Leave)

    # Apply filters
    if status:
        try:
            status_enum = LeaveStatus(status)
            query = query.where(Leave.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join([s.value for s in LeaveStatus])}",
            )

    if leave_type:
        try:
            type_enum = LeaveType(leave_type)
            query = query.where(Leave.leave_type == type_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid leave type. Must be one of: {', '.join([t.value for t in LeaveType])}",
            )

    # Execute query
    leaves = session.exec(query.offset(offset).limit(limit)).all()

    logger.info(f"Retrieved {len(leaves)} leave(s)")

    # Enrich with employee and approver names
    enriched_leaves = []
    for leave in leaves:
        leave_dict = leave.model_dump()
        employee_name = get_employee_name(leave.employee_id)
        leave_dict["employee_name"] = employee_name

        if leave.approved_by:
            approver_name = get_employee_name(leave.approved_by)
            leave_dict["approver_name"] = approver_name

        # Calculate days count
        days_count = (leave.end_date - leave.start_date).days + 1
        leave_dict["days_count"] = days_count

        enriched_leaves.append(LeavePublicEnriched(**leave_dict))

    return enriched_leaves


# ============================================================================
# LEGACY/ADMIN ENDPOINTS (Backward Compatibility)
# ============================================================================


@router.post("/", response_model=LeavePublic, status_code=201)
def create_leave(
    leave: LeaveCreate,
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(require_hr)],
):
    """
    Create a new leave request (Admin/HR operation).

    **Access**: HR (HR-Managers, HR-Administrators)

    This endpoint allows HR to create leave requests on behalf of employees.
    For self-service leave creation, use POST /leaves/me instead.

    **Business Rules**:
    - Validates that the employee exists via employee service
    - Validates that start_date is before end_date
    """
    logger.info(
        f"HR user {current_user.email} creating leave for employee {leave.employee_id}"
    )

    # Validate dates
    if leave.start_date >= leave.end_date:
        logger.warning(f"Invalid date range: {leave.start_date} >= {leave.end_date}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be before end_date",
        )

    # Verify employee exists
    if not verify_employee_exists(leave.employee_id):
        logger.warning(f"Employee {leave.employee_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    db_leave = Leave.model_validate(leave)
    db_leave.status = LeaveStatus.PENDING
    db_leave.created_at = datetime.now(timezone.utc)
    db_leave.updated_at = datetime.now(timezone.utc)

    session.add(db_leave)
    session.commit()
    session.refresh(db_leave)

    logger.info(f"Leave created successfully with ID: {db_leave.id}")
    return db_leave


@router.get("/", response_model=list[LeavePublic])
def list_leaves(
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(get_current_user)],
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 100,
    status: str | None = None,
):
    """
    List leaves with optional filtering and pagination.

    **Access**: All authenticated users

    **Behavior**:
    - Employees: See only their own leaves
    - Managers: See their team members' leaves
    - HR: See all leaves

    For better UX, use the specific endpoints:
    - GET /leaves/me (employees)
    - GET /leaves/pending (managers)
    - GET /leaves/all (HR)
    """
    logger.info(f"User {current_user.email} listing leaves")

    # Get employee ID
    employee = get_employee_by_email(current_user.email)
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee record not found",
        )

    employee_id = employee.get("id")

    # Build query based on user role
    query = select(Leave)

    # If not HR, filter to own leaves or team leaves
    if not is_hr(current_user):
        if is_manager(current_user):
            # Managers see their team members' leaves + their own
            team_members = list_team_members(employee_id)
            team_member_ids = [tm.get("id") for tm in team_members]
            team_member_ids.append(employee_id)  # Include own leaves
            query = query.where(Leave.employee_id.in_(team_member_ids))
        else:
            # Regular employees see only their own leaves
            query = query.where(Leave.employee_id == employee_id)

    # Apply status filter
    if status:
        try:
            status_enum = LeaveStatus(status)
            query = query.where(Leave.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join([s.value for s in LeaveStatus])}",
            )

    leaves = session.exec(query.offset(offset).limit(limit)).all()
    logger.info(f"Retrieved {len(leaves)} leave(s)")
    return list(leaves)


@router.get("/{leave_id}", response_model=LeavePublicEnriched)
def get_leave(
    leave_id: int,
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(get_current_user)],
):
    """
    Retrieve a specific leave request by ID.

    **Access**: All authenticated users

    **Authorization**:
    - Employees can only view their own leaves
    - Managers can view their team members' leaves
    - HR can view any leave
    """
    logger.info(f"User {current_user.email} fetching leave {leave_id}")

    # Get employee ID
    employee = get_employee_by_email(current_user.email)
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee record not found",
        )

    employee_id = employee.get("id")

    # Get leave record
    leave = session.get(Leave, leave_id)
    if not leave:
        logger.warning(f"Leave with ID {leave_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave not found",
        )

    # Check access authorization
    if not can_access_leave(current_user, leave.employee_id, employee_id):
        logger.warning(
            f"User {current_user.email} not authorized to access leave {leave_id}"
        )
        log_authorization_check(current_user, "view_leave", f"leave:{leave_id}", False)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to view this leave request",
        )

    log_authorization_check(current_user, "view_leave", f"leave:{leave_id}", True)

    # Enrich with names
    leave_dict = leave.model_dump()
    employee_name = get_employee_name(leave.employee_id)
    leave_dict["employee_name"] = employee_name

    if leave.approved_by:
        approver_name = get_employee_name(leave.approved_by)
        leave_dict["approver_name"] = approver_name

    # Calculate days count
    days_count = (leave.end_date - leave.start_date).days + 1
    leave_dict["days_count"] = days_count

    return LeavePublicEnriched(**leave_dict)


@router.get("/employee/{employee_id}", response_model=list[LeavePublicEnriched])
def get_employee_leaves(
    employee_id: int,
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(get_current_user)],
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 100,
    status: str | None = None,
):
    """
    Retrieve all leaves for a specific employee.

    **Access**: All authenticated users

    **Authorization**:
    - Employees can only view their own leaves
    - Managers can view their team members' leaves
    - HR can view any employee's leaves
    """
    logger.info(f"User {current_user.email} fetching leaves for employee {employee_id}")

    # Get current user's employee ID
    current_employee = get_employee_by_email(current_user.email)
    if not current_employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee record not found",
        )

    current_employee_id = current_employee.get("id")

    # Check access authorization
    if not can_access_leave(current_user, employee_id, current_employee_id):
        logger.warning(
            f"User {current_user.email} not authorized to access leaves for employee {employee_id}"
        )
        log_authorization_check(
            current_user,
            "view_employee_leaves",
            f"employee:{employee_id}",
            False,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to view this employee's leaves",
        )

    # Verify employee exists
    if not verify_employee_exists(employee_id):
        logger.warning(f"Employee {employee_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    # Build query
    query = select(Leave).where(Leave.employee_id == employee_id)

    if status:
        try:
            status_enum = LeaveStatus(status)
            query = query.where(Leave.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join([s.value for s in LeaveStatus])}",
            )

    leaves = session.exec(query.offset(offset).limit(limit)).all()
    logger.info(f"Retrieved {len(leaves)} leave(s) for employee {employee_id}")

    log_authorization_check(
        current_user, "view_employee_leaves", f"employee:{employee_id}", True
    )

    # Enrich with names
    enriched_leaves = []
    for leave in leaves:
        leave_dict = leave.model_dump()
        employee_name = get_employee_name(leave.employee_id)
        leave_dict["employee_name"] = employee_name

        if leave.approved_by:
            approver_name = get_employee_name(leave.approved_by)
            leave_dict["approver_name"] = approver_name

        # Calculate days count
        days_count = (leave.end_date - leave.start_date).days + 1
        leave_dict["days_count"] = days_count

        enriched_leaves.append(LeavePublicEnriched(**leave_dict))

    return enriched_leaves


@router.put("/{leave_id}", response_model=LeavePublic)
def update_leave_status(
    leave_id: int,
    status_update: LeaveStatusUpdate,
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(require_hr)],
):
    """
    Update the status of a leave request (Admin/HR operation).

    **Access**: HR (HR-Managers, HR-Administrators)

    **DEPRECATED**: Use the specific endpoints instead:
    - POST /leaves/{leave_id}/approve
    - POST /leaves/{leave_id}/reject
    - DELETE /leaves/me/{leave_id} (for cancellation)

    **Business Rules**:
    - Supports status transitions: PENDING -> APPROVED/REJECTED/CANCELLED
    - Requires approved_by when approving
    - Requires rejection_reason when rejecting
    """
    logger.info(
        f"HR user {current_user.email} updating leave {leave_id} status to {status_update.status}"
    )

    leave = session.get(Leave, leave_id)
    if not leave:
        logger.warning(f"Leave with ID {leave_id} not found for update")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave not found",
        )

    # Validate status transition
    if (
        leave.status != LeaveStatus.PENDING
        and status_update.status != LeaveStatus.CANCELLED
    ):
        logger.warning(
            f"Invalid status transition from {leave.status} to {status_update.status}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot change status from {leave.status.value} to {status_update.status.value}",
        )

    # Validate required fields for approval
    if status_update.status == LeaveStatus.APPROVED and not status_update.approved_by:
        logger.warning("Approval requires approved_by field")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="approved_by is required when approving a leave",
        )

    # Validate required fields for rejection
    if (
        status_update.status == LeaveStatus.REJECTED
        and not status_update.rejection_reason
    ):
        logger.warning("Rejection requires rejection_reason field")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="rejection_reason is required when rejecting a leave",
        )

    # Update leave
    leave.status = status_update.status
    leave.approved_by = status_update.approved_by
    leave.rejection_reason = status_update.rejection_reason
    leave.updated_at = datetime.now(timezone.utc)

    session.add(leave)
    session.commit()
    session.refresh(leave)

    logger.info(f"Leave {leave_id} status updated to {status_update.status.value}")
    return leave


@router.delete("/{leave_id}")
def cancel_leave(
    leave_id: int,
    session: SessionDep,
    current_user: Annotated[TokenData, Depends(require_hr)],
):
    """
    Cancel a leave request (Admin/HR operation).

    **Access**: HR (HR-Managers, HR-Administrators)

    **DEPRECATED**: Employees should use DELETE /leaves/me/{leave_id} instead.

    **Business Rules**:
    - Only allows cancellation of PENDING or APPROVED leaves
    - Changes status to CANCELLED
    """
    logger.info(f"HR user {current_user.email} cancelling leave {leave_id}")

    leave = session.get(Leave, leave_id)
    if not leave:
        logger.warning(f"Leave with ID {leave_id} not found for cancellation")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave not found",
        )

    # Check if leave can be cancelled
    if leave.status in [LeaveStatus.CANCELLED, LeaveStatus.REJECTED]:
        logger.warning(f"Cannot cancel leave with status {leave.status.value}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel a leave with status {leave.status.value}",
        )

    leave.status = LeaveStatus.CANCELLED
    leave.updated_at = datetime.now(timezone.utc)

    session.add(leave)
    session.commit()

    logger.info(f"Leave with ID {leave_id} cancelled successfully by HR")
    return {"ok": True}
