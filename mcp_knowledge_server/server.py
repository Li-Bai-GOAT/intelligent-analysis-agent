"""
数据分析知识库 MCP Server

使用 FastMCP 提供 HTTP 接口，供沙箱内的 KunCode 智能体远程调用。

启动方式:
    uv run python mcp_knowledge_server/server.py

默认端口: 8765
访问地址: http://localhost:8765/mcp
"""

import sys
from pathlib import Path
from typing import Optional

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from fastmcp import FastMCP

from app.config import settings
from app.utils.milvus_client import milvus_client

# 服务配置
MCP_HOST = "0.0.0.0"
MCP_PORT = 8765

# 知识库类别
CATEGORIES = ["计算公式", "概念定义", "分析方法", "分析流程"]

# 创建 FastMCP Server
mcp = FastMCP(
    name="data-knowledge",
    instructions="数据分析知识库服务，提供业务概念、计算公式、分析方法、报告模板的检索"
)


@mcp.tool()
def search_knowledge(query: str, category: Optional[str] = None, top_k: int = 3) -> str:
    """检索数据分析知识库。
    
    Args:
        query: 查询问题，如"考核利润怎么计算"、"连环替代法"、"诊断流程"
        category: 可选类别筛选，支持：计算公式、概念定义、分析方法、分析流程
        top_k: 返回结果数量，默认3
    
    Returns:
        检索到的知识内容
    
    示例：
        search_knowledge("考核利润", category="计算公式")
        search_knowledge("连环替代法", category="分析方法")
        search_knowledge("诊断步骤", category="分析流程")
    """
    # 验证类别
    cat = None
    if category:
        if category in CATEGORIES:
            cat = category
        else:
            return f"无效类别 '{category}'，支持的类别：{', '.join(CATEGORIES)}"
    
    results = milvus_client.search(
        collection_name=settings.MILVUS_COLLECTION,
        query=query,
        top_k=top_k,
        category=cat,
    )
    
    if not results:
        hint = f"（类别: {category}）" if category else ""
        return f"未找到与 '{query}' 相关的知识{hint}。请尝试其他关键词或不指定类别。"
    
    # 格式化输出
    output_parts = []
    if category:
        output_parts.append(f"## 【{category}】{query} 相关知识\n")
    else:
        output_parts.append(f"## {query} 相关知识\n")
    
    for i, item in enumerate(results, 1):
        output_parts.append(f"### {i}. {item['title']} [{item['category']}]")
        output_parts.append(f"{item['content']}\n")
    
    return "\n".join(output_parts)


if __name__ == "__main__":
    print("🚀 启动 RCA Knowledge MCP Server")
    print(f"   地址: http://{MCP_HOST}:{MCP_PORT}/mcp")
    print(f"   类别: {', '.join(CATEGORIES)}")
    mcp.run(transport="http", host=MCP_HOST, port=MCP_PORT)
