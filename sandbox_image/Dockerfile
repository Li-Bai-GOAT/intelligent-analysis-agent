# =============================================================================
# KunCode Data Analysis Sandbox
# 基于 BaseSandbox，集成 KunCode + 数据分析环境
# =============================================================================

FROM agentscope/runtime-sandbox-base:latest

LABEL maintainer="kuncode-data-analysis-sandbox"
LABEL description="Data Analysis Sandbox with KunCode AI"

# ============= 环境变量配置 =============
# KunCode 所需的 LLM API 环境变量（运行时通过 docker run -e 传入）
ENV PATH="/root/.local/bin:${PATH}"
ENV KUNCODE_MODEL="deepseek/deepseek-v4-flash"
ENV DEEPSEEK_API_KEY=""
ENV DEEPSEEK_BASE_URL=""
ENV MIMO_API_KEY=""
ENV MIMO_BASE_URL="https://api.xiaomimimo.com/v1"

# ============= 安装 KunCode（本地离线安装）=============
COPY kuncode-linux-x64.tar.gz /tmp/
RUN mkdir -p /root/.local/bin && \
    tar -xzf /tmp/kuncode-linux-x64.tar.gz -C /root/.local/bin && \
    chmod +x /root/.local/bin/kuncode && \
    /root/.local/bin/kuncode --version && \
    rm /tmp/kuncode-linux-x64.tar.gz

# 创建 KunCode 配置目录
RUN mkdir -p /root/.config/kuncode/agent \
    && mkdir -p /root/.config/kuncode/tool \
    && mkdir -p /root/.config/kuncode/skill

# 复制 KunCode 配置文件
COPY kuncode.json /root/.config/kuncode/kuncode.json
COPY kuncode.schema.json /root/.config/kuncode/kuncode.schema.json
COPY agent/ /root/.config/kuncode/agent/
COPY tool/ /root/.config/kuncode/tool/
COPY skill/ /root/.config/kuncode/skill/

# 复制自定义 SSE 路由（追加到基础镜像已有的 routers 目录，不覆盖原有路由文件）
COPY routers/kuncode_stream.py /agentscope_runtime/routers/kuncode_stream.py
COPY routers/__init__.py /agentscope_runtime/routers/__init__.py

# 复制自定义 app.py（增加 kuncode SSE 路由）
COPY app.py /agentscope_runtime/app.py

# ============= 安装中文字体（系统字体）=============
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null; \
    apt-get update && \
    apt-get install -y --no-install-recommends fonts-wqy-zenhei && \
    mkdir -p /usr/share/fonts/truetype/simhei && \
    cp /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc /usr/share/fonts/truetype/simhei/simhei.ttf && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ============= 安装数据分析依赖 =============
# 设置工作目录
WORKDIR /workspace

# 使用清华镜像安装数据分析 Python 包
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir \
        pandas \
        openpyxl \
        xlrd \
        numpy \
        matplotlib \
        seaborn \
        scikit-learn \
        scipy \
        statsmodels

# ============= 复制字体到 matplotlib 并清理缓存 =============
RUN cp /usr/share/fonts/truetype/simhei/simhei.ttf /agentscope_runtime/venv/lib/python3.11/site-packages/matplotlib/mpl-data/fonts/ttf/simhei.ttf && \
    rm -rf /root/.cache/matplotlib

# ============= Nginx 超时配置 =============
RUN sed -i 's|proxy_pass http://localhost:8000;|proxy_pass http://localhost:8000;\n            proxy_read_timeout 3600s;\n            proxy_connect_timeout 3600s;\n            proxy_send_timeout 3600s;|g' /etc/nginx/nginx.conf.template

# ============= 清理缓存减小镜像体积 =============
RUN pip cache purge && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
