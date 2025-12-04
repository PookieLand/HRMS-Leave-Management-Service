"""
Leave Pydantic schemas.
Defines request/response models for Leave API endpoints.
Separates API contracts from database models for better flexibility.
"""

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.leave import LeaveStatus, LeaveType


class LeaveBase(SQLModel):
    """
    Base leave schema with shared fields.
    Used as foundation for other leave schemas.
    """

    employee_id: int = Field(gt=0)
    leave_type: LeaveType = Field(default=LeaveType.ANNUAL)
    start_date: datetime
    end_date: datetime
    reason: str | None = Field(default=None, max_length=500)


class LeaveCreate(LeaveBase):
    """
    Schema for creating a new leave request.
    Inherits all required fields from LeaveBase.
    """

    pass


class LeaveCreateSelf(SQLModel):
    """
    Schema for self-service leave creation.
    Employee ID is automatically populated from JWT token.
    """

    leave_type: LeaveType = Field(default=LeaveType.ANNUAL)
    start_date: datetime
    end_date: datetime
    reason: str | None = Field(default=None, max_length=500)


class LeaveStatusUpdate(SQLModel):
    """
    Schema for updating leave status.
    Used for approval and rejection workflows.
    """

    status: LeaveStatus
    rejection_reason: str | None = Field(default=None, max_length=500)
    approved_by: int | None = None


class LeaveApproveRequest(SQLModel):
    """
    Schema for approving a leave request.
    Approver ID is automatically populated from JWT token.
    """

    comments: str | None = Field(default=None, max_length=500)


class LeaveRejectRequest(SQLModel):
    """
    Schema for rejecting a leave request.
    Rejection reason is required.
    """

    rejection_reason: str = Field(min_length=1, max_length=500)


class LeavePublic(LeaveBase):
    """
    Schema for leave responses.
    Includes all fields returned to clients.
    """

    id: int
    status: LeaveStatus = Field(default=LeaveStatus.PENDING)
    approved_by: int | None = None
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class LeavePublicEnriched(LeavePublic):
    """
    Schema for enriched leave responses with employee details.
    Includes employee name and approver name for better UX.
    """

    employee_name: str | None = None
    approver_name: str | None = None
    days_count: int | None = None


class LeaveSummary(SQLModel):
    """
    Schema for leave summary statistics.
    Used in dashboard and reporting endpoints.
    """

    total_leaves: int = 0
    pending_leaves: int = 0
    approved_leaves: int = 0
    rejected_leaves: int = 0
    cancelled_leaves: int = 0


class LeaveBalancePublic(SQLModel):
    """
    Schema for employee leave balance information.
    Shows available leave days by type.
    """

    employee_id: int
    annual_leave_balance: float = 0.0
    sick_leave_balance: float = 0.0
    casual_leave_balance: float = 0.0
    unpaid_leave_balance: float = 0.0
    maternity_leave_balance: float = 0.0
    paternity_leave_balance: float = 0.0
    year: int
