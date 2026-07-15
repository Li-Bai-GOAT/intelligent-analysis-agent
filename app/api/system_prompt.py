# -*- coding: utf-8 -*-
"""
系统提示词管理 API
"""

from pathlib import Path
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_admin_user
from app.models import User, SystemPrompt


router = APIRouter(prefix="/system-prompt", tags=["system-prompt"])


class PromptResponse(BaseModel):
    name: str
    title: str
    content: str
    updated_at: str | None = None


class PromptUpdateRequest(BaseModel):
    content: str


def _repair_mojibake(value: str) -> str:
    """Repair legacy UTF-8 text decoded as Latin-1 one or two times."""
    repaired = value
    for _ in range(2):
        try:
            candidate = repaired.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if candidate == repaired:
            break
        repaired = candidate
    return repaired


# 默认提示词文件路径
DEFAULT_PROMPT_FILE = Path(__file__).parent.parent.parent / "system_prompt.md"
PROMPT_NAME = "product_manager"
PROMPT_TITLE = "产品经理提示词"


async def _get_default_prompt() -> str:
    """从文件加载默认提示词"""
    if DEFAULT_PROMPT_FILE.exists():
        return DEFAULT_PROMPT_FILE.read_text(encoding="utf-8").strip()
    return ""


async def _ensure_prompt_exists() -> SystemPrompt:
    """确保数据库中存在提示词记录，不存在则从文件初始化"""
    prompt = await SystemPrompt.filter(name=PROMPT_NAME).first()
    if not prompt:
        default_content = await _get_default_prompt()
        prompt = await SystemPrompt.create(
            name=PROMPT_NAME,
            title=PROMPT_TITLE,
            content=default_content
        )
    else:
        repaired_title = _repair_mojibake(prompt.title)
        repaired_content = _repair_mojibake(prompt.content)
        if repaired_title != prompt.title or repaired_content != prompt.content:
            prompt.title = repaired_title
            prompt.content = repaired_content
            await prompt.save()
    return prompt


@router.get("", response_model=PromptResponse, summary="获取系统提示词")
async def get_system_prompt(admin: User = Depends(get_admin_user)):
    """获取系统提示词（仅管理员可查看）"""
    prompt = await _ensure_prompt_exists()
    return PromptResponse(
        name=prompt.name,
        title=prompt.title,
        content=prompt.content,
        updated_at=prompt.updated_at.isoformat() if prompt.updated_at else None
    )


@router.put("", summary="更新系统提示词")
async def update_system_prompt(
    request: PromptUpdateRequest,
    admin: User = Depends(get_admin_user)
):
    """更新系统提示词（仅管理员）"""
    prompt = await _ensure_prompt_exists()
    prompt.content = request.content
    prompt.updated_by = admin
    await prompt.save()
    
    return {
        "success": True,
        "message": "提示词已更新",
        "updated_at": prompt.updated_at.isoformat()
    }


async def get_active_system_prompt() -> str:
    """供 AgentService 调用：获取当前生效的系统提示词"""
    prompt = await SystemPrompt.filter(name=PROMPT_NAME).first()
    if prompt and prompt.content:
        return _repair_mojibake(prompt.content)
    # 回退到文件
    return await _get_default_prompt()
