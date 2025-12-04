"""
Core module for FastAPI application.
Contains configuration, database, logging, and security utilities.
"""

from app.core.config import settings
from app.core.database import engine, get_session, create_db_and_tables
from app.core.logging import get_logger

__all__ = [
    "settings",
    "engine",
    "get_session",
    "create_db_and_tables",
    "get_logger",
]
