"""Operator-side creation of tenants and users.

There is no self sign-up: every account is created by an operator, so a fresh
deployment needs this use case to get its first administrator.
"""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from invoiceflow.infrastructure.database.models import MembershipORM, TenantORM, UserORM
from invoiceflow.infrastructure.security.password import hash_password

ROLES = frozenset({"admin", "accountant", "reviewer", "viewer"})
MIN_PASSWORD_LENGTH = 12


class ProvisioningError(ValueError):
    pass


@dataclass(frozen=True)
class ProvisionedUser:
    tenant_id: str
    user_id: str
    email: str
    role: str


async def provision_user(
    session: AsyncSession,
    email: str,
    full_name: str,
    password: str,
    role: str,
    tenant_id: Optional[str] = None,
    tenant_name: Optional[str] = None,
) -> ProvisionedUser:
    """Creates a user with one tenant membership; creates the tenant when only a name is given."""
    normalized_email = email.strip().lower()
    _validate(normalized_email, full_name, password, role)

    existing = await session.execute(
        select(UserORM.id).where(func.lower(UserORM.email) == normalized_email)
    )
    if existing.first() is not None:
        raise ProvisioningError(f"A user with email {normalized_email} already exists.")

    tenant = await _resolve_tenant(session, tenant_id, tenant_name)
    user = UserORM(
        email=normalized_email,
        hashed_password=hash_password(password),
        full_name=full_name.strip(),
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(MembershipORM(tenant_id=tenant.id, user_id=user.id, role=role))
    await session.flush()
    return ProvisionedUser(tenant_id=tenant.id, user_id=user.id, email=normalized_email, role=role)


def _validate(email: str, full_name: str, password: str, role: str) -> None:
    if role not in ROLES:
        raise ProvisioningError(f"Unknown role '{role}'; expected one of {sorted(ROLES)}.")
    if "@" not in email:
        raise ProvisioningError("A valid email is required.")
    if not full_name.strip():
        raise ProvisioningError("A full name is required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ProvisioningError(
            f"The password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )


async def _resolve_tenant(
    session: AsyncSession, tenant_id: Optional[str], tenant_name: Optional[str]
) -> TenantORM:
    if tenant_id:
        tenant = await session.get(TenantORM, tenant_id)
        if tenant is None:
            raise ProvisioningError(f"Unknown tenant id {tenant_id}.")
        return tenant
    if not tenant_name or not tenant_name.strip():
        raise ProvisioningError("Either an existing tenant id or a new tenant name is required.")
    tenant = TenantORM(name=tenant_name.strip())
    session.add(tenant)
    await session.flush()
    return tenant
