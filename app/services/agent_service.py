# -*- coding: utf-8 -*-
"""
智能体服务

封装智能体创建、对话执行等核心逻辑
"""

import uuid
import json
import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Optional, AsyncGenerator, Dict, Any, List
from datetime import datetime, timezone


logger = logging.getLogger(__name__)


class InterruptMonitor:
    """独立的中断监控器，在后台定期检查中断信号，并能取消绑定的任务"""
    
    def __init__(self, redis_client, session_id: str, interval: float = 0.5):
        self._redis = redis_client
        self._session_id = session_id
        self._interval = interval
        self._interrupted = asyncio.Event()
        self._monitor_task: Optional[asyncio.Task] = None
        self._bound_task: Optional[asyncio.Task] = None
    
    async def _monitor_loop(self):
        """后台监控循环，检测到中断时取消绑定的任务"""
        interrupt_key = f"agent_interrupt:{self._session_id}"
        try:
            while not self._interrupted.is_set():
                value = await self._redis.get(interrupt_key)
                if value:
                    value_str = value.decode() if isinstance(value, bytes) else str(value)
                    if value_str == "1":
                        await self._redis.delete(interrupt_key)
                        self._interrupted.set()
                        logger.info(f"[中断监控] 检测到中断信号: {self._session_id}")
                        # 取消绑定的任务（如果有）
                        if self._bound_task and not self._bound_task.done():
                            self._bound_task.cancel()
                            logger.info(f"[中断监控] 已取消执行任务: {self._session_id}")
                        break
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            pass
    
    def bind_task(self, task: asyncio.Task):
        """绑定一个任务，中断时会取消它"""
        self._bound_task = task
    
    def start(self):
        """启动监控"""
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())
    
    def stop(self):
        """停止监控"""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            self._monitor_task = None
        self._bound_task = None
    
    def is_interrupted(self) -> bool:
        """检查是否已中断"""
        return self._interrupted.is_set()
    
    async def wait_interrupt(self, timeout: float = None) -> bool:
        """等待中断信号，返回是否被中断"""
        try:
            await asyncio.wait_for(self._interrupted.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


# 需要从模型输出中过滤的特殊标记
MODEL_SPECIAL_TOKENS = [
    "<｜end▁of▁thinking｜>",
    "<|end_of_thinking|>",
]

def filter_model_tokens(text: str) -> str:
    """过滤模型输出中的特殊标记"""
    if not text:
        return text
    for token in MODEL_SPECIAL_TOKENS:
        text = text.replace(token, "")
    return text


def _extract_tool_response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return "" if content is None else str(content)


_WORKSPACE_FILE_PATTERN = re.compile(r"(?:^|[^\w/])/?workspace/([^\s`'\"<>|]+)")


def _extract_workspace_files(output: str) -> list[str]:
    """Return unique, workspace-relative file paths mentioned by KunCode."""
    files: list[str] = []
    for match in _WORKSPACE_FILE_PATTERN.finditer(output or ""):
        path = match.group(1).rstrip(".,;:)]}")
        parts = [part for part in path.split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            continue
        normalized = "/".join(parts)
        if normalized.startswith("data/uploads/"):
            continue
        if normalized not in files:
            files.append(normalized)
    return files


def _build_kuncode_completion_message(files: list[str]) -> str:
    if not files:
        return "KunCode 已执行完成。请在右上角的“文件”页查看本次会话中的文件。"
    file_list = "\n".join(f"- `{path}`" for path in files)
    return (
        "KunCode 已执行完成，并生成以下文件：\n"
        f"{file_list}\n\n"
        "文件已同步到右上角的“文件”页，可在那里打开、预览或下载。"
    )


def _build_terminal_tool_results(
    pending_tool_calls: Dict[str, str],
    *,
    status: str = "failed",
) -> list[dict]:
    """Close tool calls that never received a real streamed result."""
    cancelled = status == "cancelled"
    return [
        {
            "type": "tool_result",
            "content": (
                f"[CANCELLED] {tool_name or '工具'} 已中断。"
                if cancelled
                else f"[ERROR] {tool_name or '工具'} 未返回完整执行结果。"
            ),
            "tool_id": tool_id,
            "phase": "cancelled" if cancelled else "failed",
            "execution_status": "cancelled" if cancelled else "failed",
        }
        for tool_id, tool_name in pending_tool_calls.items()
        if tool_id
    ]


def _build_streamed_tool_result(tool_id: str, output: Any) -> dict:
    """Normalize AgentScope tool outputs into the terminal SSE contract."""
    if isinstance(output, str):
        result_text = output
    elif output is None:
        result_text = ""
    else:
        result_text = json.dumps(output, ensure_ascii=False)

    is_error = any(
        marker in result_text.lower()
        for marker in ("[error]", "traceback", "exception", "failed")
    )
    return {
        "type": "tool_result",
        "content": result_text,
        "tool_id": tool_id,
        "phase": "failed" if is_error else "completed",
        "execution_status": "failed" if is_error else "completed",
    }


def _extract_persisted_tool_results(
    messages: list[Any],
    pending_tool_calls: Dict[str, str],
) -> list[dict]:
    """Recover terminal results that AgentScope persisted without streaming."""
    recovered: list[dict] = []
    recovered_ids: set[str] = set()

    for record in messages:
        message = record if isinstance(record, dict) else getattr(record, "message", {})
        if not isinstance(message, dict):
            continue
        msg_type = message.get("type") or message.get("msg_type")
        if msg_type not in ("plugin_call_output", "plugin_call_result"):
            continue

        for item in message.get("content", []):
            if not isinstance(item, dict) or item.get("type") != "data":
                continue
            data = item.get("data", {})
            if not isinstance(data, dict):
                continue
            tool_id = str(data.get("call_id") or "")
            if (
                not tool_id
                or tool_id not in pending_tool_calls
                or tool_id in recovered_ids
            ):
                continue
            recovered.append(
                _build_streamed_tool_result(tool_id, data.get("output"))
            )
            recovered_ids.add(tool_id)

    return recovered


import redis.asyncio as aioredis

from agentscope.agent import ReActAgent
from agentscope.message import Msg
from agentscope.plan import PlanNotebook
from agentscope.tool import Toolkit, ToolResponse
from agentscope.pipeline import stream_printing_messages

from app.services.model_factory import ModelFactory

from agentscope_runtime.engine.services.sandbox import SandboxService
from app.services.compressed_memory import CompressedSessionMemory
from agentscope_runtime.adapters.agentscope.tool import sandbox_tool_adapter
import functools
import inspect


def _is_sandbox_container_error(error_msg: str) -> bool:
    """检测是否为沙箱容器丢失错误"""
    error_lower = error_msg.lower()
    return ("no container found" in error_lower or 
            ("container" in error_lower and "not found" in error_lower) or
            "500 server error" in error_lower)


def safe_sandbox_tool_adapter(func):
    """安全的沙箱工具适配器：增加容器丢失错误处理
    
    在标准 sandbox_tool_adapter 基础上，捕获容器丢失错误并返回友好提示
    """
    from agentscope.message import TextBlock
    from agentscope.tool import ToolResponse
    
    wrapped = sandbox_tool_adapter(func)
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return wrapped(*args, **kwargs)
        except Exception as e:
            error_msg = str(e)
            if _is_sandbox_container_error(error_msg):
                return ToolResponse(
                    content=[TextBlock(text=f"Error: 沙箱容器已断开连接，请重新发送消息以重建沙箱环境。原始错误: {error_msg}")],
                )
            raise
    return wrapper


def streaming_sandbox_tool_adapter(func):
    """流式工具适配器：支持同步/异步生成器函数
    
    如果工具函数返回生成器，直接返回；否则使用标准 sandbox_tool_adapter
    增加沙箱容器丢失错误检测，返回友好提示
    """
    from agentscope.message import TextBlock
    from agentscope.tool import ToolResponse
    
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            # 异步函数需要 await
            if inspect.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            elif inspect.isasyncgenfunction(func):
                # 异步生成器函数直接调用返回异步生成器
                return func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            # 生成器直接返回
            if inspect.isgenerator(result) or inspect.isasyncgen(result):
                return result
            if isinstance(result, ToolResponse):
                return result
            return sandbox_tool_adapter(func)(*args, **kwargs)
        except Exception as e:
            error_msg = str(e)
            if _is_sandbox_container_error(error_msg):
                return ToolResponse(
                    content=[TextBlock(text=f"Error: 沙箱容器已断开连接，请重新发送消息以重建沙箱环境。原始错误: {error_msg}")],
                )
            raise
    return wrapper


def _run_async(coro):
    """安全运行异步协程，处理嵌套事件循环情况"""
    import asyncio
    try:
        asyncio.get_running_loop()
        # 已在事件循环中，使用 nest_asyncio 或创建新线程
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # 没有运行中的事件循环，直接运行
        return asyncio.run(coro)


def create_ask_user_tool(session_id: str, hitl_queue):
    """创建 ask_user 工具，实现 Human-in-the-loop 用户输入
    
    当 AI 需要向用户提问时调用此工具，等待用户回答
    """
    from app.api.kuncode import wait_for_kuncode_confirm, create_kuncode_preview
    
    def ask_user() -> ToolResponse:
        """等待用户输入。当你已经向用户提出问题后，调用此工具获取用户的回答。
        
        注意：在调用此工具之前，你应该先用自然语言输出你的问题，然后再调用此工具等待用户回答。
        """
        # 生成请求 ID（使用 ask_ 前缀区分）
        request_id = f"ask_{str(uuid.uuid4())[:8]}"
        
        # 创建 Redis 预览记录（用于确认 API）
        _run_async(create_kuncode_preview(
            session_id=session_id,
            preview_id=request_id,
            prompt="",  # ask_user 没有初始 prompt
            agent=None,
            model=None,
            timeout_seconds=180,
        ))
        
        # 通过队列通知前端需要用户输入
        hitl_queue.put({
            "type": "user_input_required",
            "request_id": request_id,
            "message": "AI 正在等待您的输入...",
            "remaining_seconds": 180,
        })
        
        # 等待用户输入（3分钟超时后自动继续）
        result = _run_async(wait_for_kuncode_confirm(session_id, request_id, timeout=180))
        
        if result.get("action") == "cancel":
            return ToolResponse(
                content=[{"type": "text", "text": "[用户取消了输入]"}],
                metadata={"success": False, "cancelled": True},
            )
        
        # 用户输入的内容（超时则为空，AI继续执行）
        user_input = result.get("prompt", "")
        is_auto_confirm = result.get("action") == "auto_confirm"
        
        if is_auto_confirm:
            user_input = "[用户未响应，继续执行]"
        
        # 通知前端用户已输入
        hitl_queue.put({
            "type": "user_input_received",
            "request_id": request_id,
            "content": user_input,
        })
        
        return ToolResponse(
            content=[{"type": "text", "text": f"用户回答: {user_input}"}],
            metadata={"success": True, "tool_name": "ask_user"},
        )
    
    return ask_user


def create_kuncode_prd_update_tool(session_id: str, hitl_queue):
    """创建 KunCode PRD 更新工具
    
    让用户预览和编辑 AI 生成的 prompt，返回编辑后的 prompt 供后续 run_kuncode 使用
    """
    from app.api.kuncode import create_kuncode_preview, wait_for_kuncode_confirm
    
    def kuncode_prd_update(prompt: str, agent: str) -> ToolResponse:
        """让用户预览和编辑 KunCode 任务的 PRD (需求描述)
        
        此工具会将 AI 生成的 prompt 展示给用户，用户可以修改后确认。
        返回用户确认（可能已编辑）的 prompt，然后你应该使用返回的 prompt 调用 run_kuncode。
        
        Args:
            prompt: AI 生成的任务需求描述
            agent: 执行任务的 KunCode Agent 名称
            
        Returns:
            用户确认后的 prompt（可能已被用户编辑）
        """
        
        # 生成预览 ID
        timeout_seconds = int(os.getenv("KUNCODE_PREVIEW_TIMEOUT_SECONDS", "30"))
        preview_id = str(uuid.uuid4())[:8]
        
        # 创建预览请求并通知前端
        _run_async(create_kuncode_preview(
            session_id=session_id,
            preview_id=preview_id,
            prompt=prompt,
            agent=agent,
            model=None,
            timeout_seconds=timeout_seconds,
        ))
        
        # 通过队列通知前端显示预览
        hitl_queue.put({
            "type": "kuncode_preview",
            "preview_id": preview_id,
            "prompt": prompt,
            "agent": agent,
            "model": None,
            "remaining_seconds": timeout_seconds,
        })
        
        # 等待用户确认（阻塞，3分钟超时后自动继续）
        result = _run_async(wait_for_kuncode_confirm(session_id, preview_id, timeout=timeout_seconds))
        
        if result.get("action") == "cancel":
            return ToolResponse(
                content=[{"type": "text", "text": "[用户取消]"}],
                metadata={"success": False, "cancelled": True},
            )
        
        # 用户确认或超时自动确认
        confirmed_prompt = result.get("prompt", prompt)
        confirmed_agent = result.get("agent", agent)
        is_auto_confirm = result.get("action") == "auto_confirm"
        
        # 通知前端已确认
        hitl_queue.put({
            "type": "kuncode_confirmed",
            "preview_id": preview_id,
            "prompt": confirmed_prompt,
            "agent": confirmed_agent,
            "auto_confirm": is_auto_confirm,
        })
        
        return ToolResponse(
            content=[{"type": "text", "text": f"用户确认的PRD内容：\n{confirmed_prompt}\n\n使用Agent: {confirmed_agent}"}],
            metadata={"success": True, "prompt": confirmed_prompt, "agent": confirmed_agent, "auto_confirm": is_auto_confirm},
        )
    
    kuncode_prd_update.__doc__ = (
        "Preview and optionally edit a KunCode PRD/prompt before execution. "
        "Use this tool only when the user explicitly asks to preview, edit, or confirm "
        "the KunCode prompt before running it. For normal requests to run/use/call "
        "KunCode, call the sandbox run_kuncode tool directly. Do not call this tool "
        "for simple execution tasks."
    )
    return kuncode_prd_update


def create_preview_plan_tool(session_id: str, hitl_queue):
    """创建计划预览工具
    
    让用户预览和编辑 AI 生成的计划，返回编辑后的计划供后续 create_plan 使用
    """
    from app.api.kuncode import create_plan_preview, wait_for_plan_confirm
    
    def preview_plan(name: str, subtasks: list[str]) -> ToolResponse:
        """让用户预览和编辑计划
        
        此工具会将 AI 生成的计划展示给用户，用户可以修改计划名称和子任务后确认。
        返回用户确认（可能已编辑）的计划，然后你应该使用返回的内容调用 create_plan。
        
        Args:
            name: 计划名称
            subtasks: 子任务列表（字符串数组）
            
        Returns:
            用户确认后的计划（JSON格式，包含 name 和 subtasks）
        """
        
        # 生成预览 ID
        preview_id = f"plan_{str(uuid.uuid4())[:8]}"
        
        # 构建子任务数据（用于前端显示）
        subtasks_data = [{"name": s, "state": "todo"} for s in subtasks]
        
        # 创建计划预览请求
        _run_async(create_plan_preview(
            session_id=session_id,
            preview_id=preview_id,
            name=name,
            subtasks=subtasks,
            timeout_seconds=180,
        ))
        
        # 通过队列通知前端显示计划预览
        hitl_queue.put({
            "type": "plan_preview",
            "preview_id": preview_id,
            "name": name,
            "state": "todo",
            "subtasks": subtasks_data,
            "remaining_seconds": 180,
        })
        
        # 等待用户确认（阻塞，3分钟超时后自动继续）
        result = _run_async(wait_for_plan_confirm(session_id, preview_id, timeout=180))
        
        if result.get("action") == "cancel":
            # 通知前端取消
            hitl_queue.put({
                "type": "plan_confirmed",
                "preview_id": preview_id,
                "auto_confirm": False,
            })
            return ToolResponse(
                content=[{"type": "text", "text": "[用户取消了计划]"}],
                metadata={"success": False, "cancelled": True},
            )
        
        # 获取用户编辑后的内容
        is_auto_confirm = result.get("action") == "auto_confirm"
        edited_name = result.get("name") or name
        edited_subtasks = result.get("subtasks") or subtasks
        
        # 通知前端已确认
        hitl_queue.put({
            "type": "plan_confirmed",
            "preview_id": preview_id,
            "auto_confirm": is_auto_confirm,
        })
        
        # 构建返回内容
        result_text = f"用户确认的计划：\n名称：{edited_name}\n子任务：\n"
        for i, st in enumerate(edited_subtasks, 1):
            result_text += f"  {i}. {st}\n"
        result_text += "\n请使用以上内容调用 create_plan 创建计划。"
        
        return ToolResponse(
            content=[{"type": "text", "text": result_text}],
            metadata={
                "success": True, 
                "name": edited_name, 
                "subtasks": edited_subtasks,
                "auto_confirm": is_auto_confirm
            },
        )
    
    return preview_plan


from app.config import settings  # noqa: E402
from app.services.postgres_session_history import PostgresSessionHistoryService  # noqa: E402
from app.services.postgres_state_service import PostgresStateService  # noqa: E402
from app.services.sandbox_cleanup_service import get_cleanup_service, SandboxCleanupService  # noqa: E402

# 导入自定义沙箱扩展，触发 @SandboxRegistry.register 装饰器
import data_analysis_sandbox  # noqa: F401, E402

# ==================== 知识库工具 ====================
from app.utils.milvus_client import milvus_client  # noqa: E402

KNOWLEDGE_CATEGORIES = ["计算公式", "概念定义", "分析方法", "分析流程"]


def search_knowledge(
    query: str,
    category: Optional[str] = None,
    top_k: int = 3,
) -> ToolResponse:
    """检索数据分析知识库"""
    try:
        if category and category not in KNOWLEDGE_CATEGORIES:
            return ToolResponse(
                content=[{"type": "text", "text": f"无效类别 '{category}'，支持：{', '.join(KNOWLEDGE_CATEGORIES)}"}],
                metadata={"success": False, "tool_name": "search_knowledge"},
            )
        
        results = milvus_client.search(
            collection_name=settings.MILVUS_COLLECTION,
            query=query,
            top_k=top_k,
            category=category,
        )
        
        if not results:
            hint = f"（类别: {category}）" if category else ""
            return ToolResponse(
                content=[{"type": "text", "text": f"未找到与 '{query}' 相关的知识{hint}。"}],
                metadata={"success": True, "tool_name": "search_knowledge"},
            )
        
        output_parts = [f"## {query} 相关知识\n"]
        for i, item in enumerate(results, 1):
            output_parts.append(f"### {i}. {item['title']} [{item['category']}]")
            output_parts.append(f"{item['content']}\n")
        
        return ToolResponse(
            content=[{"type": "text", "text": "\n".join(output_parts)}],
            metadata={"success": True, "tool_name": "search_knowledge"},
        )
        
    except Exception as e:
        return ToolResponse(
            content=[{"type": "text", "text": f"知识库检索失败: {e}"}],
            metadata={"success": False, "tool_name": "search_knowledge", "error": str(e)},
        )


async def _load_system_prompt() -> str:
    """从数据库加载系统提示词，回退到文件"""
    from app.api.system_prompt import get_active_system_prompt
    return await get_active_system_prompt()


async def _build_available_agents_prompt() -> str:
    """保留扩展点；默认执行模式不再从后台 Agent 配置中选择角色。"""
    return ""


class AgentService:
    """
    智能体服务
    
    管理智能体的创建、会话、状态等
    """
    
    _instance: Optional["AgentService"] = None
    
    def __init__(self):
        self.session_service: Optional[PostgresSessionHistoryService] = None
        self.state_service: Optional[PostgresStateService] = None
        self.sandbox_service: Optional[SandboxService] = None
        self.cleanup_service: Optional[SandboxCleanupService] = None
        self.system_prompt: str = ""
        self._redis: Optional[aioredis.Redis] = None
        self._started = False
        self._active_agents: Dict[str, Any] = {}  # session_id -> agent
    
    @classmethod
    def get_instance(cls) -> "AgentService":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def start(self) -> None:
        """启动服务"""
        if self._started:
            return
        
        # 初始化持久化服务
        self.session_service = PostgresSessionHistoryService()
        self.state_service = PostgresStateService()
        await self.session_service.start()
        await self.state_service.start()
        
        # 初始化沙箱服务
        self.sandbox_service = SandboxService(
            base_url=settings.SANDBOX_BASE_URL,
            bearer_token=settings.SANDBOX_BEARER_TOKEN,
        )
        await self.sandbox_service.start()
        
        # 系统提示词改为热加载，不再在启动时缓存
        self.system_prompt = ""
        
        # Redis 连接（用于任务流）
        self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        
        # 启动沙箱空闲清理服务（空闲 1 小时后自动释放）
        self.cleanup_service = get_cleanup_service(
            idle_timeout_seconds=7200,   # 2 小时空闲超时
            scan_interval_seconds=300,   # 每 5 分钟扫描一次
        )
        await self.cleanup_service.start()
        
        self._started = True
        print("[AgentService] 服务已启动")
    
    async def stop(self) -> None:
        """停止服务"""
        if not self._started:
            return
        
        await self.session_service.stop()
        await self.state_service.stop()
        await self.sandbox_service.stop()
        if self.cleanup_service:
            await self.cleanup_service.stop()
        if self._redis:
            await self._redis.aclose()
        
        self._started = False
        print("[AgentService] 服务已停止")
    
    async def _compress_context(self, conversation: str) -> str:
        """
        调用 AI 模型压缩对话历史为 markdown 摘要
        
        支持多模型提供商，根据配置自动选择合适的 API。
        可通过 COMPRESS_MODEL_PROVIDER 单独配置压缩使用的模型。
        
        Returns:
            str: markdown 格式的摘要文本
        """
        from app.config import COMPRESSION_PROMPT
        
        prompt = COMPRESSION_PROMPT.format(conversation=conversation)
        
        # 确定压缩使用的模型提供商
        compress_provider = settings.COMPRESS_MODEL_PROVIDER or settings.MODEL_PROVIDER
        
        try:
            if compress_provider.lower() in ("deepseek", "openai"):
                # 使用 OpenAI 兼容 API
                from openai import AsyncOpenAI
                
                if compress_provider.lower() == "deepseek":
                    api_key = settings.DEEPSEEK_API_KEY
                    base_url = settings.DEEPSEEK_BASE_URL
                    model_name = settings.COMPRESS_MODEL_NAME or settings.DEEPSEEK_MODEL_NAME
                else:
                    api_key = settings.OPENAI_API_KEY
                    base_url = settings.OPENAI_BASE_URL
                    model_name = settings.COMPRESS_MODEL_NAME or "gpt-4o-mini"
                
                client = AsyncOpenAI(api_key=api_key, base_url=base_url)
                response = await client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=2048,
                )
                content = response.choices[0].message.content or ""
                
            elif compress_provider.lower() in ("minimax", "anthropic"):
                # 使用 Anthropic 兼容 API
                import anthropic
                
                if compress_provider.lower() == "minimax":
                    api_key = settings.MINIMAX_API_KEY
                    base_url = settings.MINIMAX_BASE_URL
                    model_name = settings.COMPRESS_MODEL_NAME or "MiniMax-M2.5"
                else:
                    api_key = settings.ANTHROPIC_API_KEY
                    base_url = settings.ANTHROPIC_BASE_URL or None
                    model_name = settings.COMPRESS_MODEL_NAME or "claude-sonnet-4-20250514"
                
                client = anthropic.AsyncAnthropic(
                    api_key=api_key,
                    base_url=base_url,
                ) if base_url else anthropic.AsyncAnthropic(api_key=api_key)
                
                response = await client.messages.create(
                    model=model_name,
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                # Anthropic 返回格式不同
                content = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        content += block.text
            else:
                raise ValueError(f"不支持的压缩模型提供商: {compress_provider}")
            
            logger.debug(f"压缩摘要: {content[:200]}...")
            return content
            
        except Exception as e:
            logger.error(f"压缩上下文失败: {e}")
            return "## 会话历史摘要\n\n无法生成摘要"
    
    async def _get_session_summary(self, session_id: str) -> dict | None:
        """
        从 Redis 获取会话压缩摘要
        
        返回结构:
        {
            "text": "markdown 摘要文本",
            "covered_count": 10  # 摘要覆盖的消息数量
        }
        """
        key = f"session_summary:{session_id}"
        data = await self._redis.get(key)
        if data:
            try:
                return json.loads(data)
            except (json.JSONDecodeError, TypeError):
                return None
        return None
    
    async def _set_session_summary(self, session_id: str, summary_text: str, covered_count: int) -> None:
        """
        保存会话压缩摘要到 Redis
        
        Args:
            session_id: 会话 ID
            summary_text: markdown 摘要文本
            covered_count: 摘要覆盖的消息数量
        """
        key = f"session_summary:{session_id}"
        data = {"text": summary_text, "covered_count": covered_count}
        await self._redis.set(key, json.dumps(data, ensure_ascii=False), ex=86400 * 7)  # 7天过期
    
    async def _get_context_info(self, user_id: str, session_id: str) -> Dict[str, Any]:
        """
        获取当前上下文使用信息
        
        Returns:
            dict: {"estimated_tokens": int, "max_tokens": int, "usage_percent": float}
        """
        max_tokens = settings.MAX_TOKENS
        default_info = {"estimated_tokens": 0, "max_tokens": max_tokens, "usage_percent": 0.0}
        
        try:
            from app.repositories.session_repo import SessionRepository
            from agentscope_runtime.engine.schemas.agent_schemas import Message
            from agentscope_runtime.adapters.agentscope.message import message_to_agentscope_msg
            from agentscope.message import Msg
            
            session = await SessionRepository.get(user_id, session_id)
            if not session:
                return default_info
            
            messages = await SessionRepository.get_messages(session)
            if not messages:
                return default_info
            
            # 转换消息
            runtime_messages = [Message(**m.message) for m in messages]
            agentscope_msgs = message_to_agentscope_msg(runtime_messages)
            
            # 获取摘要
            summary = await self._get_session_summary(session_id)
            covered_count = summary.get("covered_count", 0) if summary else 0
            
            # 构建计数消息列表
            msgs_to_count = []
            if summary and covered_count > 0:
                summary_text = summary.get("text", "")
                if summary_text:
                    summary_msg = Msg(name="system", role="system", content=summary_text)
                    msgs_to_count.append(summary_msg)
                msgs_to_count.extend(agentscope_msgs[covered_count:])
            else:
                msgs_to_count = agentscope_msgs
            
            # 使用工厂模式创建格式化器和 token 计数器
            _, formatter, token_counter = ModelFactory.create_model_and_formatter()
            formatted = await formatter.format(msgs_to_count)
            current_tokens = await token_counter.count(formatted)
            
            usage_percent = round(current_tokens / max_tokens * 100, 1) if max_tokens > 0 else 0
            
            return {
                "estimated_tokens": current_tokens,
                "max_tokens": max_tokens,
                "usage_percent": usage_percent,
            }
        except Exception as e:
            logger.warning(f"_get_context_info failed: {e}")
            return default_info
    
    async def check_and_compress(self, user_id: str, session_id: str) -> bool:
        """
        检查 token 使用率，如果超过阈值则执行压缩
        
        Returns:
            bool: 是否执行了压缩
        """
        from app.api.sessions import is_compressing, _do_preemptive_compression
        
        # 如果已经在压缩，跳过
        if await is_compressing(session_id):
            return False
        
        # 获取上下文信息
        context_info = await self._get_context_info(user_id, session_id)
        usage_percent = context_info["usage_percent"]
        threshold_percent = settings.COMPRESS_THRESHOLD_PERCENT
        
        if usage_percent >= threshold_percent:
            logger.info(f"运行时压缩触发: 会话 {session_id}, 使用率 {usage_percent}% >= {threshold_percent}%")
            await _do_preemptive_compression(user_id, session_id)
            return True
        
        return False
    
    async def create_agent(
        self,
        sandbox,
        user_id: str,
        session_id: str,
        plan_callback=None,
        hitl_queue=None,
    ) -> ReActAgent:
        """创建 ReActAgent 实例
        
        Args:
            plan_callback: 可选的计划变化回调函数，接收 (plan_name, plan_state, subtasks) 参数
            hitl_queue: 可选的 HITL 事件队列，用于 kuncode 预览确认
        """
        toolkit = Toolkit()
        
        # 注册知识库工具
        toolkit.register_tool_function(search_knowledge)
        
        # Register only high-signal sandbox tools by default. Exposing shell and
        # KunCode inspection helpers to the outer agent makes simple requests
        # fan out into directory probes/session checks before doing useful work.
        sandbox_methods = []
        if os.getenv("ENABLE_AGENT_PYTHON_TOOL", "").strip().lower() in {"1", "true", "yes", "on"}:
            sandbox_methods.append(sandbox.run_ipython_cell)
        if os.getenv("ENABLE_AGENT_SHELL_TOOL", "").strip().lower() in {"1", "true", "yes", "on"}:
            sandbox_methods.extend([
                sandbox.run_shell_command,
                sandbox.kuncode_session_list,
                sandbox.kuncode_mcp_list,
            ])
        for method in sandbox_methods:
            toolkit.register_tool_function(safe_sandbox_tool_adapter(method))
        
        # run_kuncode: 始终注册流式版本
        toolkit.register_tool_function(streaming_sandbox_tool_adapter(sandbox.run_kuncode))
        
        # 如果提供了 hitl_queue，注册 HITL 工具
        if hitl_queue:
            # kuncode_prd_update: 让用户预览和编辑 prompt，返回后 AI 调用 run_kuncode
            toolkit.register_tool_function(create_kuncode_prd_update_tool(session_id, hitl_queue))
            # preview_plan: 让用户预览和编辑计划，返回后 AI 调用 create_plan
            toolkit.register_tool_function(create_preview_plan_tool(session_id, hitl_queue))
            # ask_user: AI 主动请求用户输入
            toolkit.register_tool_function(create_ask_user_tool(session_id, hitl_queue))
        
        # 创建计划笔记本并注册钩子
        plan_notebook = PlanNotebook(max_subtasks=10)
        
        # 热加载系统提示词 + 可用智能体列表 + 历史摘要
        base_prompt = await _load_system_prompt()
        agents_prompt = await _build_available_agents_prompt()
        sys_prompt = base_prompt + agents_prompt
        
        # 获取历史摘要，用于注入系统提示词和计算跳过的消息数
        summary = await self._get_session_summary(session_id)
        skip_count = 0
        if summary:
            summary_text = summary.get("text", "")
            if summary_text:
                sys_prompt = sys_prompt + "\n\n---\n## 会话历史摘要\n" + summary_text
            skip_count = summary.get("covered_count", 0)
            logger.info(f"已注入历史摘要到系统提示词，跳过 {skip_count} 条已覆盖消息")
        
        if plan_callback:
            def plan_change_hook(notebook: PlanNotebook, plan) -> None:
                """计划变更钩子 - 仅更新前端显示，不做预览等待"""
                if plan is None:
                    return
                subtasks = []
                for subtask in plan.subtasks:
                    subtasks.append({
                        "name": subtask.name,
                        "state": subtask.state,
                    })
                # 直接更新计划显示
                plan_callback(plan.name, plan.state, subtasks)
            
            plan_notebook.register_plan_change_hook("stream_plan_hook", plan_change_hook)
        
        # 使用工厂模式创建模型和格式化器
        model, formatter, token_counter = ModelFactory.create_model_and_formatter(
            tool_output_max_length=settings.TOOL_OUTPUT_MAX_LENGTH,
        )
        
        agent = ReActAgent(
            name="DataPM",
            model=model,
            sys_prompt=sys_prompt,
            plan_notebook=plan_notebook,
            formatter=formatter,
            memory=CompressedSessionMemory(
                service=self.session_service,
                user_id=user_id,
                session_id=session_id,
                skip_count=skip_count,
            ),
            toolkit=toolkit,
            parallel_tool_calls=False,
            max_iters=30,
        )
        
        agent.set_console_output_enabled(enabled=False)
        return agent    

    async def _direct_run_kuncode(
        self,
        sandbox,
        user_id: str,
        session_id: str,
        prompt: str,
        user_message: str,
        metadata: Optional[dict] = None,
    ) -> AsyncGenerator[dict, None]:
        from app.repositories.session_repo import SessionRepository

        tool_id = f"run_kuncode_{uuid.uuid4().hex}"
        tool_input = {
            "prompt": prompt,
            "agent": None,
            "model": None,
            "continue_session": False,
        }
        db_session = await SessionRepository.get(user_id, session_id)
        if db_session:
            await SessionRepository.append_message(
                db_session,
                {
                    "id": f"msg_{uuid.uuid4()}",
                    "type": "message",
                    "role": "user",
                    "object": "message",
                    "status": "completed",
                    "content": [{"type": "text", "text": prompt}],
                    "metadata": metadata,
                },
            )
            if not db_session.name and user_message.strip():
                await SessionRepository.update_name(db_session, user_message.strip()[:100])

            await SessionRepository.append_message(
                db_session,
                {
                    "id": f"msg_{uuid.uuid4()}",
                    "type": "plugin_call",
                    "role": "assistant",
                    "object": "message",
                    "status": "completed",
                    "content": [
                        {
                            "type": "data",
                            "data": {
                                "call_id": tool_id,
                                "name": "run_kuncode",
                                "arguments": json.dumps(tool_input, ensure_ascii=False),
                            },
                        }
                    ],
                },
            )
        else:
            logger.warning("Direct KunCode history skipped: session=%s not found", session_id)

        yield {
            "type": "tool_call",
            "content": "run_kuncode",
            "tool_id": tool_id,
            "input": tool_input,
        }

        accumulated_output = ""
        final_message = ""
        generated_files: list[str] = []
        is_error = False
        try:
            async for response in sandbox.run_kuncode(prompt=prompt):
                output = _extract_tool_response_text(response)
                if output and output != accumulated_output:
                    accumulated_output = output
                    yield {
                        "type": "tool_result",
                        "content": accumulated_output,
                        "tool_id": tool_id,
                        "phase": "progress",
                        "execution_status": "running",
                    }
        except Exception as e:
            accumulated_output = f"[ERROR] KunCode direct execution failed: {e}"
            final_message = accumulated_output
            is_error = True
            logger.exception("Direct KunCode execution failed: session=%s", session_id)
            yield {
                "type": "tool_result",
                "content": accumulated_output,
                "tool_id": tool_id,
                "phase": "failed",
                "execution_status": "failed",
            }
        else:
            if not accumulated_output.strip():
                accumulated_output = "[ERROR] KunCode returned no output."
                yield {
                    "type": "tool_result",
                    "content": accumulated_output,
                    "tool_id": tool_id,
                    "phase": "failed",
                    "execution_status": "failed",
                }

            is_error = "[ERROR]" in accumulated_output
            generated_files = _extract_workspace_files(accumulated_output)
            final_message = (
                "KunCode 执行失败，请查看终端输出。"
                if is_error
                else _build_kuncode_completion_message(generated_files)
            )

        # The streaming chunks above are progress updates. Emit one explicit
        # final result so clients can stop the tool spinner deterministically.
        yield {
            "type": "tool_result",
            "content": accumulated_output,
            "tool_id": tool_id,
            "phase": "failed" if is_error else "completed",
            "execution_status": "failed" if is_error else "completed",
        }

        if db_session:
            output_message = {
                "id": f"msg_{uuid.uuid4()}",
                "type": "plugin_call_output",
                "role": "system",
                "object": "message",
                "status": "completed",
                "content": [
                    {
                        "type": "data",
                        "data": {
                            "call_id": tool_id,
                            "name": "run_kuncode",
                            "output": json.dumps(
                                [{"type": "text", "text": accumulated_output}],
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            }
            await SessionRepository.insert_after_plugin_call(db_session, tool_id, output_message)
            await SessionRepository.append_message(
                db_session,
                {
                    "id": f"msg_{uuid.uuid4()}",
                    "type": "message",
                    "role": "assistant",
                    "object": "message",
                    "status": "completed",
                    "content": [{"type": "text", "text": final_message}],
                },
            )

        yield {
            "type": "error" if is_error else "text",
            "content": final_message,
            "generated_files": generated_files,
        }
    
    async def chat(
        self,
        user_id: str,
        session_id: Optional[str],
        message: str,
        file_ids: Optional[List[str]] = None,
        execution_mode: str = "auto",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        执行对话（流式输出）
        
        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            message: 用户消息
            file_ids: 要同步到沙箱的文件 ID 列表
        
        Yields:
            {"type": "thinking|text|tool_call|end", "content": "..."}
        """
        if not self._started:
            yield {"type": "error", "content": "服务未启动"}
            return
        
        # 等待预压缩完成（如果正在进行）
        from app.api.sessions import is_compressing, wait_for_compression
        if session_id and await is_compressing(session_id):
            logger.info(f"等待会话 {session_id} 预压缩完成...")
            yield {"type": "status", "content": "正在压缩历史上下文，请稍候..."}
            await wait_for_compression(session_id, timeout=180.0)
            logger.info(f"会话 {session_id} 预压缩完成，继续执行")
        
        if not session_id:
            yield {"type": "error", "content": "session_id 为必填项，请先调用 POST /api/conversation/sessions 创建会话"}
            return
        
        # 连接或创建沙箱，处理文件迁移
        result = await self._connect_or_create_sandbox(session_id, user_id, file_ids)
        if not result or not result[0]:
            yield {"type": "error", "content": "无法创建沙箱实例"}
            return
        
        sandbox, sandbox_recreated = result
        
        # 更新会话活跃时间（用于空闲超时检测）
        if self.cleanup_service:
            self.cleanup_service.touch(session_id)
        
        try:
            if sandbox_recreated:
                yield {"type": "sandbox_recreated", "content": f"沙箱已重建，新 ID: {sandbox.sandbox_id}"}
            
            # 文件已自动存储在挂载目录，无需手动同步
            # 如果有文件关联，构建文件提示
            file_paths = []
            if file_ids:
                from app.repositories.file_repo import FileRepository
                files = await FileRepository.list_by_ids(user_id, file_ids)
                file_paths = [f"/workspace/data/uploads/{f.filename}" for f in files]
            
            # 事件队列（用于在同步回调和异步生成器之间传递数据）
            import queue
            event_queue = queue.Queue()
            
            def plan_callback(name, state, subtasks):
                event_queue.put({"type": "plan", "name": name, "state": state, "subtasks": subtasks})
            
            # 创建 Agent（传入 hitl_queue 以启用 kuncode 预览确认）
            agent = await self.create_agent(
                sandbox, user_id, session_id,
                plan_callback=plan_callback,
                hitl_queue=event_queue,
            )
            
            # 存储活跃代理（用于中断）
            self._active_agents[session_id] = agent
            
            # 恢复状态
            state = await self.state_service.export_state(user_id, session_id)
            if state:
                agent.load_state_dict(state)
            
            # 修复未配对的 plugin_call（用户可能在上次中断后直接发送新消息）
            await self._repair_unpaired_plugin_calls(user_id, session_id)
            
            # 构造消息（如果有文件，在消息中注入文件路径提示）
            final_message = message
            if file_paths:
                file_hint = self._build_file_hint(file_paths)
                final_message = f"{message}\n\n{file_hint}"

            if execution_mode == "kuncode":
                metadata = (
                    {"file_ids": file_ids, "file_paths": file_paths}
                    if file_ids
                    else None
                )
                async for chunk in self._direct_run_kuncode(
                    sandbox,
                    user_id,
                    session_id,
                    final_message,
                    message,
                    metadata,
                ):
                    yield chunk
                await self._cleanup_session_pending_state(session_id, is_interrupt=False)
                yield {"type": "end", "content": "对话完成", "session_id": session_id}
                return
            
            msg = Msg(
                name="user",
                content=final_message,
                role="user",
                metadata={"file_ids": file_ids, "file_paths": file_paths} if file_ids else None,
            )
            
            # 流式执行
            # 跟踪待处理的 tool_calls（用于中断时补充 tool_result）
            pending_tool_calls = {}  # tool_id -> tool_name
            
            # 启动独立的中断监控器（每 0.5 秒检查一次）
            interrupt_monitor = InterruptMonitor(self._redis, session_id, interval=0.5)
            interrupt_monitor.start()
            
            # 使用队列在生产者和消费者之间传递流式消息
            stream_queue: asyncio.Queue = asyncio.Queue()
            stream_done = asyncio.Event()
            
            async def stream_producer():
                """生产者：从 agent 获取流式消息并放入队列"""
                try:
                    async for stream_msg, is_last_chunk in stream_printing_messages(
                        agents=[agent],
                        coroutine_task=agent(msg),
                    ):
                        await stream_queue.put((stream_msg, is_last_chunk))
                except asyncio.CancelledError:
                    logger.info(f"[流式生产者] 被中断取消: {session_id}")
                    raise
                finally:
                    stream_done.set()
            
            # 创建生产者任务并绑定到中断监控器
            producer_task = asyncio.create_task(stream_producer())
            interrupt_monitor.bind_task(producer_task)
            
            # 流式输出去重：记录已发送的内容，避免重复发送
            last_thinking_content = ""
            last_text_content = ""
            sent_tool_ids = set()
            sent_tool_inputs = {}  # tool_id -> last_sent_input，用于检测 input 变化
            
            try:
                while not stream_done.is_set() or not stream_queue.empty():
                    # 检查中断
                    if interrupt_monitor.is_interrupted():
                        if hasattr(agent, 'interrupt'):
                            await agent.interrupt()
                        
                        if pending_tool_calls:
                            await self._add_interrupted_tool_results(
                                user_id, session_id, pending_tool_calls
                            )
                            for terminal_event in _build_terminal_tool_results(
                                pending_tool_calls,
                                status="cancelled",
                            ):
                                yield terminal_event
                            pending_tool_calls.clear()
                        
                        yield {"type": "interrupted", "content": "用户中断了执行"}
                        break
                    
                    # 先检查并发送事件队列中的事件（计划、HITL等）
                    while not event_queue.empty():
                        try:
                            event = event_queue.get_nowait()
                            yield event
                        except queue.Empty:
                            break
                    
                    # 从流式队列获取消息（带超时，以便定期检查中断）
                    try:
                        stream_msg, is_last_chunk = await asyncio.wait_for(
                            stream_queue.get(), timeout=0.5
                        )
                    except asyncio.TimeoutError:
                        continue
                    
                    if hasattr(stream_msg, "content"):
                        content = stream_msg.content
                        if isinstance(content, list):
                            for item in content:
                                if isinstance(item, dict):
                                    block_type = item.get("type", "text")
                                    # 根据内容块类型映射输出类型，带去重逻辑
                                    if block_type == "thinking":
                                        thinking_content = filter_model_tokens(item.get("thinking", ""))
                                        # 只在内容变化时发送
                                        if thinking_content != last_thinking_content:
                                            last_thinking_content = thinking_content
                                            yield {"type": "thinking", "content": thinking_content}
                                    elif block_type == "text":
                                        text_content = filter_model_tokens(item.get("text", ""))
                                        # 只在内容变化时发送
                                        if text_content != last_text_content:
                                            last_text_content = text_content
                                            yield {"type": "text", "content": text_content}
                                    elif block_type == "tool_use":
                                        tool_id = item.get("id", "")
                                        tool_name = item.get("name", "")
                                        tool_input = item.get("input", {})
                                        # Providers may stream tool input incrementally. Re-emit only
                                        # when arguments become more complete; the frontend updates the
                                        # existing entry by tool_id instead of adding a duplicate.
                                        if tool_id:
                                            last_input = sent_tool_inputs.get(tool_id)
                                            input_changed = tool_input and last_input != tool_input
                                            if tool_id not in sent_tool_ids or input_changed:
                                                sent_tool_ids.add(tool_id)
                                                sent_tool_inputs[tool_id] = tool_input
                                                # 记录待处理的 tool_call
                                                pending_tool_calls[tool_id] = tool_name
                                                yield {
                                                    "type": "tool_call",
                                                    "content": tool_name,
                                                    "tool_id": tool_id,
                                                    "input": tool_input,
                                                }
                                    elif block_type == "tool_result":
                                        output = item.get("output", [])
                                        text_parts = [o.get("text", "") for o in output if isinstance(o, dict) and o.get("type") == "text"]
                                        tool_id = item.get("tool_use_id", "")
                                        result_text = "".join(text_parts)
                                        # 移除已完成的 tool_call
                                        pending_tool_calls.pop(tool_id, None)
                                        yield _build_streamed_tool_result(tool_id, result_text)
                                    elif block_type == "data":
                                        # AgentScope stores plugin_call_output blocks in this
                                        # shape. A matching block is the real terminal result.
                                        data = item.get("data", {})
                                        tool_id = data.get("call_id", "") if isinstance(data, dict) else ""
                                        if tool_id and tool_id in pending_tool_calls:
                                            pending_tool_calls.pop(tool_id, None)
                                            yield _build_streamed_tool_result(
                                                tool_id,
                                                data.get("output"),
                                            )
                                        else:
                                            yield {
                                                "type": block_type,
                                                "content": filter_model_tokens(str(item)),
                                            }
                                    else:
                                        yield {"type": block_type, "content": filter_model_tokens(str(item))}
                        else:
                            yield {"type": "text", "content": filter_model_tokens(str(content))}
                    
                    # is_last_chunk 只表示当前消息的最后一个 chunk，不是对话结束
                    # 用 step_complete 标记一个消息块完成，并携带上下文使用信息
                    if is_last_chunk:
                        # 获取上下文信息用于前端更新
                        context_info = await self._get_context_info(user_id, session_id)
                        yield {"type": "step_complete", "content": "", "context_info": context_info}
                        
                        # 每个 step 完成后检查是否需要压缩（带重试机制）
                        for retry in range(2):
                            try:
                                if await self.check_and_compress(user_id, session_id):
                                    yield {"type": "status", "content": "上下文已压缩，继续执行..."}
                                    # 压缩后重新获取上下文信息
                                    context_info = await self._get_context_info(user_id, session_id)
                                    yield {"type": "context_update", "context_info": context_info}
                                break  # 成功则跳出重试
                            except (TimeoutError, asyncio.TimeoutError, ConnectionError) as e:
                                if retry == 0:
                                    logger.warning(f"check_and_compress connection issue, retrying: {e}")
                                    await asyncio.sleep(1)  # 等待1秒后重试
                                else:
                                    logger.warning(f"check_and_compress failed after retry: {e}")
                            except Exception as e:
                                logger.warning(f"check_and_compress failed: {e}")
                                break
            finally:
                # 确保停止中断监控器和生产者任务
                interrupt_monitor.stop()
                if not producer_task.done():
                    producer_task.cancel()
                    try:
                        await producer_task
                    except asyncio.CancelledError:
                        pass
                elif producer_task.done() and not producer_task.cancelled():
                    # 检查生产者任务是否有未处理的异常（如 API 503 错误）
                    exc = producer_task.exception()
                    if exc is not None:
                        raise exc
            
            # 整个对话完成后保存状态
            # AgentScope may persist plugin_call_output without exposing that
            # message through the live stream. Recover those paired results
            # before treating any genuinely unresolved call as failed.
            if pending_tool_calls:
                try:
                    db_session = await SessionRepository.get(user_id, session_id)
                    if db_session:
                        stored_messages = await SessionRepository.get_messages(db_session)
                        for terminal_event in _extract_persisted_tool_results(
                            stored_messages,
                            pending_tool_calls,
                        ):
                            pending_tool_calls.pop(terminal_event["tool_id"], None)
                            yield terminal_event
                except Exception as recovery_error:
                    logger.warning(
                        "Failed to recover persisted tool results: session=%s error=%s",
                        session_id,
                        recovery_error,
                    )

            # Close truly omitted tool results without claiming success.
            for terminal_event in _build_terminal_tool_results(pending_tool_calls):
                yield terminal_event
            pending_tool_calls.clear()

            state_to_save = agent.state_dict()
            await self.state_service.save_state(
                user_id=user_id,
                session_id=session_id,
                state=state_to_save,
            )
            
            # 清理临时交互状态（pending/preview）
            await self._cleanup_session_pending_state(session_id, is_interrupt=interrupt_monitor.is_interrupted())
            
            # 正常结束时检查计划是否未完成，如果是则创建自动继续待确认状态
            # 用户中断时不创建（中断只是暂停，不需要弹窗询问是否继续）
            if not interrupt_monitor.is_interrupted():
                try:
                    from app.api.kuncode import create_auto_continue_pending
                    
                    plan_notebook = state_to_save.get("plan_notebook", {})
                    current_plan = plan_notebook.get("current_plan")
                    
                    if current_plan and current_plan.get("subtasks"):
                        incomplete = any(
                            st.get("state") not in ("done", "abandoned") 
                            for st in current_plan.get("subtasks", [])
                        )
                        if incomplete:
                            await create_auto_continue_pending(session_id, timeout_seconds=180, user_id=user_id)
                            logger.info(f"计划未完成，已创建自动继续待确认状态: {session_id}")
                except Exception as e:
                    logger.warning(f"检查计划状态失败: {e}")
            
            yield {"type": "end", "content": "对话完成", "session_id": session_id}
        
        except Exception as e:
            import traceback
            error_msg = str(e) or f"{type(e).__name__}: {traceback.format_exc()}"
            logger.error(f"Chat error: {error_msg}")
            yield {"type": "error", "content": error_msg}
        
        finally:
            # 清理活跃代理
            self._active_agents.pop(session_id, None)
        
        # 注意：不调用 release()，保持沙箱运行以便后续对话复用
        # 沙箱会根据 SandboxManager 的配置自动超时清理
    
    async def _cleanup_session_pending_state(self, session_id: str, is_interrupt: bool = False, user_id: Optional[str] = None) -> None:
        """清理会话的临时交互状态
        
        Args:
            session_id: 会话 ID
            is_interrupt: 是否是用户中断（中断时将未完成子任务标记为 abandoned）
            user_id: 用户 ID（中断时用于标记计划）
        """
        # 清理临时交互状态（对话结束后就没有意义了）
        keys_to_delete = [
            f"kuncode_pending:{session_id}",
            f"plan_pending:{session_id}",
            f"auto_continue:{session_id}",
        ]
        
        # 用户中断时，将未完成的子任务标记为 abandoned
        if is_interrupt and user_id:
            try:
                from app.api.kuncode import _mark_plan_subtasks_abandoned
                await _mark_plan_subtasks_abandoned(session_id, user_id)
            except Exception as e:
                logger.warning(f"标记中断的子任务为 abandoned 失败: {e}")
        
        for key in keys_to_delete:
            await self._redis.delete(key)
        
        # 清理 preview 数据（使用 SCAN 匹配模式）
        for pattern in [f"kuncode_preview:{session_id}:*", f"plan_preview:{session_id}:*"]:
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                if keys:
                    await self._redis.delete(*keys)
                if cursor == 0:
                    break
    
    async def interrupt_agent(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """中断正在执行的代理
        
        通过 Redis 设置中断信号，Celery worker 中的代理会检查并响应
        
        Args:
            session_id: 会话 ID
            user_id: 用户 ID（用于标记计划为 abandoned）
        
        Returns:
            是否成功设置中断信号
        """
        # 先尝试直接中断（如果代理在当前进程中）
        agent = self._active_agents.get(session_id)
        if agent and hasattr(agent, 'interrupt'):
            await agent.interrupt()
        
        # 设置 Redis 中断信号（用于 Celery worker）
        interrupt_key = f"agent_interrupt:{session_id}"
        await self._redis.set(interrupt_key, "1", ex=60)  # 60秒过期
        
        # 获取当前任务 ID 并尝试撤销 Celery 任务
        task_id = await self.get_session_task(session_id)
        if task_id:
            try:
                from app.tasks import celery_app
                celery_app.control.revoke(task_id, terminate=True, signal='SIGTERM')
                logger.info(f"已撤销 Celery 任务: {task_id}")
            except Exception as e:
                logger.warning(f"撤销 Celery 任务失败: {e}")
        
        # 清理会话任务映射（这样 has_active_task 会变为 false）
        await self.clear_session_task(session_id)
        
        # 清理临时交互状态
        await self._cleanup_session_pending_state(session_id, is_interrupt=True, user_id=user_id)
        
        # 写入中断结束消息到任务流（如果有）
        if task_id:
            await self.write_task_stream(task_id, {"type": "interrupted", "content": "用户中断了执行"})
            await self.write_task_stream(task_id, {"type": "end", "content": "已中断"})
        
        return True
    
    async def check_interrupt(self, session_id: str) -> bool:
        """检查是否有中断信号"""
        interrupt_key = f"agent_interrupt:{session_id}"
        value = await self._redis.get(interrupt_key)
        # Redis 返回 bytes，需要处理
        if value:
            value_str = value.decode() if isinstance(value, bytes) else str(value)
            if value_str == "1":
                await self._redis.delete(interrupt_key)
                return True
        return False
    
    async def _repair_unpaired_plugin_calls(self, user_id: str, session_id: str) -> None:
        """
        修复未配对的 plugin_call（没有对应的 plugin_call_output）
        
        在用户发送新消息前调用，确保历史消息状态正确
        """
        from app.repositories.session_repo import SessionRepository
        
        db_session = await SessionRepository.get(user_id, session_id)
        if not db_session:
            return
        
        messages = await SessionRepository.get_messages(db_session)
        if not messages:
            return
        
        # 查找未配对的 plugin_call
        pending_calls = {}  # tool_id -> tool_name
        for msg_record in messages:
            msg = msg_record.message
            # 兼容 "type" 和 "msg_type" 两种字段名（与 _reorder_by_call_id 保持一致）
            msg_type = msg.get("type") or msg.get("msg_type")
            
            if msg_type == "plugin_call":
                # 提取 tool_id 和 tool_name
                for content_item in msg.get("content", []):
                    if content_item.get("type") == "data":
                        data = content_item.get("data", {})
                        tool_id = data.get("call_id")
                        tool_name = data.get("name", "unknown")
                        if tool_id:
                            pending_calls[tool_id] = tool_name
            
            elif msg_type == "plugin_call_output" or msg_type == "plugin_call_result":
                # 移除已配对的（兼容不同的类型名称）
                for content_item in msg.get("content", []):
                    if content_item.get("type") == "data":
                        data = content_item.get("data", {})
                        tool_id = data.get("call_id")
                        pending_calls.pop(tool_id, None)
        
        # 为未配对的添加中断结果
        if pending_calls:
            logger.info(f"发现 {len(pending_calls)} 个未配对的 plugin_call，正在修复...")
            await self._add_interrupted_tool_results(user_id, session_id, pending_calls)
    
    async def _add_interrupted_tool_results(
        self, user_id: str, session_id: str, pending_tool_calls: dict
    ) -> None:
        """
        为未完成的 tool_calls 添加中断结果到会话历史
        
        解决中断时缺少 tool_result 导致的 API 错误：
        "An assistant message with 'tool_calls' must be followed by tool messages"
        """
        from app.repositories.session_repo import SessionRepository
        
        db_session = await SessionRepository.get(user_id, session_id)
        if not db_session:
            logger.warning(f"无法找到会话 {session_id}，跳过添加中断 tool_result")
            return
        
        for tool_id, tool_name in pending_tool_calls.items():
            # 构建符合实际数据库存储格式的 plugin_call_output
            # 必须包含 id 字段（格式: msg_uuid）
            interrupted_result = {
                "id": f"msg_{uuid.uuid4()}",
                "type": "plugin_call_output",
                "role": "system",
                "object": "message",
                "status": "completed",
                "content": [
                    {
                        "type": "data",
                        "data": {
                            "call_id": tool_id,
                            "name": tool_name,
                            "output": "[{\"type\": \"text\", \"text\": \"[用户中断调用]\"}]",
                        }
                    }
                ],
            }
            # 在对应的 plugin_call 后插入，确保顺序正确
            await SessionRepository.insert_after_plugin_call(db_session, tool_id, interrupted_result)
            logger.info(f"已为中断的 tool_call {tool_id} ({tool_name}) 添加 plugin_call_output")
    
    async def set_session_task(self, session_id: str, task_id: str) -> None:
        """设置会话的当前任务"""
        key = f"session_task:{session_id}"
        await self._redis.set(key, task_id, ex=3600)  # 1小时过期

    async def set_task_owner(self, task_id: str, user_id: str, session_id: str) -> None:
        """记录任务所属用户和会话，供 SSE 订阅和重连时鉴权。"""
        key = f"task_owner:{task_id}"
        payload = json.dumps(
            {"user_id": str(user_id), "session_id": session_id},
            ensure_ascii=False,
        )
        await self._redis.set(key, payload, ex=3600)

    async def get_task_owner(self, task_id: str) -> Optional[Dict[str, str]]:
        """返回任务所属信息；任务流过期后返回 None。"""
        value = await self._redis.get(f"task_owner:{task_id}")
        if not value:
            return None
        try:
            data = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            logger.warning("Invalid task ownership record: task=%s", task_id)
            return None
        if not isinstance(data, dict) or not data.get("user_id") or not data.get("session_id"):
            return None
        return {"user_id": str(data["user_id"]), "session_id": str(data["session_id"])}
    
    async def get_session_task(self, session_id: str) -> str | None:
        """获取会话的当前任务"""
        key = f"session_task:{session_id}"
        task_id = await self._redis.get(key)
        return task_id
    
    async def clear_session_task(self, session_id: str, task_id: str | None = None) -> None:
        """清除会话的当前任务"""
        key = f"session_task:{session_id}"
        if task_id is not None and await self._redis.get(key) != task_id:
            return
        await self._redis.delete(key)
    
    async def write_task_stream(self, task_id: str, data: dict, session_id: str = None) -> None:
        """写入任务流消息 - 使用独立 Redis 连接避免跨进程问题"""
        stream_key = f"task_stream:{task_id}"
        event = dict(data)
        event_type = event.get("type", "status")
        phase, execution_status = {
            "tool_call": ("started", "running"),
            "tool_result": ("completed", "completed"),
            "error": ("failed", "failed"),
            "interrupted": ("cancelled", "cancelled"),
            "end": ("completed", "completed"),
        }.get(event_type, ("progress", "running"))
        event.setdefault("event_id", f"evt_{uuid.uuid4().hex}")
        event.setdefault("task_id", task_id)
        event.setdefault("session_id", session_id)
        event.setdefault("phase", phase)
        event.setdefault("execution_status", execution_status)
        event.setdefault("created_at", datetime.now(timezone.utc).isoformat())

        # 创建独立的 Redis 连接，避免 Celery Worker 和 FastAPI 之间的连接冲突
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

        try:
            # maxlen=70000 约保留7万条消息，足够长时间任务的所有输出
            # 使用 ~ 近似裁剪，性能更好
            await redis_client.xadd(stream_key, {"data": json.dumps(event, ensure_ascii=False)}, maxlen=70000, approximate=True)
            await redis_client.expire(stream_key, 3600)

            # 心跳：每次写入时刷新session_task的过期时间
            if session_id:
                session_key = f"session_task:{session_id}"
                await redis_client.expire(session_key, 3600)  # 续期1小时
                await redis_client.expire(f"task_owner:{task_id}", 3600)
        finally:
            await redis_client.aclose()
    
    async def read_task_stream(self, task_id: str, last_id: str = "0") -> AsyncGenerator[dict, None]:
        """读取任务流消息 - 创建独立的 Redis 连接避免跨进程连接问题"""
        stream_key = f"task_stream:{task_id}"

        # 创建独立的 Redis 连接，避免 Celery Worker 和 FastAPI 之间的连接冲突
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

        try:
            while True:
                try:
                    messages = await redis_client.xread({stream_key: last_id}, count=10, block=1000)
                    if messages:
                        for stream_name, stream_messages in messages:
                            for msg_id, msg_data in stream_messages:
                                last_id = msg_id
                                data = json.loads(msg_data.get("data", "{}"))
                                data["_stream_id"] = msg_id
                                yield data
                                if data.get("type") == "end":
                                    return
                    else:
                        exists = await redis_client.exists(stream_key)
                        if not exists:
                            import asyncio
                            await asyncio.sleep(0.5)
                except Exception as e:
                    yield {"type": "error", "content": str(e)}
                    return
        finally:
            await redis_client.aclose()
    
    async def _connect_or_create_sandbox(self, session_id: str, user_id: str, file_ids: List[str] = None):
        """
        连接或创建沙箱，处理沙箱重建时的文件迁移
        
        流程：
        1. 连接沙箱（可能从池中获取新沙箱）
        2. 检查是否沙箱重建（sandbox_id 变化）
        3. 如果重建，迁移旧沙箱挂载目录的所有文件到新沙箱
        4. 同步本次对话新上传的文件
        5. 更新绑定关系
        6. 注入 Agent/Skill/MCP 配置到沙箱
        """
        from app.repositories.file_repo import SandboxBindingRepository
        from app.services.sandbox_injection import get_injection_service
        
        # 获取旧绑定信息
        old_binding = await SandboxBindingRepository.get_by_session(session_id)
        old_mount_dir = old_binding.mount_dir if old_binding else None
        old_sandbox_id = old_binding.sandbox_id if old_binding else None
        
        # 连接沙箱
        sandboxes = self.sandbox_service.connect(
            session_id=session_id,
            user_id=user_id,
            sandbox_types=["data_analysis"],
        )
        
        if not sandboxes:
            return None, False
        
        sandbox = sandboxes[0]
        
        # 获取新沙箱的挂载目录
        new_mount_dir = await self._get_sandbox_mount_dir(sandbox)
        
        # 检查是否沙箱重建
        sandbox_recreated = old_sandbox_id and old_sandbox_id != sandbox.sandbox_id
        
        if sandbox_recreated and old_mount_dir:
            # 沙箱重建，迁移旧沙箱的所有文件到新沙箱
            await self._migrate_sandbox_files(old_mount_dir, new_mount_dir)
        
        # 同步本次对话新上传的文件
        await self._sync_new_files_to_sandbox(session_id, new_mount_dir, file_ids)
        
        # 更新绑定关系
        await self._update_sandbox_binding(
            user_id=user_id,
            session_id=session_id,
            sandbox_id=sandbox.sandbox_id,
            mount_dir=new_mount_dir,
        )
        
        # 注入 Agent/Skill/MCP 配置到沙箱容器
        try:
            injection_service = get_injection_service()
            inject_result = await injection_service.inject_all(sandbox.sandbox_id)
            if inject_result.get("success"):
                logger.info(f"沙箱配置注入成功: agents={inject_result.get('agents', {}).get('injected', [])}, "
                           f"skills={inject_result.get('skills', {}).get('injected', [])}, "
                           f"mcps={inject_result.get('mcps', {}).get('injected', [])}")
            else:
                logger.warning(f"沙箱配置注入部分失败: {inject_result}")
        except Exception as e:
            logger.error(f"沙箱配置注入异常: {e}")
        
        return sandbox, sandbox_recreated
    
    async def _get_sandbox_mount_dir(self, sandbox) -> Optional[str]:
        """获取沙箱的实际挂载目录"""
        try:
            container_info = self.sandbox_service.manager_api.get_info(sandbox.sandbox_id)
            if container_info:
                return container_info.get("mount_dir")
        except Exception:
            pass
        return None
    
    async def _migrate_sandbox_files(self, old_mount_dir: str, new_mount_dir: str):
        """迁移旧沙箱的所有文件到新沙箱（包括沙箱内产生的文件）"""
        import shutil
        
        if not old_mount_dir or not new_mount_dir:
            return
        
        old_path = Path(old_mount_dir)
        new_path = Path(new_mount_dir)
        
        if not old_path.exists():
            return
        
        if old_path.resolve() == new_path.resolve():
            return
        
        try:
            new_path.mkdir(parents=True, exist_ok=True)
            for item in old_path.iterdir():
                dest = new_path / item.name
                if not dest.exists():
                    if item.is_file():
                        shutil.copy2(item, dest)
                    elif item.is_dir():
                        shutil.copytree(item, dest)
        except Exception:
            pass
    
    async def _sync_new_files_to_sandbox(self, session_id: str, mount_dir: str, file_ids: List[str] = None):
        """同步本次对话新上传的文件到沙箱的 /workspace/data/uploads/ 目录"""
        import shutil
        from app.services.file_service import USER_UPLOADS_DIR
        
        if not mount_dir:
            return
        
        user_dir = USER_UPLOADS_DIR / session_id
        if not user_dir.exists():
            return
        
        # 用户上传的文件放到 data/uploads/ 子目录
        uploads_path = Path(mount_dir) / "data" / "uploads"
        uploads_path.mkdir(parents=True, exist_ok=True)
        
        try:
            for item in user_dir.iterdir():
                dest = uploads_path / item.name
                if not dest.exists():
                    if item.is_file():
                        shutil.copy2(item, dest)
                    elif item.is_dir():
                        shutil.copytree(item, dest)
        except Exception:
            pass
    
    async def _update_sandbox_binding(self, user_id: str, session_id: str, sandbox_id: str, mount_dir: str):
        """更新沙箱绑定关系"""
        from app.repositories.file_repo import SandboxBindingRepository
        
        binding = await SandboxBindingRepository.get_by_session(session_id)
        if binding:
            if binding.sandbox_id != sandbox_id:
                await SandboxBindingRepository.update(
                    session_id=session_id,
                    sandbox_id=sandbox_id,
                    mount_dir=mount_dir,
                    is_active=True,
                )
        else:
            await SandboxBindingRepository.create(
                user_id=user_id,
                session_id=session_id,
                sandbox_id=sandbox_id,
                mount_dir=mount_dir,
            )
    
    def _build_file_hint(self, sandbox_paths: List[str]) -> str:
        """构建文件路径提示"""
        if not sandbox_paths:
            return ""
        
        files_list = "\n".join([f"  - {p}" for p in sandbox_paths])
        return f"""[系统提示] 用户已上传以下文件到沙箱 /workspace/data/uploads/ 目录：
{files_list}

你可以直接使用这些文件路径进行分析。"""


async def get_agent_service() -> AgentService:
    """获取 AgentService 单例实例"""
    return AgentService.get_instance()
