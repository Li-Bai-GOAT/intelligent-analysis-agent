# -*- coding: utf-8 -*-
"""
智能体状态模型
"""

from tortoise import fields
from tortoise.models import Model


class AgentState(Model):
    """智能体状态表"""
    
    id = fields.IntField(pk=True)
    user_id = fields.CharField(max_length=128, index=True)
    session_id = fields.CharField(max_length=128, default="default", index=True)
    round_id = fields.IntField()
    state = fields.JSONField()
    created_at = fields.DatetimeField(auto_now_add=True)
    
    class Meta:
        table = "agent_states"
        unique_together = (("user_id", "session_id", "round_id"),)
        ordering = ["-round_id"]
