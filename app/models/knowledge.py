# -*- coding: utf-8 -*-
"""
知识库模型
"""

from tortoise import fields
from tortoise.models import Model


class KnowledgeItem(Model):
    """知识库条目表"""
    
    id = fields.UUIDField(pk=True)
    title = fields.CharField(max_length=256, index=True)
    content = fields.TextField()
    category = fields.CharField(max_length=64, index=True)
    metadata = fields.JSONField(null=True)
    milvus_id = fields.CharField(max_length=128, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    
    class Meta:
        table = "knowledge_items"
