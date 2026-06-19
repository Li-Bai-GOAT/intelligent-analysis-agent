# -*- coding: utf-8 -*-
"""
会话模型
"""

from tortoise import fields
from tortoise.models import Model


class Session(Model):
    """会话表"""
    
    id = fields.UUIDField(pk=True)
    session_id = fields.CharField(max_length=128, index=True)
    user_id = fields.CharField(max_length=128, index=True)
    name = fields.CharField(max_length=200, null=True)  # 会话名称，默认用第一条消息
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    
    messages: fields.ReverseRelation["SessionMessage"]
    
    class Meta:
        table = "sessions"
        unique_together = (("user_id", "session_id"),)
    
    def __str__(self):
        return f"{self.user_id}:{self.session_id}"


class SessionMessage(Model):
    """会话消息表"""
    
    id = fields.IntField(pk=True)
    session = fields.ForeignKeyField(
        "models.Session", related_name="messages", on_delete=fields.CASCADE
    )
    message = fields.JSONField()
    created_at = fields.DatetimeField(auto_now_add=True)
    
    class Meta:
        table = "session_messages"
        ordering = ["created_at"]
