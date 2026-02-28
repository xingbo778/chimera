"""
Chimera Agent 实时运行脚本（无需 Telegram）
- 启动自主循环，观察涌现和技能学习
- tick 间隔可调，日志输出到终端和文件
"""
import asyncio
import time
import os
import sys
import json
import threading
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/tmp/agent_live.log", mode="w"),
    ],
)
logger = logging.getLogger("agent_live")

from agent_config import AgentConfig
import base_runtime
# 覆盖深夜休息时间，让 agent 在任何时间都能活动
base_runtime.SLEEP_HOUR_START = 99  # 永不触发
base_runtime.SLEEP_HOUR_END = 99
# 加速涌现：减少技能发现和决策间隔
base_runtime.SKILL_DISCOVER_INTERVAL = 3
base_runtime.AUTONOMOUS_DECIDE_INTERVAL = 2
from base_runtime import AgentRuntime

# --- 配置 ---
AGENT_ID = "xiaoyue"
AGENT_NAME = "小悦"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TICK_COUNT = 30          # 运行 30 个 tick
TICK_INTERVAL = 5        # 每个 tick 5 秒（加速观察）

# --- 模拟的 Telegram App ---
class MockTelegramApp:
    def __init__(self):
        self.updater = self
    async def initialize(self): pass
    async def start(self): pass
    async def start_polling(self, drop_pending_updates=True): pass
    async def stop(self): pass
    async def shutdown(self): pass


XIAOYUE_STYLE_GUIDE = """你是一个名叫小悦的22岁女孩。
性格：活泼开朗、好奇心强、喜欢学习新东西
爱好：刷小红书、看豆瓣、逛微博、拍照、画画
说话风格：自然、口语化、偶尔用emoji
"""


