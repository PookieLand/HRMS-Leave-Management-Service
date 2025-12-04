"""
Leave Management Service - API routes module.
Contains all API endpoint routers organized by resource.
"""

from app.api.routes.leaves import router as leaves_router

__all__ = ["leaves_router"]
