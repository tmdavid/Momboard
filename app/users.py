"""User management CLI: create users from command line."""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.auth import hash_password
from app.config import get_settings
from app.db import create_engine, create_session_factory
from app.models import User


async def create_user(email: str, password: str, name: str = "", role: str = "member") -> None:
    """Create a user in the database."""
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)

    async with factory() as session:
        # Check if user exists
        result = await session.execute(select(User).where(User.email == email))
        existing = result.scalar_one_or_none()
        if existing:
            print(f"User {email} already exists (id={existing.id}, role={existing.role})")
            await engine.dispose()
            return

        user = User(
            email=email,
            name=name or email.split("@")[0],
            password_hash=hash_password(password),
            role=role,
        )
        session.add(user)
        await session.commit()
        print(f"Created user: {email} (role={role})")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="MomBoard user management")
    sub = parser.add_subparsers(dest="command")

    create_parser = sub.add_parser("create", help="Create a new user")
    create_parser.add_argument("--email", required=True)
    create_parser.add_argument("--name", default="")
    create_parser.add_argument("--role", choices=["admin", "member"], default="member")
    create_parser.add_argument("--password", default=None, help="Password (prompted if not given)")

    args = parser.parse_args()

    if args.command == "create":
        password = args.password
        if password is None:
            password = getpass.getpass("Password: ")
            confirm = getpass.getpass("Confirm: ")
            if password != confirm:
                print("Passwords do not match", file=sys.stderr)
                sys.exit(1)

        asyncio.run(create_user(args.email, password, args.name, args.role))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
