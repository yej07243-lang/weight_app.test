import argparse
import getpass
import sqlite3
from contextlib import closing
from pathlib import Path

from werkzeug.security import generate_password_hash

import weight_app


def get_password(args: argparse.Namespace) -> str:
    if args.password:
        return args.password

    password = getpass.getpass("New password: ")
    confirm_password = getpass.getpass("Confirm password: ")
    if password != confirm_password:
        raise ValueError("Passwords do not match.")
    return password


def validate_password(username: str, password: str) -> None:
    ok, message = weight_app.validate_user_credentials(username, password)
    if not ok:
        raise ValueError(message)


def create_invites(args: argparse.Namespace) -> int:
    weight_app.init_db()
    for _ in range(args.count):
        print(weight_app.create_invite_code())
    return 0


def list_invites(args: argparse.Namespace) -> int:
    weight_app.init_db()
    with closing(weight_app.get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT invite_codes.code, invite_codes.created_at, invite_codes.used_at, users.username AS used_by
            FROM invite_codes
            LEFT JOIN users ON invite_codes.used_by_user_id = users.id
            ORDER BY invite_codes.id DESC
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()

    if not rows:
        print("No invite codes found.")
        return 0

    print("code\tstatus\tcreated_at\tused_by")
    for row in rows:
        status = "used" if row["used_at"] else "unused"
        used_by = row["used_by"] or ""
        print(f"{row['code']}\t{status}\t{row['created_at']}\t{used_by}")
    return 0


def list_users(args: argparse.Namespace) -> int:
    weight_app.init_db()
    with closing(weight_app.get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT id, username, created_at
            FROM users
            ORDER BY id
            """
        ).fetchall()

    if not rows:
        print("No users found.")
        return 0

    print("id\tusername\tcreated_at")
    for row in rows:
        print(f"{row['id']}\t{row['username']}\t{row['created_at']}")
    return 0


def set_user_password(args: argparse.Namespace) -> int:
    weight_app.init_db()
    username = args.username.strip()
    password = get_password(args)
    validate_password(username, password)

    with closing(weight_app.get_connection()) as connection:
        result = connection.execute(
            """
            UPDATE users
            SET password_hash = ?
            WHERE username = ?
            """,
            (generate_password_hash(password), username),
        )
        connection.commit()

    if result.rowcount == 0:
        raise ValueError(f"User not found: {username}")

    print(f"Password updated for {username}.")
    return 0


def set_all_passwords(args: argparse.Namespace) -> int:
    weight_app.init_db()
    password = get_password(args)

    with closing(weight_app.get_connection()) as connection:
        users = connection.execute("SELECT username FROM users ORDER BY id").fetchall()
        if not users:
            print("No users found.")
            return 0

        for user in users:
            validate_password(user["username"], password)

        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            UPDATE users
            SET password_hash = ?
            """,
            (generate_password_hash(password),),
        )
        connection.commit()

    print(f"Password updated for {len(users)} users.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage weight app invite codes and account passwords.",
    )
    parser.add_argument(
        "--db",
        help="Optional SQLite database path. Defaults to WEIGHT_DB_PATH or weight_records.db next to weight_app.py.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    invite_parser = subparsers.add_parser("invite", help="Manage invite codes.")
    invite_subparsers = invite_parser.add_subparsers(dest="invite_command", required=True)

    invite_create_parser = invite_subparsers.add_parser("create", help="Create invite codes.")
    invite_create_parser.add_argument("-n", "--count", type=int, default=1, help="Number of invite codes to create.")
    invite_create_parser.set_defaults(handler=create_invites)

    invite_list_parser = invite_subparsers.add_parser("list", help="List recent invite codes.")
    invite_list_parser.add_argument("--limit", type=int, default=50, help="Maximum rows to show.")
    invite_list_parser.set_defaults(handler=list_invites)

    user_parser = subparsers.add_parser("user", help="Manage accounts.")
    user_subparsers = user_parser.add_subparsers(dest="user_command", required=True)

    user_list_parser = user_subparsers.add_parser("list", help="List accounts.")
    user_list_parser.set_defaults(handler=list_users)

    set_password_parser = user_subparsers.add_parser("set-password", help="Set one account password.")
    set_password_parser.add_argument("username", help="Username to update.")
    set_password_parser.add_argument("--password", help="New password. If omitted, the script prompts securely.")
    set_password_parser.set_defaults(handler=set_user_password)

    set_all_passwords_parser = user_subparsers.add_parser("set-all-passwords", help="Set every account to one password.")
    set_all_passwords_parser.add_argument("--password", help="New password. If omitted, the script prompts securely.")
    set_all_passwords_parser.set_defaults(handler=set_all_passwords)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.db:
        weight_app.DB_PATH = Path(args.db)

    if hasattr(args, "count") and args.count < 1:
        parser.error("--count must be at least 1.")
    if hasattr(args, "limit") and args.limit < 1:
        parser.error("--limit must be at least 1.")

    try:
        return args.handler(args)
    except (ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
