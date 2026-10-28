# -*- coding: utf-8 -*-
"""接口与权限契约测试。

这一层不验证业务算法，只锁定"外部可观察的行为契约"：

1. 认证与授权：匿名 401、越权管理员 403、跨用户资源 404/403；
2. 状态码语义：401/403/404/409/422 各自出现在什么场景；
3. 资源隔离：用户 A 不能读取、取消或下载用户 B 的会话/文件/任务流；
4. 并发与幂等：并发确认只有一次生效、重复确认与重复取消返回冲突；
5. SSE：重连游标格式校验与透传、事件 ``id:`` 顺序、``_stream_id`` 不外泄。

所有用例都在 ASGI 进程内跑（``TestClient``），不依赖 Docker / PostgreSQL /
Redis。外部依赖一律用"作用域严格"的假实现替代：假仓储只按
``(user_id, session_id)`` 精确命中，一旦路由把 session_id 当唯一键、或
用错用户去查，就会查不到数据，从而让越权问题在测试里暴露出来。
"""

import asyncio
import json
import re
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, params
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api.deps import get_admin_user, get_current_user
from app.main import app as fastapi_app
from app.models.user import User
from app.repositories.file_repo import FileRepository, SandboxBindingRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.state_repo import StateRepository
from app.services import file_service as file_service_module
from app.services.agent_service import AgentService
from app.api import kuncode as kuncode_api


def _user(name: str, *, is_admin: bool = False) -> User:
    return User(
        id=uuid.uuid5(uuid.NAMESPACE_DNS, f"contract-test-{name}"),
        username=name,
        password_hash="x",
        is_admin=is_admin,
    )


USER_A = _user("alice")
USER_B = _user("bob")
ADMIN = _user("root", is_admin=True)

PUBLIC_API_PREFIXES = ("/api/auth/",)
PUBLIC_PATHS = {"/live", "/health", "/ready", "/openapi.json", "/docs", "/redoc"}


class _ContractCase(unittest.TestCase):
    """共用的客户端与登录态切换。"""

    def setUp(self):
        self.client = TestClient(fastapi_app, raise_server_exceptions=False)
        self.addCleanup(fastapi_app.dependency_overrides.clear)

    def login_as(self, user: User) -> None:
        fastapi_app.dependency_overrides[get_current_user] = lambda: user

    # ---- 路由枚举 -------------------------------------------------------
    @staticmethod
    def _api_routes():
        routes = []
        for route in fastapi_app.routes:
            if not isinstance(route, APIRoute):
                continue
            if not route.path.startswith("/api"):
                continue
            if route.path.startswith(PUBLIC_API_PREFIXES):
                continue
            routes.append(route)
        return routes

    @staticmethod
    def _fill_path(path: str) -> str:
        def repl(match):
            name = match.group(1)
            if name == "subtask_idx":
                return "0"
            if name == "file_path":
                return "note.txt"
            return "contract-session"

        return re.sub(r"\{([^}:]+)(?::path)?\}", repl, path)

    @staticmethod
    def _is_multipart(route: APIRoute) -> bool:
        return any(
            isinstance(param.field_info, (params.Form, params.File))
            for param in route.dependant.body_params
        )


