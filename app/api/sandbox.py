# -*- coding: utf-8 -*-
"""
沙箱配置管理 API：Agent、Skill、MCP 的增删改查
"""

import io
import re
import zipfile
import shutil
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_admin_user
from app.models import User, SandboxAgent, SandboxSkill, SandboxMcp
from app.services.sandbox_injection import get_injection_service

# Skill 存储目录
SKILL_STORAGE_DIR = Path("sandbox_skills")


router = APIRouter(prefix="/sandbox", tags=["sandbox"])


# ==================== Schemas ====================

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., min_length=1, max_length=1024)
    mode: str = Field(default="all", pattern="^(primary|subagent|all)$")
    tools: dict = Field(default_factory=dict)
    permission: dict = Field(default_factory=dict)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_steps: Optional[int] = Field(default=None, ge=1)
    hidden: bool = False
    content: str = ""
    enabled: bool = True


class AgentUpdate(BaseModel):
    description: Optional[str] = Field(default=None, max_length=1024)
    mode: Optional[str] = Field(default=None, pattern="^(primary|subagent|all)$")
    tools: Optional[dict] = None
    permission: Optional[dict] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_steps: Optional[int] = Field(default=None, ge=1)
    hidden: Optional[bool] = None
    content: Optional[str] = None
    enabled: Optional[bool] = None


class AgentResponse(BaseModel):
    id: int
    name: str
    description: str
    mode: str
    tools: dict
    permission: dict
    temperature: Optional[float]
    max_steps: Optional[int]
    hidden: bool
    content: str
    enabled: bool
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class SkillResponse(BaseModel):
    id: int
    name: str
    description: str
    metadata: dict
    enabled: bool
    created_at: str
    updated_at: str


def parse_skill_md(content: str) -> dict:
    """解析 SKILL.md 的 YAML frontmatter"""
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not match:
        raise ValueError("SKILL.md 缺少 YAML frontmatter")
    
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        raise ValueError(f"YAML 解析错误: {e}")
    
    if not frontmatter.get("name"):
        raise ValueError("SKILL.md 缺少 name 字段")
    if not frontmatter.get("description"):
        raise ValueError("SKILL.md 缺少 description 字段")
    
    return frontmatter


class McpCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    mcp_type: str = Field(..., pattern="^(local|remote)$")
    url: Optional[str] = None
    command: list = Field(default_factory=list)
    headers: dict = Field(default_factory=dict)
    environment: dict = Field(default_factory=dict)
    enabled: bool = True


class McpUpdate(BaseModel):
    mcp_type: Optional[str] = Field(default=None, pattern="^(local|remote)$")
    url: Optional[str] = None
    command: Optional[list] = None
    headers: Optional[dict] = None
    environment: Optional[dict] = None
    enabled: Optional[bool] = None


class McpResponse(BaseModel):
    id: int
    name: str
    mcp_type: str
    url: Optional[str]
    command: list
    headers: dict
    environment: dict
    enabled: bool
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


# ==================== Agent APIs ====================

@router.get("/agents", response_model=list[AgentResponse], summary="获取Agent列表")
async def list_agents(admin: User = Depends(get_admin_user)):
    """获取所有 Agent 列表"""
    agents = await SandboxAgent.all().order_by("-updated_at")
    return [
        AgentResponse(
            id=a.id,
            name=a.name,
            description=a.description,
            mode=a.mode,
            tools=a.tools,
            permission=a.permission,
            temperature=a.temperature,
            max_steps=a.max_steps,
            hidden=a.hidden,
            content=a.content,
            enabled=a.enabled,
            created_at=a.created_at.isoformat(),
            updated_at=a.updated_at.isoformat(),
        )
        for a in agents
    ]


@router.get("/agents/names", summary="获取可用Agent名称列表")
async def list_agent_names(mode: str = "primary"):
    """获取可用 Agent 名称列表（用于下拉选择）
    
    Args:
        mode: 筛选模式，primary=主Agent，subagent=子Agent，all=全部
    """
    if mode == "primary":
        # 主 Agent：mode 为 primary 或 all
        agents = await SandboxAgent.filter(enabled=True, hidden=False, mode__in=["primary", "all"]).order_by("name")
    elif mode == "subagent":
        # 子 Agent：mode 为 subagent 或 all
        agents = await SandboxAgent.filter(enabled=True, hidden=False, mode__in=["subagent", "all"]).order_by("name")
    else:
        agents = await SandboxAgent.filter(enabled=True, hidden=False).order_by("name")
    
    return [{"name": a.name, "description": a.description} for a in agents]


