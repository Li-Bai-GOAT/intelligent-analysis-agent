# -*- coding: utf-8 -*-
"""SSE 心跳与帧编码。

长任务经常连续几十秒不产生任何 token（模型思考、沙箱执行、KunCode 终端）。
代理层在连接静默期间会判定后端失联并断开——nginx 默认 ``proxy_read_timeout``
是 60s，多数网关是 90s——前端只能看到"任务流意外结束"，还在跑的任务就丢了。

心跳用 SSE 注释帧（``: keep-alive``）保持字节流动。注释帧没有 data 段，
``EventSource`` 和手写解析器都会直接忽略它，所以能安全地混在业务事件之间。
"""

import asyncio
import json
from typing import AsyncIterable, AsyncIterator, Optional

HEARTBEAT_FRAME = ": keep-alive\n\n"

# 下限只是为了防止配置写成 0 后退化成"每帧都心跳"；生产默认 15s。
MIN_HEARTBEAT_SECONDS = 0.05


def encode_sse_event(payload: dict, event_id: Optional[str] = None) -> str:
    """把一个事件对象编码成 SSE 帧。"""
    frame = ""
    if event_id:
        frame += f"id: {event_id}\n"
    frame += f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    return frame


async def iter_with_heartbeat(
    source: AsyncIterable,
    interval: float,
) -> AsyncIterator[Optional[object]]:
    """转发 ``source`` 的元素；静默超过 ``interval`` 秒时产出 ``None``。

    调用方收到 ``None`` 就写一帧心跳，收到其它值就写业务帧。

    这里刻意不用 ``asyncio.wait_for``：它在超时时会 cancel 掉 ``__anext__``，
    CancelledError 会打进内层异步生成器把它关闭——也就是"心跳把模型流杀了"。
    改用 ``asyncio.wait`` 只判断"这一轮有没有结果"，超时后任务保留，下一轮
    继续等同一个 ``__anext__``，源生成器始终不被打断。
    """
    # ``__aiter__`` 只调用一次：对可重复迭代的对象（每次返回新生成器）而言，
    # 每次取下一个元素都重建迭代器会让流永远停在第一个元素上。
    iterator = source.__aiter__()
    unresolved: Optional[asyncio.Future] = None
    try:
        while True:
            if unresolved is None:
                unresolved = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({unresolved}, timeout=interval)
            if unresolved not in done:
                yield None
                continue

            finished, unresolved = unresolved, None
            if finished.cancelled():
                return
            # 用 exception() 而不是 result()：StopAsyncIteration 若在这个异步
            # 生成器的栈帧里抛出，会被 CPython 改写成 RuntimeError；先取出异常
            # 再判断，结束路径就只是普通的 return。
            error = finished.exception()
            if error is not None:
                if isinstance(error, StopAsyncIteration):
                    return
                raise error
            yield finished.result()
    finally:
        # 消费方提前退出（客户端断开）时，别把源生成器留在挂起状态。
        if unresolved is not None and not unresolved.done():
            unresolved.cancel()
            try:
                await unresolved
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            except Exception:  # noqa: BLE001 - 清理阶段不再向上抛
                pass
