# -*- coding: utf-8 -*-
"""
沙箱配置注入服务

使用 Docker API 将动态配置（Agent、Skill、MCP）注入到沙箱容器中
"""

import io
import json
import tarfile
import logging
from pathlib import Path
from typing import Optional

import docker
from docker.errors import NotFound, APIError

from app.models import SandboxAgent, SandboxSkill, SandboxSkillPermission, SandboxMcp

# Skill 本地存储目录
SKILL_STORAGE_DIR = Path("sandbox_skills")

logger = logging.getLogger(__name__)


class SandboxInjectionService:
    """沙箱配置注入服务"""
    
    # KunCode 配置路径
    KUNCODE_CONFIG_DIR = "/root/.config/kuncode"
    AGENT_DIR = f"{KUNCODE_CONFIG_DIR}/agent"
    SKILL_DIR = f"{KUNCODE_CONFIG_DIR}/skill"
    KUNCODE_JSON_PATH = f"{KUNCODE_CONFIG_DIR}/kuncode.json"
    
    def __init__(self, docker_client: Optional[docker.DockerClient] = None):
        """
        初始化注入服务
        
        Args:
            docker_client: Docker 客户端实例，为空则自动创建
        """
        self._client = docker_client
    
    @property
    def client(self) -> docker.DockerClient:
        """获取 Docker 客户端（延迟初始化）"""
        if self._client is None:
            self._client = docker.from_env()
        return self._client
    
    def _create_tar_archive(self, files: dict[str, bytes]) -> io.BytesIO:
        """
        创建 tar 归档
        
        Args:
            files: 文件字典 {文件路径: 内容}，支持嵌套路径如 "subdir/file.py"
        
        Returns:
            tar 归档的字节流
        """
        tar_stream = io.BytesIO()
        created_dirs = set()
        
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            for filepath, content in files.items():
                # 先创建所有父目录条目
                parts = filepath.split("/")
                for i in range(1, len(parts)):
                    dir_path = "/".join(parts[:i])
                    if dir_path and dir_path not in created_dirs:
                        dir_info = tarfile.TarInfo(name=dir_path + "/")
                        dir_info.type = tarfile.DIRTYPE
                        dir_info.mode = 0o755
                        tar.addfile(dir_info)
                        created_dirs.add(dir_path)
                
                # 添加文件
                file_data = io.BytesIO(content)
                tarinfo = tarfile.TarInfo(name=filepath)
                tarinfo.size = len(content)
                tarinfo.mode = 0o644
                tar.addfile(tarinfo, file_data)
        
        tar_stream.seek(0)
        return tar_stream
    
    def _put_file_to_container(
        self,
        container_id: str,
        target_dir: str,
        filename: str,
        content: bytes,
    ) -> bool:
        """
        将单个文件上传到容器
        
        Args:
            container_id: 容器 ID 或名称
            target_dir: 目标目录
            filename: 文件名
            content: 文件内容
        
        Returns:
            是否成功
        """
        try:
            container = self.client.containers.get(container_id)
            tar_stream = self._create_tar_archive({filename: content})
            container.put_archive(target_dir, tar_stream)
            logger.debug(f"上传文件到容器 {container_id}: {target_dir}/{filename}")
            return True
        except NotFound:
            logger.error(f"容器不存在: {container_id}")
            return False
        except APIError as e:
            logger.error(f"Docker API 错误: {e}")
            return False
    
    def _put_directory_to_container(
        self,
        container_id: str,
        target_dir: str,
        files: dict[str, bytes],
    ) -> bool:
        """
        将多个文件上传到容器的同一目录
        
        Args:
            container_id: 容器 ID 或名称
            target_dir: 目标目录
            files: 文件字典 {文件名: 内容}
        
        Returns:
            是否成功
        """
        if not files:
            return True
        
        try:
            container = self.client.containers.get(container_id)
            tar_stream = self._create_tar_archive(files)
            container.put_archive(target_dir, tar_stream)
            logger.debug(f"上传 {len(files)} 个文件到容器 {container_id}: {target_dir}")
            return True
        except NotFound:
            logger.error(f"容器不存在: {container_id}")
            return False
        except APIError as e:
            logger.error(f"Docker API 错误: {e}")
            return False
    
    def _exec_in_container(self, container_id: str, command: list[str]) -> tuple[int, str]:
        """
        在容器中执行命令
        
        Args:
            container_id: 容器 ID
            command: 命令列表
        
        Returns:
            (退出码, 输出)
        """
        try:
            container = self.client.containers.get(container_id)
            result = container.exec_run(command, demux=True)
            stdout = result.output[0].decode() if result.output[0] else ""
            stderr = result.output[1].decode() if result.output[1] else ""
            return result.exit_code, stdout + stderr
        except Exception as e:
            logger.error(f"执行命令失败: {e}")
            return -1, str(e)
    
    def _ensure_mimo_provider(self, kuncode_config: dict) -> None:
        """Ensure KunCode can use Mimo through an OpenAI-compatible provider."""
        if kuncode_config.get("model") == "mimo-v2.5-pro":
            kuncode_config["model"] = "mimo/mimo-v2.5-pro"
        kuncode_config.setdefault("small_model", kuncode_config.get("model", "{env:KUNCODE_MODEL}"))

        providers = kuncode_config.setdefault("provider", {})
        providers["mimo"] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Mimo",
            "options": {
                "apiKey": "{env:MIMO_API_KEY}",
                "baseURL": "{env:MIMO_BASE_URL}",
            },
            "models": {
                "mimo-v2.5-pro": {
                    "name": "mimo-v2.5-pro",
                    "tool_call": True,
                    "temperature": True,
                    "limit": {
                        "context": 200000,
                        "output": 32000,
                    },
                },
            },
        }

    async def inject_agents(self, container_id: str) -> dict:
        """
        注入所有启用的 Agent 配置到容器
        
        Args:
            container_id: 容器 ID
        
        Returns:
            注入结果 {success: bool, injected: list, errors: list}
        """
        result = {"success": True, "injected": [], "errors": []}
        
        # 获取所有启用的 Agent
        agents = await SandboxAgent.filter(enabled=True).all()
        
        if not agents:
            logger.info("没有启用的 Agent 需要注入")
            return result
        
        # 确保目录存在
        self._exec_in_container(container_id, ["mkdir", "-p", self.AGENT_DIR])
        
        # 生成 Agent 文件
        files = {}
        for agent in agents:
            filename = f"{agent.name}.md"
            content = agent.to_markdown().encode("utf-8")
            files[filename] = content
        
        # 上传到容器
        if self._put_directory_to_container(container_id, self.AGENT_DIR, files):
            result["injected"] = [a.name for a in agents]
            logger.info(f"成功注入 {len(agents)} 个 Agent: {result['injected']}")
        else:
            result["success"] = False
            result["errors"].append("Agent 文件上传失败")
        
        return result
    
    async def inject_skills(self, container_id: str) -> dict:
        """
        注入所有启用的 Skill 配置到容器
        
        Args:
            container_id: 容器 ID
        
        Returns:
            注入结果 {success: bool, injected: list, errors: list}
        """
        result = {"success": True, "injected": [], "errors": []}
        
        # 获取所有启用的 Skill
        skills = await SandboxSkill.filter(enabled=True).all()
        
        if not skills:
            logger.info("没有启用的 Skill 需要注入")
            return result
        
        # 确保基础目录存在
        self._exec_in_container(container_id, ["mkdir", "-p", self.SKILL_DIR])
        
        for skill in skills:
            # 从本地存储读取 Skill 文件
            local_skill_dir = SKILL_STORAGE_DIR / skill.name
            if not local_skill_dir.exists():
                result["errors"].append(f"Skill '{skill.name}' 本地目录不存在")
                continue
            
            # 收集目录下所有文件
            files = {}
            for file_path in local_skill_dir.rglob("*"):
                if file_path.is_file():
                    rel_path = file_path.relative_to(local_skill_dir)
                    files[str(rel_path)] = file_path.read_bytes()
            
            if not files:
                result["errors"].append(f"Skill '{skill.name}' 目录为空")
                continue
            
            # 创建目标目录并上传
            skill_target_dir = f"{self.SKILL_DIR}/{skill.name}"
            self._exec_in_container(container_id, ["mkdir", "-p", skill_target_dir])
            
            if self._put_directory_to_container(container_id, skill_target_dir, files):
                result["injected"].append(skill.name)
            else:
                result["errors"].append(f"Skill '{skill.name}' 上传失败")
        
        if result["errors"]:
            result["success"] = False
        else:
            logger.info(f"成功注入 {len(skills)} 个 Skill: {result['injected']}")
        
        return result
    
    async def inject_mcps(self, container_id: str) -> dict:
        """
        注入 MCP 配置到容器的 kuncode.json
        
        Args:
            container_id: 容器 ID
        
        Returns:
            注入结果 {success: bool, injected: list, errors: list}
        """
        result = {"success": True, "injected": [], "errors": []}
        
        # 获取所有启用的 MCP
        mcps = await SandboxMcp.filter(enabled=True).all()
        
        # 读取现有的 kuncode.json
        exit_code, output = self._exec_in_container(
            container_id, 
            ["cat", self.KUNCODE_JSON_PATH]
        )
        
        if exit_code != 0:
            logger.warning(f"无法读取 kuncode.json: {output}，使用默认配置")
            kuncode_config = {"mcp": {}, "permission": {"*": "allow"}}
        else:
            kuncode_config = json.loads(output)

        self._ensure_mimo_provider(kuncode_config)
        
        # 更新 MCP 配置（仅合并，不覆盖其他字段）
        if "mcp" not in kuncode_config:
            kuncode_config["mcp"] = {}

        # 确保 permission 配置为 "*": "allow"（静默全允许）
        if kuncode_config.get("permission", {}).get("*") != "allow":
            kuncode_config["permission"] = {"*": "allow"}
            logger.info("已设置 permission.*=allow，静默全允许")
        
        for mcp in mcps:
            kuncode_config["mcp"][mcp.name] = mcp.to_config()
            result["injected"].append(mcp.name)
        
        # 写回 kuncode.json
        config_content = json.dumps(kuncode_config, indent=2, ensure_ascii=False).encode("utf-8")
        if self._put_file_to_container(
            container_id, 
            self.KUNCODE_CONFIG_DIR, 
            "kuncode.json", 
            config_content
        ):
            logger.info(f"成功注入 {len(mcps)} 个 MCP: {result['injected']}")
            logger.info(
                "已写入默认 permission=allow (edit/bash/webfetch/external_directory) 到 kuncode.json，用于禁用交互式授权提示"
            )
        else:
            result["success"] = False
            result["errors"].append("kuncode.json 更新失败")
        
        return result
    
    async def inject_skill_permissions(self, container_id: str) -> dict:
        """
        注入 Skill 权限配置到各 Agent
        
        Skill 权限通过 Agent 的 permission.skill 字段配置
        
        Args:
            container_id: 容器 ID
        
        Returns:
            注入结果
        """
        result = {"success": True, "updated_agents": [], "errors": []}
        
        # 获取所有有权限配置的 Agent
        agents = await SandboxAgent.filter(enabled=True).all()
        
        for agent in agents:
            # 获取该 Agent 的所有 Skill 权限配置
            perms = await SandboxSkillPermission.filter(agent=agent).prefetch_related("skill")
            
            if not perms:
                continue
            
            # 构建 skill 权限字典
            skill_perms = {}
            for perm in perms:
                if perm.skill.enabled:
                    skill_perms[perm.skill.name] = perm.permission
            
            if not skill_perms:
                continue
            
            # 更新 Agent 的 permission.skill
            if "skill" not in agent.permission:
                agent.permission["skill"] = {}
            agent.permission["skill"].update(skill_perms)
            
            # 重新生成并上传 Agent 文件
            filename = f"{agent.name}.md"
            content = agent.to_markdown().encode("utf-8")
            if self._put_file_to_container(container_id, self.AGENT_DIR, filename, content):
                result["updated_agents"].append(agent.name)
            else:
                result["errors"].append(f"Agent '{agent.name}' 权限更新失败")
        
        if result["errors"]:
            result["success"] = False
        
        return result
    
    async def inject_all(self, container_id: str) -> dict:
        """
        注入所有配置到容器
        
        Args:
            container_id: 容器 ID
        
        Returns:
            完整注入结果
        """
        result = {
            "success": True,
            "agents": None,
            "skills": None,
            "mcps": None,
            "skill_permissions": None,
        }
        
        try:
            # 1. 注入 Agent
            result["agents"] = await self.inject_agents(container_id)
            if not result["agents"]["success"]:
                result["success"] = False
            
            # 2. 注入 Skill
            result["skills"] = await self.inject_skills(container_id)
            if not result["skills"]["success"]:
                result["success"] = False
            
            # 3. 注入 MCP
            result["mcps"] = await self.inject_mcps(container_id)
            if not result["mcps"]["success"]:
                result["success"] = False
            
            # 4. 注入 Skill 权限（更新 Agent 文件）
            result["skill_permissions"] = await self.inject_skill_permissions(container_id)
            if not result["skill_permissions"]["success"]:
                result["success"] = False
            
            logger.info(f"沙箱配置注入完成: {result}")
            
        except Exception as e:
            logger.error(f"沙箱配置注入异常: {e}")
            result["success"] = False
            result["error"] = str(e)
        
        return result


# 单例实例
_injection_service: Optional[SandboxInjectionService] = None


def get_injection_service() -> SandboxInjectionService:
    """获取注入服务单例"""
    global _injection_service
    if _injection_service is None:
        _injection_service = SandboxInjectionService()
    return _injection_service
