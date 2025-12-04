"""
Security module for JWT authentication using JWKS endpoint.
Implements token validation, role/permission extraction for Asgardeo.
"""

import json
from datetime import datetime, timedelta
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# HTTP Bearer scheme for JWT tokens
security = HTTPBearer()

# JWKS client for fetching and caching public keys
jwks_client = PyJWKClient(
    uri=settings.jwks_url,
    cache_keys=True,
    max_cached_keys=16,
)


class TokenData(BaseModel):
    """
    Decoded token data structure.
    Contains user information, roles, and permissions from JWT.
    """

    sub: str  # Subject (user ID)
    username: str | None = None
    email: str | None = None
    roles: list[str] = []
    permissions: list[str] = []
    groups: list[str] = []
    iss: str | None = None  # Issuer
    aud: str | list[str] | None = None  # Audience
    exp: int | None = None  # Expiration
    iat: int | None = None  # Issued at
    raw_claims: dict[str, Any] = {}  # All other claims


def decode_token(token: str) -> TokenData:
    """
    Decode and validate JWT token using JWKS endpoint.

    Args:
        token: JWT token string

    Returns:
        TokenData with decoded information

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        # Get the signing key from JWKS
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Prepare decode options
        decode_options = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_iat": True,
            "verify_aud": settings.JWT_AUDIENCE is not None,
            "verify_iss": settings.JWT_ISSUER is not None,
        }

        # Decode and validate the token with optional audience and issuer
        if settings.JWT_AUDIENCE and settings.JWT_ISSUER:
            # Validate both audience and issuer
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.JWT_AUDIENCE,
                issuer=settings.JWT_ISSUER,
                options=decode_options,
            )
        elif settings.JWT_AUDIENCE:
            # Validate only audience
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.JWT_AUDIENCE,
                options=decode_options,
            )
        elif settings.JWT_ISSUER:
            # Validate only issuer
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=settings.JWT_ISSUER,
                options=decode_options,
            )
        else:
            # No audience or issuer validation
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options=decode_options,
            )

        logger.info(f"Token decoded successfully for subject: {payload.get('sub')}")

        # Extract roles from various possible claim locations
        roles = []
        if "roles" in payload:
            roles = (
                payload["roles"]
                if isinstance(payload["roles"], list)
                else [payload["roles"]]
            )
        elif "role" in payload:
            roles = (
                payload["role"]
                if isinstance(payload["role"], list)
                else [payload["role"]]
            )
        elif "groups" in payload:
            # Sometimes roles are in groups
            groups = (
                payload["groups"]
                if isinstance(payload["groups"], list)
                else [payload["groups"]]
            )
            roles = [g for g in groups if not g.startswith("/")]

        # Extract permissions
        permissions = []
        if "permissions" in payload:
            permissions = (
                payload["permissions"]
                if isinstance(payload["permissions"], list)
                else [payload["permissions"]]
            )
        elif "scope" in payload:
            # OAuth2 scopes as permissions
            scopes = payload["scope"]
            permissions = scopes.split() if isinstance(scopes, str) else scopes

        # Extract groups
        groups = []
        if "groups" in payload:
            groups = (
                payload["groups"]
                if isinstance(payload["groups"], list)
                else [payload["groups"]]
            )

        # Create TokenData object
        token_data = TokenData(
            sub=payload.get("sub", ""),
            username=payload.get("username") or payload.get("preferred_username"),
            email=payload.get("email"),
            roles=roles,
            permissions=permissions,
            groups=groups,
            iss=payload.get("iss"),
            aud=payload.get("aud"),
            exp=payload.get("exp"),
            iat=payload.get("iat"),
            raw_claims=payload,
        )

        return token_data

    except jwt.ExpiredSignatureError:
        logger.warning("Token has expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        logger.error(f"Error decoding token: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> TokenData:
    """
    Dependency to get the current authenticated user from JWT token.

    Usage:
        @app.get("/protected")
        def protected_route(user: Annotated[TokenData, Depends(get_current_user)]):
            return {"username": user.username}

    Args:
        credentials: HTTP Authorization credentials (Bearer token)

    Returns:
        TokenData with user information

    Raises:
        HTTPException: 401 if authentication fails
    """
    token = credentials.credentials
    return decode_token(token)


async def get_current_active_user(
    current_user: Annotated[TokenData, Depends(get_current_user)],
) -> TokenData:
    """
    Dependency to ensure the current user is active.
    Can be extended to check user status in database.

    Args:
        current_user: Current user from get_current_user dependency

    Returns:
        Active user TokenData
    """
    # Future: Check if user is active in database
    # For now, if token is valid, user is active
    return current_user


def require_role(*required_roles: str):
    """
    Dependency factory to require specific roles.

    Usage:
        @app.delete("/admin/users/{user_id}")
        def delete_user(
            user_id: int,
            user: Annotated[TokenData, Depends(require_role("admin", "superuser"))]
        ):
            # Only users with admin OR superuser role can access
            pass

    Args:
        *required_roles: One or more required roles (user needs at least one)

    Returns:
        Dependency function that validates roles
    """

    async def check_roles(
        current_user: Annotated[TokenData, Depends(get_current_active_user)],
    ) -> TokenData:
        user_roles = set(current_user.roles)
        required = set(required_roles)

        if not user_roles.intersection(required):
            logger.warning(
                f"User {current_user.sub} lacks required roles. "
                f"Has: {user_roles}, Required: {required}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {', '.join(required_roles)}",
            )

        return current_user

    return check_roles


def require_permission(*required_permissions: str):
    """
    Dependency factory to require specific permissions.

    Usage:
        @app.post("/employees/")
        def create_employee(
            employee: EmployeeCreate,
            user: Annotated[TokenData, Depends(require_permission("employees:create"))]
        ):
            # Only users with employees:create permission can access
            pass

    Args:
        *required_permissions: One or more required permissions (user needs at least one)

    Returns:
        Dependency function that validates permissions
    """

    async def check_permissions(
        current_user: Annotated[TokenData, Depends(get_current_active_user)],
    ) -> TokenData:
        user_perms = set(current_user.permissions)
        required = set(required_permissions)

        if not user_perms.intersection(required):
            logger.warning(
                f"User {current_user.sub} lacks required permissions. "
                f"Has: {user_perms}, Required: {required}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {', '.join(required_permissions)}",
            )

        return current_user

    return check_permissions


def require_all_roles(*required_roles: str):
    """
    Dependency factory to require ALL specified roles.

    Args:
        *required_roles: All roles that user must have

    Returns:
        Dependency function that validates user has all roles
    """

    async def check_all_roles(
        current_user: Annotated[TokenData, Depends(get_current_active_user)],
    ) -> TokenData:
        user_roles = set(current_user.roles)
        required = set(required_roles)

        if not required.issubset(user_roles):
            missing = required - user_roles
            logger.warning(f"User {current_user.sub} missing required roles: {missing}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required roles: {', '.join(missing)}",
            )

        return current_user

    return check_all_roles


# Type aliases for common dependencies
CurrentUser = Annotated[TokenData, Depends(get_current_user)]
CurrentActiveUser = Annotated[TokenData, Depends(get_current_active_user)]