class AuthenticationContractTests(_ContractCase):
    """401 / 403 契约：没有凭据必须 401，权限不足必须 403。"""

    def test_every_protected_route_rejects_anonymous_requests(self):
        """所有受保护端点都必须先做认证，不允许"漏挂鉴权"的裸接口。"""
        failures = []
        for route in self._api_routes():
            method = sorted(route.methods - {"HEAD", "OPTIONS"})[0]
            url = self._fill_path(route.path)
            kwargs = {}
            if self._is_multipart(route):
                kwargs["files"] = {"files": ("a.txt", b"x")}
                kwargs["params"] = {"session_id": "s"}
            elif method in {"POST", "PUT", "PATCH"}:
                kwargs["json"] = {}

            response = self.client.request(method, url, **kwargs)
            if response.status_code != 401:
                failures.append((method, route.path, response.status_code))

        self.assertEqual(
            failures,
            [],
            f"以下端点未在认证失败时返回 401: {failures}",
        )

    def test_anonymous_401_uses_consistent_body(self):
        response = self.client.get("/api/sessions")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "未提供认证令牌")

    def test_invalid_token_is_401_not_500(self):
        with patch(
            "app.services.auth_service.AuthService.get_current_user",
            AsyncMock(return_value=None),
        ):
            response = self.client.get(
                "/api/sessions",
                headers={"Authorization": "Bearer not-a-real-token"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "无效的认证令牌")

    def test_non_admin_gets_403_on_administrator_routes(self):
        self.login_as(USER_B)
        for path in ("/api/admin/model-audits", "/api/sandbox/runtime", "/api/sandbox/agents"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["detail"], "需要管理员权限")

    def test_administrator_dependency_contract(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_admin_user(USER_B))
        self.assertEqual(ctx.exception.status_code, 403)

        self.assertIs(asyncio.run(get_admin_user(ADMIN)), ADMIN)

    def test_write_routes_are_wrapped_by_admin_dependency(self):
        """写接口的管理员门禁是静态契约：新增写端点必须挂 get_admin_user。"""
        write_routes = {
            ("POST", "/api/knowledge"),
            ("PUT", "/api/knowledge/{item_id}"),
            ("DELETE", "/api/knowledge/{item_id}"),
            ("PUT", "/api/system-prompt"),
            ("POST", "/api/sandbox/skills/upload"),
            ("DELETE", "/api/sandbox/skills/{skill_id}"),
            ("POST", "/api/sandbox/mcps"),
            ("PUT", "/api/sandbox/mcps/{mcp_id}"),
            ("DELETE", "/api/sandbox/mcps/{mcp_id}"),
            ("POST", "/api/sandbox/inject"),
        }
        by_key = {}
        for route in fastapi_app.routes:
            if not isinstance(route, APIRoute):
                continue
            by_key[(route.path, frozenset(route.methods))] = route

        for method, path in write_routes:
            with self.subTest(path=path, method=method):
                route = next(
                    r for (p, methods), r in by_key.items()
                    if p == path and method in methods
                )
                names = _dependency_names(route.dependant)
                self.assertIn("get_admin_user", names)


def _dependency_names(dependant, acc=None):
    acc = [] if acc is None else acc
    for dependency in dependant.dependencies:
        acc.append(getattr(dependency.call, "__name__", str(dependency.call)))
        _dependency_names(dependency, acc)
    return acc


class SessionOwnershipContractTests(_ContractCase):
    """会话级资源隔离：用户 A 的会话对用户 B 必须不可见、不可操作。"""

    def setUp(self):
        super().setUp()
        self.session = SimpleNamespace(
            id=uuid.uuid5(uuid.NAMESPACE_DNS, "session-row"),
            session_id="session-of-alice",
            user_id=str(USER_A.id),
            name="alice-session",
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        self._patch_sessions()

    def _patch_sessions(self):
        store = {(str(USER_A.id), self.session.session_id): self.session}

        async def fake_get(user_id, session_id="default", *args, **kwargs):
            return store.get((str(user_id), str(session_id)))

        async def fake_get_messages(session=None, *args, **kwargs):
            return []

        patches = [
            patch.object(SessionRepository, "get", staticmethod(fake_get)),
            patch.object(SessionRepository, "get_messages", staticmethod(fake_get_messages)),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_owner_can_read_and_delete_session(self):
        self.login_as(USER_A)
        response = self.client.get(f"/api/sessions/{self.session.session_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], self.session.session_id)

    def test_other_user_reads_session_as_404(self):
        self.login_as(USER_B)
        response = self.client.get(f"/api/sessions/{self.session.session_id}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "会话不存在")

    def test_other_user_delete_session_as_404_without_side_effects(self):
        self.login_as(USER_B)
        cleanup = AsyncMock()
        with patch(
            "app.api.sessions.get_cleanup_service", AsyncMock(return_value=cleanup)
        ):
            response = self.client.delete(f"/api/sessions/{self.session.session_id}")

        self.assertEqual(response.status_code, 404)
        cleanup.cleanup_session.assert_not_awaited()

    def test_plan_of_other_session_does_not_leak(self):
        """B 用 A 的 session_id 读计划：返回空，且绝不返回 A 的计划内容。"""
        self.login_as(USER_B)
        async def fake_state_get(user_id, session_id="default", *args, **kwargs):
            return None

        with patch.object(StateRepository, "get", staticmethod(fake_state_get)):
            response = self.client.get(f"/api/plans/{self.session.session_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())

    def test_other_user_cannot_update_plan(self):
        self.login_as(USER_B)
        async def fake_state_get(user_id, session_id="default", *args, **kwargs):
            return None

        with patch.object(StateRepository, "get", staticmethod(fake_state_get)):
            response = self.client.put(
                f"/api/plans/{self.session.session_id}", json={"name": "hijack"}
            )

        self.assertEqual(response.status_code, 404)


class KuncodeOwnershipContractTests(_ContractCase):
    """kuncode 是人机确认入口，越权确认等于替别人按下"执行"。"""

    SESSION_ID = "session-of-alice"
    PREVIEW_ID = "preview-1"

    def setUp(self):
        super().setUp()
        store = {
            (str(USER_A.id), self.SESSION_ID): SimpleNamespace(
                id=uuid.uuid5(uuid.NAMESPACE_DNS, "kuncode-session"),
                session_id=self.SESSION_ID,
                user_id=str(USER_A.id),
            )
        }

        async def fake_get(user_id, session_id="default", *args, **kwargs):
            return store.get((str(user_id), str(session_id)))

        patcher = patch.object(SessionRepository, "get", staticmethod(fake_get))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _forbidden_redis(self):
        def boom():
            raise AssertionError("越权请求不应触达 Redis")

        return patch.object(kuncode_api, "_get_redis", boom)

    def test_session_scoped_kuncode_routes_use_ownership_guard(self):
        names_ok = {"require_owned_session"}
        for route in fastapi_app.routes:
            if not isinstance(route, APIRoute):
                continue
            if not route.path.startswith("/api/kuncode/"):
                continue
            with self.subTest(path=route.path):
                names = set(_dependency_names(route.dependant))
                self.assertTrue(
                    names_ok & names,
                    f"{route.path} 缺少会话归属校验依赖",
                )

    def test_foreign_pending_preview_is_404_before_redis(self):
        self.login_as(USER_B)
        with self._forbidden_redis():
            response = self.client.get(f"/api/kuncode/{self.SESSION_ID}/pending")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "会话不存在")

    def test_foreign_confirm_is_404_before_redis(self):
        self.login_as(USER_B)
        with self._forbidden_redis():
            response = self.client.post(
                f"/api/kuncode/{self.SESSION_ID}/confirm/{self.PREVIEW_ID}",
                json={"prompt": "rm -rf /", "action": "confirm"},
            )

        self.assertEqual(response.status_code, 404)

    def test_foreign_plan_confirm_is_404_before_redis(self):
        self.login_as(USER_B)
        with self._forbidden_redis():
            response = self.client.post(
                f"/api/kuncode/{self.SESSION_ID}/plan/confirm/{self.PREVIEW_ID}",
                json={"action": "confirm", "name": "hijack", "subtasks": []},
            )

        self.assertEqual(response.status_code, 404)

    def test_foreign_countdown_reset_is_404_before_redis(self):
        self.login_as(USER_B)
        for path in (
            f"/api/kuncode/{self.SESSION_ID}/auto_continue/reset",
            f"/api/kuncode/{self.SESSION_ID}/preview/reset",
            f"/api/kuncode/{self.SESSION_ID}/auto_continue/confirm",
        ):
            with self.subTest(path=path):
                with self._forbidden_redis():
                    response = self.client.post(path, json={"action": "continue"})
                self.assertEqual(response.status_code, 404)


class RequestValidationContractTests(_ContractCase):
    """422 契约：缺字段、类型错误必须由框架统一拒绝。"""

    def test_login_without_credentials_is_422(self):
        response = self.client.post("/api/auth/login", json={})
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertTrue(all("loc" in item and "msg" in item for item in detail))

    def test_chat_without_message_is_422(self):
        self.login_as(USER_A)
        response = self.client.post(
            "/api/conversation/chat", json={"session_id": "s"}
        )
        self.assertEqual(response.status_code, 422)

    def test_invalid_execution_mode_is_422(self):
        self.login_as(USER_A)
        response = self.client.post(
            "/api/conversation/chat",
            json={"session_id": "s", "message": "hi", "execution_mode": "shell"},
        )
        self.assertEqual(response.status_code, 422)

    def test_plan_confirm_without_action_is_422(self):
        """归属校验通过后，缺 action 字段必须由框架返回 422（而不是 500/400）。"""
        self.login_as(USER_A)

        async def fake_get(user_id, session_id="default", *args, **kwargs):
            return SimpleNamespace(
                id=uuid.uuid5(uuid.NAMESPACE_DNS, "validate-session"),
                session_id=session_id,
                user_id=str(user_id),
            )

        with patch.object(SessionRepository, "get", staticmethod(fake_get)):
            response = self.client.post(
                "/api/kuncode/session-x/plan/confirm/preview-1", json={}
            )

        self.assertEqual(response.status_code, 422)
        locs = {tuple(item["loc"]) for item in response.json()["detail"]}
        self.assertIn(("body", "action"), locs)

    def test_confirm_action_type_error_is_422(self):
        self.login_as(USER_A)

        async def fake_get(user_id, session_id="default", *args, **kwargs):
            return SimpleNamespace(
                id=uuid.uuid5(uuid.NAMESPACE_DNS, "validate-session"),
                session_id=session_id,
                user_id=str(user_id),
            )

        with patch.object(SessionRepository, "get", staticmethod(fake_get)):
            response = self.client.post(
                "/api/kuncode/session-x/plan/confirm/preview-1",
                json={"action": "confirm", "subtasks": "not-a-list"},
            )

        self.assertEqual(response.status_code, 422)


class FileOwnershipContractTests(_ContractCase):
    """文件资源隔离：上传件与沙箱工作区都不能跨用户读取。"""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = patch.object(file_service_module, "USER_UPLOADS_DIR", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.session = SimpleNamespace(
            id=uuid.uuid5(uuid.NAMESPACE_DNS, "file-session"),
            session_id="session-of-alice",
            user_id=str(USER_A.id),
        )

        async def fake_get(user_id, session_id="default", *args, **kwargs):
            if (str(user_id), str(session_id)) == (str(USER_A.id), self.session.session_id):
                return self.session
            return None

        session_patcher = patch.object(SessionRepository, "get", staticmethod(fake_get))
        session_patcher.start()
        self.addCleanup(session_patcher.stop)

    def _write_upload(self, session_id: str, name: str, payload: bytes) -> None:
        folder = self.root / session_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(payload)

    def test_owner_lists_own_uploads(self):
        self._write_upload(self.session.session_id, "report.csv", b"a,b\n1,2\n")
        self.login_as(USER_A)
        response = self.client.get(
            f"/api/files/uploads/{self.session.session_id}/list"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["name"] for item in response.json()["files"]], ["report.csv"]
        )

    def test_other_user_cannot_list_uploads(self):
        self._write_upload(self.session.session_id, "report.csv", b"top-secret")
        self.login_as(USER_B)
        response = self.client.get(
            f"/api/files/uploads/{self.session.session_id}/list"
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("top-secret", response.text)

    def test_other_user_cannot_download_uploads(self):
        self._write_upload(self.session.session_id, "report.csv", b"top-secret")
        self.login_as(USER_B)
        response = self.client.get(
            f"/api/files/uploads/{self.session.session_id}/download",
            params={"filename": "report.csv"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("top-secret", response.text)

    def test_download_rejects_path_traversal(self):
        self._write_upload("session-of-bob", "bob-private.txt", b"bob-private")
        self.login_as(USER_A)
        for filename in (
            "../session-of-bob/bob-private.txt",
            "..\\session-of-bob\\bob-private.txt",
            "..",
            ".",
            "",
        ):
            with self.subTest(filename=filename):
                response = self.client.get(
                    f"/api/files/uploads/{self.session.session_id}/download",
                    params={"filename": filename},
                )
                self.assertIn(response.status_code, {400, 422})
                self.assertNotIn("bob-private", response.text)

    def test_owner_downloads_upload(self):
        self._write_upload(self.session.session_id, "report.csv", b"ok")
        self.login_as(USER_A)
        response = self.client.get(
            f"/api/files/uploads/{self.session.session_id}/download",
            params={"filename": "report.csv"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_other_user_download_file_id_is_404(self):
        async def fake_get_by_user(user_id, file_id):
            if str(user_id) == str(USER_A.id) and file_id == "file-of-alice":
                return SimpleNamespace(
                    local_path=str(self.root / "x"), content_type="text/plain",
                    original_name="x.txt", filename="x.txt",
                )
            return None

        self.login_as(USER_B)
        with patch.object(
            FileRepository, "get_by_user", staticmethod(fake_get_by_user)
        ):
            response = self.client.get("/api/files/file-of-alice/download")
        self.assertEqual(response.status_code, 404)

    def test_sandbox_binding_of_other_user_is_forbidden(self):
        async def fake_binding(session_id):
            return SimpleNamespace(
                id=1,
                session_id=session_id,
                user_id=str(USER_A.id),
                sandbox_id="sbx-1",
                workspace_path="/workspace",
                mount_dir=str(self.root),
                is_active=True,
                status="ready",
                last_activity_at=None,
                lease_expires_at=None,
                release_attempts=0,
                last_error=None,
                synced_file_ids=[],
                created_at=None,
                updated_at=None,
            )

        self.login_as(USER_B)
        with patch.object(
            SandboxBindingRepository, "get_by_session", staticmethod(fake_binding)
        ):
            response = self.client.get(
                f"/api/files/sandbox/{self.session.session_id}/binding"
            )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("sbx-1", response.text)


class TaskStreamContractTests(_ContractCase):
    """SSE 契约：任务归属、重连游标、事件 id 顺序。"""

    def setUp(self):
        super().setUp()
        self.owner_patch = patch.object(
            AgentService,
            "get_task_owner",
            AsyncMock(return_value={"user_id": str(USER_A.id), "session_id": "s-a"}),
        )
        self.owner_patch.start()
        self.addCleanup(self.owner_patch.stop)

        start_patch = patch.object(AgentService, "start", AsyncMock(return_value=None))
        start_patch.start()
        self.addCleanup(start_patch.stop)

        self.captured = {}

        async def fake_stream(task_id, last_id="0"):
            self.captured["task_id"] = task_id
            self.captured["last_id"] = last_id
            for index in range(1, 4):
                yield {"type": "text", "content": f"chunk-{index}", "_stream_id": f"{index}-0"}

        stream_patch = patch.object(
            AgentService, "read_task_stream", staticmethod(fake_stream)
        )
        stream_patch.start()
        self.addCleanup(stream_patch.stop)

    def test_other_user_cannot_subscribe_task_stream(self):
        self.login_as(USER_B)
        response = self.client.get("/api/conversation/stream/task-1")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("last_id", self.captured)

    def test_owner_subscribes_with_default_cursor(self):
        self.login_as(USER_A)
        response = self.client.get("/api/conversation/stream/task-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.captured["last_id"], "0")

    def test_malformed_cursor_falls_back_to_zero(self):
        self.login_as(USER_A)
        for header in ("../etc/passwd", "abc", "1-", "-1"):
            with self.subTest(header=header):
                self.captured.clear()
                response = self.client.get(
                    "/api/conversation/stream/task-1",
                    headers={"Last-Event-ID": header},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.captured["last_id"], "0")

    def test_valid_cursor_is_passed_through(self):
        self.login_as(USER_A)
        response = self.client.get(
            "/api/conversation/stream/task-1",
            headers={"Last-Event-ID": "12-5"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.captured["last_id"], "12-5")

    def test_event_ids_are_emitted_in_order_and_not_leaked(self):
        self.login_as(USER_A)
        response = self.client.get("/api/conversation/stream/task-1")
        body = response.text
        ids = re.findall(r"^id: (.+)$", body, flags=re.MULTILINE)
        self.assertEqual(ids, ["1-0", "2-0", "3-0"])
        self.assertNotIn("_stream_id", body)
        payloads = [
            json.loads(line[len("data: "):])
            for line in body.splitlines()
            if line.startswith("data: ")
        ]
        self.assertEqual([p["content"] for p in payloads], ["chunk-1", "chunk-2", "chunk-3"])
        self.assertEqual(response.headers["content-type"].split(";")[0], "text/event-stream")


class _RaceRedis:
    """模拟 Redis 语义：``SET NX`` 是原子的，其余操作可被打断。"""

    def __init__(self):
        self.values = {}
        self.set_calls = 0

    async def set(self, key, value, ex=None, nx=False):
        # 让出控制权，制造"两个请求都已进入临界区前"的并发窗口
        await asyncio.sleep(0)
        if nx:
            self.set_calls += 1
            if key in self.values:
                return False
            self.values[key] = value
            return True
        self.values[key] = value
        return True

    async def get(self, key):
        await asyncio.sleep(0)
        return self.values.get(key)

    async def delete(self, key):
        await asyncio.sleep(0)
        return 1 if self.values.pop(key, None) is not None else 0

    async def aclose(self):
        return None


class ConfirmationIdempotencyContractTests(unittest.TestCase):
    """确认动作的并发与幂等：一次预览只能被确认一次。"""

    def _seed_plan_preview(self, redis, session_id="s-1", preview_id="p-1"):
        redis.values[f"plan_pending:{session_id}"] = preview_id
        redis.values[f"plan_preview:{session_id}:{preview_id}"] = json.dumps(
            {"status": "pending", "name": "plan", "subtasks": ["a"]}
        )

    def test_concurrent_plan_confirm_only_applies_once(self):
        redis = _RaceRedis()
        self._seed_plan_preview(redis)

        async def scenario():
            with patch.object(kuncode_api, "_get_redis", AsyncMock(return_value=redis)):
                return await asyncio.gather(
                    kuncode_api.confirm_plan_preview("s-1", "p-1", "confirm", name="plan"),
                    kuncode_api.confirm_plan_preview("s-1", "p-1", "confirm", name="plan"),
                    return_exceptions=True,
                )

        results = asyncio.run(scenario())
        conflicts = [r for r in results if isinstance(r, HTTPException)]
        successes = [r for r in results if not isinstance(r, Exception)]

        self.assertEqual(len(successes), 1, f"并发确认应只有一次生效: {results}")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].status_code, 409)

    def test_repeated_confirm_is_conflict(self):
        redis = _RaceRedis()
        self._seed_plan_preview(redis)

        async def scenario():
            with patch.object(kuncode_api, "_get_redis", AsyncMock(return_value=redis)):
                await kuncode_api.confirm_plan_preview("s-1", "p-1", "confirm", name="plan")
                with self.assertRaises(HTTPException) as ctx:
                    await kuncode_api.confirm_plan_preview("s-1", "p-1", "confirm", name="plan")
                return ctx.exception

        self.assertEqual(asyncio.run(scenario()).status_code, 409)

    def test_repeated_cancel_is_conflict(self):
        redis = _RaceRedis()
        self._seed_plan_preview(redis)

        async def scenario():
            with patch.object(kuncode_api, "_get_redis", AsyncMock(return_value=redis)):
                await kuncode_api.confirm_plan_preview("s-1", "p-1", "cancel")
                with self.assertRaises(HTTPException) as ctx:
                    await kuncode_api.confirm_plan_preview("s-1", "p-1", "cancel")
                return ctx.exception

        self.assertEqual(asyncio.run(scenario()).status_code, 409)

    def test_unknown_plan_preview_is_404(self):
        redis = _RaceRedis()
        redis.values["plan_pending:s-1"] = "p-1"

        async def scenario():
            with patch.object(kuncode_api, "_get_redis", AsyncMock(return_value=redis)):
                with self.assertRaises(HTTPException) as ctx:
                    await kuncode_api.confirm_plan_preview("s-1", "p-1", "confirm")
                return ctx.exception

        self.assertEqual(asyncio.run(scenario()).status_code, 404)

    def test_stale_preview_is_409(self):
        redis = _RaceRedis()
        redis.values["plan_pending:s-1"] = "p-new"
        redis.values["plan_preview:s-1:p-old"] = json.dumps({"status": "pending"})

        async def scenario():
            with patch.object(kuncode_api, "_get_redis", AsyncMock(return_value=redis)):
                with self.assertRaises(HTTPException) as ctx:
                    await kuncode_api.confirm_plan_preview("s-1", "p-old", "confirm")
                return ctx.exception

        self.assertEqual(asyncio.run(scenario()).status_code, 409)

    def test_concurrent_kuncode_confirm_only_applies_once(self):
        redis = _RaceRedis()

        async def scenario():
            with patch.object(kuncode_api, "_get_redis", AsyncMock(return_value=redis)):
                results = await asyncio.gather(
                    kuncode_api.confirm_kuncode(
                        "s-1", "p-1",
                        kuncode_api.KuncodeConfirmRequest(prompt="ls", action="confirm"),
                        USER_A,
                    ),
                    kuncode_api.confirm_kuncode(
                        "s-1", "p-1",
                        kuncode_api.KuncodeConfirmRequest(prompt="ls", action="confirm"),
                        USER_A,
                    ),
                    return_exceptions=True,
                )
                return results

        # 预览尚未创建时两个请求都返回 404；先建预览再并发
        self.assertTrue(all(isinstance(r, HTTPException) for r in asyncio.run(scenario())))

        redis = _RaceRedis()
        redis.values["kuncode_preview:s-1:p-1"] = json.dumps({"status": "pending", "prompt": "ls"})
        redis.values["kuncode_pending:s-1"] = "p-1"

        async def scenario2():
            with patch.object(kuncode_api, "_get_redis", AsyncMock(return_value=redis)):
                return await asyncio.gather(
                    kuncode_api.confirm_kuncode(
                        "s-1", "p-1",
                        kuncode_api.KuncodeConfirmRequest(prompt="ls", action="confirm"),
                        USER_A,
                    ),
                    kuncode_api.confirm_kuncode(
                        "s-1", "p-1",
                        kuncode_api.KuncodeConfirmRequest(prompt="ls", action="confirm"),
                        USER_A,
                    ),
                    return_exceptions=True,
                )

        results = asyncio.run(scenario2())
        conflicts = [r for r in results if isinstance(r, HTTPException)]
        self.assertEqual(len(conflicts), 1, f"应当只有一次确认生效: {results}")
        self.assertEqual(conflicts[0].status_code, 409)


class RoutingFallbackContractTests(_ContractCase):
    """未知 API 路径必须是 JSON 404，不能落到 SPA 的 index.html。"""

    def test_unknown_api_path_returns_404(self):
        response = self.client.get("/api/does-not-exist")
        self.assertEqual(response.status_code, 404)
        if response.headers.get("content-type", "").startswith("application/json"):
            self.assertEqual(response.json()["detail"], "接口不存在")

    def test_health_endpoint_stays_public(self):
        response = self.client.get("/live")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
