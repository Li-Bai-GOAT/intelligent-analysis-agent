# -*- coding: utf-8 -*-
"""真实依赖下的接口与权限契约测试（Live）。

和 ``test_api_contract.py`` 的区别：那个文件用假仓储跑进程内契约，这个文件
连**真实的 PostgreSQL + Redis**，验证"契约在真实仓储/真实 Redis 语义下同样
成立"。尤其是归属隔离，只有走真实查询才能证明它不是"只在 mock 里成立"。

默认跳过，避免污染 CI 与本地数据库。需要时：

    CONTRACT_LIVE=1 PYTHONPATH=. python -m unittest tests.test_api_contract_live -v

注意：TestClient 以上下文管理器方式启动 lifespan，Tortoise 的连接绑定在该
portal 的事件循环上。所以所有直连数据库/Redis 的辅助操作都必须通过
``client.portal.call`` 回到同一个循环里执行，否则 asyncpg 会报
"attached to a different loop"。
"""

import json
import os
import unittest
import uuid

import redis.asyncio as aioredis
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app as fastapi_app

LIVE = os.getenv("CONTRACT_LIVE") == "1"


# ==================== 真实依赖操作（在 portal 循环内执行） ====================

async def _promote_admin(username: str) -> None:
    from app.models.user import User

    await User.filter(username=username).update(is_admin=True)


async def _purge_users(usernames) -> None:
    from app.models.session import Session, SessionMessage
    from app.models.user import User

    for username in usernames:
        user = await User.filter(username=username).first()
        if not user:
            continue
        for session in await Session.filter(user_id=str(user.id)):
            await SessionMessage.filter(session_id=session.id).delete()
        await Session.filter(user_id=str(user.id)).delete()
        await User.filter(id=user.id).delete()


async def _purge_redis(suffix: str, extra_keys=()) -> None:
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        for key in await client.keys(f"*{suffix}*"):
            await client.delete(key)
        for key in extra_keys:
            await client.delete(key)
    finally:
        await client.aclose()


async def _seed_plan_preview(session_id: str, preview_id: str) -> None:
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await client.set(
            f"plan_preview:{session_id}:{preview_id}",
            json.dumps({"status": "pending", "name": "plan", "subtasks": ["s1"]}),
            ex=120,
        )
        await client.set(f"plan_pending:{session_id}", preview_id, ex=120)
    finally:
        await client.aclose()


async def _plan_preview_status(session_id: str, preview_id: str):
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        raw = await client.get(f"plan_preview:{session_id}:{preview_id}")
        return json.loads(raw)["status"] if raw else None
    finally:
        await client.aclose()


