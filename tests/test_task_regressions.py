import asyncio
import importlib.util
import inspect
import queue
import tarfile
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi import HTTPException

from app.api.conversation import ChatRequest, _require_session_owner
from app.api.kuncode import (
    confirm_plan_preview,
    create_plan_preview,
    wait_for_plan_confirm,
)
from app.api.plans import (
    extract_last_finished_plan_from_state,
    extract_plan_from_state,
    plan_to_schema,
    update_plan_in_state,
)
from app.api.files import _is_internal_workspace_item, _is_within_workspace
from app.repositories.session_repo import SessionRepository
from app.services.agent_service import (
    AgentService,
    _build_streamed_tool_result,
    _build_streamed_tool_progress,
    _get_tool_result_id,
    _build_terminal_tool_results,
    _build_kuncode_completion_message,
    _detect_kuncode_stage,
    _extract_persisted_tool_results,
    _extract_workspace_files,
    _should_emit_tool_progress,
    _tool_output_failed,
    ConfirmedPlanNotebook,
    PlanConfirmationGate,
    create_preview_plan_tool,
)
from agentscope.plan import SubTask
from data_analysis_sandbox import _is_kuncode_failure
from app.services.sandbox_injection import SandboxInjectionService
from app.services.sandbox_cleanup_service import SandboxCleanupService
from app.services.model_factory import RetryingStreamingModel
from app.tasks import _local_tasks, start_local_task


