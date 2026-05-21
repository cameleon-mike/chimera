"""Bearer-token authentication for state-changing endpoints.

The token is loaded from `scraper.env::BRIDGE_AUTH_TOKEN` (never hardcoded).
The HTTPBearer scheme is registered with FastAPI so cameleon can discover
the auth requirement via /openapi.json.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings

bearer_scheme = HTTPBearer(auto_error=False, description="Token from scraper.env::BRIDGE_AUTH_TOKEN.")


async def require_bearer(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    settings = get_settings()
    # Constant-time comparison defeats timing-based token enumeration.
    if not hmac.compare_digest(credentials.credentials, settings.bridge_auth_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials
