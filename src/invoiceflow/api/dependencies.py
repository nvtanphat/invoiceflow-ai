from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional
import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.config import Settings, get_settings
from invoiceflow.infrastructure.database.models import MembershipORM, UserORM
from invoiceflow.infrastructure.database.session import DatabaseSessionManager
from invoiceflow.infrastructure.storage.service import LocalStorageService, StoragePort

security = HTTPBearer()

_db_manager: Optional[DatabaseSessionManager] = None
_storage: Optional[StoragePort] = None


def set_global_dependencies(db_manager: DatabaseSessionManager, storage: StoragePort) -> None:
    global _db_manager, _storage
    _db_manager = db_manager
    _storage = storage


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    global _db_manager
    if _db_manager is None:
        settings = get_settings()
        _db_manager = DatabaseSessionManager(settings.DATABASE_URL)
    async with _db_manager.session() as session:
        yield session


def get_storage() -> StoragePort:
    global _storage
    if _storage is None:
        settings = get_settings()
        _storage = LocalStorageService(settings.LOCAL_STORAGE_DIR)
    return _storage


class AuthenticatedContext:
    def __init__(self, user_id: str, tenant_id: str, role: str, email: str):
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.role = role
        self.email = email


def create_access_token(
    user_id: str,
    tenant_id: str,
    role: str,
    email: str,
    settings: Settings,
) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "email": email,
        "exp": expires,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def get_current_context(
    credentials: HTTPAuthorizationCredentials = Security(security),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedContext:
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return AuthenticatedContext(
            user_id=payload["sub"],
            tenant_id=payload["tenant_id"],
            role=payload.get("role", "viewer"),
            email=payload.get("email", ""),
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_role(allowed_roles: list[str]):
    async def role_checker(ctx: AuthenticatedContext = Depends(get_current_context)):
        if ctx.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted for role '{ctx.role}'. Required: {allowed_roles}",
            )
        return ctx

    return role_checker
