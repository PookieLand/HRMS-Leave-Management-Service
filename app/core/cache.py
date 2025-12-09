"""
Redis cache module for Leave Management Service.

Provides caching utilities for:
- Dashboard metrics (leave counts, pending requests)
- Employee leave records
- Leave balances
- Today's leave status
- Approved/pending leave lists

All cached data has TTL to ensure freshness while reducing database load.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

import redis
from redis import Redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


# Cache TTL constants (in seconds)
CACHE_TTL_SHORT = 60  # 1 minute - for rapidly changing data
CACHE_TTL_MEDIUM = 300  # 5 minutes - for dashboard metrics
CACHE_TTL_LONG = 3600  # 1 hour - for summary data
CACHE_TTL_DAY = 86400  # 24 hours - for historical data


class CacheKeys:
    """Centralized cache key definitions for consistency."""

    # Dashboard metrics
    DASHBOARD_METRICS_TODAY = "leave:dashboard:metrics:today"
    DASHBOARD_METRICS_PREFIX = "leave:dashboard:metrics"

    # Today's leave status
    TODAY_ON_LEAVE = "leave:today:on_leave"
    TODAY_STARTING = "leave:today:starting"
    TODAY_ENDING = "leave:today:ending"

    # Pending leaves (for managers)
    PENDING_LEAVES_PREFIX = "leave:pending"
    PENDING_LEAVES_MANAGER_PREFIX = "leave:pending:manager"
    PENDING_LEAVES_DEPARTMENT_PREFIX = "leave:pending:department"

    # Employee-specific
    EMPLOYEE_LEAVES_PREFIX = "leave:employee"
    EMPLOYEE_BALANCE_PREFIX = "leave:balance"
    EMPLOYEE_PENDING_PREFIX = "leave:employee:pending"
    EMPLOYEE_HISTORY_PREFIX = "leave:employee:history"

    # Summary data
    MONTHLY_SUMMARY_PREFIX = "leave:summary:monthly"
    YEARLY_SUMMARY_PREFIX = "leave:summary:yearly"
    DEPARTMENT_SUMMARY_PREFIX = "leave:summary:department"

    # Leave type counts
    LEAVE_TYPE_COUNT_PREFIX = "leave:type:count"


class RedisClient:
    """Singleton Redis client manager."""

    _instance: Optional[Redis] = None

    @classmethod
    def get_client(cls) -> Redis:
        """Get or create Redis client instance."""
        if cls._instance is None:
            cls._instance = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
                db=settings.REDIS_DB,
                decode_responses=True,
            )
            logger.info(
                f"Redis client connected to {settings.REDIS_HOST}:{settings.REDIS_PORT}"
            )
        return cls._instance

    @classmethod
    def close(cls):
        """Close Redis connection."""
        if cls._instance:
            cls._instance.close()
            cls._instance = None
            logger.info("Redis client closed")

    @classmethod
    def ping(cls) -> bool:
        """Check if Redis is reachable."""
        try:
            client = cls.get_client()
            return client.ping()
        except Exception as e:
            logger.error(f"Redis ping failed: {e}")
            return False


def json_serializer(obj: Any) -> Any:
    """Custom JSON serializer for complex types."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def get_cache_key(prefix: str, identifier: str | int) -> str:
    """
    Generate a cache key from prefix and identifier.

    Args:
        prefix: Key prefix (e.g., 'leave:employee')
        identifier: Unique identifier (e.g., employee_id, date)

    Returns:
        Complete cache key string
    """
    return f"{prefix}:{identifier}"


def get_from_cache(key: str) -> Optional[Any]:
    """
    Retrieve data from Redis cache.

    Args:
        key: Cache key

    Returns:
        Cached data or None if not found/error
    """
    try:
        client = RedisClient.get_client()
        data = client.get(key)
        if data:
            return json.loads(data)
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Cache JSON decode error for key {key}: {e}")
        return None
    except Exception as e:
        logger.error(f"Cache get error for key {key}: {e}")
        return None


