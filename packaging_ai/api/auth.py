from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

from packaging_ai.config import API_KEYS


def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    """Validate X-API-Key against configured keys (constant-time)."""
    if not API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API keys not configured (set PACKAGING_AI_API_KEYS)",
        )
    provided = (x_api_key or "").strip()
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )
    for key in API_KEYS:
        if secrets.compare_digest(provided, key):
            return provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid X-API-Key",
    )
