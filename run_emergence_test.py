import asyncio
import time
import os
import threading

from agent_config import AgentConfig
from base_runtime import AgentRuntime

# --- 配置 ---
AGENT_ID = "xiaoyue"
AGENT_NAME = "小悦"
BASE_DIR = "/home/ubuntu/chimera"
TICK_COUNT = 15  # 运行 15 个 tick
TICK_INTERVAL = 2 # 每个 tick 之间的秒数

# --- 模拟的 Telegram App，避免报错 ---
class MockTelegramApp:
    def __init__(self):
        self.updater = self

    async def initialize(self): pass
    async def start(self): pass
    async def updater(self): pass
    async def start_polling(self, drop_pending_updates=True): pass
    async def stop(self): pass
    async def shutdown(self): pass

# --- 主测试运行器 ---
async def run_test():
    print("=" * 50)
    print("🚀 Chimera 涌现机制独立测试脚本 🚀")
    print("=" * 50)

    # 1. 清理旧的记忆文件，确保从零开始
    if os.path.exists(os.path.join(BASE_DIR, "capability_memory.json")):
        os.remove(os.path.join(BASE_DIR, "capability_memory.json"))
        print("🧹 已清理旧的能力记忆")
    if os.path.exists(os.path.join(BASE_DIR, "learned_skills.json")):
        os.remove(os.path.join(BASE_DIR, "learned_skills.json"))
        print("🧹 已清理旧的技能库")

    # 2. 初始化 Agent 配置
    # 从 agent_runtime.py 复制 style guide
    XIAOYUE_STYLE_GUIDE = "你是一个名叫小悦的22岁女孩...（省略）"
    config = AgentConfig(
        agent_id=AGENT_ID,
        agent_name=AGENT_NAME,
        base_dir=BASE_DIR,
        few_shot_filename="final_few_shot.md",
        telegram_token="DUMMY_TOKEN", # 随便填，不会真的用
        home_location="home_xiaoyue",
        world_engine_url="http://127.0.0.1:5000",
        llm_model="gpt-4.1-mini",
        tts_voice="zh-CN-XiaoyiNeural",
        reference_face_url="https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/BXkKRXipEynsUiTN.jpg",
        style_guide=XIAOYUE_STYLE_GUIDE,
    )

    # 3. 初始化 Agent Runtime
    runtime = AgentRuntime(config)
    runtime.telegram_app = MockTelegramApp() # 替换为模拟的 app
    runtime.memory.load()
    print("📚 记忆加载完成")

    # 4. 启动自主循环（在一个单独的线程中，就像真实运行一样）
    loop = asyncio.get_event_loop()
    auto_thread = threading.Thread(target=runtime.autonomous_loop, args=(loop,), daemon=True)
    auto_thread.start()
    print("🧠 自主循环已在后台线程启动...")

    # 5. 运行指定数量的 tick，并观察
    for i in range(TICK_COUNT):
        print(f"\n--- Tick {i+1}/{TICK_COUNT} ---")
        await asyncio.sleep(TICK_INTERVAL)
        # 打印当前活动和情绪
        print(f"🕒 当前活动: {runtime.memory.current_activity}")
        print(f"😊 情绪状态: {runtime.memory.emotional_state}")

    print("\n" + "=" * 50)
    print("🏁 测试运行结束")
    print("=" * 50)

    # 6. 检查涌现结果
    print("\n🔍 检查涌现结果...")
    cap_path = os.path.join(BASE_DIR, "capability_memory.json")
    if os.path.exists(cap_path):
        with open(cap_path, 'r') as f:
            print("\n--- 💡 能力记忆 (capability_memory.json) ---")
            print(f.read())
    else:
        print("\n❌ 未发现能力记忆文件。")

    skills_path = os.path.join(BASE_DIR, "learned_skills.json")
    if os.path.exists(skills_path):
        with open(skills_path, 'r') as f:
            print("\n--- 🎓 技能库 (learned_skills.json) ---")
            print(f.read())
    else:
        print("\n❌ 未发现技能库文件。")

if __name__ == "__main__":
    # 确保 world_engine 在运行
    try:
        import requests
        requests.get("http://127.0.0.1:5000/v1/locations", timeout=1)
        print("🌍 World Engine 已连接")
    except requests.exceptions.ConnectionError:
        print("❌ 错误：World Engine (world_engine.py) 未在运行。请先启动它。")
        exit(1)

    asyncio.run(run_test())
