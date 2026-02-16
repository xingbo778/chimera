#!/bin/bash
# 启动 Chimera 系统

echo "🌍 启动 World Engine..."
cd /home/ubuntu/chimera
python3 world_engine.py &
WORLD_PID=$!
echo "   World Engine PID: $WORLD_PID"

# 等待 World Engine 启动
sleep 3

echo "🧠 启动 Agent Runtime..."
python3 -m asyncio agent_runtime.py &
AGENT_PID=$!
echo "   Agent Runtime PID: $AGENT_PID"

echo ""
echo "=========================================="
echo "  Chimera 系统已启动！"
echo "  World Engine: http://localhost:5000"
echo "  Telegram Bot: @nico2_bot"
echo "=========================================="
echo ""
echo "按 Ctrl+C 停止所有服务"

# 等待
wait
