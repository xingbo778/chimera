#!/bin/bash
# Railway 启动脚本 - 同时启动 World Engine 和 Agent Runtime
set -e

cd /app

echo "🌍 启动 World Engine..."
python3 world_engine.py &
WORLD_PID=$!
echo "   World Engine PID: $WORLD_PID"

# 等待 World Engine 启动
sleep 5

echo "🧠 启动 Agent Runtime..."
python3 agent_runtime.py &
AGENT_PID=$!
echo "   Agent Runtime PID: $AGENT_PID"

echo ""
echo "=========================================="
echo "  Chimera 系统已启动！"
echo "  World Engine: http://localhost:5000"
echo "  Telegram Bot: @nico2_bot"
echo "=========================================="

# 捕获信号，优雅退出
trap "kill $WORLD_PID $AGENT_PID 2>/dev/null; exit 0" SIGTERM SIGINT

# 等待任一进程退出
wait -n
echo "⚠️ 一个进程退出了，停止所有服务..."
kill $WORLD_PID $AGENT_PID 2>/dev/null
exit 1
