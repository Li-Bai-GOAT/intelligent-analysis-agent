#!/bin/bash
# -*- coding: utf-8 -*-
# 数据分析智能体 - 统一启动脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# 日志目录
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

# PID 文件目录
PID_DIR="$PROJECT_DIR/.pids"
mkdir -p "$PID_DIR"

# 跨平台 venv 路径检测
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    VENV_PYTHON="$PROJECT_DIR/.venv/Scripts/python"
    VENV_CELERY="$PROJECT_DIR/.venv/Scripts/celery"
else
    VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
    VENV_CELERY="$PROJECT_DIR/.venv/bin/celery"
fi

print_header() {
    echo -e "${BLUE}============================================================${NC}"
    echo -e "${BLUE}  数据分析智能体 - 服务管理${NC}"
    echo -e "${BLUE}============================================================${NC}"
}

print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# 检查外部依赖
check_port() {
    # 跨平台端口检测：优先用 nc，fallback 到 bash /dev/tcp
    local host=$1 port=$2
    if command -v nc &>/dev/null; then
        nc -z "$host" "$port" 2>/dev/null
    elif command -v powershell &>/dev/null; then
        powershell -NoProfile -Command "exit !(Test-NetConnection -ComputerName $host -Port $port -WarningAction SilentlyContinue).TcpTestSucceeded" 2>/dev/null
    else
        (echo > /dev/tcp/"$host"/"$port") 2>/dev/null
    fi
}

check_dependencies() {
    echo -e "\n${BLUE}检查外部依赖...${NC}"

    # PostgreSQL
    if check_port localhost 5488; then
        print_status "PostgreSQL (localhost:5488) - 可用"
    else
        print_error "PostgreSQL (localhost:5488) - 不可用"
        return 1
    fi

    # Redis
    if check_port localhost 6380; then
        print_status "Redis (localhost:6380) - 可用"
    else
        print_error "Redis (localhost:6380) - 不可用"
        return 1
    fi

    # Milvus
    if check_port localhost 19530; then
        print_status "Milvus (localhost:19530) - 可用"
    else
        print_warning "Milvus (localhost:19530) - 不可用（知识库功能受限）"
    fi

    # Sandbox Server
    if check_port localhost 10001; then
        print_status "Sandbox Server (localhost:10001) - 可用"
    else
        print_error "Sandbox Server (localhost:10001) - 不可用"
        return 1
    fi

    return 0
}

# 启动 MCP Server
start_mcp_server() {
    echo -e "\n${BLUE}启动知识库 MCP Server...${NC}"
    
    if [ -f "$PID_DIR/mcp.pid" ] && kill -0 $(cat "$PID_DIR/mcp.pid") 2>/dev/null; then
        print_warning "MCP Server 已在运行 (PID: $(cat $PID_DIR/mcp.pid))"
        return 0
    fi
    
    nohup "$VENV_PYTHON" "$PROJECT_DIR/mcp_knowledge_server/server.py" \
        > "$LOG_DIR/mcp_server.log" 2>&1 &
    echo $! > "$PID_DIR/mcp.pid"
    
    sleep 2
    if kill -0 $(cat "$PID_DIR/mcp.pid") 2>/dev/null; then
        print_status "MCP Server 已启动 (PID: $(cat $PID_DIR/mcp.pid), 端口: 8765)"
    else
        print_error "MCP Server 启动失败，查看日志: $LOG_DIR/mcp_server.log"
        return 1
    fi
}

# 启动主服务
start_main_server() {
    echo -e "\n${BLUE}启动主 API 服务...${NC}"
    
    if [ -f "$PID_DIR/main.pid" ] && kill -0 $(cat "$PID_DIR/main.pid") 2>/dev/null; then
        print_warning "主服务已在运行 (PID: $(cat $PID_DIR/main.pid))"
        return 0
    fi
    
    nohup "$VENV_PYTHON" -m app.main \
        > "$LOG_DIR/main_server.log" 2>&1 &
    echo $! > "$PID_DIR/main.pid"
    
    sleep 3
    if kill -0 $(cat "$PID_DIR/main.pid") 2>/dev/null; then
        print_status "主服务已启动 (PID: $(cat $PID_DIR/main.pid), 端口: 8090)"
    else
        print_error "主服务启动失败，查看日志: $LOG_DIR/main_server.log"
        return 1
    fi
}

