"""
Leave Management Service - Employee Service Integration.
Handles communication with the Employee Service for employee validation and lookup.
Uses internal service-to-service endpoints (no authentication required).
"""

from typing import Any, Dict

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Cache for employee verification (simple in-memory cache)
_employee_cache: Dict[int, bool] = {}
_employee_data_cache: Dict[int, Dict[str, Any]] = {}
_email_to_employee_cache: Dict[str, Dict[str, Any]] = {}


def verify_employee_exists(employee_id: int) -> bool:
    """
    Verify that an employee exists via Employee Service.

    Integration Strategy:
    1. Check local cache first for performance
    2. Call Employee Service internal API if configured
    3. Return False if service unavailable or employee not found

    Args:
        employee_id: The ID of the employee to verify

    Returns:
        True if employee exists, False otherwise
    """
    # Check cache first
    if employee_id in _employee_cache:
        logger.debug(f"Employee {employee_id} found in cache")
        return _employee_cache[employee_id]

    # Call Employee Service internal API
    try:
        if not settings.EMPLOYEE_SERVICE_URL:
            logger.warning(
                f"EMPLOYEE_SERVICE_URL not configured, cannot verify employee {employee_id}"
            )
            return False

        result = _verify_via_employee_service(employee_id)
        _employee_cache[employee_id] = result
        return result

    except Exception as e:
        logger.error(f"Failed to verify employee {employee_id}: {e}")
        return False


def _verify_via_employee_service(employee_id: int) -> bool:
    """
    Verify employee existence by calling the Employee Service internal API.

    Args:
        employee_id: The ID of the employee to verify

    Returns:
        True if employee exists, False otherwise
    """
    try:
        employee_service_url = settings.EMPLOYEE_SERVICE_URL
        # Use internal endpoint (no authentication required)
        url = f"{employee_service_url}/api/v1/employees/internal/{employee_id}"

        with httpx.Client(timeout=settings.EMPLOYEE_SERVICE_TIMEOUT) as client:
            response = client.get(url)

            if response.status_code == 200:
                logger.info(f"Employee {employee_id} verified via Employee Service")
                return True
            elif response.status_code == 404:
                logger.info(f"Employee {employee_id} not found in Employee Service")
                return False
            else:
                logger.warning(
                    f"Employee Service returned status {response.status_code} "
                    f"for employee {employee_id}"
                )
                return False

    except httpx.ConnectError as e:
        logger.error(f"Failed to connect to Employee Service: {e}")
        return False
    except httpx.TimeoutException as e:
        logger.error(f"Employee Service request timed out: {e}")
        return False
    except Exception as e:
        logger.error(f"Error calling Employee Service: {e}")
        return False


def get_employee_by_id(employee_id: int) -> Dict[str, Any] | None:
    """
    Retrieve employee data by ID from Employee Service.

    Uses internal endpoint for service-to-service communication.

    Args:
        employee_id: The ID of the employee

    Returns:
        Employee data dict if found, None otherwise
    """
    # Check cache first
    if employee_id in _employee_data_cache:
        logger.debug(f"Employee {employee_id} data found in cache")
        return _employee_data_cache[employee_id]

    try:
        if not settings.EMPLOYEE_SERVICE_URL:
            logger.warning("EMPLOYEE_SERVICE_URL not configured")
            return None

        employee_service_url = settings.EMPLOYEE_SERVICE_URL
        # Use internal endpoint (no authentication required)
        url = f"{employee_service_url}/api/v1/employees/internal/{employee_id}"

        with httpx.Client(timeout=settings.EMPLOYEE_SERVICE_TIMEOUT) as client:
            response = client.get(url)

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Employee {employee_id} data retrieved successfully")
                # Cache the result
                _employee_data_cache[employee_id] = data
                return data
            elif response.status_code == 404:
                logger.info(f"Employee {employee_id} not found")
                return None
            else:
                logger.warning(
                    f"Employee Service returned status {response.status_code}"
                )
                return None

    except Exception as e:
        logger.error(f"Failed to get employee {employee_id}: {e}")
        return None


