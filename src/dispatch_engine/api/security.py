"""API-key authentication. One shared key, compared in constant time.

Declared through fastapi.security so it shows up in OpenAPI (and the /docs
"Authorize" button) instead of being an undocumented header check. There is no
default key on purpose: a hardcoded fallback is a production backdoor, so an
unset API_KEY fails the app at startup (see create_app) rather than at the
first unauthenticated request.
"""

import hmac
import os
from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def expected_api_key() -> str | None:
    """The configured key, or None when the operator never set one."""
    return os.environ.get("API_KEY") or None


def require_api_key(presented: Annotated[str | None, Security(api_key_header)]) -> None:
    expected = expected_api_key()
    if expected is None:  # pragma: no cover - create_app refuses to start without it
        raise HTTPException(status_code=500, detail="API_KEY is not configured")
    if presented is None or not hmac.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing API key"
        )
