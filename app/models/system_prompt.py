# -*- coding: utf-8 -*-
"""
系统提示词模型
"""

from tortoise import fields
from tortoise.models import Model


class SystemPrompt(Model):
    """系统提示词表 产品经理 - 存储可动态修改的提示词"""
    
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=64, unique=True, index=True)  # 提示词名称标识
    title = fields.CharField(max_length=128)  # 显示标题
    content = fields.TextField()  # Markdown 内容
    updated_by = fields.ForeignKeyField("models.User", null=True, on_delete=fields.SET_NULL)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    
    class Meta:
        table = "system_prompts"