def set_to_cache(key: str, value: Any, ttl: int = CACHE_TTL_MEDIUM) -> bool:
    """
    Store data in Redis cache with TTL.

    Args:
        key: Cache key
        value: Data to cache (will be JSON serialized)
        ttl: Time-to-live in seconds

    Returns:
        True if successful, False otherwise
    """
    try:
        client = RedisClient.get_client()
        serialized = json.dumps(value, default=json_serializer)
        client.setex(key, ttl, serialized)
        return True
    except Exception as e:
        logger.error(f"Cache set error for key {key}: {e}")
        return False


def delete_from_cache(key: str) -> bool:
    """
    Delete a specific key from cache.

    Args:
        key: Cache key to delete

    Returns:
        True if successful, False otherwise
    """
    try:
        client = RedisClient.get_client()
        client.delete(key)
        return True
    except Exception as e:
        logger.error(f"Cache delete error for key {key}: {e}")
        return False


def clear_cache_pattern(pattern: str) -> bool:
    """
    Delete all keys matching a pattern.

    Args:
        pattern: Key pattern with wildcards (e.g., 'leave:employee:*')

    Returns:
        True if successful, False otherwise
    """
    try:
        client = RedisClient.get_client()
        keys = client.keys(pattern)
        if keys:
            client.delete(*keys)
            logger.debug(f"Cleared {len(keys)} keys matching pattern: {pattern}")
        return True
    except Exception as e:
        logger.error(f"Cache clear pattern error for {pattern}: {e}")
        return False


def increment_counter(key: str, amount: int = 1, ttl: Optional[int] = None) -> int:
    """
    Increment a counter in cache.

    Args:
        key: Counter key
        amount: Amount to increment by
        ttl: Optional TTL to set if key doesn't exist

    Returns:
        New counter value
    """
    try:
        client = RedisClient.get_client()
        value = client.incrby(key, amount)
        if ttl and value == amount:  # First increment, set TTL
            client.expire(key, ttl)
        return value
    except Exception as e:
        logger.error(f"Counter increment error for key {key}: {e}")
        return 0


def decrement_counter(key: str, amount: int = 1) -> int:
    """
    Decrement a counter in cache.

    Args:
        key: Counter key
        amount: Amount to decrement by

    Returns:
        New counter value
    """
    try:
        client = RedisClient.get_client()
        return client.decrby(key, amount)
    except Exception as e:
        logger.error(f"Counter decrement error for key {key}: {e}")
        return 0


def add_to_set(key: str, *values: str, ttl: Optional[int] = None) -> int:
    """
    Add values to a Redis set.

    Args:
        key: Set key
        values: Values to add
        ttl: Optional TTL for the set

    Returns:
        Number of elements added
    """
    try:
        client = RedisClient.get_client()
        added = client.sadd(key, *values)
        if ttl:
            client.expire(key, ttl)
        return added
    except Exception as e:
        logger.error(f"Set add error for key {key}: {e}")
        return 0


def remove_from_set(key: str, *values: str) -> int:
    """
    Remove values from a Redis set.

    Args:
        key: Set key
        values: Values to remove

    Returns:
        Number of elements removed
    """
    try:
        client = RedisClient.get_client()
        return client.srem(key, *values)
    except Exception as e:
        logger.error(f"Set remove error for key {key}: {e}")
        return 0


def get_set_members(key: str) -> set:
    """
    Get all members of a Redis set.

    Args:
        key: Set key

    Returns:
        Set of members
    """
    try:
        client = RedisClient.get_client()
        return client.smembers(key)
    except Exception as e:
        logger.error(f"Set get members error for key {key}: {e}")
        return set()


def set_count(key: str) -> int:
    """
    Get the count of members in a Redis set.

    Args:
        key: Set key

    Returns:
        Number of members
    """
    try:
        client = RedisClient.get_client()
        return client.scard(key)
    except Exception as e:
        logger.error(f"Set count error for key {key}: {e}")
        return 0


# Dashboard Metrics Cache Functions


def cache_dashboard_metrics(metrics: dict, date_str: Optional[str] = None) -> bool:
    """
    Cache dashboard metrics for a specific date.

    Args:
        metrics: Dictionary of dashboard metrics
        date_str: Date string (YYYY-MM-DD), defaults to today

    Returns:
        True if successful
    """
    if not date_str:
        date_str = datetime.now().date().isoformat()

    key = f"{CacheKeys.DASHBOARD_METRICS_PREFIX}:{date_str}"
    return set_to_cache(key, metrics, ttl=CACHE_TTL_MEDIUM)


