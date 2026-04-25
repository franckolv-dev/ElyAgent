"""Create the first admin user for ELY (headless/scripted setup).

Usage (from project root, backend container running) :

  docker exec cyberentity-backend bash -c \
    "cd /app && PYTHONPATH=/app uv run --no-sync python /app/scripts/create_admin.py \
       --username franck --password 'Str0ngPa$$w0rd!' --email me@example.com"

Or via the Makefile shortcut :

  make create-admin USER=franck PASS='Str0ngPa$$w0rd!' EMAIL=me@example.com

Note : the FIRST user to register via the web UI is auto-promoted to admin,
so this script is only needed for headless / fully-scripted deployments.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from sqlalchemy import select

from app.auth.passwords import hash_password
from app.database import async_session
from app.models.user import User


async def main(username: str, password: str, email: str) -> int:
    async with async_session() as db:
        existing = await db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none() is not None:
            print(f"❌ User '{username}' already exists.", file=sys.stderr)
            return 1
        user = User(
            username=username,
            email=email,
            hashed_password=await hash_password(password),
            role="admin",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        print(f"✅ Admin user '{username}' created (id={user.id}).")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create an admin user for ELY.")
    parser.add_argument("--username", required=True, help="Login name")
    parser.add_argument("--password", required=True, help="Password (min 12 chars)")
    parser.add_argument("--email", default=None, help="Email (defaults to <username>@local)")
    args = parser.parse_args()

    if len(args.password) < 12:
        print("❌ Password must be at least 12 characters.", file=sys.stderr)
        sys.exit(2)

    email = args.email or f"{args.username}@local"
    sys.exit(asyncio.run(main(args.username, args.password, email)))