def get_employee_by_email(email: str) -> Dict[str, Any] | None:
    """
    Retrieve employee data by email address from Employee Service.

    Uses internal endpoint for service-to-service communication.
    This is critical for mapping JWT email claims to employee IDs.

    Args:
        email: The email address of the employee

    Returns:
        Employee data dict if found, None otherwise
    """
    # Check cache first
    if email in _email_to_employee_cache:
        logger.debug(f"Employee with email {email} found in cache")
        return _email_to_employee_cache[email]

    try:
        if not settings.EMPLOYEE_SERVICE_URL:
            logger.warning("EMPLOYEE_SERVICE_URL not configured")
            return None

        employee_service_url = settings.EMPLOYEE_SERVICE_URL
        # Use internal endpoint (no authentication required)
        url = f"{employee_service_url}/api/v1/employees/internal/by-email/{email}"

        with httpx.Client(timeout=settings.EMPLOYEE_SERVICE_TIMEOUT) as client:
            response = client.get(url)

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Employee with email {email} retrieved successfully")
                # Cache the result
                _email_to_employee_cache[email] = data
                # Also cache by ID for future lookups
                if "id" in data:
                    _employee_data_cache[data["id"]] = data
                return data
            elif response.status_code == 404:
                logger.info(f"Employee with email {email} not found")
                return None
            else:
                logger.warning(
                    f"Employee Service returned status {response.status_code}"
                )
                return None

    except Exception as e:
        logger.error(f"Failed to get employee by email {email}: {e}")
        return None


def get_employee_name(employee_id: int) -> str | None:
    """
    Retrieve the name of an employee by ID from Employee Service.

    This is a helper function for enriching leave data with employee information.

    Args:
        employee_id: The ID of the employee

    Returns:
        Employee name if found, None otherwise
    """
    employee = get_employee_by_id(employee_id)
    if employee:
        # Try different possible name fields
        return (
            employee.get("full_name")
            or employee.get("name")
            or f"{employee.get('first_name', '')} {employee.get('last_name', '')}".strip()
            or None
        )
    return None


def get_employee_manager(employee_id: int) -> int | None:
    """
    Retrieve the manager ID of an employee.

    Args:
        employee_id: The ID of the employee

    Returns:
        Manager's employee ID if found, None otherwise
    """
    employee = get_employee_by_id(employee_id)
    if employee:
        return employee.get("manager_id") or employee.get("reports_to")
    return None


def is_manager_of(manager_id: int, employee_id: int) -> bool:
    """
    Check if one employee is the manager of another.

    This is used for Team Manager approval workflows.

    Args:
        manager_id: The ID of the potential manager
        employee_id: The ID of the employee

    Returns:
        True if manager_id is the manager of employee_id
    """
    employee_manager_id = get_employee_manager(employee_id)
    if employee_manager_id:
        return employee_manager_id == manager_id
    return False


def list_team_members(manager_id: int) -> list[Dict[str, Any]]:
    """
    Get all employees who report to a specific manager.

    This is used for Team Manager leave approval workflows.

    Args:
        manager_id: The ID of the manager

    Returns:
        List of employee data dicts
    """
    try:
        if not settings.EMPLOYEE_SERVICE_URL:
            logger.warning("EMPLOYEE_SERVICE_URL not configured")
            return []

        employee_service_url = settings.EMPLOYEE_SERVICE_URL
        # Use internal list endpoint
        url = f"{employee_service_url}/api/v1/employees/internal/list"

        with httpx.Client(timeout=settings.EMPLOYEE_SERVICE_TIMEOUT) as client:
            response = client.get(url, params={"limit": 1000})

            if response.status_code == 200:
                all_employees = response.json()
                # Filter employees who report to this manager
                team_members = [
                    emp
                    for emp in all_employees
                    if emp.get("manager_id") == manager_id
                    or emp.get("reports_to") == manager_id
                ]
                logger.info(
                    f"Found {len(team_members)} team members for manager {manager_id}"
                )
                return team_members
            else:
                logger.warning(
                    f"Employee Service returned status {response.status_code}"
                )
                return []

    except Exception as e:
        logger.error(f"Failed to list team members for manager {manager_id}: {e}")
        return []


def clear_employee_cache():
    """
    Clear the employee verification and data caches.

    Useful for testing or when employee data has been updated.
    """
    global _employee_cache, _employee_data_cache, _email_to_employee_cache
    _employee_cache.clear()
    _employee_data_cache.clear()
    _email_to_employee_cache.clear()
    logger.info("Employee cache cleared")