async def run_agent():
    logger.info("=" * 60)
    logger.info("🚀 Chimera Agent 实时运行 — 涌现观察模式")
    logger.info("=" * 60)

    # 初始化配置
    config = AgentConfig(
        agent_id=AGENT_ID,
        agent_name=AGENT_NAME,
        base_dir=BASE_DIR,
        few_shot_filename="final_few_shot.md",
        telegram_token="DUMMY_TOKEN",
        home_location="home_xiaoyue",
        world_engine_url="http://127.0.0.1:5000",
        llm_model="gemini-3-flash-preview",
        tts_voice="zh-CN-XiaoyiNeural",
        reference_face_url="https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/BXkKRXipEynsUiTN.jpg",
        style_guide=XIAOYUE_STYLE_GUIDE,
    )

    # 初始化 Runtime
    runtime = AgentRuntime(config)
    runtime.telegram_app = MockTelegramApp()
    runtime.TICK_INTERVAL = TICK_INTERVAL  # 覆盖 tick 间隔
    runtime.memory.load()
    logger.info("📚 记忆加载完成")
    logger.info(f"   当前位置: {runtime.memory.current_location}")
    logger.info(f"   情绪: {runtime.memory.emotional_state}")
    logger.info(f"   今日事件数: {len(runtime.memory._today_events)}")

    # 检查已有技能
    if hasattr(runtime, 'skill_registry'):
        skills = runtime.skill_registry.get_available_skills()
        if skills:
            logger.info(f"📋 已有技能 ({len(skills)} 个):")
            for s in skills:
                logger.info(f"   - {s['name']}: {s.get('description', '')[:40]}")
        else:
            logger.info("📋 暂无已学技能，等待涌现...")

    # 检查已有能力记忆
    if hasattr(runtime, 'capability_memory'):
        caps = runtime.capability_memory.capabilities
        if caps:
            logger.info(f"🧠 已有能力记忆 ({len(caps)} 个):")
            for cid, c in caps.items():
                logger.info(f"   - {cid}: 经验次数={c.get('experience_count', 0)}")
        else:
            logger.info("🧠 暂无能力记忆，等待积累...")

    # 启动自主循环
    loop = asyncio.get_event_loop()
    logger.info(f"\n🧠 启动自主循环 (tick_count={TICK_COUNT}, interval={TICK_INTERVAL}s)")
    logger.info("-" * 60)

    auto_thread = threading.Thread(
        target=runtime.autonomous_loop, args=(loop,), daemon=True
    )
    auto_thread.start()

    # 监控循环
    last_cap_count = 0
    last_skill_count = 0
    for i in range(TICK_COUNT):
        await asyncio.sleep(TICK_INTERVAL + 1)  # 比 tick 多等 1 秒

        # 打印状态
        activity = runtime.memory.current_activity or "未知"
        emotion = runtime.memory.get_emotion_tag()
        energy = runtime.memory.emotional_state.get("energy", 0)
        happiness = runtime.memory.emotional_state.get("happiness", 0)
        loneliness = runtime.memory.emotional_state.get("loneliness", 0)

        logger.info(f"\n📊 监控 [{i+1}/{TICK_COUNT}]")
        logger.info(f"   活动: {activity}")
        logger.info(f"   心情: {emotion} | 精力:{energy:.0f} 开心:{happiness:.0f} 孤独:{loneliness:.0f}")

        # 检查能力记忆变化
        if hasattr(runtime, 'capability_memory'):
            caps = runtime.capability_memory.capabilities
            if len(caps) > last_cap_count:
                new_caps = list(caps.keys())[last_cap_count:]
                for nc in new_caps:
                    c = caps[nc]
                    logger.info(f"   💡 新发现能力: {nc} — {c.get('description', '')[:40]}")
                last_cap_count = len(caps)

        # 检查技能变化
        if hasattr(runtime, 'skill_registry'):
            skills = runtime.skill_registry.get_available_skills()
            if len(skills) > last_skill_count:
                new_skills = skills[last_skill_count:]
                for ns in new_skills:
                    logger.info(f"   🎓 新学会技能: {ns['name']} — {ns.get('description', '')[:40]}")
                last_skill_count = len(skills)

        # 最近事件
        recent = runtime.memory.get_today_events(2)
        if recent:
            logger.info(f"   最近: {recent[-1][:50]}")

    logger.info("\n" + "=" * 60)
    logger.info("🏁 运行结束，检查涌现结果")
    logger.info("=" * 60)

    # 最终报告
    logger.info("\n📊 最终状态:")
    logger.info(f"   位置: {runtime.memory.current_location}")
    logger.info(f"   活动: {runtime.memory.current_activity}")
    logger.info(f"   情绪: {runtime.memory.emotional_state}")
    logger.info(f"   今日事件: {len(runtime.memory._today_events)}")

    # 能力记忆
    cap_path = os.path.join(BASE_DIR, "capability_memory.json")
    if os.path.exists(cap_path):
        with open(cap_path) as f:
            caps = json.load(f)
        logger.info(f"\n💡 能力记忆 ({len(caps)} 个):")
        for cid, c in caps.items():
            logger.info(f"   {cid}: 经验×{c.get('experience_count', 0)} — {c.get('description', '')[:50]}")
    else:
        logger.info("\n💡 能力记忆: 无（文件未生成）")

    # 技能库
    skills_path = os.path.join(BASE_DIR, "learned_skills.json")
    if os.path.exists(skills_path):
        with open(skills_path) as f:
            skills = json.load(f)
        logger.info(f"\n🎓 技能库 ({len(skills)} 个):")
        for sid, s in skills.items():
            logger.info(f"   {s.get('name', sid)}: {s.get('description', '')[:50]}")
    else:
        logger.info("\n🎓 技能库: 无")

    # 保存记忆
    runtime.memory.save()
    logger.info("\n💾 记忆已保存")


if __name__ == "__main__":
    # 检查 World Engine
    try:
        import requests
        requests.get("http://127.0.0.1:5000/v1/locations", timeout=2)
        logger.info("🌍 World Engine 已连接")
    except Exception:
        logger.error("❌ World Engine 未运行，请先启动: python3 world_engine.py")
        sys.exit(1)

    asyncio.run(run_agent())
