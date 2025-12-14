"""
Leave Management Service - Main Application Entry Point.

This service handles employee leave management including:
- Leave request submission and tracking
- Manager approval workflows
- Leave balance tracking
- Dashboard metrics with Redis caching
- Kafka event publishing for audit and notifications
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.debug import router as debug_router
from app.api.routes.leaves import router as leaves_router
from app.core.cache import RedisClient
from app.core.config import settings
from app.core.database import create_db_and_tables
from app.core.kafka import KafkaConsumer, KafkaProducer
from app.core.logging import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting Leave Management Service...")

    logger.info("Creating database and tables...")
    create_db_and_tables()
    logger.info("Database and tables created successfully")

    logger.info("Initializing Redis client...")
    try:
        RedisClient.get_client()
        if RedisClient.ping():
            logger.info("Redis client connected successfully")
        else:
            logger.warning("Redis connection failed, caching will be disabled")
    except Exception as e:
        logger.warning(f"Failed to initialize Redis: {e}")

    logger.info("Initializing Kafka producer...")
    await KafkaProducer.start()
    logger.info("Kafka producer initialized")

    # Start Kafka consumer if there are handlers registered
    logger.info("Starting Kafka consumer...")
    await KafkaConsumer.start()
    logger.info("Kafka consumer started")

    logger.info("Leave Management Service startup complete")

    yield

    # Shutdown
    logger.info("Leave Management Service shutting down...")

    logger.info("Stopping Kafka consumer...")
    await KafkaConsumer.stop()
    logger.info("Kafka consumer stopped")

    logger.info("Stopping Kafka producer...")
    await KafkaProducer.stop()
    logger.info("Kafka producer stopped")

    logger.info("Closing Redis client...")
    RedisClient.close()
    logger.info("Redis client closed")

    logger.info("Leave Management Service shutdown complete")


# Initialize FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Leave Management Service for HRMS - Handles leave requests, approvals, and balance tracking",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)


# Include routers
app.include_router(leaves_router, prefix="/api/v1")
app.include_router(debug_router, prefix="/api/v1")


# Health check endpoint
@app.get("/health", tags=["health"])
async def health_check():
    """
    Health check endpoint for container orchestration and monitoring.
    """
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@app.get("/ready", tags=["health"])
async def readiness_check():
    """
    Readiness check endpoint for Kubernetes.
    Verifies that the service is ready to accept traffic.
    """
    # Check Redis connection
    redis_ready = False
    try:
        redis_ready = RedisClient.ping()
    except Exception:
        pass

    # Check Kafka producer
    kafka_ready = KafkaProducer._started

    all_ready = redis_ready and kafka_ready

    return {
        "status": "ready" if all_ready else "not_ready",
        "checks": {
            "redis": "ok" if redis_ready else "error",
            "kafka_producer": "ok" if kafka_ready else "error",
        },
    }


@app.get("/", tags=["root"])
async def root():
    """
    Root endpoint with service information.
    """
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
    }
