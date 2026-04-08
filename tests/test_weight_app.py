import importlib
import os
import re
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from werkzeug.security import check_password_hash


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


class WeightAppTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["SECRET_KEY"] = "test-secret-key"
        os.environ["WEIGHT_DB_PATH"] = str(Path(self.temp_dir.name) / "weight_records.db")
        os.environ["SESSION_COOKIE_SECURE"] = "false"
        os.environ["REGISTRATION_ENABLED"] = "true"
        os.environ["REGISTER_INVITE_CODE"] = "invite-123"
        os.environ["INVITE_ADMIN_KEY"] = "admin-key"

        sys.modules.pop("weight_app", None)
        self.weight_app = importlib.import_module("weight_app")
        self.weight_app.RATE_LIMITS.clear()
        self.weight_app.init_db()
        self.client = self.weight_app.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def csrf_from(self, response) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
        self.assertIsNotNone(match)
        return match.group(1)

    def invite_code(self) -> str:
        return self.weight_app.create_invite_code()

    def register(self, username: str, password: str = "secret123", invite_code: str | None = None):
        invite_code = invite_code or self.invite_code()
        response = self.client.get("/auth")
        return self.client.post(
            "/register",
            data={
                "csrf_token": self.csrf_from(response),
                "username": username,
                "password": password,
                "invite_code": invite_code,
            },
            follow_redirects=True,
        )

    def login(self, username: str, password: str = "secret123"):
        response = self.client.get("/auth")
        return self.client.post(
            "/login",
            data={"csrf_token": self.csrf_from(response), "username": username, "password": password},
            follow_redirects=True,
        )

    def post_with_csrf(self, path: str, data: dict):
        response = self.client.get("/")
        return self.client.post(
            path,
            data={"csrf_token": self.csrf_from(response), **data},
            follow_redirects=True,
        )

    def record_id_from_index(self) -> int:
        response = self.client.get("/")
        match = re.search(r"edit=(\d+)", response.get_data(as_text=True))
        self.assertIsNotNone(match)
        return int(match.group(1))

    def test_csrf_blocks_post_without_token(self):
        response = self.client.post("/login", data={"username": "alice", "password": "secret123"})
        self.assertEqual(response.status_code, 400)

    def test_auth_page_does_not_link_to_admin_page(self):
        response = self.client.get("/auth")
        page = response.get_data(as_text=True)
        self.assertNotIn("/invites", page)
        self.assertNotIn("生成邀请码", page)

    def test_registration_requires_invite_code(self):
        response = self.register("alice", invite_code="wrong")
        self.assertIn("邀请码错误或已被使用", response.get_data(as_text=True))

        invite_code = self.invite_code()
        response = self.register("alice", invite_code=invite_code)
        self.assertIn("注册成功", response.get_data(as_text=True))

        response = self.register("bob", invite_code=invite_code)
        self.assertIn("邀请码错误或已被使用", response.get_data(as_text=True))

    def test_invite_code_generator_creates_registration_code(self):
        response = self.client.get("/invites")
        csrf_token = self.csrf_from(response)
        response = self.client.post(
            "/invites",
            data={"csrf_token": csrf_token, "admin_key": "admin-key"},
            follow_redirects=True,
        )
        page = response.get_data(as_text=True)
        self.assertIn("邀请码已生成", page)
        match = re.search(r'<div class="code-value">([^<]+)</div>', page)
        self.assertIsNotNone(match)

        response = self.register("alice", invite_code=match.group(1))
        self.assertIn("注册成功", response.get_data(as_text=True))

    def test_admin_page_lists_users_and_updates_one_password(self):
        self.register("alice")
        response = self.client.get("/invites")
        response = self.client.post(
            "/admin/authorize",
            data={"csrf_token": self.csrf_from(response), "admin_key": "admin-key"},
            follow_redirects=True,
        )
        page = response.get_data(as_text=True)
        self.assertIn("账号列表", page)
        self.assertIn("alice", page)

        response = self.client.post(
            "/admin/users/1/password",
            data={"csrf_token": self.csrf_from(response), "admin_key": "admin-key", "password": "new-secret"},
            follow_redirects=True,
        )
        self.assertIn("alice 的密码已修改", response.get_data(as_text=True))

        with closing(self.weight_app.get_connection()) as connection:
            row = connection.execute(
                "SELECT password_hash FROM users WHERE username = ?",
                ("alice",),
            ).fetchone()
        self.assertTrue(check_password_hash(row["password_hash"], "new-secret"))

    def test_admin_page_updates_all_passwords(self):
        self.register("alice")
        self.register("bob")
        response = self.client.get("/invites")
        response = self.client.post(
            "/admin/users/passwords",
            data={"csrf_token": self.csrf_from(response), "admin_key": "admin-key", "password": "shared-secret"},
            follow_redirects=True,
        )
        self.assertIn("已修改 2 个账号的密码", response.get_data(as_text=True))

        with closing(self.weight_app.get_connection()) as connection:
            rows = connection.execute("SELECT password_hash FROM users ORDER BY id").fetchall()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(check_password_hash(row["password_hash"], "shared-secret"))

    def test_registration_can_be_disabled(self):
        self.weight_app.app.config["REGISTRATION_ENABLED"] = False
        response = self.register("alice")
        self.assertIn("当前未开放注册", response.get_data(as_text=True))

    def test_login_add_update_delete_record_and_filter(self):
        self.register("alice")
        response = self.login("alice")
        self.assertIn("登录成功", response.get_data(as_text=True))

        response = self.post_with_csrf(
            "/add",
            {"record_date": "2026-04-01", "weight": "60.5", "note": "morning"},
        )
        self.assertIn("保存成功", response.get_data(as_text=True))
        self.assertIn("60.5 kg", response.get_data(as_text=True))

        record_id = self.record_id_from_index()
        response = self.post_with_csrf(
            f"/update/{record_id}",
            {"record_date": "2026-04-02", "weight": "59.8", "note": "updated"},
        )
        page = response.get_data(as_text=True)
        self.assertIn("修改成功", page)
        self.assertIn("59.8 kg", page)
        self.assertIn("updated", page)

        response = self.client.get("/?start_date=2026-04-03&end_date=2026-04-04")
        self.assertIn("还没有记录", response.get_data(as_text=True))

        response = self.post_with_csrf(f"/delete/{record_id}", {})
        self.assertIn("记录已删除", response.get_data(as_text=True))
        self.assertIn("还没有记录", response.get_data(as_text=True))

    def test_records_are_isolated_between_users(self):
        self.register("alice")
        self.login("alice")
        self.post_with_csrf(
            "/add",
            {"record_date": "2026-04-01", "weight": "60.5", "note": "alice-only"},
        )
        self.client.get("/logout")

        self.register("bob")
        response = self.login("bob")
        page = response.get_data(as_text=True)
        self.assertNotIn("alice-only", page)
        self.assertIn("还没有记录", page)


if __name__ == "__main__":
    unittest.main()
