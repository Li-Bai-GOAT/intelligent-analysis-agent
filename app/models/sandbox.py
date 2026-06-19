# -*- coding: utf-8 -*-
"""
沙箱配置模型：Agent、Skill、MCP
"""

from tortoise import fields
from tortoise.models import Model


class SandboxAgent(Model):
    """沙箱 Agent 配置"""
    
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=64, unique=True, description="Agent 名称（文件名，不含 .md）")
    description = fields.CharField(max_length=1024, description="Agent 描述")
    mode = fields.CharField(max_length=20, default="all", description="模式: primary/subagent/all")
    tools = fields.JSONField(default=dict, description="工具配置 {tool_name: true/false}")
    permission = fields.JSONField(default=dict, description="权限配置 {action: allow/ask/deny}")
    temperature = fields.FloatField(null=True, description="温度参数 0.0-1.0")
    max_steps = fields.IntField(null=True, description="最大迭代步数")
    hidden = fields.BooleanField(default=False, description="是否隐藏（仅 subagent）")
    content = fields.TextField(default="", description="Agent 正文内容（Markdown）")
    enabled = fields.BooleanField(default=True, description="是否启用")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "sandbox_agents"

    def to_markdown(self) -> str:
        """生成完整的 Agent Markdown 文件内容"""
        frontmatter_lines = ["---"]
        frontmatter_lines.append(f"description: {self.description}")
        
        if self.mode and self.mode != "all":
            frontmatter_lines.append(f"mode: {self.mode}")
        
        if self.tools:
            frontmatter_lines.append("tools:")
            for tool, enabled in self.tools.items():
                frontmatter_lines.append(f"  {tool}: {str(enabled).lower()}")
        
        if self.permission:
            frontmatter_lines.append("permission:")
            for action, value in self.permission.items():
                if isinstance(value, dict):
                    frontmatter_lines.append(f"  {action}:")
                    for k, v in value.items():
                        frontmatter_lines.append(f"    \"{k}\": {v}")
                else:
                    frontmatter_lines.append(f"  {action}: {value}")
        
        if self.temperature is not None:
            frontmatter_lines.append(f"temperature: {self.temperature}")
        
        if self.max_steps is not None:
            frontmatter_lines.append(f"maxSteps: {self.max_steps}")
        
        if self.hidden:
            frontmatter_lines.append("hidden: true")
        
        frontmatter_lines.append("---")
        frontmatter_lines.append("")
        frontmatter_lines.append(self.content)
        
        return "\n".join(frontmatter_lines)


class SandboxSkill(Model):
    """沙箱 Skill 配置（通过压缩包上传）"""
    
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=64, unique=True, description="Skill 名称（目录名）")
    description = fields.CharField(max_length=1024, description="Skill 描述")
    metadata = fields.JSONField(default=dict, description="SKILL.md 的 YAML frontmatter")
    enabled = fields.BooleanField(default=True, description="是否启用")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "sandbox_skills"


class SandboxSkillPermission(Model):
    """Skill 对 Agent 的权限配置"""
    
    id = fields.IntField(pk=True)
    skill = fields.ForeignKeyField("models.SandboxSkill", related_name="permissions", on_delete=fields.CASCADE)
    agent = fields.ForeignKeyField("models.SandboxAgent", related_name="skill_permissions", on_delete=fields.CASCADE)
    permission = fields.CharField(max_length=10, default="allow", description="权限: allow/deny/ask")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "sandbox_skill_permissions"
        unique_together = (("skill", "agent"),)


class SandboxMcp(Model):
    """沙箱 MCP 配置"""
    
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=64, unique=True, description="MCP 名称")
    mcp_type = fields.CharField(max_length=20, description="类型: local/remote")
    url = fields.CharField(max_length=500, null=True, description="远程 URL（remote 类型）")
    command = fields.JSONField(default=list, description="本地命令（local 类型）")
    headers = fields.JSONField(default=dict, description="请求头")
    environment = fields.JSONField(default=dict, description="环境变量")
    enabled = fields.BooleanField(default=True, description="是否启用")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "sandbox_mcps"

    def to_config(self) -> dict:
        """生成 MCP 配置字典"""
        config = {
            "type": self.mcp_type,
            "enabled": self.enabled,
        }
        
        if self.mcp_type == "remote" and self.url:
            config["url"] = self.url
        elif self.mcp_type == "local" and self.command:
            config["command"] = self.command
        
        if self.headers:
            config["headers"] = self.headers
        
        if self.environment:
            config["environment"] = self.environment
        
        return config
