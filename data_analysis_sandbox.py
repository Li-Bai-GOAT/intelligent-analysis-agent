# -*- coding: utf-8 -*-

"""
KunCode Data Analysis Sandbox
基于 AgentScope Runtime 的自定义数据分析沙箱
使用方法:
1. 从源码安装 agentscope-runtime (可编辑模式):
   git clone https://github.com/agentscope-ai/agentscope-runtime.git
   cd agentscope-runtime
   git submodule update --init --recursive
   pip install -e .
2. 将此文件复制到 src/agentscope_runtime/sandbox/custom/ 目录下
3. 构建镜像:
   runtime-sandbox-builder data_analysis \
       --dockerfile_path /path/to/sandbox_image/Dockerfile \
       --extension /path/to/sandbox_image/data_analysis_sandbox.py

"""
import os
import re
import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional, List, Generator, AsyncGenerator
logger = logging.getLogger(__name__)


KUNCODE_RUNTIME_CONTEXT = """[DataAgent execution environment]
You are running inside a Debian Linux Docker sandbox, not on the Windows host.
Use POSIX/Bash commands and the /workspace working directory. Do not assume
macOS or Windows paths. Write deliverable files under /workspace subdirectories
and report workspace-relative paths to the user. Never execute generated code
on the host machine.

[Delivery and execution policy]
For a file-generation request, deliver only the artifact(s) the user asked for.
Put temporary scripts in /workspace/code (never /workspace/scripts), treat them
as internal implementation details, and do not list them as deliverables. Put
user-facing outputs in /workspace/results, /workspace/charts, or
/workspace/reports. Before installing any dependency, check whether the needed
package already exists. For a single-file request, use a focused generator and
one targeted verification; do not dump exhaustive workbook contents or perform
unrelated repeated checks after the requested artifact has validated."""
KUNCODE_OUTCOME_MARKER_PREFIX = "[[DATAAGENT_KUNCODE_OUTCOME:"
KUNCODE_OUTCOME_MARKER_SUFFIX = "]]"


def _build_kuncode_runtime_prompt(prompt: str) -> str:
    """Add deterministic sandbox facts without changing the user-visible task."""
    normalized = str(prompt or "").strip()
    if KUNCODE_RUNTIME_CONTEXT in normalized:
        return normalized
    return f"{KUNCODE_RUNTIME_CONTEXT}\n\n[User task]\n{normalized}"


def _normalize_kuncode_outcome(value: Any) -> dict[str, Any] | None:
    """Validate only the small terminal outcome contract used by this adapter."""
    if not isinstance(value, dict) or value.get("event") != "kuncode_result":
        return None
    exit_code = value.get("exit_code")
    if isinstance(exit_code, bool):
        exit_code = None
    elif exit_code is not None:
        try:
            exit_code = int(exit_code)
        except (TypeError, ValueError):
            exit_code = None
    error_code = value.get("error_code")
    termination_reason = value.get("termination_reason")
    if termination_reason not in {"completed", "timeout", "cancelled", "process_error"}:
        termination_reason = "completed" if value.get("success") else "process_error"
    return {
        "success": bool(value.get("success")),
        "exit_code": exit_code,
        "error_code": str(error_code) if error_code else None,
        "termination_reason": termination_reason,
        "execution_id": str(value.get("execution_id")) if value.get("execution_id") else None,
    }


def _encode_kuncode_outcome_marker(outcome: dict[str, Any]) -> str:
    """Keep terminal metadata available through AgentScope's text-only block."""
    payload = {
        "success": bool(outcome.get("success")),
        "exit_code": outcome.get("exit_code"),
        "error_code": outcome.get("error_code"),
        "termination_reason": outcome.get("termination_reason"),
        "execution_id": outcome.get("execution_id"),
    }
    return (
        f"\n{KUNCODE_OUTCOME_MARKER_PREFIX}"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        f"{KUNCODE_OUTCOME_MARKER_SUFFIX}"
    )

# ==================== 加载环境变量 ====================
# 注意：runtime-sandbox-server 的 extension 加载顺序在 config 之前，
# 所以这里需要手动加载 sandbox.env 以确保环境变量可用