def _load_kuncode_stream_module():
    """Load the standalone sandbox router without importing its package hooks."""
    router_path = Path(__file__).resolve().parents[1] / "sandbox_image" / "routers" / "kuncode_stream.py"
    spec = importlib.util.spec_from_file_location("test_kuncode_stream_router", router_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    async def aclose(self):
        return None


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


class FakeSandboxRecoveredRun:
    async def run_kuncode(self, prompt):
        yield SimpleNamespace(
            content="Traceback (most recent call last):\nValueError: bad range\n",
            metadata=None,
        )
        yield SimpleNamespace(
            content=(
                "Traceback (most recent call last):\nValueError: bad range\n"
                "Done. Generated /workspace/results/recovered.csv\n"
            ),
            metadata={"success": True, "exit_code": 0, "error_code": None},
        )


class TaskRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_stream_retries_a_transient_connection_close_before_tools_run(self):
        class FlakyModel:
            stream = True

            def __init__(self):
                self.calls = 0

            async def __call__(self, *_args, **_kwargs):
                self.calls += 1
                call_number = self.calls

                async def response():
                    if call_number == 1:
                        yield "partial reasoning"
                        raise httpx.RemoteProtocolError("incomplete chunked read")
                    yield "retried reasoning"

                return response()

        model = FlakyModel()
        retrying_model = RetryingStreamingModel(
            model,
            max_retries=1,
            retry_delay_seconds=0,
        )

        response = await retrying_model([], tools=[])
        chunks = [chunk async for chunk in response]

        self.assertEqual(chunks, ["partial reasoning", "retried reasoning"])
        self.assertEqual(model.calls, 2)

    async def test_plan_confirmation_is_scoped_to_exact_preview(self):
        redis = FakeRedis()
        with patch("app.api.kuncode._get_redis", new=AsyncMock(return_value=redis)):
            await create_plan_preview(
                "session-1",
                "plan-current",
                "计划",
                ["步骤一"],
            )

            with self.assertRaises(HTTPException) as context:
                await confirm_plan_preview(
                    "session-1",
                    "plan-stale",
                    "cancel",
                )
            self.assertEqual(context.exception.status_code, 409)

            await confirm_plan_preview(
                "session-1",
                "plan-current",
                "cancel",
            )
            result = await wait_for_plan_confirm(
                "session-1",
                "plan-current",
            )

        self.assertEqual(result["action"], "cancel")
        self.assertEqual(result["preview_id"], "plan-current")
        self.assertNotIn("plan_confirm:session-1", redis.values)

    async def test_plan_confirmation_timeout_cancels_instead_of_auto_confirming(self):
        redis = FakeRedis()
        with patch("app.api.kuncode._get_redis", new=AsyncMock(return_value=redis)):
            await create_plan_preview(
                "session-1",
                "plan-timeout",
                "计划",
                ["步骤一"],
                timeout_seconds=0,
            )
            result = await wait_for_plan_confirm(
                "session-1",
                "plan-timeout",
            )

        self.assertEqual(result["action"], "cancel")
        self.assertTrue(result["timeout"])

    async def test_plan_preview_tool_is_async_and_cancel_revokes_creation(self):
        event_queue = queue.Queue()
        gate = PlanConfirmationGate()
        wait_result = {
            "action": "cancel",
            "name": "",
            "subtasks": [],
        }
        with (
            patch(
                "app.api.kuncode.create_plan_preview",
                new=AsyncMock(),
            ),
            patch(
                "app.api.kuncode.wait_for_plan_confirm",
                new=AsyncMock(return_value=wait_result),
            ),
        ):
            tool = create_preview_plan_tool(
                "session-1",
                event_queue,
                gate,
            )
            self.assertTrue(inspect.iscoroutinefunction(tool))
            response = await tool("计划", ["步骤一"])

        self.assertTrue(response.metadata["cancelled"])
        events = []
        while not event_queue.empty():
            events.append(event_queue.get_nowait())
        self.assertEqual(events[-1]["action"], "cancel")
        self.assertTrue(events[-1]["cancelled"])

        notebook = ConfirmedPlanNotebook(gate, max_subtasks=10)
        blocked = await notebook.create_plan(
            name="计划",
            description="描述",
            expected_outcome="结果",
            subtasks=[
                SubTask(
                    name="步骤一",
                    description="执行步骤一",
                    expected_outcome="完成步骤一",
                ),
            ],
        )
        self.assertTrue(blocked.metadata["confirmation_required"])
        self.assertIsNone(notebook.current_plan)

    async def test_confirmed_preview_accepts_concise_create_plan_task_names(self):
        gate = PlanConfirmationGate()
        gate.approve(
            "PACS操作说明PPT制作",
            [
                "1. 内容提炼与结构化：从 PDF 中提取核心内容",
                "2. PPT制作与输出：创建并保存演示文稿",
            ],
        )
        notebook = ConfirmedPlanNotebook(gate, max_subtasks=10)

        response = await notebook.create_plan(
            name="PACS操作说明PPT制作",
            description="制作说明文档",
            expected_outcome="PPT 文件",
            subtasks=[
                SubTask(
                    name="内容提炼与结构化",
                    description="从 PDF 中提取核心内容",
                    expected_outcome="PPT 大纲",
                ),
                SubTask(
                    name="PPT制作与输出",
                    description="创建并保存演示文稿",
                    expected_outcome="PPT 文件",
                ),
            ],
        )

        self.assertNotIn("confirmation_required", response.metadata or {})
        self.assertIsNotNone(notebook.current_plan)

    async def test_plan_confirmation_accepts_preview_titles_with_detail_or_context(self):
        detailed_gate = PlanConfirmationGate()
        detailed_gate.approve(
            "房产模拟数据生成与可视化看板",
            [
                "1. 生成200条房产模拟数据 - 包含区域、户型、面积和价格字段",
                "2. 制作可视化HTML网页 - 包含图表和交互看板",
            ],
        )

        self.assertTrue(
            detailed_gate.consume(
                "房产模拟数据生成与可视化看板",
                ["生成200条房产模拟数据", "制作可视化HTML网页"],
            )
        )

        contextual_gate = PlanConfirmationGate()
        contextual_gate.approve(
            "房产模拟数据生成与可视化看板",
            [
                "生成200条房产模拟数据",
                "基于模拟数据制作可视化HTML网页",
            ],
        )

        self.assertTrue(
            contextual_gate.consume(
                "房产模拟数据生成与可视化看板",
                ["生成200条房产模拟数据", "制作可视化HTML网页"],
            )
        )

    async def test_plan_confirmation_rejects_unapproved_subtask(self):
        gate = PlanConfirmationGate()
        gate.approve("计划", ["生成模拟数据", "制作可视化网页"])

        self.assertFalse(gate.consume("计划", ["生成模拟数据", "删除原始数据"]))

    async def test_plan_confirmation_accepts_compact_title_with_same_action_and_artifact(self):
        gate = PlanConfirmationGate()
        gate.approve(
            "暑假学习计划文档",
            [
                "设计并生成不同高中生暑假学习计划的Word文档",
                "将Word文档转换为PDF文件",
            ],
        )

        self.assertTrue(
            gate.consume(
                "暑假学习计划文档",
                ["设计并生成Word文档", "转换为PDF文件"],
            )
        )

    async def test_partial_persisted_state_is_loaded_non_strictly(self):
        agent = Mock()
        agent.state_dict.return_value = {
            "memory": {"messages": []},
            "plan_notebook": {
                "storage": {"plans": {}},
                "current_plan": None,
            },
        }
        partial_state = {"plan_notebook": {"current_plan": {"name": "计划"}}}

        AgentService._restore_agent_state(agent, partial_state)

        agent.load_state_dict.assert_called_once_with(
            {
                "memory": {"messages": []},
                "plan_notebook": {
                    "storage": {"plans": {}},
                    "current_plan": {"name": "计划"},
                },
            },
            strict=False,
        )

    async def test_legacy_completed_plan_is_migrated_before_restore(self):
        agent = Mock()
        agent.state_dict.return_value = {
            "memory": {"messages": []},
            "plan_notebook": {
                "storage": {"plans": {"finished": {"state": "todo"}}},
                "current_plan": None,
            },
        }
        legacy_state = {
            "plan_notebook": {
                "storage": {"plans": {"finished": {"state": "completed"}}},
                "current_plan": {
                    "name": "已完成计划",
                    "state": "completed",
                    "subtasks": [{"name": "步骤", "state": "completed"}],
                },
            },
        }

        restored_state = AgentService._restore_agent_state(agent, legacy_state)

        self.assertIsNone(restored_state["plan_notebook"]["current_plan"])
        self.assertEqual(
            restored_state["plan_notebook"]["last_finished_plan"]["state"],
            "done",
        )
        self.assertEqual(
            restored_state["plan_notebook"]["last_finished_plan"]["subtasks"][0]["state"],
            "done",
        )
        self.assertEqual(
            restored_state["plan_notebook"]["storage"]["plans"]["finished"]["state"],
            "done",
        )
        agent.load_state_dict.assert_called_once()

    async def test_finish_plan_retains_terminal_snapshot_for_persistence(self):
        gate = PlanConfirmationGate()
        gate.approve("计划", ["步骤"])
        notebook = ConfirmedPlanNotebook(gate, max_subtasks=10)
        await notebook.create_plan(
            name="计划",
            description="描述",
            expected_outcome="结果",
            subtasks=[
                SubTask(
                    name="步骤",
                    description="执行步骤",
                    expected_outcome="步骤完成",
                ),
            ],
        )

        await notebook.finish_plan("done", "结果已生成")

        self.assertIsNone(notebook.current_plan)
        self.assertIsNotNone(notebook.last_finished_plan)
        self.assertEqual(notebook.last_finished_plan.state, "done")
        self.assertEqual(notebook.last_finished_plan.outcome, "结果已生成")

    async def test_finish_plan_normalizes_legacy_completed_state(self):
        gate = PlanConfirmationGate()
        gate.approve("计划", ["步骤"])
        notebook = ConfirmedPlanNotebook(gate, max_subtasks=10)
        await notebook.create_plan(
            name="计划",
            description="描述",
            expected_outcome="结果",
            subtasks=[SubTask(name="步骤", description="执行步骤", expected_outcome="步骤完成")],
        )

        await notebook.finish_plan("completed", "结果已生成")

        self.assertEqual(notebook.last_finished_plan.state, "done")

    async def test_finished_plan_is_displayed_without_becoming_active_plan(self):
        state = {
            "plan_notebook": {
                "current_plan": None,
                "last_finished_plan": {"name": "已完成计划", "state": "done", "subtasks": []},
            },
        }

        self.assertIsNone(extract_plan_from_state(state))
        finished = extract_last_finished_plan_from_state(state)
        self.assertEqual(plan_to_schema(finished).state, "done")

    async def test_plan_state_update_is_persisted(self):
        state = {"plan_notebook": {"current_plan": {"name": "计划", "state": "todo"}}}

        updated = update_plan_in_state(state, {"state": "done"})

        self.assertEqual(updated["plan_notebook"]["current_plan"]["state"], "done")

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

    async def test_structured_kuncode_outcome_overrides_recovered_tracebacks(self):
        event = _build_streamed_tool_result(
            "call-recovered",
            (
                "Traceback (most recent call last):\n"
                "ValueError: empty range\n"
                "Done. Generated /workspace/results/rental_records.csv\n"
            ),
            outcome={"success": True, "exit_code": 0},
            tool_name="run_kuncode",
        )

        self.assertEqual(event["execution_status"], "completed")
        self.assertEqual(event["stage"], "completed")
        self.assertEqual(event["exit_code"], 0)

        failed = _build_streamed_tool_result(
            "call-failed",
            "Done. Generated /workspace/results/looks-successful.csv",
            outcome={
                "success": False,
                "exit_code": 1,
                "error_code": "KUNCODE_NONZERO_EXIT",
            },
            tool_name="run_kuncode",
        )
        self.assertEqual(failed["execution_status"], "failed")
        self.assertEqual(failed["error_code"], "KUNCODE_NONZERO_EXIT")

    async def test_streamed_tool_progress_remains_running_until_the_final_chunk(self):
        event = _build_streamed_tool_progress(
            "call-1",
            [{"type": "text", "text": "Resolving dependencies\n"}],
            tool_name="run_kuncode",
        )

        self.assertEqual(event["type"], "tool_progress")
        self.assertEqual(event["tool_id"], "call-1")
        self.assertEqual(event["phase"], "progress")
        self.assertEqual(event["execution_status"], "running")
        self.assertEqual(event["stage"], "dependency_checking")

    async def test_kuncode_stage_uses_the_latest_runtime_evidence(self):
        self.assertEqual(
            _detect_kuncode_stage(
                "Resolving dependencies\nResolved, downloaded and extracted [6]\n",
            )[0],
            "dependency_installing",
        )
        self.assertEqual(
            _detect_kuncode_stage(
                "Resolving dependencies\nWrite /workspace/code/build_report.py\n",
            )[0],
            "file_generating",
        )
        self.assertEqual(
            _detect_kuncode_stage(
                "Traceback\nValueError\nEdit /workspace/code/build_report.py\n",
            )[0],
            "repairing",
        )
        self.assertEqual(
            _detect_kuncode_stage("Write /workspace/results/report.xlsx\nVerify workbook structure"),
            ("validating", None),
        )

    async def test_tool_progress_throttles_cumulative_chunks_but_not_stage_changes(self):
        previous = {}
        first = {"tool_id": "call-1", "content": "a" * 100, "stage": "model_processing"}
        self.assertTrue(_should_emit_tool_progress(first, previous))
        self.assertFalse(_should_emit_tool_progress(
            {"tool_id": "call-1", "content": "a" * 200, "stage": "model_processing"},
            previous,
        ))
        self.assertTrue(_should_emit_tool_progress(
            {"tool_id": "call-1", "content": "a" * 200, "stage": "dependency_installing"},
            previous,
        ))
        self.assertTrue(_should_emit_tool_progress(
            {"tool_id": "call-1", "content": "a" * 2500, "stage": "dependency_installing"},
            previous,
        ))

    async def test_sandbox_terminal_result_event_is_json_encoded(self):
        router_module = _load_kuncode_stream_module()
        event = router_module._kuncode_result_event(success=True, exit_code=0)
        payload = json.loads(event.removeprefix("data: ").strip())
        self.assertEqual(payload["event"], "kuncode_result")
        self.assertTrue(payload["success"])
        self.assertEqual(payload["exit_code"], 0)

    async def test_live_tool_result_accepts_agentscope_id_field(self):
        self.assertEqual(
            _get_tool_result_id({"id": "call-from-agentscope"}),
            "call-from-agentscope",
        )
        self.assertEqual(
            _get_tool_result_id({"tool_use_id": "call-from-provider", "id": "legacy"}),
            "call-from-provider",
        )

    async def test_recovered_intermediate_error_keeps_successful_final_status(self):
        recovered = (
            "Traceback (most recent call last):\nFileNotFoundError: report.html\n"
            "Created reports directory\nReport generated successfully!\n"
            "[ERROR] KunCode execution failed. Check the configured agent."
        )

        self.assertFalse(_tool_output_failed(recovered))
        self.assertFalse(_is_kuncode_failure(
            "Traceback\nFileNotFoundError\nReport generated successfully!"
        ))
        self.assertTrue(_tool_output_failed("Traceback\nRuntimeError: failed"))
        self.assertTrue(_is_kuncode_failure("[ERROR] KunCode exited with code 1."))

    async def test_persisted_structured_success_recovers_a_traceback_history(self):
        output = (
            "Traceback (most recent call last):\nValueError: bad range\n"
            "Done. Generated /workspace/results/recovered.csv\n"
            "[[DATAAGENT_KUNCODE_OUTCOME:{\"success\":true,\"exit_code\":0,\"error_code\":null}]]"
        )
        messages = [
            SimpleNamespace(message={
                "type": "plugin_call_output",
                "content": [{
                    "type": "data",
                    "data": {
                        "call_id": "call-recovered",
                        "output": json.dumps([{"type": "text", "text": output}]),
                    },
                }],
            }),
        ]

        events = _extract_persisted_tool_results(
            messages,
            {"call-recovered": "run_kuncode"},
        )

        self.assertEqual(events[0]["execution_status"], "completed")
        self.assertNotIn("DATAAGENT_KUNCODE_OUTCOME", events[0]["content"])

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

    async def test_agent_service_loads_persisted_terminal_results(self):
        db_session = SimpleNamespace(id=1)
        stored_messages = [
            SimpleNamespace(message={
                "type": "plugin_call_output",
                "content": [{
                    "type": "data",
                    "data": {
                        "call_id": "call-1",
                        "output": "analysis complete",
                    },
                }],
            }),
        ]

        with (
            patch.object(
                SessionRepository,
                "get",
                new=AsyncMock(return_value=db_session),
            ),
            patch.object(
                SessionRepository,
                "get_messages",
                new=AsyncMock(return_value=stored_messages),
            ),
        ):
            events = await AgentService()._recover_persisted_terminal_results(
                "user-1",
                "session-1",
                {"call-1": "run_kuncode"},
            )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tool_id"], "call-1")
        self.assertEqual(events[0]["execution_status"], "completed")

    async def test_workspace_path_check_rejects_prefix_collision(self):
        self.assertTrue(_is_within_workspace(r"C:\data\workspace\report.txt", r"C:\data\workspace"))
        self.assertFalse(_is_within_workspace(r"C:\data\workspace-secret\report.txt", r"C:\data\workspace"))

    async def test_delivery_file_listing_hides_internal_execution_artifacts(self):
        self.assertTrue(_is_internal_workspace_item("scripts/build_report.py", is_directory=False))
        self.assertTrue(_is_internal_workspace_item("code", is_directory=True))
        self.assertTrue(_is_internal_workspace_item("results/debug.log", is_directory=False))
        self.assertFalse(_is_internal_workspace_item("results/report.xlsx", is_directory=False))
        self.assertFalse(_is_internal_workspace_item("reports/summary.html", is_directory=False))

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

    async def test_idle_sandbox_release_uses_binding_owner_and_marks_inactive(self):
        cleanup = SandboxCleanupService(idle_timeout_seconds=60)
        cleanup._last_activity["session-1"] = datetime.now() - timedelta(minutes=5)
        cleanup._session_users["session-1"] = "user-1"
        sandbox_service = SimpleNamespace(release=Mock())
        agent_service = SimpleNamespace(
            sandbox_service=sandbox_service,
            _active_agents={},
            _redis=FakeRedis(),
        )

        with (
            patch(
                "app.services.agent_service.AgentService.get_instance",
                return_value=agent_service,
            ),
            patch(
                "app.repositories.file_repo.SandboxBindingRepository.update",
                new=AsyncMock(),
            ) as update_binding,
        ):
            await cleanup._cleanup_idle_sessions()

        sandbox_service.release.assert_called_once_with("session-1", "user-1")
        update_binding.assert_awaited_once_with("session-1", is_active=False)
        self.assertNotIn("session-1", cleanup._last_activity)

    async def test_active_task_prevents_idle_sandbox_release(self):
        cleanup = SandboxCleanupService(idle_timeout_seconds=60)
        cleanup._last_activity["session-1"] = datetime.now() - timedelta(minutes=5)
        cleanup._session_users["session-1"] = "user-1"
        sandbox_service = SimpleNamespace(release=Mock())
        redis = FakeRedis()
        redis.values["session_task:session-1"] = "task-1"
        agent_service = SimpleNamespace(
            sandbox_service=sandbox_service,
            _active_agents={},
            _redis=redis,
        )

        with patch(
            "app.services.agent_service.AgentService.get_instance",
            return_value=agent_service,
        ):
            await cleanup._cleanup_idle_sessions()

        sandbox_service.release.assert_not_called()
        self.assertIn("session-1", cleanup._last_activity)

    async def test_startup_restores_active_sandbox_scope_from_database(self):
        cleanup = SandboxCleanupService()
        binding_time = datetime.now() - timedelta(hours=4)
        session_time = datetime.now() - timedelta(minutes=30)
        binding = SimpleNamespace(
            session_id="session-1",
            user_id="user-1",
            sandbox_id="data-sandbox-1",
            updated_at=binding_time,
        )
        session = SimpleNamespace(
            session_id="session-1",
            user_id="user-1",
            updated_at=session_time,
        )

        with (
            patch(
                "app.repositories.file_repo.SandboxBindingRepository.list_active",
                new=AsyncMock(return_value=[binding]),
            ),
            patch(
                "app.repositories.session_repo.SessionRepository.list_by_session_ids",
                new=AsyncMock(return_value=[session]),
            ),
        ):
            await cleanup._restore_from_persisted_bindings()

        self.assertEqual(cleanup._session_users["session-1"], "user-1")
        self.assertEqual(cleanup._last_activity["session-1"], session_time)

    async def test_orphan_cleanup_uses_labels_and_preserves_bound_or_recent_sandboxes(self):
        cleanup = SandboxCleanupService(idle_timeout_seconds=60)
        cleanup._session_sandbox_ids["session-1"] = "data-sandbox-bound"
        old_created = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        recent_created = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        labels = json.dumps({
            "maintainer": "kuncode-data-analysis-sandbox",
            "description": "Data Analysis Sandbox with KunCode AI",
        })
        commands = []

        def run_docker(arguments):
            commands.append(arguments)
            if arguments[0] == "ps":
                return "bound-id\norphan-id\nrecent-id\n"
            if arguments[0] == "inspect":
                container_id = arguments[-1]
                if container_id == "bound-id":
                    return f"bound-id|/data-sandbox-bound|{old_created}|{labels}\n"
                if container_id == "orphan-id":
                    return f"orphan-id|/data-sandbox-orphan|{old_created}|{labels}\n"
                return f"recent-id|/data-sandbox-recent|{recent_created}|{labels}\n"
            if arguments[0] == "rm":
                return "orphan-id\n"
            self.fail(f"Unexpected Docker arguments: {arguments}")

        with (
            patch.object(cleanup, "_has_any_active_task", new=AsyncMock(return_value=False)),
            patch.object(cleanup, "_run_docker", side_effect=run_docker),
        ):
            await cleanup._cleanup_orphan_runtime_containers()

        self.assertIn(["rm", "-f", "orphan-id"], commands)

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
        persisted_output = json.loads(output_data["output"])[0]["text"]
        self.assertTrue(persisted_output.startswith("final result"))
        self.assertIn("DATAAGENT_KUNCODE_OUTCOME", persisted_output)

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

    async def test_direct_kuncode_marks_a_recovered_run_completed(self):
        with patch.object(SessionRepository, "get", new=AsyncMock(return_value=None)):
            service = AgentService.__new__(AgentService)
            events = [
                event
                async for event in service._direct_run_kuncode(
                    FakeSandboxRecoveredRun(),
                    "user-1",
                    "session-1",
                    "create recovered file",
                    "create recovered file",
                )
            ]

        tool_events = [event for event in events if event["type"] == "tool_result"]
        self.assertEqual(len(tool_events), 1)
        self.assertEqual(tool_events[0]["execution_status"], "completed")
        self.assertEqual(tool_events[0]["stage"], "completed")
        self.assertIn("recovered.csv", events[-1]["content"])