def get_dashboard_metrics(date_str: Optional[str] = None) -> Optional[dict]:
    """
    Get cached dashboard metrics for a specific date.

    Args:
        date_str: Date string (YYYY-MM-DD), defaults to today

    Returns:
        Cached metrics or None
    """
    if not date_str:
        date_str = datetime.now().date().isoformat()

    key = f"{CacheKeys.DASHBOARD_METRICS_PREFIX}:{date_str}"
    return get_from_cache(key)


def invalidate_dashboard_metrics(date_str: Optional[str] = None) -> bool:
    """
    Invalidate dashboard metrics cache for a specific date.

    Args:
        date_str: Date string (YYYY-MM-DD), defaults to today

    Returns:
        True if successful
    """
    if not date_str:
        date_str = datetime.now().date().isoformat()

    key = f"{CacheKeys.DASHBOARD_METRICS_PREFIX}:{date_str}"
    return delete_from_cache(key)


# Employee Leave Cache Functions


def cache_employee_leaves(
    employee_id: int, leaves_data: list, ttl: int = CACHE_TTL_MEDIUM
) -> bool:
    """
    Cache an employee's leave records.

    Args:
        employee_id: Employee ID
        leaves_data: List of leave records
        ttl: Cache TTL

    Returns:
        True if successful
    """
    key = f"{CacheKeys.EMPLOYEE_LEAVES_PREFIX}:{employee_id}"
    return set_to_cache(key, leaves_data, ttl=ttl)


def get_employee_leaves(employee_id: int) -> Optional[list]:
    """
    Get cached leave records for an employee.

    Args:
        employee_id: Employee ID

    Returns:
        Cached leave data or None
    """
    key = f"{CacheKeys.EMPLOYEE_LEAVES_PREFIX}:{employee_id}"
    return get_from_cache(key)


def invalidate_employee_leaves(employee_id: int) -> bool:
    """
    Invalidate all leave cache for an employee.

    Args:
        employee_id: Employee ID

    Returns:
        True if successful
    """
    patterns = [
        f"{CacheKeys.EMPLOYEE_LEAVES_PREFIX}:{employee_id}",
        f"{CacheKeys.EMPLOYEE_BALANCE_PREFIX}:{employee_id}:*",
        f"{CacheKeys.EMPLOYEE_PENDING_PREFIX}:{employee_id}",
        f"{CacheKeys.EMPLOYEE_HISTORY_PREFIX}:{employee_id}:*",
    ]
    for pattern in patterns:
        if "*" in pattern:
            clear_cache_pattern(pattern)
        else:
            delete_from_cache(pattern)
    return True


# Leave Balance Cache Functions


def cache_leave_balance(employee_id: int, year: int, balances: dict) -> bool:
    """
    Cache leave balance for an employee.

    Args:
        employee_id: Employee ID
        year: Year for the balance
        balances: Dictionary of leave_type: balance

    Returns:
        True if successful
    """
    key = f"{CacheKeys.EMPLOYEE_BALANCE_PREFIX}:{employee_id}:{year}"
    return set_to_cache(key, balances, ttl=CACHE_TTL_LONG)


def get_leave_balance(employee_id: int, year: int) -> Optional[dict]:
    """
    Get cached leave balance for an employee.

    Args:
        employee_id: Employee ID
        year: Year for the balance

    Returns:
        Cached balance data or None
    """
    key = f"{CacheKeys.EMPLOYEE_BALANCE_PREFIX}:{employee_id}:{year}"
    return get_from_cache(key)


def invalidate_leave_balance(employee_id: int, year: Optional[int] = None) -> bool:
    """
    Invalidate leave balance cache.

    Args:
        employee_id: Employee ID
        year: Specific year or None for all years

    Returns:
        True if successful
    """
    if year:
        key = f"{CacheKeys.EMPLOYEE_BALANCE_PREFIX}:{employee_id}:{year}"
        return delete_from_cache(key)
    else:
        pattern = f"{CacheKeys.EMPLOYEE_BALANCE_PREFIX}:{employee_id}:*"
        return clear_cache_pattern(pattern)


