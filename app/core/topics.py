"""
Kafka Topic Definitions for Leave Management Service.

Topic naming follows the pattern: <domain>-<event-type>
This makes topics easily identifiable and organized by business domain.
"""


class KafkaTopics:
    """
    Central registry of all Kafka topics used by the Leave Management Service.
    Topics are named following the pattern: <domain>-<event-type>
    """

    # Leave Request Events - Employee actions
    LEAVE_REQUESTED = "leave-requested"
    LEAVE_CANCELLED = "leave-cancelled"
    LEAVE_MODIFIED = "leave-modified"

    # Leave Decision Events - Manager/HR actions
    LEAVE_APPROVED = "leave-approved"
    LEAVE_REJECTED = "leave-rejected"
    LEAVE_REVOKED = "leave-revoked"

    # Leave Status Events
    LEAVE_STARTED = "leave-started"
    LEAVE_ENDED = "leave-ended"
    LEAVE_EXTENDED = "leave-extended"

    # Leave Balance Events
    LEAVE_BALANCE_UPDATED = "leave-balance-updated"
    LEAVE_BALANCE_RESET = "leave-balance-reset"
    LEAVE_ACCRUED = "leave-accrued"

    # Dashboard Metrics Events
    LEAVE_METRICS_TODAY = "leave-metrics-today"
    LEAVE_METRICS_UPDATED = "leave-metrics-updated"

    # Summary Events
    LEAVE_DAILY_SUMMARY = "leave-daily-summary"
    LEAVE_MONTHLY_SUMMARY = "leave-monthly-summary"

    # Notification Events - Triggers for notification service
    NOTIFICATION_LEAVE_PENDING = "notification-leave-pending"
    NOTIFICATION_LEAVE_APPROVED = "notification-leave-approved"
    NOTIFICATION_LEAVE_REJECTED = "notification-leave-rejected"
    NOTIFICATION_LEAVE_REMINDER = "notification-leave-reminder"

    # Audit Events - For audit service consumption
    AUDIT_LEAVE_ACTION = "audit-leave-action"

    # HR Events - For HR notifications
    HR_LEAVE_BALANCE_LOW = "hr-leave-balance-low"
    HR_EXCESSIVE_LEAVE = "hr-excessive-leave"

    @classmethod
    def all_topics(cls) -> list[str]:
        """Return list of all topic names."""
        return [
            value
            for name, value in vars(cls).items()
            if isinstance(value, str) and not name.startswith("_")
        ]

    @classmethod
    def leave_request_topics(cls) -> list[str]:
        """Return list of leave request topics."""
        return [
            cls.LEAVE_REQUESTED,
            cls.LEAVE_CANCELLED,
            cls.LEAVE_MODIFIED,
        ]

    @classmethod
    def leave_decision_topics(cls) -> list[str]:
        """Return list of leave decision topics."""
        return [
            cls.LEAVE_APPROVED,
            cls.LEAVE_REJECTED,
            cls.LEAVE_REVOKED,
        ]

    @classmethod
    def leave_status_topics(cls) -> list[str]:
        """Return list of leave status topics."""
        return [
            cls.LEAVE_STARTED,
            cls.LEAVE_ENDED,
            cls.LEAVE_EXTENDED,
        ]

    @classmethod
    def notification_topics(cls) -> list[str]:
        """Return list of notification-related topics."""
        return [
            cls.NOTIFICATION_LEAVE_PENDING,
            cls.NOTIFICATION_LEAVE_APPROVED,
            cls.NOTIFICATION_LEAVE_REJECTED,
            cls.NOTIFICATION_LEAVE_REMINDER,
        ]

    @classmethod
    def balance_topics(cls) -> list[str]:
        """Return list of leave balance topics."""
        return [
            cls.LEAVE_BALANCE_UPDATED,
            cls.LEAVE_BALANCE_RESET,
            cls.LEAVE_ACCRUED,
        ]
