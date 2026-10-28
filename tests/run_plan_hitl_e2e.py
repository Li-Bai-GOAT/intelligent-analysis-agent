# -*- coding: utf-8 -*-
"""真实链路端到端验证：计划 HITL 全流程 + 长任务 SSE 心跳。

它验证的两个缺陷：

- **缺陷 A**：真实模型调用 ``preview_plan`` → 用户确认 → ``create_plan``。
  断言"只出现一次 ``plan_preview``"（重复确认弹窗消失），并且计划真的落库。
- **缺陷 B**：整条流式响应里静默期不会超过心跳间隔太多，
  断言相邻两个字节块的最大间隔 < 2×心跳周期，且过程中收到 ``: keep-alive``。

默认不跑（需要真实服务、模型、Redis、PostgreSQL）：

    python tests/run_plan_hitl_e2e.py --base-url http://127.0.0.1:8090

退出码 0 表示所有断言成立。
"""

import argparse
import asyncio
import json
import os
import sys
import time
import uuid

import httpx

DEFAULT_PROMPT = (
    "帮我制定一个数据分析计划并先让我确认：读取 /workspace 下的示例数据文件，"
    "统计每一列的缺失率，最后给出一段结论。请严格按流程：先调用 preview_plan "
    "把计划给我确认，我确认后立刻调用 create_plan 创建计划。"
    "创建完计划就结束本轮回复，不要开始执行子任务。"
)


class Check:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def expect(self, condition: bool, message: str) -> None:
        print(f"  [{'PASS' if condition else 'FAIL'}] {message}", flush=True)
        if not condition:
            self.failures.append(message)


async def _register_and_login(client: httpx.AsyncClient, base: str) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    username = f"e2e_plan_{suffix}"
    password = "E2e#12345678"
    register = await client.post(
        f"{base}/api/auth/register", json={"username": username, "password": password}
    )
    register.raise_for_status()
    login = await client.post(
        f"{base}/api/auth/login", json={"username": username, "password": password}
    )
    login.raise_for_status()
    return username, login.json()["access_token"]