# 启动 Celery Worker
start_celery_worker() {
    echo -e "\n${BLUE}启动 Celery Worker...${NC}"
    
    if [ -f "$PID_DIR/celery.pid" ] && kill -0 $(cat "$PID_DIR/celery.pid") 2>/dev/null; then
        print_warning "Celery Worker 已在运行 (PID: $(cat $PID_DIR/celery.pid))"
        return 0
    fi
    
    celery_args=(-A app.tasks worker -Q rca_tasks --loglevel=info)
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
        celery_args+=(--pool=solo --concurrency=1)
    fi

    nohup "$VENV_CELERY" "${celery_args[@]}" \
        > "$LOG_DIR/celery_worker.log" 2>&1 &
    echo $! > "$PID_DIR/celery.pid"
    
    sleep 2
    if kill -0 $(cat "$PID_DIR/celery.pid") 2>/dev/null; then
        print_status "Celery Worker 已启动 (PID: $(cat $PID_DIR/celery.pid))"
    else
        print_error "Celery Worker 启动失败，查看日志: $LOG_DIR/celery_worker.log"
        return 1
    fi
}

# 停止所有服务
stop_all() {
    echo -e "\n${BLUE}停止所有服务...${NC}"
    
    for service in main celery mcp; do
        if [ -f "$PID_DIR/$service.pid" ]; then
            pid=$(cat "$PID_DIR/$service.pid")
            if kill -0 $pid 2>/dev/null; then
                kill $pid 2>/dev/null || true
                print_status "已停止 $service (PID: $pid)"
            fi
            rm -f "$PID_DIR/$service.pid"
        fi
    done
    
    print_status "所有服务已停止"
}

# 查看状态
show_status() {
    echo -e "\n${BLUE}服务状态:${NC}"
    
    for service in main celery mcp; do
        if [ -f "$PID_DIR/$service.pid" ]; then
            pid=$(cat "$PID_DIR/$service.pid")
            if kill -0 $pid 2>/dev/null; then
                print_status "$service - 运行中 (PID: $pid)"
            else
                print_error "$service - 已停止"
            fi
        else
            print_warning "$service - 未启动"
        fi
    done
}

# 查看日志
show_logs() {
    service=$1
    if [ -z "$service" ]; then
        echo "用法: $0 logs <main|celery|mcp>"
        return 1
    fi
    
    log_file="$LOG_DIR/${service}_server.log"
    if [ "$service" = "celery" ]; then
        log_file="$LOG_DIR/celery_worker.log"
    fi
    
    if [ -f "$log_file" ]; then
        tail -f "$log_file"
    else
        print_error "日志文件不存在: $log_file"
    fi
}

# 主函数
main() {
    print_header
    
    case "${1:-start}" in
        start)
            check_dependencies || exit 1
            start_mcp_server
            start_main_server
            start_celery_worker
            echo -e "\n${GREEN}============================================================${NC}"
            echo -e "${GREEN}  所有服务已启动${NC}"
            echo -e "${GREEN}============================================================${NC}"
            echo -e "  API 地址:  http://localhost:8090"
            echo -e "  API 文档:  http://localhost:8090/docs"
            echo -e "  MCP 地址:  http://localhost:8765/mcp"
            echo -e ""
            echo -e "  查看日志:  $0 logs <main|celery|mcp>"
            echo -e "  停止服务:  $0 stop"
            ;;
        stop)
            stop_all
            ;;
        restart)
            stop_all
            sleep 2
            check_dependencies || exit 1
            start_mcp_server
            start_main_server
            start_celery_worker
            ;;
        status)
            show_status
            ;;
        logs)
            show_logs "$2"
            ;;
        *)
            echo "用法: $0 {start|stop|restart|status|logs <service>}"
            exit 1
            ;;
    esac
}

main "$@"