# Pending Leaves Cache Functions


def cache_pending_leaves_for_manager(manager_id: int, leaves_data: list) -> bool:
    """
    Cache pending leave requests for a manager to review.

    Args:
        manager_id: Manager's employee ID
        leaves_data: List of pending leave requests

    Returns:
        True if successful
    """
    key = f"{CacheKeys.PENDING_LEAVES_MANAGER_PREFIX}:{manager_id}"
    return set_to_cache(key, leaves_data, ttl=CACHE_TTL_SHORT)


def get_pending_leaves_for_manager(manager_id: int) -> Optional[list]:
    """
    Get cached pending leave requests for a manager.

    Args:
        manager_id: Manager's employee ID

    Returns:
        Cached pending leaves or None
    """
    key = f"{CacheKeys.PENDING_LEAVES_MANAGER_PREFIX}:{manager_id}"
    return get_from_cache(key)


def invalidate_pending_leaves(manager_id: Optional[int] = None) -> bool:
    """
    Invalidate pending leaves cache.

    Args:
        manager_id: Specific manager ID or None for all

    Returns:
        True if successful
    """
    if manager_id:
        key = f"{CacheKeys.PENDING_LEAVES_MANAGER_PREFIX}:{manager_id}"
        return delete_from_cache(key)
    else:
        return clear_cache_pattern(f"{CacheKeys.PENDING_LEAVES_MANAGER_PREFIX}:*")


# Today's Leave Tracking


def track_on_leave_today(employee_id: int) -> bool:
    """
    Track that an employee is on leave today.

    Args:
        employee_id: Employee ID

    Returns:
        True if successful
    """
    today = datetime.now().date().isoformat()
    key = f"{CacheKeys.TODAY_ON_LEAVE}:{today}"
    add_to_set(key, str(employee_id), ttl=CACHE_TTL_DAY)
    invalidate_dashboard_metrics()
    return True


def remove_on_leave_today(employee_id: int) -> bool:
    """
    Remove an employee from today's on-leave list.

    Args:
        employee_id: Employee ID

    Returns:
        True if successful
    """
    today = datetime.now().date().isoformat()
    key = f"{CacheKeys.TODAY_ON_LEAVE}:{today}"
    remove_from_set(key, str(employee_id))
    invalidate_dashboard_metrics()
    return True


def get_on_leave_count_today() -> int:
    """Get the count of employees on leave today."""
    today = datetime.now().date().isoformat()
    key = f"{CacheKeys.TODAY_ON_LEAVE}:{today}"
    return set_count(key)


def get_on_leave_today() -> set:
    """Get the set of employee IDs on leave today."""
    today = datetime.now().date().isoformat()
    key = f"{CacheKeys.TODAY_ON_LEAVE}:{today}"
    return get_set_members(key)


# Summary Cache Functions


def cache_monthly_summary(year: int, month: int, summary: dict) -> bool:
    """
    Cache monthly leave summary.

    Args:
        year: Year
        month: Month (1-12)
        summary: Summary data

    Returns:
        True if successful
    """
    key = f"{CacheKeys.MONTHLY_SUMMARY_PREFIX}:{year}:{month:02d}"
    return set_to_cache(key, summary, ttl=CACHE_TTL_LONG)


def get_monthly_summary(year: int, month: int) -> Optional[dict]:
    """
    Get cached monthly leave summary.

    Args:
        year: Year
        month: Month (1-12)

    Returns:
        Cached summary or None
    """
    key = f"{CacheKeys.MONTHLY_SUMMARY_PREFIX}:{year}:{month:02d}"
    return get_from_cache(key)


def invalidate_monthly_summary(year: int, month: int) -> bool:
    """
    Invalidate monthly summary cache.

    Args:
        year: Year
        month: Month (1-12)

    Returns:
        True if successful
    """
    key = f"{CacheKeys.MONTHLY_SUMMARY_PREFIX}:{year}:{month:02d}"
    return delete_from_cache(key)
