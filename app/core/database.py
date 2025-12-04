"""
Database configuration and session management.
Handles database engine creation, session management, and table initialization.
"""

from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy import text
from typing import Generator

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def create_database() -> None:
    """
    Create the database if it doesn't exist.
    Connects to MySQL server without specifying a database.
    """
    temp_engine = create_engine(settings.database_url_without_db)

    try:
        with temp_engine.connect() as conn:
            _ = conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {settings.DB_NAME}"))
            conn.commit()
            logger.info(f"Database '{settings.DB_NAME}' ready")
    except Exception as e:
        logger.error(f"Failed to create database: {e}")
        raise
    finally:
        temp_engine.dispose()


def create_db_and_tables() -> None:
    """
    Create database and all tables defined in SQLModel.
    Called during application startup.
    """
    create_database()
    SQLModel.metadata.create_all(engine)
    logger.info("Database tables created successfully")


# Create the database engine
engine = create_engine(
    settings.database_url,
    echo=settings.DEBUG,  # Log SQL queries in debug mode
    pool_pre_ping=True,  # Verify connections before using them
    pool_recycle=3600,  # Recycle connections after 1 hour
)


def get_session() -> Generator[Session, None, None]:
    """
    Dependency that provides a database session.
    Automatically handles session lifecycle and cleanup.

    Yields:
        Session: SQLModel database session
    """
    with Session(engine) as session:
        yield session
