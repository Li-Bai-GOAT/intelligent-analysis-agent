import asyncio
import tarfile
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api.conversation import ChatRequest, _require_session_owner
from app.api.files import _is_within_workspace
from app.repositories.session_repo import SessionRepository
from app.services.agent_service import (
    AgentService,
    _build_streamed_tool_result,
    _build_terminal_tool_results,
    _build_kuncode_completion_message,
    _extract_persisted_tool_results,
    _extract_workspace_files,
)
from app.services.sandbox_injection import SandboxInjectionService
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

    async def delete(self, key):
        self.values.pop(key, None)


class FakeStreamRedis(FakeRedis):
    def __init__(self):
        super().__init__()
        self.entries = []

    async def xadd(self, key, fields, maxlen=None, approximate=None):
        self.entries.append((key, fields, maxlen, approximate))
        return "1-0"

    async def aclose(self):
        return None


class FakeSandbox:
    async def run_kuncode(self, prompt):
        yield SimpleNamespace(content="partial")
        yield SimpleNamespace(content="final result")


class FakeSandboxWithFiles:
    async def run_kuncode(self, prompt):
        yield SimpleNamespace(
            content=(
                "Created /workspace/reports/summary.html and "
                "/workspace/data/uploads/source.csv"
            )
        )


class TaskRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_kuncode_completion_reports_workspace_files(self):
        files = _extract_workspace_files(
            "Created /workspace/reports/summary.html, workspace/data/result.csv, "
            "and checked /workspace/data/uploads/source.csv."
        )
        self.assertEqual(files, ["reports/summary.html", "data/result.csv"])
        message = _build_kuncode_completion_message(files)
        self.assertIn("`reports/summary.html`", message)
        self.assertIn("data/result.csv", message)

    async def test_skill_tar_uses_posix_member_paths(self):
        service = SandboxInjectionService()
        archive = service._create_tar_archive({"scripts/tool.py": b"print('ok')"})
        with tarfile.open(fileobj=archive, mode="r") as tar:
            self.assertEqual(tar.getnames(), ["scripts", "scripts/tool.py"])

    async def test_execution_mode_is_explicit_and_defaults_to_auto(self):
        request = ChatRequest(message="please explain kuncode", session_id="session-1")
        self.assertEqual(request.execution_mode, "auto")

        direct = ChatRequest(
            message="run this task",
            session_id="session-1",
            execution_mode="kuncode",
        )
        self.assertEqual(direct.execution_mode, "kuncode")

    async def test_uploaded_file_hint_contains_exact_sandbox_path(self):
        service = AgentService()
        hint = service._build_file_hint([
            "/workspace/data/uploads/sales report.xlsx",
            "/workspace/data/uploads/customers.csv",
        ])

        self.assertIn("/workspace/data/uploads/sales report.xlsx", hint)
        self.assertIn("/workspace/data/uploads/customers.csv", hint)
        self.assertIn("可以直接使用这些文件路径进行分析", hint)

    async def test_pending_tool_calls_receive_terminal_results(self):
        events = _build_terminal_tool_results({
            "call-1": "run_kuncode",
            "call-2": "search_knowledge",
        })

        self.assertEqual([event["type"] for event in events], ["tool_result", "tool_result"])
        self.assertEqual([event["tool_id"] for event in events], ["call-1", "call-2"])
        self.assertTrue(all(event["execution_status"] == "failed" for event in events))
        self.assertIn("未返回完整执行结果", events[0]["content"])

        cancelled = _build_terminal_tool_results({"call-1": "run_kuncode"}, status="cancelled")
        self.assertEqual(cancelled[0]["execution_status"], "cancelled")

    async def test_streamed_agentscope_data_output_is_a_completed_tool_result(self):
        event = _build_streamed_tool_result(
            "call-1",
            [{"type": "text", "text": "KunCode analysis completed"}],
        )

        self.assertEqual(event["type"], "tool_result")
        self.assertEqual(event["tool_id"], "call-1")
        self.assertEqual(event["execution_status"], "completed")
        self.assertIn("KunCode analysis completed", event["content"])

        failed = _build_streamed_tool_result("call-2", "[ERROR] sandbox failed")
        self.assertEqual(failed["execution_status"], "failed")

    async def test_persisted_tool_output_recovers_an_unstreamed_call(self):
        messages = [
            SimpleNamespace(message={
                "type": "plugin_call_output",
                "content": [{
                    "type": "data",
                    "data": {
                        "call_id": "call-1",
                        "name": "run_kuncode",
                        "output": '[{"type":"text","text":"analysis complete"}]',
                    },
                }],
            }),
        ]

        events = _extract_persisted_tool_results(
            messages,
            {"call-1": "run_kuncode", "call-2": "run_kuncode"},
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tool_id"], "call-1")
        self.assertEqual(events[0]["execution_status"], "completed")

    async def test_workspace_path_check_rejects_prefix_collision(self):
        self.assertTrue(_is_within_workspace(r"C:\data\workspace\report.txt", r"C:\data\workspace"))
        self.assertFalse(_is_within_workspace(r"C:\data\workspace-secret\report.txt", r"C:\data\workspace"))

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

    async def test_tool_result_stream_is_terminal_by_default(self):
        stream_redis = FakeStreamRedis()
        with patch("app.services.agent_service.aioredis.from_url", return_value=stream_redis):
            service = AgentService()
            await service.write_task_stream(
                "task-1",
                {"type": "tool_result", "tool_id": "call-1", "content": "done"},
                "session-1",
            )

        event = json.loads(stream_redis.entries[0][1]["data"])
        self.assertEqual(event["phase"], "completed")
        self.assertEqual(event["execution_status"], "completed")

    async def test_clear_session_task_only_clears_matching_task(self):
        service = AgentService()
        service._redis = FakeRedis()
        service._redis.values["session_task:session-1"] = "new-task"

        await service.clear_session_task("session-1", "old-task")
        self.assertEqual(await service.get_session_task("session-1"), "new-task")

        await service.clear_session_task("session-1", "new-task")
        self.assertIsNone(await service.get_session_task("session-1"))

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
        self.assertEqual(events[-1]["type"], "text")
        self.assertEqual(events[-1]["generated_files"], [])

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

    async def test_direct_kuncode_emits_generated_files(self):
        with (
            patch.object(SessionRepository, "get", new=AsyncMock(return_value=None)),
        ):
            service = AgentService.__new__(AgentService)
            events = [
                event
                async for event in service._direct_run_kuncode(
                    FakeSandboxWithFiles(),
                    "user-1",
                    "session-1",
                    "create report",
                    "create report",
                )
            ]

        self.assertEqual(events[-1]["generated_files"], ["reports/summary.html"])
        self.assertIn("reports/summary.html", events[-1]["content"])
