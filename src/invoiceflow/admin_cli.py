"""Operator CLI: ``python -m invoiceflow.admin_cli create-user ...``.

The password is read from an environment variable or an interactive prompt, never
from argv, so it does not land in shell history or process listings.
"""

import argparse
import asyncio
from getpass import getpass
import os
import sys
from typing import Optional, Sequence

from invoiceflow.application.accounts.provisioning import (
    ROLES,
    ProvisioningError,
    provision_user,
)
from invoiceflow.config import get_settings
from invoiceflow.infrastructure.database.session import DatabaseSessionManager

PASSWORD_ENV = "INVOICEFLOW_NEW_USER_PASSWORD"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="invoiceflow.admin_cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="Create a user and its tenant membership")
    create.add_argument("--email", required=True)
    create.add_argument("--full-name", required=True)
    create.add_argument("--role", required=True, choices=sorted(ROLES))
    tenant = create.add_mutually_exclusive_group(required=True)
    tenant.add_argument("--tenant-id", help="Add the user to this existing tenant")
    tenant.add_argument("--tenant-name", help="Create a new tenant with this name")
    create.add_argument("--database-url", help="Defaults to DATABASE_URL from settings")
    return parser


def _read_password() -> str:
    from_env = os.environ.get(PASSWORD_ENV)
    if from_env:
        return from_env
    password = getpass("Password: ")
    if password != getpass("Repeat password: "):
        raise ProvisioningError("The passwords do not match.")
    return password


async def _create_user(args: argparse.Namespace, password: str) -> None:
    manager = DatabaseSessionManager(database_url=args.database_url or get_settings().DATABASE_URL)
    try:
        async with manager.session() as session:
            created = await provision_user(
                session,
                email=args.email,
                full_name=args.full_name,
                password=password,
                role=args.role,
                tenant_id=args.tenant_id,
                tenant_name=args.tenant_name,
            )
    finally:
        await manager.close()
    print(f"Created {created.email} ({created.role}) in tenant {created.tenant_id}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        asyncio.run(_create_user(args, _read_password()))
    except ProvisioningError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
