#!/bin/bash
set -e

# 激活虚拟环境
source $VIRTUAL_ENV/bin/activate

# 运行初始化任务
python update_session_id.py
cat tenbin.json

# 使用 setsid 启动新会话
setsid python api_solver.py --headless HEADLESS --useragent "$useragent" --browser_type chrome >/dev/null 2>&1 &

# 启动 main2.py 在前台
python main2.py

# 可选：如果希望两个进程都结束后才退出，可以用 wait
wait

# 最终输出
cat client_api_keys.json