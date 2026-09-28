from app.config import settings
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def get_tenant_or_ip_key(request: Request) -> str:
    """Extract tenant organization ID if authenticated, else client IP address."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    if org_id and user_id:
        return f"org:{org_id}:user:{user_id}"
    return get_remote_address(request)


# Initialize SlowAPI rate limiter
limiter = Limiter(
    key_func=get_tenant_or_ip_key,
    default_limits=["120/minute"],
    storage_uri=settings.REDIS_URL,
    enabled=settings.ENVIRONMENT != "test",
)
