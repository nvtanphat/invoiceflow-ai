import hashlib
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.api.dependencies import create_access_token, get_db
from invoiceflow.config import Settings, get_settings
from invoiceflow.infrastructure.database.models import MembershipORM, UserORM

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    tenant_id: str
    role: str
    email: str


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    stmt = select(UserORM).where(UserORM.email == req.email, UserORM.is_active.is_(True))
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    # Verification: check password against sha256 or exact for demo
    hashed_input = hashlib.sha256(req.password.encode()).hexdigest()
    if user.hashed_password not in (hashed_input, req.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    # Fetch user tenant membership
    m_stmt = select(MembershipORM).where(MembershipORM.user_id == user.id)
    m_res = await session.execute(m_stmt)
    membership = m_res.scalar_one_or_none()
    tenant_id = membership.tenant_id if membership else "00000000-0000-0000-0000-000000000000"
    role = membership.role if membership else "viewer"

    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant_id,
        role=role,
        email=user.email,
        settings=settings,
    )

    return TokenResponse(
        access_token=token,
        user_id=user.id,
        tenant_id=tenant_id,
        role=role,
        email=user.email,
    )
