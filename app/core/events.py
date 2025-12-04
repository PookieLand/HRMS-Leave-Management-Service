services / leave - management - service / app / core / events.py
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    LEAVE_REQUESTED = "leave.requested"
    LEAVE_APPROVED = "leave.approved"
    LEAVE_REJECTED = "leave.rejected"
    LEAVE_CANCELLED = "leave.cancelled"


class EventMetadata(BaseModel):
    source_service: str = "leave-management-service"
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    causation_id: str | None = None
    user_id: str | None = None
    trace_id: str | None = None


class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    version: str = "1.0"
    data: dict[str, Any]
    metadata: EventMetadata


class LeaveRequestedEvent(BaseModel):
    leave_id: int
    employee_id: int
    leave_type: str
    start_date: str
    end_date: str
    reason: str | None


class LeaveApprovedEvent(BaseModel):
    leave_id: int
    employee_id: int
    approved_by: int
    approval_date: str


class LeaveRejectedEvent(BaseModel):
    leave_id: int
    employee_id: int
    rejected_by: int
    rejection_reason: str | None
    rejection_date: str


class LeaveCancelledEvent(BaseModel):
    leave_id: int
    employee_id: int
    cancelled_by: int
    cancellation_date: str
