#!/bin/bash
# =============================================================================
# 启动数据分析沙箱服务器
# 参考: https://runtime.agentscope.io/v1.0.4/zh/sandbox/advanced.html
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "启动数据分析沙箱服务器"
echo "=========================================="
echo "配置文件: sandbox.env"
echo "扩展模块: data_analysis_sandbox.py"
echo "=========================================="

# 使用自定义配置文件启动沙箱服务器
# --config: 指定配置文件路径
# --extension: 加载自定义沙箱扩展
runtime-sandbox-server \
    --config "$SCRIPT_DIR/sandbox.env" \
    --extension "$SCRIPT_DIR/data_analysis_sandbox.py" \
    --extension "$SCRIPT_DIR/sandbox_proxy_extension.py"