def _load_env_file():

    """手动加载 sandbox.env 文件"""
    # 尝试多个可能的路径
    possible_paths = [
        Path(__file__).parent / "sandbox.env",
        Path(__file__).parent / ".env",
    ]
    try:
        possible_paths.append(Path.cwd() / "sandbox.env")
        possible_paths.append(Path.cwd() / ".env")
    except OSError:
        pass
    for env_path in possible_paths:
        if env_path.exists():
            with open(env_path, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and value and not os.environ.get(key):
                            os.environ[key] = value
_load_env_file()
from agentscope_runtime.sandbox.utils import build_image_uri  # noqa: E402
from agentscope_runtime.sandbox.registry import SandboxRegistry  # noqa: E402
from agentscope_runtime.sandbox.enums import SandboxType  # noqa: E402
from agentscope_runtime.sandbox.box.sandbox import Sandbox, SandboxAsync  # noqa: E402

# ==================== Streaming Client ====================

class StreamingClient:

    """
    封装 httpx 的流式客户端，用于 SSE 请求
    参考 agentscope-runtime 代码风格，提供同步和异步两种模式。

    """
    _sync_client = None
    _async_client = None

    @classmethod

    def get_sync_client(cls):

        """获取同步 httpx 客户端（懒加载）"""
        if cls._sync_client is None:
            import httpx
            cls._sync_client = httpx.Client(timeout=7200.0)
        return cls._sync_client

    @classmethod

    def get_async_client(cls):

        """获取异步 httpx 客户端（懒加载）"""
        if cls._async_client is None:
            import httpx
            # 使用分段超时：连接10秒，读取1800秒（30分钟，KunCode任务可能需要较长处理时间），总时间7200秒
            timeout = httpx.Timeout(timeout=7200.0, connect=10.0, read=1800.0)
            cls._async_client = httpx.AsyncClient(timeout=timeout)
        return cls._async_client

    @classmethod

    def close_clients(cls):

        """关闭所有客户端"""
        if cls._sync_client is not None:
            cls._sync_client.close()
            cls._sync_client = None
        if cls._async_client is not None:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(cls._async_client.aclose())
                else:
                    loop.run_until_complete(cls._async_client.aclose())
            except Exception:
                pass
            cls._async_client = None

    @classmethod

    def stream_sse_sync(
        cls,
        url: str,
        json_data: dict,
        headers: Optional[dict] = None,
    ) -> Generator[Any, None, None]:

        """
        同步 SSE 流式请求（真正流式，立即输出）
        Args:
            url: 请求 URL
            json_data: POST 请求体
            headers: 请求头
        Yields:
            收到的内容片段

        """
        import codecs
        import json
        client = cls.get_sync_client()
        headers = headers or {}
        with client.stream("POST", url, json=json_data, headers=headers) as response:
            response.raise_for_status()
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            buffer = ""
            for chunk in response.iter_bytes():
                text = decoder.decode(chunk)
                buffer += text
                # 处理完整的 SSE 事件（以 \n\n 分隔）
                while "\n\n" in buffer:
                    event, buffer = buffer.split("\n\n", 1)
                    for line in event.split("\n"):
                        line = line.strip()
                        if line.startswith("data: "):
                            content = line[6:]
                            if content == "[DONE]":
                                return
                            if content.startswith("[ERROR]"):
                                logger.error(f"SSE Error: {content}")
                                yield content
                                return
                            # JSON 解码恢复换行符等特殊字符
                            try:
                                decoded = json.loads(content)
                                yield decoded
                            except json.JSONDecodeError:
                                yield content

    @classmethod
    async def stream_sse_async(
        cls,
        url: str,
        json_data: dict,
        headers: Optional[dict] = None,
        timeout_seconds: Optional[float] = None,
    ) -> AsyncGenerator[Any, None]:

        """
        异步 SSE 流式请求（真正流式，立即输出）
        Args:
            url: 请求 URL
            json_data: POST 请求体
            headers: 请求头
        Yields:
            收到的内容片段

        """
        import codecs
        import json
        headers = headers or {}
        import httpx
        total_timeout = max(0.1, timeout_seconds or 7200.0)
        timeout = httpx.Timeout(
            timeout=total_timeout,
            connect=min(10.0, total_timeout),
            read=total_timeout,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=json_data, headers=headers) as response:
                response.raise_for_status()
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                buffer = ""
                async for chunk in response.aiter_bytes():
                    text = decoder.decode(chunk)
                    buffer += text
                    # 处理完整的 SSE 事件（以 \n\n 分隔）
                    while "\n\n" in buffer:
                        event, buffer = buffer.split("\n\n", 1)
                        for line in event.split("\n"):
                            line = line.strip()
                            if line.startswith("data: "):
                                content = line[6:]
                                if content == "[DONE]":
                                    return
                                # JSON 解码恢复换行符等特殊字符
                                try:
                                    decoded = json.loads(content)
                                    yield decoded
                                except json.JSONDecodeError:
                                    yield content

    @classmethod
    async def request_json_async(
        cls,
        method: str,
        url: str,
        *,
        json_data: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout_seconds: float = 10.0,
    ) -> dict:
        import httpx
        timeout_seconds = max(0.1, timeout_seconds)
        timeout = httpx.Timeout(
            timeout=timeout_seconds,
            connect=min(10.0, timeout_seconds),
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                url,
                json=json_data,
                headers=headers or {},
            )
            response.raise_for_status()
            return response.json()
# 沙箱类型标识符
SANDBOX_TYPE = "data_analysis"
SANDBOX_TYPE_ASYNC = "data_analysis_async"
# 禁止通过 run_shell_command 直接执行的 kuncode 命令模式
KUNCODE_COMMAND_PATTERN = re.compile(r"^\s*kuncode\b", re.IGNORECASE)
# 禁止在 Python 代码中通过 subprocess/os.system 执行 kuncode 命令的模式
KUNCODE_IN_CODE_PATTERN = re.compile(
    r"(subprocess\.(run|call|Popen|check_output|check_call)\s*\(.*kuncode|" +
    r"os\.(system|popen)\s*\(.*kuncode|" +
    r"!\s*kuncode)",
    re.IGNORECASE | re.DOTALL
)

KUNCODE_FAILURE_PATTERNS = (
    "exited with code",
    "was stopped",
)


def _is_kuncode_failure(output: str) -> bool:
    lowered = output.lower().strip()
    if not lowered:
        return True
    last_line = next(
        (line.strip() for line in reversed(lowered.splitlines()) if line.strip()),
        "",
    )
    return (
        last_line.startswith("[error]")
        or any(pattern in last_line for pattern in KUNCODE_FAILURE_PATTERNS)
    )


def _append_kuncode_failure_hint(output: str) -> str:
    if not output.strip():
        output = "[ERROR] KunCode returned no output."
    hint = (
        "\n[ERROR] KunCode execution failed. "
        "Check the configured agent, model, provider API key, and sandbox KunCode config."
    )
    return output if hint in output else output + hint


def _finalize_kuncode_outcome(
    output: str,
    outcome: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a structured terminal outcome for both new and old sandboxes."""
    if outcome is not None:
        return outcome
    failed = _is_kuncode_failure(output)
    return {
        "success": not failed,
        "exit_code": None,
        "error_code": "KUNCODE_STREAM_ERROR" if failed else None,
        "termination_reason": "process_error" if failed else "completed",
        "execution_id": None,
    }


def _normalize_kuncode_agent(agent: Optional[str]) -> Optional[str]:
    if agent is None:
        return None
    normalized = str(agent).strip()
    if not normalized or normalized.lower() in {"none", "null", "undefined", "default"}:
        return None
    return normalized


class _KunCodeExecutionControl:
    """Carry one top-level execution deadline through the sandbox HTTP calls."""

    def configure_execution_context(
        self,
        *,
        execution_id: str,
        deadline_at_ms: int,
    ) -> None:
        self._dataagent_execution_id = execution_id
        self._dataagent_deadline_at_ms = deadline_at_ms

    def _execution_context(self) -> tuple[str, int | None, float]:
        execution_id = getattr(self, "_dataagent_execution_id", None) or uuid.uuid4().hex
        deadline_at_ms = getattr(self, "_dataagent_deadline_at_ms", None)
        if deadline_at_ms is None:
            remaining = 7200.0
        else:
            remaining = max(0.1, (deadline_at_ms - int(time.time() * 1000)) / 1000.0)
        return execution_id, deadline_at_ms, remaining

    def _control_url(self, path: str) -> str:
        return f"{self.base_url}/sandbox/{self.sandbox_id}/fastapi/{path}"

    async def cancel_kuncode(
        self,
        execution_id: Optional[str] = None,
        *,
        grace_seconds: float = 5.0,
        confirmation_timeout: float = 10.0,
        termination_reason: str = "cancelled",
    ) -> dict[str, Any]:
        execution_id = execution_id or getattr(self, "_dataagent_execution_id", None)
        if not execution_id:
            return {
                "active": False,
                "termination_confirmed": True,
                "already_stopped": True,
            }
        return await StreamingClient.request_json_async(
            "POST",
            self._control_url("cancel_kuncode"),
            json_data={
                "execution_id": execution_id,
                "grace_seconds": grace_seconds,
                "termination_reason": termination_reason,
            },
            headers=self._get_auth_headers(),
            timeout_seconds=confirmation_timeout,
        )

    async def kuncode_process_status(
        self,
        execution_id: Optional[str] = None,
    ) -> dict[str, Any]:
        execution_id = execution_id or getattr(self, "_dataagent_execution_id", None)
        if not execution_id:
            return {"active": False, "termination_confirmed": True, "not_found": True}
        return await StreamingClient.request_json_async(
            "GET",
            self._control_url(f"kuncode/process/{execution_id}"),
            headers=self._get_auth_headers(),
            timeout_seconds=10.0,
        )


@SandboxRegistry.register(
    build_image_uri(f"runtime-sandbox-{SANDBOX_TYPE}"),
    sandbox_type=SANDBOX_TYPE,
    security_level="medium",
    timeout=7200,
    description="Data Analysis Sandbox with KunCode AI (pandas, numpy, matplotlib, seaborn, scikit-learn)",
    environment={
        # KunCode 模型配置
        "KUNCODE_MODEL": os.getenv("KUNCODE_MODEL", "deepseek/deepseek-v4-flash"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        # MiniMax
        "MINIMAX_API_KEY": os.getenv("MINIMAX_API_KEY", ""),
        # DeepSeek
        "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""),
        "DEEPSEEK_BASE_URL": os.getenv("DEEPSEEK_BASE_URL", ""),
        # Anthropic
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
        "ANTHROPIC_BASE_URL": os.getenv("ANTHROPIC_BASE_URL", ""),
        # 自定义 MMChat Claude
        "mmchat_ANTHROPIC_API_KEY": os.getenv("mmchat_ANTHROPIC_API_KEY", ""),
        "mmchat_ANTHROPIC_BASE_URL": os.getenv("mmchat_ANTHROPIC_BASE_URL", ""),
        # OpenAI
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", ""),
        # Mimo (OpenAI-compatible)
        "MIMO_API_KEY": os.getenv("MIMO_API_KEY", ""),
        "MIMO_BASE_URL": os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"),
        # 硅基流动
        "SILICONFLOW_API_KEY": os.getenv("SILICONFLOW_API_KEY", "")
    },
    runtime_config={
        # Session sandboxes are runtime-managed resources, not persistent
        # infrastructure. A Docker daemon restart must not revive an orphan.
        "restart_policy": {"Name": "no"},
        # Session-specific metadata is persisted in PostgreSQL and Runtime
        # mapping metadata. AgentScope 1.0.5 only accepts static Docker labels
        # at registry time, so use these labels to identify project ownership.
        "labels": {
            "app": "dataagent",
            "sandbox_type": "data_analysis",
            "config_version": os.getenv("SANDBOX_CONFIG_VERSION", "deepseek-v1"),
        },
    },
)

class DataAnalysisSandbox(_KunCodeExecutionControl, Sandbox):

    """
    数据分析沙箱类（同步版本）
    特性:
    - 集成 KunCode CLI 工具，支持多种 LLM 提供商
    - 预装数据分析库: pandas, numpy, matplotlib, seaborn, scikit-learn, scipy, statsmodels
    - 支持 Excel 文件处理: openpyxl, xlrd
    - 支持数据分析: 连环替代法、SHAP归因、K-means聚类
    - 工作目录: /workspace

    """

    def __init__(
        self,
        sandbox_id: Optional[str] = None,
        timeout: int = 7200,
        base_url: Optional[str] = None,
        bearer_token: Optional[str] = None,
    ):
        super().__init__(
            sandbox_id,
            timeout,
            base_url,
            bearer_token,
            SandboxType(SANDBOX_TYPE),
        )
        # 保存 bearer_token 供 SSE 流式请求使用
        self._bearer_token = bearer_token

    def run_ipython_cell(self, code: str):

        """
        在 IPython 环境中执行 Python 代码（禁止通过 subprocess/os.system 执行 kuncode）
        Args:
            code (str): 要执行的 Python 代码
        Returns:
            执行结果
        Raises:
            ValueError: 如果代码中包含通过 subprocess/os.system 执行 kuncode 的调用

        """
        if KUNCODE_IN_CODE_PATTERN.search(code):
            raise ValueError(
                "禁止在 Python 代码中通过 subprocess/os.system 执行 kuncode 命令。"
                "请使用沙箱提供的专用方法: run_kuncode(), kuncode_models() 等。"
            )
        return self.call_tool("run_ipython_cell", {"code": code})

    def run_shell_command(self, command: str):

        """
        执行 Shell 命令（禁止直接执行 kuncode 命令，请使用专用方法）
        Args:
            command (str): 要执行的 Shell 命令
        Returns:
            命令输出
        Raises:
            ValueError: 如果尝试直接执行 kuncode 命令

        """
        if KUNCODE_COMMAND_PATTERN.match(command):
            raise ValueError(
                "禁止通过 run_shell_command 直接执行 kuncode 命令。"
                "请使用专用方法: run_kuncode(), kuncode_models(), kuncode_session_list(), "
                "kuncode_mcp_list() 等。"
            )
        return self.call_tool("run_shell_command", {"command": command})

    def _run_kuncode_command(self, command: str):

        """内部方法：执行 kuncode 命令（绕过拦截）"""
        return self.call_tool("run_shell_command", {"command": command})

    # ==================== KunCode Run (流式输出) ====================

    def _get_sse_url(self) -> str:

        """
        获取 SSE 路由的 URL
        使用 SandboxManager 代理路由，支持远程场景：
        /sandbox/{sandbox_id}/fastapi/run_kuncode

        """
        return f"{self.base_url}/sandbox/{self.sandbox_id}/fastapi/run_kuncode"

    def _get_auth_headers(self) -> dict:

        """获取认证请求头（使用 SandboxManager 的 bearer token）"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        return headers
    async def run_kuncode(
        self,
        prompt: str,
        agent: Optional[str] = None,
        model: Optional[str] = None,
        files: Optional[List[str]] = None,
        continue_session: bool = False,
        session_id: Optional[str] = None,
        output_format: str = "default",
    ) -> AsyncGenerator:

        """
        执行 KunCode run 命令（异步流式输出）
        通过容器内 SSE 路由实现流式输出，每个 chunk 作为一个 ToolResponse 返回。
        Args:
            prompt (str): 发送给 KunCode 的提示/任务描述
            agent (str): 指定使用的智能体名称
            model (str, optional): 覆盖默认模型
            continue_session (bool): 是否继续上次会话
            session_id (str, optional): 指定会话 ID
            output_format (str): 输出格式 ("default" 或 "json")
        Yields:
            ToolResponse: 流式输出的每个 chunk（累积式）

        """
        from agentscope.tool import ToolResponse
        # 构建请求参数
        request_data = {
            "prompt": _build_kuncode_runtime_prompt(prompt),
            "agent": _normalize_kuncode_agent(agent),
            "model": model,
            "files": files,
            "continue_session": continue_session,
            "session_id": session_id,
            "output_format": output_format,
        }
        execution_id, deadline_at_ms, remaining_seconds = self._execution_context()
        request_data.update({
            "execution_id": execution_id,
            "deadline_at_ms": deadline_at_ms,
        })
        url = self._get_sse_url()
        headers = self._get_auth_headers()
        accumulated_output = ""
        terminal_outcome: dict[str, Any] | None = None
        try:
            # 使用异步 SSE 流，不阻塞事件循环
            async for event in StreamingClient.stream_sse_async(
                url,
                request_data,
                headers,
                timeout_seconds=remaining_seconds + 7.0,
            ):
                structured_outcome = _normalize_kuncode_outcome(event)
                if structured_outcome is not None:
                    terminal_outcome = structured_outcome
                    continue
                line = (
                    event
                    if isinstance(event, str)
                    else json.dumps(event, ensure_ascii=False)
                )
                # 实时打印到终端
                print(line, end='', flush=True)
                accumulated_output += line
                # 流式返回：累积式，当前块包含之前所有内容
                yield ToolResponse(
                    content=[{"type": "text", "text": accumulated_output}],
                    stream=True,
                    is_last=False,
                )
        except asyncio.CancelledError:
            logger.info("KunCode SSE streaming cancelled by user")
            cancel_reason = (
                "timeout"
                if deadline_at_ms is not None
                and deadline_at_ms <= int(time.time() * 1000)
                else "cancelled"
            )
            try:
                await asyncio.shield(self.cancel_kuncode(
                    execution_id,
                    termination_reason=cancel_reason,
                ))
            except Exception:
                logger.exception("KunCode cancellation confirmation failed")
            raise
        except Exception as e:
            logger.exception("KunCode SSE streaming failed")
            error_msg = f"\n[ERROR] KunCode stream request failed: {str(e)}"
            accumulated_output += error_msg
            terminal_outcome = {
                "success": False,
                "exit_code": None,
                "error_code": "KUNCODE_STREAM_INCOMPLETE",
                "termination_reason": "timeout" if e.__class__.__name__.endswith("Timeout") else "process_error",
                "execution_id": execution_id,
            }
        terminal_outcome = _finalize_kuncode_outcome(
            accumulated_output,
            terminal_outcome,
        )
        if not terminal_outcome["success"]:
            accumulated_output = _append_kuncode_failure_hint(accumulated_output)
        # 最后一个 chunk 标记 is_last=True，包含完整累积内容
        yield ToolResponse(
            content=[{
                "type": "text",
                "text": accumulated_output + _encode_kuncode_outcome_marker(terminal_outcome),
            }],
            metadata=terminal_outcome,
            stream=True,
            is_last=True,
        )

    # ==================== KunCode Session ====================

    def kuncode_session_list(self):

        """
        列出所有会话
        Returns:
            会话列表

        """
        return self._run_kuncode_command("kuncode session list")

    # ==================== KunCode MCP ====================

    def kuncode_mcp_list(self):

        """
        列出所有 MCP 服务器
        Returns:
            MCP 服务器列表

        """
        # Remote MCP endpoints may include credentials in query parameters.
        # Preserve the diagnostic while never echoing credential values.
        return self._run_kuncode_command(
            "kuncode mcp list | sed -E 's/([?&](key|api_key|apikey|token|access_token|secret)=)[^&[:space:]]+/\\1***/Ig'"
        )

@SandboxRegistry.register(
    build_image_uri(f"runtime-sandbox-{SANDBOX_TYPE}"),
    sandbox_type=SANDBOX_TYPE_ASYNC,
    security_level="medium",
    timeout=7200,
    description="Data Analysis Sandbox with KunCode AI (Async)",
    environment={
        # KunCode 模型配置
        "KUNCODE_MODEL": os.getenv("KUNCODE_MODEL", "deepseek/deepseek-v4-flash"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        # MiniMax
        "MINIMAX_API_KEY": os.getenv("MINIMAX_API_KEY", ""),
        # DeepSeek
        "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""),
        "DEEPSEEK_BASE_URL": os.getenv("DEEPSEEK_BASE_URL", ""),
        # Anthropic
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
        "ANTHROPIC_BASE_URL": os.getenv("ANTHROPIC_BASE_URL", ""),
        # 自定义 MMChat Claude
        "mmchat_ANTHROPIC_API_KEY": os.getenv("mmchat_ANTHROPIC_API_KEY", ""),
        "mmchat_ANTHROPIC_BASE_URL": os.getenv("mmchat_ANTHROPIC_BASE_URL", ""),
        # OpenAI
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", ""),
        # Mimo (OpenAI-compatible)
        "MIMO_API_KEY": os.getenv("MIMO_API_KEY", ""),
        "MIMO_BASE_URL": os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"),
        # 硅基流动
        "SILICONFLOW_API_KEY": os.getenv("SILICONFLOW_API_KEY", "")
    },
    runtime_config={
        "restart_policy": {"Name": "no"},
        "labels": {
            "app": "dataagent",
            "sandbox_type": "data_analysis",
            "config_version": os.getenv("SANDBOX_CONFIG_VERSION", "deepseek-v1"),
        },
    },
)

class DataAnalysisSandboxAsync(_KunCodeExecutionControl, SandboxAsync):

    """
    数据分析沙箱类（异步版本）
    特性:
    - 集成 KunCode CLI 工具，支持多种 LLM 提供商
    - 预装数据分析库: pandas, numpy, matplotlib, seaborn, scikit-learn, scipy, statsmodels
    - 支持 Excel 文件处理: openpyxl, xlrd
    - 支持数据分析: 连环替代法、SHAP归因、K-means聚类
    - 工作目录: /workspace

    """

    def __init__(
        self,
        sandbox_id: Optional[str] = None,
        timeout: int = 7200,
        base_url: Optional[str] = None,
        bearer_token: Optional[str] = None,
    ):
        super().__init__(
            sandbox_id,
            timeout,
            base_url,
            bearer_token,
            SandboxType(SANDBOX_TYPE_ASYNC),
        )
        # 保存 bearer_token 供 SSE 流式请求使用
        self._bearer_token = bearer_token
    async def run_ipython_cell(self, code: str):

        """
        在 IPython 环境中异步执行 Python 代码（禁止通过 subprocess/os.system 执行 kuncode）
        Args:
            code (str): 要执行的 Python 代码
        Returns:
            执行结果
        Raises:
            ValueError: 如果代码中包含通过 subprocess/os.system 执行 kuncode 的调用

        """
        if KUNCODE_IN_CODE_PATTERN.search(code):
            raise ValueError(
                "禁止在 Python 代码中通过 subprocess/os.system 执行 kuncode 命令。"
                "请使用沙箱提供的专用方法: run_kuncode(), kuncode_models() 等。"
            )
        return await self.call_tool_async("run_ipython_cell", {"code": code})
    async def run_shell_command(self, command: str):

        """
        异步执行 Shell 命令（禁止直接执行 kuncode 命令，请使用专用方法）
        Args:
            command (str): 要执行的 Shell 命令
        Returns:
            命令输出
        Raises:
            ValueError: 如果尝试直接执行 kuncode 命令

        """
        if KUNCODE_COMMAND_PATTERN.match(command):
            raise ValueError(
                "禁止通过 run_shell_command 直接执行 kuncode 命令。"
                "请使用专用方法: run_kuncode(), kuncode_models(), kuncode_session_list(), "
                "kuncode_mcp_list() 等。"
            )
        return await self.call_tool_async("run_shell_command", {"command": command})
    async def _run_kuncode_command(self, command: str):

        """内部方法：执行 kuncode 命令（绕过拦截）"""
        return await self.call_tool_async("run_shell_command", {"command": command})

    # ==================== KunCode Run (流式输出) ====================

    def _get_sse_url(self) -> str:

        """
        获取 SSE 路由的 URL
        使用 SandboxManager 代理路由，支持远程场景：
        /sandbox/{sandbox_id}/fastapi/run_kuncode

        """
        return f"{self.base_url}/sandbox/{self.sandbox_id}/fastapi/run_kuncode"

    def _get_auth_headers(self) -> dict:

        """获取认证请求头（使用 SandboxManager 的 bearer token）"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        return headers
    async def run_kuncode(
        self,
        prompt: str,
        agent: Optional[str] = None,
        model: Optional[str] = None,
        files: Optional[List[str]] = None,
        continue_session: bool = False,
        session_id: Optional[str] = None,
        output_format: str = "default",
    ):

        """
        异步执行 KunCode run 命令（流式输出）
        通过容器内 SSE 路由实现流式输出。
        Args:
            prompt (str): 发送给 KunCode 的提示/任务描述
            agent (str, optional): 指定使用的智能体名称，不指定则使用默认智能体
            model (str, optional): 覆盖默认模型
            files (List[str], optional): 附加到上下文的文件路径列表
            continue_session (bool): 是否继续上次会话
            session_id (str, optional): 指定会话 ID
            output_format (str): 输出格式 ("default" 或 "json")
        Yields:
            ToolResponse: 流式输出的每一块内容

        """
        from agentscope.tool import ToolResponse
        # 构建请求参数
        request_data = {
            "prompt": _build_kuncode_runtime_prompt(prompt),
            "agent": _normalize_kuncode_agent(agent),
            "model": model,
            "files": files,
            "continue_session": continue_session,
            "session_id": session_id,
            "output_format": output_format,
        }
        execution_id, deadline_at_ms, remaining_seconds = self._execution_context()
        request_data.update({
            "execution_id": execution_id,
            "deadline_at_ms": deadline_at_ms,
        })
        url = self._get_sse_url()
        headers = self._get_auth_headers()
        accumulated_output = ""
        terminal_outcome: dict[str, Any] | None = None
        try:
            async for event in StreamingClient.stream_sse_async(
                url,
                request_data,
                headers,
                timeout_seconds=remaining_seconds + 7.0,
            ):
                structured_outcome = _normalize_kuncode_outcome(event)
                if structured_outcome is not None:
                    terminal_outcome = structured_outcome
                    continue
                line = (
                    event
                    if isinstance(event, str)
                    else json.dumps(event, ensure_ascii=False)
                )
                # 实时打印到终端
                print(line, end='', flush=True)
                accumulated_output += line
                # yield 累积输出
                yield ToolResponse(
                    content=[{"type": "text", "text": accumulated_output}],
                    stream=True,
                    is_last=False,
                )
        except asyncio.CancelledError:
            logger.info("KunCode SSE streaming cancelled by user")
            cancel_reason = (
                "timeout"
                if deadline_at_ms is not None
                and deadline_at_ms <= int(time.time() * 1000)
                else "cancelled"
            )
            try:
                await asyncio.shield(self.cancel_kuncode(
                    execution_id,
                    termination_reason=cancel_reason,
                ))
            except Exception:
                logger.exception("KunCode cancellation confirmation failed")
            raise
        except Exception as e:
            logger.exception("KunCode SSE streaming failed")
            accumulated_output += f"\n[ERROR] KunCode stream request failed: {str(e)}"
            terminal_outcome = {
                "success": False,
                "exit_code": None,
                "error_code": "KUNCODE_STREAM_INCOMPLETE",
                "termination_reason": "timeout" if e.__class__.__name__.endswith("Timeout") else "process_error",
                "execution_id": execution_id,
            }
        terminal_outcome = _finalize_kuncode_outcome(
            accumulated_output,
            terminal_outcome,
        )
        if not terminal_outcome["success"]:
            accumulated_output = _append_kuncode_failure_hint(accumulated_output)
        # 最终 yield
        yield ToolResponse(
            content=[{
                "type": "text",
                "text": accumulated_output + _encode_kuncode_outcome_marker(terminal_outcome),
            }],
            metadata=terminal_outcome,
            stream=True,
            is_last=True,
        )

    # ==================== KunCode Session ====================
    async def kuncode_session_list(self):

        """
        列出所有会话
        Returns:
            会话列表

        """
        return await self._run_kuncode_command("kuncode session list")

    # ==================== KunCode MCP ====================
    async def kuncode_mcp_list(self):

        """
        列出所有 MCP 服务器
        Returns:
            MCP 服务器列表

        """
        # Keep asynchronous diagnostics subject to the same redaction policy.
        return await self._run_kuncode_command(
            "kuncode mcp list | sed -E 's/([?&](key|api_key|apikey|token|access_token|secret)=)[^&[:space:]]+/\\1***/Ig'"
        )