@unittest.skipUnless(LIVE, "需要真实 PostgreSQL/Redis：设置 CONTRACT_LIVE=1 启用")
class LiveContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._client_ctx = TestClient(fastapi_app)
        cls.client = cls._client_ctx.__enter__()  # 触发 lifespan：连库/连 Redis
        cls.suffix = uuid.uuid4().hex[:10]
        cls.users = {}

    @classmethod
    def tearDownClass(cls):
        try:
            cls.client.portal.call(_purge_users, list(cls.users))
            cls.client.portal.call(
                _purge_redis, cls.suffix, (f"task_owner:task-{cls.suffix}",)
            )
        finally:
            cls._client_ctx.__exit__(None, None, None)

    # ---- 工具 -----------------------------------------------------------
    def _register(self, role: str, *, is_admin: bool = False) -> str:
        """注册并登录，返回 access token。"""
        username = f"contract_{role}_{self.suffix}"
        password = "Contract#12345"
        response = self.client.post(
            "/api/auth/register", json={"username": username, "password": password}
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.users[username] = response.json()["id"]

        if is_admin:
            self.client.portal.call(_promote_admin, username)

        login = self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        self.assertEqual(login.status_code, 200, login.text)
        return login.json()["access_token"]

    @staticmethod
    def _auth(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def _create_session(self, token: str) -> str:
        response = self.client.post(
            "/api/conversation/sessions", headers=self._auth(token)
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["session_id"]

    # ---- 用例 -----------------------------------------------------------
    def test_01_authentication_contract(self):
        self.assertEqual(self.client.get("/api/sessions").status_code, 401)

        response = self.client.get(
            "/api/sessions", headers={"Authorization": "Bearer bogus"}
        )
        self.assertEqual(response.status_code, 401)

        token = self._register("auth")
        self.assertEqual(
            self.client.get("/api/sessions", headers=self._auth(token)).status_code, 200
        )

        username = f"contract_auth_{self.suffix}"
        duplicate = self.client.post(
            "/api/auth/register",
            json={"username": username, "password": "Contract#12345"},
        )
        self.assertEqual(duplicate.status_code, 400)

        wrong = self.client.post(
            "/api/auth/login", json={"username": username, "password": "wrong-pass"}
        )
        self.assertEqual(wrong.status_code, 401)

    def test_02_session_ownership_isolation(self):
        token_a = self._register("owner")
        token_b = self._register("intruder")
        session_id = self._create_session(token_a)

        self.assertEqual(
            self.client.get(
                f"/api/sessions/{session_id}", headers=self._auth(token_a)
            ).status_code,
            200,
        )

        for method in ("get", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    f"/api/sessions/{session_id}", headers=self._auth(token_b)
                )
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(session_id, response.text)

        self.assertEqual(
            self.client.get(
                f"/api/sessions/{session_id}", headers=self._auth(token_a)
            ).status_code,
            200,
            "越权删除请求不得真的删掉会话",
        )

        plan = self.client.get(f"/api/plans/{session_id}", headers=self._auth(token_b))
        self.assertEqual(plan.status_code, 200)
        self.assertIsNone(plan.json())

    def test_03_upload_ownership_and_traversal(self):
        token_a = self._register("uploader")
        token_b = self._register("peeker")
        session_a = self._create_session(token_a)
        session_b = self._create_session(token_b)

        upload = self.client.post(
            f"/api/files/upload?session_id={session_a}",
            headers=self._auth(token_a),
            files={"files": ("secret.csv", b"owner,secret\n1,x\n", "text/csv")},
        )
        self.assertEqual(upload.status_code, 200, upload.text)

        listing = self.client.get(
            f"/api/files/uploads/{session_a}/list", headers=self._auth(token_a)
        )
        self.assertEqual(listing.status_code, 200)
        self.assertIn(
            "secret.csv", [item["name"] for item in listing.json()["files"]]
        )

        for response in (
            self.client.get(
                f"/api/files/uploads/{session_a}/list", headers=self._auth(token_b)
            ),
            self.client.get(
                f"/api/files/uploads/{session_a}/download?filename=secret.csv",
                headers=self._auth(token_b),
            ),
        ):
            self.assertEqual(response.status_code, 404)
            self.assertNotIn("owner,secret", response.text)

        traversal = self.client.get(
            f"/api/files/uploads/{session_a}/download"
            f"?filename=../{session_b}/secret.csv",
            headers=self._auth(token_a),
        )
        self.assertEqual(traversal.status_code, 400)

    def test_04_kuncode_preview_is_not_cross_tenant(self):
        token_a = self._register("executor")
        token_b = self._register("hijacker")
        session_a = self._create_session(token_a)
        preview_id = f"preview-{self.suffix}"

        self.assertEqual(
            self.client.get(
                f"/api/kuncode/{session_a}/pending", headers=self._auth(token_b)
            ).status_code,
            404,
        )

        self.client.portal.call(_seed_plan_preview, session_a, preview_id)

        hijack = self.client.post(
            f"/api/kuncode/{session_a}/plan/confirm/{preview_id}",
            headers=self._auth(token_b),
            json={"action": "cancel", "name": "", "subtasks": []},
        )
        self.assertEqual(hijack.status_code, 404)
        self.assertEqual(
            self.client.portal.call(_plan_preview_status, session_a, preview_id),
            "pending",
            "越权取消不得改变他人预览状态",
        )

        confirmed = self.client.post(
            f"/api/kuncode/{session_a}/plan/confirm/{preview_id}",
            headers=self._auth(token_a),
            json={"action": "confirm", "name": "plan", "subtasks": ["s1"]},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(
            self.client.portal.call(_plan_preview_status, session_a, preview_id),
            "confirmed",
        )

        # 重复确认 -> 409（不是静默成功，也不是 500）
        replay = self.client.post(
            f"/api/kuncode/{session_a}/plan/confirm/{preview_id}",
            headers=self._auth(token_a),
            json={"action": "confirm", "name": "plan", "subtasks": ["s1"]},
        )
        self.assertEqual(replay.status_code, 409)

    def test_05_task_stream_ownership(self):
        token_b = self._register("listener")
        task_id = f"task-{self.suffix}"
        other_user_id = str(uuid.uuid4())

        async def seed():
            client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            try:
                await client.set(
                    f"task_owner:{task_id}",
                    json.dumps({"user_id": other_user_id, "session_id": "s"}),
                    ex=120,
                )
            finally:
                await client.aclose()

        self.client.portal.call(seed)

        denied = self.client.get(
            f"/api/conversation/stream/{task_id}", headers=self._auth(token_b)
        )
        self.assertEqual(denied.status_code, 404)
        self.assertNotIn("text/event-stream", denied.headers.get("content-type", ""))

    def test_06_admin_routes_require_admin(self):
        token_user = self._register("plain")
        token_admin = self._register("admin", is_admin=True)

        self.assertEqual(
            self.client.get(
                "/api/admin/model-audits", headers=self._auth(token_user)
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                "/api/admin/model-audits", headers=self._auth(token_admin)
            ).status_code,
            200,
        )

    def test_07_unknown_api_path_is_json_404(self):
        response = self.client.get("/api/definitely-not-a-route")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "接口不存在")


if __name__ == "__main__":
    unittest.main()
