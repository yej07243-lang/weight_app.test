import importlib
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path


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

    def register(self, username: str, password: str = "secret123", invite_code: str = "invite-123"):
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

    def test_registration_requires_invite_code(self):
        response = self.register("alice", invite_code="wrong")
        self.assertIn("邀请码错误", response.get_data(as_text=True))

        response = self.register("alice")
        self.assertIn("注册成功", response.get_data(as_text=True))

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
