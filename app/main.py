from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.leaves import router as leaves_router
from app.core.config import settings
from app.core.database import create_db_and_tables
from app.core.kafka import KafkaProducer
from app.core.logging import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup
    logger.info("Starting Leave Management Service...")
    logger.info("Creating database and tables...")
    create_db_and_tables()
    logger.info("Database and tables created successfully")

    logger.info("Initializing Kafka producer...")
    await KafkaProducer.start()
    logger.info("Kafka producer initialized successfully")

    logger.info("Leave Management Service startup complete")

    yield

    # Shutdown
    logger.info("Leave Management Service shutting down...")
    await KafkaProducer.stop()
    logger.info("Kafka producer stopped")


# Initialize FastAPI application
app = FastAPI(
    title="Leave Management Service",
    version=settings.APP_VERSION,
    lifespan=lifespan,
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


# Health check endpoint
@app.get("/", tags=["health"])
async def health_check():
    """
    Health check endpoint.
    Returns service status and basic information.
    """
    return {
        "status": "healthy",
        "service": "Leave Management Service",
        "version": settings.APP_VERSION,
    }