@router.post("/agents", response_model=AgentResponse, status_code=status.HTTP_201_CREATED, summary="创建Agent")
async def create_agent(data: AgentCreate, admin: User = Depends(get_admin_user)):
    """创建新 Agent"""
    existing = await SandboxAgent.filter(name=data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Agent '{data.name}' 已存在")
    
    agent = await SandboxAgent.create(**data.model_dump())
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        mode=agent.mode,
        tools=agent.tools,
        permission=agent.permission,
        temperature=agent.temperature,
        max_steps=agent.max_steps,
        hidden=agent.hidden,
        content=agent.content,
        enabled=agent.enabled,
        created_at=agent.created_at.isoformat(),
        updated_at=agent.updated_at.isoformat(),
    )


@router.get("/agents/{agent_id}", response_model=AgentResponse, summary="获取Agent详情")
async def get_agent(agent_id: int, admin: User = Depends(get_admin_user)):
    """获取单个 Agent 详情"""
    agent = await SandboxAgent.filter(id=agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        mode=agent.mode,
        tools=agent.tools,
        permission=agent.permission,
        temperature=agent.temperature,
        max_steps=agent.max_steps,
        hidden=agent.hidden,
        content=agent.content,
        enabled=agent.enabled,
        created_at=agent.created_at.isoformat(),
        updated_at=agent.updated_at.isoformat(),
    )


@router.put("/agents/{agent_id}", response_model=AgentResponse, summary="更新Agent")
async def update_agent(agent_id: int, data: AgentUpdate, admin: User = Depends(get_admin_user)):
    """更新 Agent"""
    agent = await SandboxAgent.filter(id=agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(agent, key, value)
    await agent.save()
    
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        mode=agent.mode,
        tools=agent.tools,
        permission=agent.permission,
        temperature=agent.temperature,
        max_steps=agent.max_steps,
        hidden=agent.hidden,
        content=agent.content,
        enabled=agent.enabled,
        created_at=agent.created_at.isoformat(),
        updated_at=agent.updated_at.isoformat(),
    )


@router.delete("/agents/{agent_id}", summary="删除Agent")
async def delete_agent(agent_id: int, admin: User = Depends(get_admin_user)):
    """删除 Agent"""
    agent = await SandboxAgent.filter(id=agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    
    await agent.delete()
    return {"success": True, "message": f"Agent '{agent.name}' 已删除"}


# ==================== Skill APIs ====================

async def _skill_to_response(skill: SandboxSkill) -> SkillResponse:
    """将 Skill 模型转换为响应对象"""
    return SkillResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        metadata=skill.metadata,
        enabled=skill.enabled,
        created_at=skill.created_at.isoformat(),
        updated_at=skill.updated_at.isoformat(),
    )


@router.get("/skills", response_model=list[SkillResponse], summary="获取Skill列表")
async def list_skills(admin: User = Depends(get_admin_user)):
    """获取所有 Skill 列表"""
    skills = await SandboxSkill.all().order_by("-updated_at")
    return [await _skill_to_response(s) for s in skills]


@router.post("/skills/upload", response_model=SkillResponse, status_code=status.HTTP_201_CREATED, summary="上传Skill压缩包")
async def upload_skill(
    file: UploadFile = File(..., description="Skill 压缩包 (.zip)"),
    admin: User = Depends(get_admin_user)
):
    """
    上传 Skill 压缩包
    
    压缩包结构要求:
    - 必须包含 SKILL.md 文件
    - SKILL.md 必须有 YAML frontmatter，包含 name 和 description
    """
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 .zip 格式")
    
    # 读取压缩包
    content = await file.read()
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            # 查找 SKILL.md
            skill_md_path = None
            for name in zf.namelist():
                if name.endswith("SKILL.md"):
                    skill_md_path = name
                    break
            
            if not skill_md_path:
                raise HTTPException(status_code=400, detail="压缩包中未找到 SKILL.md")
            
            # 解析 SKILL.md
            skill_md_content = zf.read(skill_md_path).decode("utf-8")
            try:
                frontmatter = parse_skill_md(skill_md_content)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            
            skill_name = frontmatter["name"]
            
            # 检查是否已存在
            existing = await SandboxSkill.filter(name=skill_name).first()
            if existing:
                raise HTTPException(status_code=400, detail=f"Skill '{skill_name}' 已存在，如需更新请先删除")
            
            # 保存压缩包到本地
            SKILL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            skill_dir = SKILL_STORAGE_DIR / skill_name
            if skill_dir.exists():
                shutil.rmtree(skill_dir)
            skill_dir.mkdir(parents=True, exist_ok=True)
            
            # 解压时去除顶层目录（如果 zip 内有单个根目录）
            # 检测是否所有文件都在同一个顶层目录下
            all_names = zf.namelist()
            top_dirs = set()
            for name in all_names:
                parts = name.split("/")
                if len(parts) > 1 and parts[0]:
                    top_dirs.add(parts[0])
            
            # 如果只有一个顶层目录，去除它
            strip_prefix = ""
            if len(top_dirs) == 1:
                strip_prefix = list(top_dirs)[0] + "/"
            
            for member in zf.namelist():
                # 跳过目录条目
                if member.endswith("/"):
                    continue
                
                # 去除顶层目录前缀
                if strip_prefix and member.startswith(strip_prefix):
                    target_path = member[len(strip_prefix):]
                else:
                    target_path = member
                
                if not target_path:
                    continue
                
                # 创建目标路径
                target_file = skill_dir / target_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                
                # 写入文件
                with zf.open(member) as src, open(target_file, "wb") as dst:
                    dst.write(src.read())
            
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="无效的压缩包")
    
    # 创建数据库记录
    skill = await SandboxSkill.create(
        name=skill_name,
        description=frontmatter.get("description", ""),
        metadata=frontmatter,
    )
    
    return await _skill_to_response(skill)


