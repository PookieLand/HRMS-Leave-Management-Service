"""
Event definitions for Leave Management Service.

Defines all event types and their data structures for Kafka publishing.
Events are categorized into:
- Leave request events (requested, cancelled, modified)
- Leave decision events (approved, rejected, revoked)
- Leave status events (started, ended)
- Leave balance events
- Audit events
"""

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """All event types produced by the Leave Management Service."""

    # Leave Request Events
    LEAVE_REQUESTED = "leave.requested"
    LEAVE_CANCELLED = "leave.cancelled"
    LEAVE_MODIFIED = "leave.modified"

    # Leave Decision Events
    LEAVE_APPROVED = "leave.approved"
    LEAVE_REJECTED = "leave.rejected"
    LEAVE_REVOKED = "leave.revoked"

    # Leave Status Events
    LEAVE_STARTED = "leave.started"
    LEAVE_ENDED = "leave.ended"
    LEAVE_EXTENDED = "leave.extended"

    # Leave Balance Events
    LEAVE_BALANCE_UPDATED = "leave.balance.updated"
    LEAVE_BALANCE_RESET = "leave.balance.reset"
    LEAVE_ACCRUED = "leave.accrued"

    # Dashboard Metrics Events
    LEAVE_METRICS_UPDATED = "leave.metrics.updated"

    # Notification Events
    NOTIFICATION_LEAVE_PENDING = "notification.leave.pending"
    NOTIFICATION_LEAVE_APPROVED = "notification.leave.approved"
    NOTIFICATION_LEAVE_REJECTED = "notification.leave.rejected"

    # Audit Events
    AUDIT_LEAVE_ACTION = "audit.leave.action"


class EventMetadata(BaseModel):
    """Metadata attached to every event for tracing and correlation."""

    source_service: str = "leave-management-service"
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    causation_id: Optional[str] = None
    actor_user_id: Optional[str] = None
    actor_role: Optional[str] = None
    trace_id: Optional[str] = None
    ip_address: Optional[str] = None


class EventEnvelope(BaseModel):
    """
    Standard envelope for all events.
    Provides consistent structure for Kafka messages.
    """

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    version: str = "1.0"
    data: dict[str, Any]
    metadata: EventMetadata = Field(default_factory=EventMetadata)


# Leave Request Event Data Models


class LeaveRequestedEvent(BaseModel):
    """Data for leave.requested event."""

    leave_id: int
    employee_id: int
    user_id: Optional[int] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    leave_type: str
    start_date: date
    end_date: date
    return_date: date  # Date employee returns to work
    total_days: int
    reason: Optional[str] = None
    department: Optional[str] = None
    manager_id: Optional[int] = None
    manager_email: Optional[str] = None
    is_half_day: bool = False
    half_day_type: Optional[str] = None  # 'morning' or 'afternoon'


class LeaveCancelledEvent(BaseModel):
    """Data for leave.cancelled event."""

    leave_id: int
    employee_id: int
    user_id: Optional[int] = None
    email: Optional[str] = None
    leave_type: str
    start_date: date
    end_date: date
    total_days: int
    cancelled_by: int
    cancellation_reason: Optional[str] = None
    cancellation_date: datetime


class LeaveModifiedEvent(BaseModel):
    """Data for leave.modified event."""

    leave_id: int
    employee_id: int
    user_id: Optional[int] = None
    email: Optional[str] = None
    leave_type: str
    old_start_date: date
    old_end_date: date
    new_start_date: date
    new_end_date: date
    old_total_days: int
    new_total_days: int
    modified_by: int
    modification_reason: Optional[str] = None


# Leave Decision Event Data Models


class LeaveApprovedEvent(BaseModel):
    """Data for leave.approved event."""

    leave_id: int
    employee_id: int
    user_id: Optional[int] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    leave_type: str
    start_date: date
    end_date: date
    return_date: date
    total_days: int
    approved_by: int
    approver_name: Optional[str] = None
    approver_role: Optional[str] = None
    approval_date: datetime
    approval_notes: Optional[str] = None
    department: Optional[str] = None


class LeaveRejectedEvent(BaseModel):
    """Data for leave.rejected event."""

    leave_id: int
    employee_id: int
    user_id: Optional[int] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    leave_type: str
    start_date: date
    end_date: date
    total_days: int
    rejected_by: int
    rejector_name: Optional[str] = None
    rejection_reason: str
    rejection_date: datetime
    department: Optional[str] = None


class LeaveRevokedEvent(BaseModel):
    """Data for leave.revoked event."""

    leave_id: int
    employee_id: int
    user_id: Optional[int] = None
    email: Optional[str] = None
    leave_type: str
    start_date: date
    end_date: date
    revoked_by: int
    revocation_reason: str
    revocation_date: datetime
    was_approved: bool = True


# Leave Status Event Data Models


class LeaveStartedEvent(BaseModel):
    """Data for leave.started event."""

    leave_id: int
    employee_id: int
    user_id: Optional[int] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    leave_type: str
    start_date: date
    end_date: date
    return_date: date
    total_days: int
    department: Optional[str] = None
    manager_id: Optional[int] = None


