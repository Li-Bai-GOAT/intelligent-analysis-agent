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
import logging
from pathlib import Path
from typing import Optional, List, Generator, AsyncGenerator
logger = logging.getLogger(__name__)

# ==================== 加载环境变量 ====================
# 注意：runtime-sandbox-server 的 extension 加载顺序在 config 之前，
# 所以这里需要手动加载 sandbox.env 以确保环境变量可用

def _load_env_file():

    """手动加载 sandbox.env 文件"""
    # 尝试多个可能的路径
    possible_paths = [
        Path(__file__).parent / "sandbox.env",
    ]
    try:
        possible_paths.append(Path.cwd() / "sandbox.env")
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
            break
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
    ) -> Generator[str, None, None]:

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
    ) -> AsyncGenerator[str, None]:

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
        client = cls.get_async_client()
        headers = headers or {}
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
                            if content.startswith("[ERROR]"):
                                logger.error(f"SSE Error: {content}")
                                return
                            # JSON 解码恢复换行符等特殊字符
                            try:
                                decoded = json.loads(content)
                                yield decoded
                            except json.JSONDecodeError:
                                yield content
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

@SandboxRegistry.register(
    build_image_uri(f"runtime-sandbox-{SANDBOX_TYPE}"),
    sandbox_type=SANDBOX_TYPE,
    security_level="medium",
    timeout=7200,
    description="Data Analysis Sandbox with KunCode AI (pandas, numpy, matplotlib, seaborn, scikit-learn)",
    environment={
        # KunCode 模型配置
        "KUNCODE_MODEL": os.getenv("KUNCODE_MODEL", "minimax-cn/MiniMax-M2.5"),
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
        # 硅基流动
        "SILICONFLOW_API_KEY": os.getenv("SILICONFLOW_API_KEY", "")
    },
    runtime_config={
        "restart_policy": {"Name": "unless-stopped"},
    },
)

class DataAnalysisSandbox(Sandbox):

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
            "prompt": prompt,
            "agent": agent,
            "model": model,
            "files": files,
            "continue_session": continue_session,
            "session_id": session_id,
            "output_format": output_format,
        }
        url = self._get_sse_url()
        headers = self._get_auth_headers()
        accumulated_output = ""
        has_error = False
        try:
            # 使用异步 SSE 流，不阻塞事件循环
            async for line in StreamingClient.stream_sse_async(url, request_data, headers):
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
            # 中断时重新抛出，确保取消正确传播
            logger.info("KunCode SSE streaming cancelled by user")
            raise
        except Exception as e:
            logger.exception("KunCode SSE streaming failed")
            error_msg = f"\n[ERROR] {str(e)}"
            accumulated_output += error_msg
            has_error = True
        # 最后一个 chunk 标记 is_last=True，包含完整累积内容
        yield ToolResponse(
            content=[{"type": "text", "text": accumulated_output}],
            metadata={"success": not has_error},
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
        return self._run_kuncode_command("kuncode mcp list")

@SandboxRegistry.register(
    build_image_uri(f"runtime-sandbox-{SANDBOX_TYPE}"),
    sandbox_type=SANDBOX_TYPE_ASYNC,
    security_level="medium",
    timeout=7200,
    description="Data Analysis Sandbox with KunCode AI (Async)",
    environment={
        # KunCode 模型配置
        "KUNCODE_MODEL": os.getenv("KUNCODE_MODEL", "minimax-cn/MiniMax-M2.5"),
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
        # 硅基流动
        "SILICONFLOW_API_KEY": os.getenv("SILICONFLOW_API_KEY", "")
    },
    runtime_config={
        "restart_policy": {"Name": "unless-stopped"},
    },
)

class DataAnalysisSandboxAsync(SandboxAsync):

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
            "prompt": prompt,
            "agent": agent,
            "model": model,
            "files": files,
            "continue_session": continue_session,
            "session_id": session_id,
            "output_format": output_format,
        }
        url = self._get_sse_url()
        headers = self._get_auth_headers()
        accumulated_output = ""
        try:
            async for line in StreamingClient.stream_sse_async(url, request_data, headers):
                # 实时打印到终端
                print(line, end='', flush=True)
                accumulated_output += line
                # yield 累积输出
                yield ToolResponse(
                    content=[{"type": "text", "text": accumulated_output}],
                    stream=True,
                    is_last=False,
                )
        except Exception as e:
            logger.exception("KunCode SSE streaming failed")
            accumulated_output += f"\n[ERROR] {str(e)}"
        # 最终 yield
        yield ToolResponse(
            content=[{"type": "text", "text": accumulated_output}],
            metadata={"success": "[ERROR]" not in accumulated_output},
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
        return await self._run_kuncode_command("kuncode mcp list")
