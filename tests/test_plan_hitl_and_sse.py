# -*- coding: utf-8 -*-
"""缺陷 A / B 的回归测试。

缺陷 A：用户确认计划后，``create_plan`` 被闸门误判为"未确认"，模型按拒绝提示
        重新 ``preview_plan``，前端于是对同一份计划弹第二次确认。
缺陷 B：长任务 SSE 静默超过代理超时（90s）后连接被断开，前端看到"任务流意外结束"。

这里同时锁死"修好了"和"没有为了修好而放水"：名称差异可以通过，但子任务被替换、
数量不符、用户已取消，都必须继续拒绝。
"""

import asyncio
import json
import queue
import unittest
from unittest.mock import AsyncMock, patch

from agentscope.plan import SubTask

from app.api import conversation as conversation_api
from app.services.agent_service import (
    ConfirmedPlanNotebook,
    PlanConfirmationGate,
    create_preview_plan_tool,
)
from app.utils.sse import HEARTBEAT_FRAME, encode_sse_event, iter_with_heartbeat


def _drain(hitl_queue: "queue.Queue") -> list[dict]:
    events = []
    while not hitl_queue.empty():
        events.append(hitl_queue.get_nowait())
    return events


def _subtask(name: str) -> SubTask:
    return SubTask(name=name, description=f"执行{name}", expected_outcome=f"完成{name}")


class PlanGateIdentityTests(unittest.TestCase):
    """闸门的判定口径：子任务是实质身份，名称不是。"""

    def test_name_difference_does_not_reject_a_matching_plan(self):
        gate = PlanConfirmationGate()
        gate.approve("华东区销售分析计划", ["读取销售明细", "生成区域对比图表"])

        self.assertTrue(gate.consume("华东区销售分析", ["读取销售明细", "生成区域对比图表"]))

    def test_user_renamed_plan_still_creates(self):
        """用户在前端把名字改过，模型按原名调用也必须通过。"""
        gate = PlanConfirmationGate()
        gate.approve("用户改过的名字", ["清洗数据", "输出结论"])

        self.assertTrue(gate.consume("模型原来的名字", ["清洗数据", "输出结论"]))

    def test_subtask_count_mismatch_is_still_rejected(self):
        gate = PlanConfirmationGate()
        gate.approve("计划", ["读取数据", "生成图表"])

        self.assertFalse(gate.consume("计划", ["读取数据"]))
        self.assertFalse(gate.consume("计划", ["读取数据", "生成图表", "多发一封邮件"]))

    def test_substituted_subtask_is_still_rejected(self):
        gate = PlanConfirmationGate()
        gate.approve("计划", ["读取数据", "生成图表"])

        self.assertFalse(gate.consume("计划", ["读取数据", "删除生产数据"]))

    def test_consumed_approval_cannot_be_reused(self):
        gate = PlanConfirmationGate()
        gate.approve("计划", ["读取数据"])

        self.assertTrue(gate.consume("计划", ["读取数据"]))
        self.assertFalse(gate.consume("计划", ["读取数据"]))

    def test_cancelled_gate_rejects_everything(self):
        gate = PlanConfirmationGate()
        gate.approve("计划", ["读取数据"])
        gate.cancel()

        self.assertFalse(gate.consume("计划", ["读取数据"]))
        self.assertTrue(gate.is_cancelled)


class ConfirmedPlanNotebookTests(unittest.IsolatedAsyncioTestCase):
    """拒绝提示必须把模型引回 ``create_plan``，而不是重新预览。"""

    async def test_rejection_tells_the_model_to_retry_create_plan_not_preview(self):
        gate = PlanConfirmationGate()
        gate.approve("销售分析计划", ["读取数据", "生成图表"])
        notebook = ConfirmedPlanNotebook(gate, max_subtasks=10)

        response = await notebook.create_plan(
            name="销售分析计划",
            description="描述",
            expected_outcome="结论",
            subtasks=[_subtask("读取数据"), _subtask("删除生产数据")],
        )

        text = response.content[0]["text"]
        self.assertIn("Do NOT call preview_plan again", text)
        self.assertNotIn("Call preview_plan and wait for confirmation", text)
        # 必须把用户确认过的内容原样回给模型，否则它只能瞎猜
        self.assertIn("读取数据", text)
        self.assertIn("生成图表", text)
        self.assertTrue(response.metadata["confirmation_required"])
        self.assertIsNone(notebook.current_plan)

    async def test_cancelled_plan_instruction_does_not_ask_for_another_preview(self):
        gate = PlanConfirmationGate()
        gate.cancel()
        notebook = ConfirmedPlanNotebook(gate, max_subtasks=10)

        response = await notebook.create_plan(
            name="计划",
            description="描述",
            expected_outcome="结论",
            subtasks=[_subtask("读取数据")],
        )

        text = response.content[0]["text"]
        self.assertIn("cancelled", text)
        self.assertIn("Do not call preview_plan again", text)

    async def test_name_mismatch_creates_the_plan(self):
        """缺陷 A 的原始复现路径：名称不一致但内容一致，必须成功建计划。"""
        gate = PlanConfirmationGate()
        gate.approve("华东区销售分析计划", ["读取销售明细", "生成区域对比图表"])
        notebook = ConfirmedPlanNotebook(gate, max_subtasks=10)

        response = await notebook.create_plan(
            name="华东区销售分析",
            description="描述",
            expected_outcome="结论",
            subtasks=[_subtask("读取销售明细"), _subtask("生成区域对比图表")],
        )

        self.assertNotIn("confirmation_required", response.metadata or {})
        self.assertIsNotNone(notebook.current_plan)


class PreviewIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    """同一轮内重复 preview_plan 不得再弹一次确认。"""

    async def test_repeated_preview_does_not_push_a_second_preview_event(self):
        hitl_queue: queue.Queue = queue.Queue()
        gate = PlanConfirmationGate()
        wait_result = {
            "action": "confirm",
            "name": "销售分析计划",
            "subtasks": ["读取数据", "生成图表"],
        }

        with (
            patch("app.api.kuncode.create_plan_preview", new=AsyncMock()),
            patch(
                "app.api.kuncode.wait_for_plan_confirm",
                new=AsyncMock(return_value=wait_result),
            ) as waiter,
        ):
            tool = create_preview_plan_tool("session-1", hitl_queue, gate)
            first = await tool("销售分析计划", ["读取数据", "生成图表"])
            second = await tool("销售分析计划", ["读取数据", "生成图表"])

        self.assertEqual(waiter.await_count, 1, "第二次预览不应再等待用户确认")

        events = _drain(hitl_queue)
        preview_events = [e for e in events if e["type"] == "plan_preview"]
        self.assertEqual(len(preview_events), 1, f"重复弹窗: {events}")

        self.assertEqual(first.content[0]["text"], second.content[0]["text"])
        self.assertTrue(second.metadata["success"])

    async def test_repeated_preview_keeps_the_approval_usable(self):
        """返回缓存后闸门里的确认仍然有效，create_plan 不会因为缓存而失效。"""
        hitl_queue: queue.Queue = queue.Queue()
        gate = PlanConfirmationGate()
        wait_result = {
            "action": "confirm",
            "name": "销售分析计划",
            "subtasks": ["读取数据", "生成图表"],
        }

        with (
            patch("app.api.kuncode.create_plan_preview", new=AsyncMock()),
            patch(
                "app.api.kuncode.wait_for_plan_confirm",
                new=AsyncMock(return_value=wait_result),
            ),
        ):
            tool = create_preview_plan_tool("session-1", hitl_queue, gate)
            await tool("销售分析计划", ["读取数据", "生成图表"])
            await tool("销售分析计划", ["读取数据", "生成图表"])

        notebook = ConfirmedPlanNotebook(gate, max_subtasks=10)
        response = await notebook.create_plan(
            name="销售分析计划",
            description="描述",
            expected_outcome="结论",
            subtasks=[_subtask("读取数据"), _subtask("生成图表")],
        )
        self.assertNotIn("confirmation_required", response.metadata or {})

    async def test_different_plan_still_asks_the_user(self):
        hitl_queue: queue.Queue = queue.Queue()
        gate = PlanConfirmationGate()
        results = [
            {"action": "confirm", "name": "计划A", "subtasks": ["步骤一"]},
            {"action": "confirm", "name": "计划B", "subtasks": ["步骤二"]},
        ]

        with (
            patch("app.api.kuncode.create_plan_preview", new=AsyncMock()),
            patch(
                "app.api.kuncode.wait_for_plan_confirm",
                new=AsyncMock(side_effect=results),
            ) as waiter,
        ):
            tool = create_preview_plan_tool("session-1", hitl_queue, gate)
            await tool("计划A", ["步骤一"])
            await tool("计划B", ["步骤二"])

        self.assertEqual(waiter.await_count, 2)
        preview_events = [e for e in _drain(hitl_queue) if e["type"] == "plan_preview"]
        self.assertEqual(len(preview_events), 2)


class _SlowSource:
    def __init__(self, items, delay):
        self._items = list(items)
        self._delay = delay

    async def __aiter__(self):
        for item in self._items:
            await asyncio.sleep(self._delay)
            yield item