class LeaveEndedEvent(BaseModel):
    """Data for leave.ended event."""

    leave_id: int
    employee_id: int
    user_id: Optional[int] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    leave_type: str
    start_date: date
    end_date: date
    actual_end_date: date
    total_days_taken: int
    department: Optional[str] = None


class LeaveExtendedEvent(BaseModel):
    """Data for leave.extended event."""

    leave_id: int
    employee_id: int
    user_id: Optional[int] = None
    email: Optional[str] = None
    leave_type: str
    original_end_date: date
    new_end_date: date
    additional_days: int
    extension_reason: str
    approved_by: int
    approval_date: datetime


# Leave Balance Event Data Models


class LeaveBalanceUpdatedEvent(BaseModel):
    """Data for leave.balance.updated event."""

    employee_id: int
    user_id: Optional[int] = None
    email: Optional[str] = None
    leave_type: str
    previous_balance: float
    new_balance: float
    change_amount: float
    change_reason: str  # 'approved_leave', 'cancelled_leave', 'adjustment', 'accrual'
    year: int
    updated_by: Optional[int] = None


class LeaveBalanceResetEvent(BaseModel):
    """Data for leave.balance.reset event."""

    employee_id: int
    user_id: Optional[int] = None
    email: Optional[str] = None
    year: int
    balances: dict[str, float]  # leave_type: balance
    carried_forward: dict[str, float]  # leave_type: carried_forward_days
    reset_date: date
    reset_by: Optional[int] = None


class LeaveAccruedEvent(BaseModel):
    """Data for leave.accrued event."""

    employee_id: int
    user_id: Optional[int] = None
    email: Optional[str] = None
    leave_type: str
    accrued_days: float
    new_balance: float
    accrual_date: date
    accrual_period: str  # 'monthly', 'quarterly', 'yearly'


# Dashboard Metrics Event Data Model


class LeaveMetricsEvent(BaseModel):
    """Data for leave.metrics.updated event."""

    date: str
    timestamp: str
    total_employees: int
    on_leave_today: int
    pending_requests: int
    approved_this_month: int
    rejected_this_month: int
    leave_by_type: dict[str, int]  # leave_type: count
    department_breakdown: Optional[dict[str, dict[str, int]]] = None


# Notification Event Data Models


class LeaveNotificationPendingEvent(BaseModel):
    """Data for notification.leave.pending event - sent to managers."""

    leave_id: int
    employee_id: int
    employee_email: str
    employee_name: str
    leave_type: str
    start_date: date
    end_date: date
    total_days: int
    reason: Optional[str] = None
    manager_id: int
    manager_email: str
    manager_name: Optional[str] = None
    department: Optional[str] = None


class LeaveNotificationApprovedEvent(BaseModel):
    """Data for notification.leave.approved event - sent to employee."""

    leave_id: int
    employee_id: int
    employee_email: str
    employee_name: str
    leave_type: str
    start_date: date
    end_date: date
    total_days: int
    approved_by_name: str
    approval_notes: Optional[str] = None


class LeaveNotificationRejectedEvent(BaseModel):
    """Data for notification.leave.rejected event - sent to employee."""

    leave_id: int
    employee_id: int
    employee_email: str
    employee_name: str
    leave_type: str
    start_date: date
    end_date: date
    total_days: int
    rejected_by_name: str
    rejection_reason: str


# Audit Event Data Model


class AuditLeaveActionEvent(BaseModel):
    """Data for audit.leave.action event."""

    actor_user_id: int
    actor_email: str
    actor_role: str
    action: str  # request, approve, reject, cancel, modify, revoke
    resource_type: str = "leave"
    resource_id: int
    employee_id: int
    leave_type: str
    description: str
    old_value: Optional[dict[str, Any]] = None
    new_value: Optional[dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


# Helper functions for creating events


def create_event(
    event_type: EventType,
    data: BaseModel,
    actor_user_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> EventEnvelope:
    """
    Helper function to create an event envelope with proper metadata.

    Args:
        event_type: Type of the event
        data: Event data as a Pydantic model
        actor_user_id: ID of the user performing the action
        actor_role: Role of the user performing the action
        correlation_id: Optional correlation ID for tracing

    Returns:
        EventEnvelope ready for publishing
    """
    metadata = EventMetadata(
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        correlation_id=correlation_id or str(uuid4()),
    )

    return EventEnvelope(
        event_type=event_type,
        data=data.model_dump(mode="json"),
        metadata=metadata,
    )


def calculate_leave_days(start_date: date, end_date: date) -> int:
    """
    Calculate the number of leave days between two dates.

    Args:
        start_date: Leave start date
        end_date: Leave end date

    Returns:
        Number of days (inclusive)
    """
    if end_date < start_date:
        return 0
    return (end_date - start_date).days + 1


def calculate_return_date(end_date: date) -> date:
    """
    Calculate the return to work date (day after leave ends).

    Args:
        end_date: Leave end date

    Returns:
        Return to work date
    """
    from datetime import timedelta

    return end_date + timedelta(days=1)
