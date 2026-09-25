"""Accounts from the command line, for a server where nothing is seeded.

Production refuses the demo accounts (`SEED_USERS` must be false there), so a fresh
database has no administrator to sign in with and no collector account for the scheduler's
workers. This makes both, inside the image, without an HTTP call:

    python -m app.features.users.cli create --email ops@example.com --role admin
    python -m app.features.users.cli ensure-worker
    python -m app.features.users.cli retire-demo

The password is read from standard input, never from an argument: an argument ends up in
the shell history and in the process list. `ensure-worker` takes the collector's from
`WORKER_EMAIL` / `WORKER_PASSWORD`, the settings its workers sign in with, and sets it on
an account that already exists — a database copied from a laptop brings the worker with the
laptop's password. `retire-demo` switches off the demo accounts such a copy brings along,
whose passwords are in this repository.
"""

import argparse
import asyncio
import getpass
import sys

from app.core.config import settings
from app.db.session import session_factory
from app.features.users.schemas import Role, UserCreate, UserUpdate
from app.features.users.service import SEED_ACCOUNTS, UserService


async def create(email: str, role: Role, full_name: str | None, password: str) -> str:
    async with session_factory() as session:
        service = UserService(session)
        if await service.get_by_email(email):
            return f"{email} exists, left as it is"
        await service.create_user(
            UserCreate(email=email, password=password, full_name=full_name, role=role)
        )
        await session.commit()
        return f"{email} created as {role.value}"


async def ensure_worker() -> str:
    """The collector account at the settings' password, made or reset to it."""
    email = settings.worker_email
    password = settings.worker_password.get_secret_value()
    async with session_factory() as session:
        service = UserService(session)
        found = await service.get_by_email(email)
        if found is None:
            await service.create_user(
                UserCreate(email=email, password=password, full_name="Collector", role=Role.WORKER)
            )
            await session.commit()
            return f"{email} created as worker"
        # Set from here rather than by an administrator: the settings are what its workers
        # sign in with, and a reset through the service ends the sessions it had.
        await service.reset_password(found.id, password, actor_id=0)
        if not found.is_active:
            await service.update_user(found.id, UserUpdate(is_active=True), actor_id=0)
        await session.commit()
        return f"{email} set to the configured password"


async def retire_demo() -> list[str]:
    """Switch off the demo accounts, whose passwords are in this repository."""
    retired: list[str] = []
    async with session_factory() as session:
        service = UserService(session)
        for email, _, _, _ in SEED_ACCOUNTS:
            if email == settings.worker_email:
                continue
            found = await service.get_by_email(email)
            if found is not None and found.is_active:
                await service.update_user(found.id, UserUpdate(is_active=False), actor_id=0)
                retired.append(email)
        await session.commit()
    return retired


def _password() -> str:
    if sys.stdin.isatty():
        first = getpass.getpass("Password: ")
        if first != getpass.getpass("Again: "):
            raise SystemExit("the two passwords differ")
        return first
    return sys.stdin.readline().rstrip("\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.features.users.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    made = commands.add_parser("create", help="an account, its password read from stdin")
    made.add_argument("--email", required=True)
    made.add_argument("--role", choices=[role.value for role in Role], default="admin")
    made.add_argument("--full-name")
    commands.add_parser("ensure-worker", help="the collector account, at the settings' password")
    commands.add_parser("retire-demo", help="switch off the demo accounts")
    args = parser.parse_args(argv)

    if args.command == "create":
        print(asyncio.run(create(args.email, Role(args.role), args.full_name, _password())))
    elif args.command == "ensure-worker":
        print(asyncio.run(ensure_worker()))
    else:
        retired = asyncio.run(retire_demo())
        print("switched off: " + (", ".join(retired) if retired else "none"))


if __name__ == "__main__":
    main()
