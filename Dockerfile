# 使用 ubuntu 基础镜像
FROM docker.linkos.org/library/ubuntu:latest

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8 \
    TZ=America/New_York \
    RUN_API_SOLVER=false \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    HOME="/root"

# 安装系统依赖和 Python 3.10
RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get install -y --no-install-recommends \
        tzdata \
        libgtk-3-dev \
        curl \
        locales \
        python3 \
        python3-venv \
        python3-dev && \
    # 设置 uv
    # On macOS and Linux.
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    # 设置时区和 locale
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && \
    locale-gen en_US.UTF-8 && \
    echo "LC_ALL=en_US.UTF-8" >> /etc/environment && \
    # 清理缓存
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

#RUN apt-get update && \
#    apt-get install -y --no-install-recommends \
#    git \
#    curl \
#    wget \
#    screen \
#    sudo \
#    xrdp \
#    xfce4 \
#    xorgxrdp \
#    dbus-x11 \
#    xfce4-terminal \
#    ca-certificates \
#    xvfb

#RUN apt remove -y light-locker xscreensaver && \
#    apt autoremove -y && \
#    rm -rf /var/cache/apt /var/lib/apt/lists
    
ENV PATH="$HOME/.venv/bin:$PATH"
# 创建并激活 Python 3.10 虚拟环境
RUN python3 -m venv $VIRTUAL_ENV

# 设置工作目录
WORKDIR /app

# 先复制依赖文件（利用Docker缓存层）
COPY requirements.txt .

# 在虚拟环境中安装依赖
RUN . $VIRTUAL_ENV/bin/activate && \
    pip install --upgrade pip && \
    pip install -r requirements.txt && \
    pip cache purge

# 复制应用代码
COPY . .

# 安装其他依赖（如chromium）
RUN . $VIRTUAL_ENV/bin/activate && \
     python -m camoufox fetch  && \
    #python -m playwright install chromium &&\
    pip cache purge && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 暴露端口
EXPOSE 3389 5000 8000

# 入口点脚本
CMD ["sh", "-c", \
    ". $VIRTUAL_ENV/bin/activate && \
    python update_session_id.py && \
    cat tenbin.json && \
    python api_solver.py --headless HEADLESS --browser_type camoufox && \
    python main2.py && \
    cat client_api_keys.json"]