class HeartbeatTests(unittest.IsolatedAsyncioTestCase):
    """心跳必须"能发得出去"，而且**不能把源生成器打断**。"""

    async def test_silence_produces_heartbeat_frames(self):
        source = _SlowSource(["a", "b"], delay=0.2)
        frames = [item async for item in iter_with_heartbeat(source, 0.02)]

        heartbeats = [f for f in frames if f is None]
        payloads = [f for f in frames if f is not None]
        self.assertGreaterEqual(len(heartbeats), 4, frames)
        self.assertEqual(payloads, ["a", "b"], "心跳期间不得丢数据或改变顺序")

    async def test_fast_source_emits_no_heartbeat(self):
        async def fast():
            for item in ("a", "b", "c"):
                yield item

        frames = [item async for item in iter_with_heartbeat(fast(), 5.0)]
        self.assertEqual(frames, ["a", "b", "c"])

    async def test_source_is_not_cancelled_by_heartbeats(self):
        """回归 90s 超时的根因：用 wait_for 实现会 cancel 掉 __anext__。"""
        closed = {"value": False, "completed": False}

        async def guarded():
            try:
                for index in range(3):
                    await asyncio.sleep(0.06)
                    yield index
                closed["completed"] = True
            finally:
                closed["value"] = True

        frames = [item async for item in iter_with_heartbeat(guarded(), 0.01)]

        self.assertEqual([f for f in frames if f is not None], [0, 1, 2])
        self.assertTrue(closed["completed"], "源生成器被心跳提前终止了")

    async def test_heartbeat_frame_is_a_valid_sse_comment(self):
        self.assertTrue(HEARTBEAT_FRAME.startswith(":"))
        self.assertTrue(HEARTBEAT_FRAME.endswith("\n\n"))
        self.assertNotIn("data:", HEARTBEAT_FRAME)

    async def test_encode_event_keeps_event_id_and_chinese_text(self):
        frame = encode_sse_event({"type": "text", "content": "完成"}, event_id="12-0")
        self.assertTrue(frame.startswith("id: 12-0\n"))
        self.assertIn("完成", frame)
        payload = json.loads(frame.split("data: ", 1)[1].strip())
        self.assertEqual(payload["content"], "完成")

    async def test_consumer_break_cancels_the_pending_source_read(self):
        """客户端断开时，不能把源生成器留在挂起状态。"""
        state = {"closed": False}

        async def endless():
            try:
                while True:
                    await asyncio.sleep(0.05)
                    yield "tick"
            finally:
                state["closed"] = True

        stream = iter_with_heartbeat(endless(), 0.01)
        for _ in range(3):
            await stream.__anext__()
        await stream.aclose()
        await asyncio.sleep(0.1)
        self.assertTrue(state["closed"])


class _FakeStreamRequest:
    def __init__(self, disconnect_after: int | None = None):
        self.calls = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self.calls += 1
        if self._disconnect_after is None:
            return False
        return self.calls > self._disconnect_after


class StreamFramesTests(unittest.IsolatedAsyncioTestCase):
    """/api/conversation 的帧封装：心跳与业务帧交替，且断开后停止产出。"""

    async def test_frames_interleave_heartbeat_and_payload(self):
        # 心跳下限是 0.05s（配置里写更小会被夹住），所以这里让静默期拉到 0.3s，
        # 稳定拿到多次心跳。
        source = _SlowSource([{"type": "text", "content": "hi"}], delay=0.3)
        request = _FakeStreamRequest()

        with patch.object(conversation_api.settings, "SSE_HEARTBEAT_SECONDS", 0.05):
            frames = [
                frame
                async for frame in conversation_api._stream_frames(
                    source, request, encode_sse_event
                )
            ]

        self.assertGreaterEqual(sum(1 for f in frames if f == HEARTBEAT_FRAME), 2)
        self.assertTrue(any('"hi"' in frame for frame in frames))
        # 心跳必须出现在业务帧之前，且业务帧本身没有被心跳挤掉
        self.assertEqual(frames[-1].count("hi"), 1)

    async def test_disconnect_stops_the_stream(self):
        source = _SlowSource([{"n": index} for index in range(20)], delay=0.0)
        request = _FakeStreamRequest(disconnect_after=3)

        with patch.object(conversation_api.settings, "SSE_HEARTBEAT_SECONDS", 5.0):
            frames = [
                frame
                async for frame in conversation_api._stream_frames(
                    source, request, encode_sse_event
                )
            ]

        self.assertLessEqual(len(frames), 3)


if __name__ == "__main__":
    unittest.main()
