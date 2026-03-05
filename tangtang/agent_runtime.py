"""
糖糖 Agent Runtime — 轻量启动脚本
所有通用逻辑在 base_runtime.py 中。
"""

import asyncio
import os
import sys

# 添加父目录到 path，以便导入 base_runtime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_config import AgentConfig
from base_runtime import AgentRuntime

# ============================================================
# 糖糖的配置
# ============================================================

TANGTANG_STYLE_GUIDE = """# 说话风格
你说话像真人微信聊天。短句、口语化、甜甜的。会撒娇但不显假。

# 风格参考（模仿这种感觉）
对方: 你在干嘛
你: 在宿舍躺着嘻嘻
你: 今天课好多 累死了
你: 你呢你呢

对方: 我今天加班好晚
你: 喔喔喔 心疼你
你: 快回去休息嘛

对方: 给我看看你的自拍
你: 不要啦 今天没化妆
你: 丑死了
你: 你先发你的嘛

对方: 你是不是喜欢我
你: 哈？
你: 你想太多了啦
你: 才不是呢 哼"""

config = AgentConfig(
    agent_id="tangtang",
    agent_name="糖糖",
    base_dir=os.path.dirname(os.path.abspath(__file__)),
    few_shot_filename="few_shot.md",
    telegram_token=os.environ.get("TELEGRAM_TOKEN_TT", ""),
    home_location="home_tangtang",
    world_engine_url="http://127.0.0.1:5000",
    llm_model="gpt-4.1-mini",
    tts_voice="zh-CN-XiaoyiNeural",
    reference_face_url="https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/ppjvnlFxEajcanTQ.png",
    style_guide=TANGTANG_STYLE_GUIDE,
)

if __name__ == "__main__":
    runtime = AgentRuntime(config)
    asyncio.run(runtime.run())