async def run(
    base: str,
    prompt: str,
    heartbeat: float,
    timeout: float,
    observe_seconds: float,
) -> int:
    check = Check()
    preview_events: list[dict] = []
    confirmed_events: list[dict] = []
    type_counter: dict[str, int] = {}
    gaps: list[float] = []
    heartbeat_count = 0
    plan_data = None
    plan_ready = False
    stream_ended = False
    observed_enough = False

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        username, token = await _register_and_login(client, base)
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        print(f"用户 {username} 已登录", flush=True)

        session = await client.post(f"{base}/api/conversation/sessions", headers=headers)
        session.raise_for_status()
        session_id = session.json()["session_id"]
        print(f"会话 {session_id}", flush=True)

        task = await client.post(
            f"{base}/api/conversation/async",
            headers=headers,
            json={"session_id": session_id, "message": prompt},
        )
        task.raise_for_status()
        task_id = task.json()["task_id"]
        print(f"任务 {task_id} 已提交，开始订阅流", flush=True)

        last_seen = time.monotonic()
        observe_until = 0.0

        async with client.stream(
            "GET",
            f"{base}/api/conversation/stream/{task_id}",
            headers={
                **headers,
                "Accept": "text/event-stream",
                "Last-Event-ID": "0",
            },
            timeout=httpx.Timeout(timeout, connect=30.0),
        ) as response:
            response.raise_for_status()
            buffer = ""
            async for chunk in response.aiter_text():
                now = time.monotonic()
                gaps.append(now - last_seen)
                last_seen = now
                buffer += chunk

                while "\n\n" in buffer:
                    raw, buffer = buffer.split("\n\n", 1)
                    if not raw.strip():
                        continue
                    if raw.lstrip().startswith(":"):
                        heartbeat_count += 1
                        print(f"  · 心跳 (第 {len(gaps)} 块)", flush=True)
                        continue

                    payload = "\n".join(
                        line[5:].lstrip()
                        for line in raw.splitlines()
                        if line.startswith("data:")
                    )
                    if not payload:
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    event_type = str(event.get("type"))
                    type_counter[event_type] = type_counter.get(event_type, 0) + 1
                    print(f"  ← {event_type}", flush=True)

                    if event_type == "plan_preview":
                        preview_events.append(event)
                        # 模拟前端点击"确认"：把面板里的内容原样提交
                        confirm = await client.post(
                            f"{base}/api/kuncode/{session_id}/plan/confirm/"
                            f"{event['preview_id']}",
                            headers=headers,
                            json={
                                "action": "confirm",
                                "name": event.get("name", ""),
                                "subtasks": [
                                    item["name"]
                                    for item in event.get("subtasks", [])
                                    if isinstance(item, dict) and item.get("name")
                                ],
                            },
                        )
                        print(
                            f"  → 确认计划 {event['preview_id']}: {confirm.status_code}",
                            flush=True,
                        )
                        confirm.raise_for_status()
                    elif event_type == "plan_confirmed":
                        confirmed_events.append(event)
                    elif event_type == "end":
                        stream_ended = True
                    elif event_type == "error":
                        print(f"  !! 错误事件: {event.get('content')}", flush=True)

                # 计划落库后继续观察一段时间收集心跳证据即可收尾；
                # 不必等整个任务执行完（执行本身可能持续很久）。
                if confirmed_events and not plan_ready:
                    resp = await client.get(
                        f"{base}/api/plans/{session_id}", headers=headers
                    )
                    body = resp.json() if resp.status_code == 200 else None
                    if body and body.get("subtasks"):
                        plan_data = body
                        plan_ready = True
                        observe_until = time.monotonic() + observe_seconds
                        print(
                            f"  ✓ 计划已落库，继续观察 {observe_seconds:.0f}s 收集心跳",
                            flush=True,
                        )

                if plan_ready and time.monotonic() >= observe_until:
                    print("  → 观察窗口结束，主动断开流", flush=True)
                    observed_enough = True
                if stream_ended or observed_enough:
                    break

        print("\n=== 流统计 ===", flush=True)
        print(f"事件类型分布: {type_counter}", flush=True)
        print(f"心跳帧: {heartbeat_count}", flush=True)
        if gaps:
            print(
                f"最大静默间隔: {max(gaps):.2f}s / 心跳周期 {heartbeat:.1f}s",
                flush=True,
            )

        if plan_data is None:
            resp = await client.get(f"{base}/api/plans/{session_id}", headers=headers)
            plan_data = resp.json() if resp.status_code == 200 else None
        print(
            f"计划接口: {json.dumps(plan_data, ensure_ascii=False)[:400]}",
            flush=True,
        )

        cleanup = await client.delete(f"{base}/api/sessions/{session_id}", headers=headers)
        print(f"会话清理: {cleanup.status_code}", flush=True)

    print("\n=== 断言 ===", flush=True)
    check.expect(
        len(preview_events) == 1,
        f"只出现 1 次 plan_preview（实际 {len(preview_events)} 次）",
    )
    check.expect(len(confirmed_events) >= 1, "收到了 plan_confirmed 事件")
    check.expect(plan_ready, "计划已落库（GET /api/plans 返回子任务）")
    if preview_events and plan_data:
        approved = preview_events[0].get("subtasks") or []
        created = plan_data.get("subtasks") or []
        check.expect(
            len(approved) == len(created),
            f"落库子任务数与确认内容一致（确认 {len(approved)} / 落库 {len(created)}）",
        )
    check.expect(heartbeat_count >= 1, f"静默期收到心跳帧（实际 {heartbeat_count} 个）")
    if gaps:
        check.expect(
            max(gaps) < max(heartbeat * 2, 2.0),
            f"相邻数据块间隔不超过 2×心跳周期（实际最大 {max(gaps):.2f}s）",
        )
    if stream_ended:
        print("  · 补充：任务流随后以 end 结束", flush=True)

    if check.failures:
        print(f"\n失败 {len(check.failures)} 项:", flush=True)
        for item in check.failures:
            print(f"  - {item}", flush=True)
        return 1
    print("\n全部通过", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("E2E_BASE_URL", "http://127.0.0.1:8090"),
    )
    parser.add_argument("--prompt", default=os.getenv("E2E_PROMPT", DEFAULT_PROMPT))
    parser.add_argument(
        "--heartbeat",
        type=float,
        default=float(os.getenv("SSE_HEARTBEAT_SECONDS", "15")),
        help="服务端配置的心跳周期，用于判断静默间隔是否异常",
    )
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument(
        "--observe",
        type=float,
        default=45.0,
        help="计划落库后继续观察心跳的秒数",
    )
    args = parser.parse_args()
    return asyncio.run(
        run(
            args.base_url.rstrip("/"),
            args.prompt,
            args.heartbeat,
            args.timeout,
            args.observe,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