@router.get("/skills/{skill_id}", response_model=SkillResponse, summary="获取Skill详情")
async def get_skill(skill_id: int, admin: User = Depends(get_admin_user)):
    """获取单个 Skill 详情"""
    skill = await SandboxSkill.filter(id=skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return await _skill_to_response(skill)


@router.patch("/skills/{skill_id}/toggle", summary="启用/禁用Skill")
async def toggle_skill(skill_id: int, admin: User = Depends(get_admin_user)):
    """启用/禁用 Skill"""
    skill = await SandboxSkill.filter(id=skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    
    skill.enabled = not skill.enabled
    await skill.save()
    return {"success": True, "enabled": skill.enabled}


@router.delete("/skills/{skill_id}", summary="删除Skill")
async def delete_skill(skill_id: int, admin: User = Depends(get_admin_user)):
    """删除 Skill（同时删除本地文件）"""
    skill = await SandboxSkill.filter(id=skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    
    # 删除本地文件
    skill_dir = SKILL_STORAGE_DIR / skill.name
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    
    await skill.delete()
    return {"success": True, "message": f"Skill '{skill.name}' 已删除"}


@router.get("/skills/{skill_id}/files", summary="获取Skill文件树")
async def get_skill_files(skill_id: int, admin: User = Depends(get_admin_user)):
    """获取 Skill 文件树"""
    skill = await SandboxSkill.filter(id=skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    
    skill_dir = SKILL_STORAGE_DIR / skill.name
    if not skill_dir.exists():
        raise HTTPException(status_code=404, detail="Skill 目录不存在")
    
    def build_tree(path: Path, base: Path) -> list:
        items = []
        for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
            rel_path = str(item.relative_to(base))
            node = {
                "name": item.name,
                "path": rel_path,
                "type": "directory" if item.is_dir() else "file",
            }
            if item.is_dir():
                node["children"] = build_tree(item, base)
            else:
                node["size"] = item.stat().st_size
            items.append(node)
        return items
    
    return {"name": skill.name, "children": build_tree(skill_dir, skill_dir)}


@router.get("/skills/{skill_id}/files/{file_path:path}", summary="获取Skill文件内容")
async def get_skill_file_content(
    skill_id: int, 
    file_path: str, 
    admin: User = Depends(get_admin_user)
):
    """获取 Skill 文件内容"""
    skill = await SandboxSkill.filter(id=skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    
    skill_dir = SKILL_STORAGE_DIR / skill.name
    target_file = skill_dir / file_path
    
    # 安全检查：确保路径在 skill 目录内
    try:
        target_file.resolve().relative_to(skill_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="非法路径")
    
    if not target_file.exists() or not target_file.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    # 判断文件类型
    suffix = target_file.suffix.lower()
    text_extensions = {'.md', '.txt', '.py', '.js', '.ts', '.json', '.yaml', '.yml', 
                       '.html', '.css', '.sh', '.bash', '.xml', '.toml', '.ini', '.cfg',
                       '.sql', '.r', '.go', '.java', '.c', '.cpp', '.h', '.hpp', '.rs'}
    
    if suffix in text_extensions or target_file.stat().st_size < 100000:
        try:
            content = target_file.read_text(encoding='utf-8')
            return {"path": file_path, "content": content, "type": "text"}
        except UnicodeDecodeError:
            pass
    
    return {"path": file_path, "content": None, "type": "binary", "size": target_file.stat().st_size}


# ==================== MCP APIs ====================

@router.get("/mcps", response_model=list[McpResponse], summary="获取MCP列表")
async def list_mcps(admin: User = Depends(get_admin_user)):
    """获取所有 MCP 列表"""
    mcps = await SandboxMcp.all().order_by("-updated_at")
    return [
        McpResponse(
            id=m.id,
            name=m.name,
            mcp_type=m.mcp_type,
            url=m.url,
            command=m.command,
            headers=m.headers,
            environment=m.environment,
            enabled=m.enabled,
            created_at=m.created_at.isoformat(),
            updated_at=m.updated_at.isoformat(),
        )
        for m in mcps
    ]


@router.post("/mcps", response_model=McpResponse, status_code=status.HTTP_201_CREATED, summary="创建MCP")
async def create_mcp(data: McpCreate, admin: User = Depends(get_admin_user)):
    """创建新 MCP"""
    existing = await SandboxMcp.filter(name=data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"MCP '{data.name}' 已存在")
    
    mcp = await SandboxMcp.create(**data.model_dump())
    return McpResponse(
        id=mcp.id,
        name=mcp.name,
        mcp_type=mcp.mcp_type,
        url=mcp.url,
        command=mcp.command,
        headers=mcp.headers,
        environment=mcp.environment,
        enabled=mcp.enabled,
        created_at=mcp.created_at.isoformat(),
        updated_at=mcp.updated_at.isoformat(),
    )


@router.get("/mcps/{mcp_id}", response_model=McpResponse, summary="获取MCP详情")
async def get_mcp(mcp_id: int, admin: User = Depends(get_admin_user)):
    """获取单个 MCP 详情"""
    mcp = await SandboxMcp.filter(id=mcp_id).first()
    if not mcp:
        raise HTTPException(status_code=404, detail="MCP 不存在")
    
    return McpResponse(
        id=mcp.id,
        name=mcp.name,
        mcp_type=mcp.mcp_type,
        url=mcp.url,
        command=mcp.command,
        headers=mcp.headers,
        environment=mcp.environment,
        enabled=mcp.enabled,
        created_at=mcp.created_at.isoformat(),
        updated_at=mcp.updated_at.isoformat(),
    )


@router.put("/mcps/{mcp_id}", response_model=McpResponse, summary="更新MCP")
async def update_mcp(mcp_id: int, data: McpUpdate, admin: User = Depends(get_admin_user)):
    """更新 MCP"""
    mcp = await SandboxMcp.filter(id=mcp_id).first()
    if not mcp:
        raise HTTPException(status_code=404, detail="MCP 不存在")
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(mcp, key, value)
    await mcp.save()
    
    return McpResponse(
        id=mcp.id,
        name=mcp.name,
        mcp_type=mcp.mcp_type,
        url=mcp.url,
        command=mcp.command,
        headers=mcp.headers,
        environment=mcp.environment,
        enabled=mcp.enabled,
        created_at=mcp.created_at.isoformat(),
        updated_at=mcp.updated_at.isoformat(),
    )


@router.delete("/mcps/{mcp_id}", summary="删除MCP")
async def delete_mcp(mcp_id: int, admin: User = Depends(get_admin_user)):
    """删除 MCP"""
    mcp = await SandboxMcp.filter(id=mcp_id).first()
    if not mcp:
        raise HTTPException(status_code=404, detail="MCP 不存在")
    
    await mcp.delete()
    return {"success": True, "message": f"MCP '{mcp.name}' 已删除"}


# ==================== Injection API ====================

class InjectRequest(BaseModel):
    container_id: str = Field(..., description="容器 ID 或名称")


@router.post("/inject", summary="注入配置到沙箱")
async def inject_to_sandbox(data: InjectRequest, admin: User = Depends(get_admin_user)):
    """
    将所有启用的配置注入到指定沙箱容器
    
    注入内容包括：
    - Agent 配置（/root/.config/kuncode/agent/*.md）
    - Skill 配置（/root/.config/kuncode/skill/*/SKILL.md）
    - MCP 配置（更新 kuncode.json）
    """
    service = get_injection_service()
    result = await service.inject_all(data.container_id)
    
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result)
    
    return result


@router.post("/inject/agents", summary="注入Agent配置")
async def inject_agents_to_sandbox(data: InjectRequest, admin: User = Depends(get_admin_user)):
    """仅注入 Agent 配置"""
    service = get_injection_service()
    result = await service.inject_agents(data.container_id)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result)
    return result


@router.post("/inject/skills", summary="注入Skill配置")
async def inject_skills_to_sandbox(data: InjectRequest, admin: User = Depends(get_admin_user)):
    """仅注入 Skill 配置"""
    service = get_injection_service()
    result = await service.inject_skills(data.container_id)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result)
    return result


@router.post("/inject/mcps", summary="注入MCP配置")
async def inject_mcps_to_sandbox(data: InjectRequest, admin: User = Depends(get_admin_user)):
    """仅注入 MCP 配置"""
    service = get_injection_service()
    result = await service.inject_mcps(data.container_id)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result)
    return result
