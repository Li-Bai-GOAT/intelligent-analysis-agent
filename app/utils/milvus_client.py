# -*- coding: utf-8 -*-
"""
Milvus 向量数据库客户端

提供统一的 Milvus 连接和操作接口
"""

import logging
from typing import List, Optional, Dict, Any

import httpx
from pymilvus import connections, Collection, utility, db

from app.config import settings

logger = logging.getLogger(__name__)


class MilvusClient:
    """Milvus 客户端单例"""
    
    _instance = None
    _connected = False
    _collections: Dict[str, Collection] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def connect(self) -> bool:
        """连接 Milvus"""
        if self._connected:
            return True
        
        try:
            uri = settings.MILVUS_URI.replace("http://", "").replace("https://", "")
            host, port = uri.split(":") if ":" in uri else (uri, "19530")
            user, password = settings.MILVUS_TOKEN.split(":", 1) if ":" in settings.MILVUS_TOKEN else ("root", "Milvus")
            
            if not connections.has_connection("default"):
                connections.connect(alias="default", host=host, port=port, user=user, password=password)
            
            if settings.MILVUS_DATABASE:
                db.using_database(settings.MILVUS_DATABASE)
            
            self._connected = True
            logger.info(f"[Milvus] 已连接: {host}:{port}/{settings.MILVUS_DATABASE}")
            return True
        except Exception as e:
            logger.error(f"[Milvus] 连接失败: {e}")
            return False
    
    def get_collection(self, name: str) -> Optional[Collection]:
        """获取集合（带缓存）"""
        if name in self._collections:
            return self._collections[name]
        
        if not self.connect():
            return None
        
        try:
            if not utility.has_collection(name):
                logger.warning(f"[Milvus] 集合 {name} 不存在")
                return None
            
            collection = Collection(name)
            collection.load()
            self._collections[name] = collection
            return collection
        except Exception as e:
            logger.error(f"[Milvus] 获取集合失败: {e}")
            return None
    
    @staticmethod
    def get_embedding(text: str) -> Optional[List[float]]:
        """获取文本向量"""
        try:
            response = httpx.post(
                f"{settings.EMBEDDING_BASE_URL}/embeddings",
                headers={"Authorization": f"Bearer {settings.EMBEDDING_API_KEY}"},
                json={"model": settings.EMBEDDING_MODEL, "input": text, "dimensions": settings.MILVUS_DIM},
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()["data"][0]["embedding"]
        except Exception as e:
            logger.error(f"[Embedding] 获取向量失败: {e}")
            return None
    
    def insert(self, collection_name: str, data: Dict[str, Any]) -> bool:
        """插入数据"""
        collection = self.get_collection(collection_name)
        if not collection:
            return False
        
        try:
            collection.insert([[v] for v in data.values()])
            collection.flush()
            return True
        except Exception as e:
            logger.error(f"[Milvus] 插入失败: {e}")
            return False
    
    def delete(self, collection_name: str, expr: str) -> bool:
        """删除数据"""
        collection = self.get_collection(collection_name)
        if not collection:
            return False
        
        try:
            collection.delete(expr)
            return True
        except Exception as e:
            logger.error(f"[Milvus] 删除失败: {e}")
            return False
    
    def search(
        self, 
        collection_name: str, 
        query: str, 
        top_k: int = 5, 
        category: Optional[str] = None,
        output_fields: List[str] = None
    ) -> List[Dict[str, Any]]:
        """向量搜索"""
        collection = self.get_collection(collection_name)
        if not collection:
            return []
        
        embedding = self.get_embedding(query)
        if not embedding:
            return []
        
        try:
            search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}
            expr = f'category == "{category}"' if category else None
            
            results = collection.search(
                data=[embedding],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=expr,
                output_fields=output_fields or ["id", "title", "content", "category"],
            )
            
            items = []
            for hits in results:
                for hit in hits:
                    items.append({
                        "id": hit.entity.get("id"),
                        "title": hit.entity.get("title"),
                        "content": hit.entity.get("content"),
                        "category": hit.entity.get("category"),
                        "score": hit.distance,
                    })
            return items
        except Exception as e:
            logger.error(f"[Milvus] 搜索失败: {e}")
            return []


# 全局实例
milvus_client = MilvusClient()
