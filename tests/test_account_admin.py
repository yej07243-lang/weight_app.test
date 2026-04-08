import importlib
import os
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path

from werkzeug.security import check_password_hash


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


class AccountAdminTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["SECRET_KEY"] = "test-secret-key"
        os.environ["WEIGHT_DB_PATH"] = str(Path(self.temp_dir.name) / "weight_records.db")
        os.environ["SESSION_COOKIE_SECURE"] = "false"
        os.environ["REGISTRATION_ENABLED"] = "true"
        os.environ["REGISTER_INVITE_CODE"] = ""
        os.environ["INVITE_ADMIN_KEY"] = "admin-key"

        sys.modules.pop("weight_app", None)
        sys.modules.pop("account_admin", None)
        self.weight_app = importlib.import_module("weight_app")
        self.account_admin = importlib.import_module("account_admin")
        self.weight_app.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_admin(self, *args: str) -> str:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = self.account_admin.main(list(args))
        self.assertEqual(exit_code, 0)
        return output.getvalue()

    def test_invite_create_prints_usable_codes(self):
        output = self.run_admin("invite", "create", "--count", "2")
        codes = [line.strip() for line in output.splitlines() if line.strip()]
        self.assertEqual(len(codes), 2)

        with closing(self.weight_app.get_connection()) as connection:
            rows = connection.execute(
                "SELECT code FROM invite_codes ORDER BY id",
            ).fetchall()

        self.assertEqual(codes, [row["code"] for row in rows])

    def test_set_password_updates_password_hash(self):
        ok, message = self.weight_app.create_user("alice", "old-password")
        self.assertTrue(ok, message)

        output = self.run_admin("user", "set-password", "alice", "--password", "new-password")
        self.assertIn("Password updated for alice.", output)

        with closing(self.weight_app.get_connection()) as connection:
            row = connection.execute(
                "SELECT password_hash FROM users WHERE username = ?",
                ("alice",),
            ).fetchone()

        self.assertTrue(check_password_hash(row["password_hash"], "new-password"))
        self.assertFalse(check_password_hash(row["password_hash"], "old-password"))

    def test_set_all_passwords_updates_every_account(self):
        for username in ("alice", "bob"):
            ok, message = self.weight_app.create_user(username, "old-password")
            self.assertTrue(ok, message)

        output = self.run_admin("user", "set-all-passwords", "--password", "shared-password")
        self.assertIn("Password updated for 2 users.", output)

        with closing(self.weight_app.get_connection()) as connection:
            rows = connection.execute("SELECT password_hash FROM users ORDER BY id").fetchall()

        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(check_password_hash(row["password_hash"], "shared-password"))


if __name__ == "__main__":
    unittest.main()
