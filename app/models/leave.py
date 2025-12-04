"""
Leave database model.
Defines the SQLModel table structure for the Leave entity.
"""

from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel


class LeaveStatus(str, Enum):
    """Leave status enumeration."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class LeaveType(str, Enum):
    """Leave type enumeration."""

    SICK = "sick"
    CASUAL = "casual"
    ANNUAL = "annual"
    UNPAID = "unpaid"
    MATERNITY = "maternity"
    PATERNITY = "paternity"


class Leave(SQLModel, table=True):
    """
    Leave database table model.
    Represents the leave table in the database with all required fields.
    """

    id: int | None = Field(default=None, primary_key=True)
    employee_id: int = Field(index=True, nullable=False)
    leave_type: LeaveType = Field(default=LeaveType.CASUAL, nullable=False)
    start_date: datetime = Field(nullable=False)
    end_date: datetime = Field(nullable=False)
    reason: str = Field(max_length=500, nullable=True)
    status: LeaveStatus = Field(default=LeaveStatus.PENDING, nullable=False)
    approved_by: int | None = Field(nullable=True)
    rejection_reason: str | None = Field(max_length=500, nullable=True)
    created_at: datetime = Field(default_factory=datetime.now, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.now, nullable=False)
