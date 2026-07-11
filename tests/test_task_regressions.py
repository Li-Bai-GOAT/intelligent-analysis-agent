import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api.conversation import _require_session_owner
from app.repositories.session_repo import SessionRepository
from app.services.agent_service import AgentService
from app.tasks import _local_tasks, start_local_task


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    async def set(self, key, value, ex=None):
        self.values[key] = value
        self.expirations[key] = ex

    async def get(self, key):
        return self.values.get(key)

    async def expire(self, key, seconds):
        self.expirations[key] = seconds


class FakeStreamRedis(FakeRedis):
    def __init__(self):
        super().__init__()
        self.entries = []

    async def xadd(self, key, fields, maxlen=None, approximate=None):
        self.entries.append((key, fields, maxlen, approximate))
        return "1-0"

    async def close(self):
        return None


class FakeSandbox:
    async def run_kuncode(self, prompt):
        yield SimpleNamespace(content="partial")
        yield SimpleNamespace(content="final result")


class TaskRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_task_uses_requested_task_id(self):
        completed = asyncio.Event()

        async def work():
            completed.set()

        task_id = start_local_task(work, task_id="expected-task-id")
        self.assertEqual(task_id, "expected-task-id")
        await asyncio.wait_for(completed.wait(), timeout=1)

        for _ in range(20):
            if task_id not in _local_tasks:
                break
            await asyncio.sleep(0.01)
        self.assertNotIn(task_id, _local_tasks)

    async def test_task_owner_round_trip(self):
        service = AgentService()
        service._redis = FakeRedis()

        await service.set_task_owner("task-1", "user-1", "session-1")

        self.assertEqual(
            await service.get_task_owner("task-1"),
            {"user_id": "user-1", "session_id": "session-1"},
        )

    async def test_task_stream_adds_replayable_event_metadata(self):
        stream_redis = FakeStreamRedis()
        with patch("app.services.agent_service.aioredis.from_url", return_value=stream_redis):
            service = AgentService()
            await service.write_task_stream(
                "task-1",
                {"type": "tool_call", "tool_id": "call-1", "content": "run_kuncode"},
                "session-1",
            )

        self.assertEqual(len(stream_redis.entries), 1)
        _, fields, maxlen, approximate = stream_redis.entries[0]
        event = json.loads(fields["data"])
        self.assertEqual(maxlen, 70000)
        self.assertTrue(approximate)
        self.assertEqual(event["task_id"], "task-1")
        self.assertEqual(event["session_id"], "session-1")
        self.assertEqual(event["phase"], "started")
        self.assertEqual(event["execution_status"], "running")
        self.assertTrue(event["event_id"].startswith("evt_"))

    async def test_session_owner_rejects_unknown_session(self):
        with patch.object(SessionRepository, "get", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as context:
                await _require_session_owner("user-1", "missing-session")

        self.assertEqual(context.exception.status_code, 404)

    async def test_direct_kuncode_persists_a_paired_history(self):
        db_session = SimpleNamespace(name="existing")
        append_message = AsyncMock()
        insert_after_plugin_call = AsyncMock()

        with (
            patch.object(SessionRepository, "get", new=AsyncMock(return_value=db_session)),
            patch.object(SessionRepository, "append_message", new=append_message),
            patch.object(
                SessionRepository,
                "insert_after_plugin_call",
                new=insert_after_plugin_call,
            ),
            patch.object(SessionRepository, "update_name", new=AsyncMock()),
        ):
            service = AgentService.__new__(AgentService)
            events = [
                event
                async for event in service._direct_run_kuncode(
                    FakeSandbox(),
                    "user-1",
                    "session-1",
                    "run a calculation",
                    "run a calculation",
                )
            ]

        self.assertEqual(events[0]["type"], "tool_call")
        self.assertEqual(events[-1], {"type": "text", "content": "KunCode 执行完成，结果已在右侧终端输出。"})

        persisted = [call.args[1] for call in append_message.await_args_list]
        self.assertEqual([message["type"] for message in persisted], ["message", "plugin_call", "message"])

        tool_id = events[0]["tool_id"]
        call_data = persisted[1]["content"][0]["data"]
        self.assertEqual(call_data["call_id"], tool_id)
        self.assertEqual(json.loads(call_data["arguments"])["prompt"], "run a calculation")

        output_message = insert_after_plugin_call.await_args.args[2]
        output_data = output_message["content"][0]["data"]
        self.assertEqual(output_data["call_id"], tool_id)
        self.assertEqual(json.loads(output_data["output"])[0]["text"], "final result")
