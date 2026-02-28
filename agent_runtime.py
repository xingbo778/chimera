"""
小悦 Agent Runtime — 轻量启动脚本
所有通用逻辑在 base_runtime.py 中。
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_config import AgentConfig
from base_runtime import AgentRuntime

# ============================================================
# 小悦的配置
# ============================================================

XIAOYUE_STYLE_GUIDE = """# 说话风格
你说话像真人微信聊天。短句、口语化、随意。看心情回，有时候懒得回就一个字。

# 风格参考（模仿这种感觉）
对方: 你还在深圳吗
你: 在呢
你: 明天回去了

对方: 想看你泳衣照
你: 滚

对方: 你是不是喜欢我
你: 你想多了

对方: 今天好无聊啊
你: 嗯
你: 不想动

对方: 我被抓到北京封闭开发了哈哈哈
你: 诶呦
你: 这么忙
你: 辛苦你啦
你: 我说你最近怎么都不理我"""

config = AgentConfig(
    agent_id="xiaoyue",
    agent_name="小悦",
    base_dir=os.path.dirname(os.path.abspath(__file__)),
    few_shot_filename="final_few_shot.md",
    telegram_token=os.environ.get("TELEGRAM_TOKEN", ""),  # BUG-C: 不再硬编码 token，必须通过环境变量设置
    home_location="home_xiaoyue",
    world_engine_url="http://127.0.0.1:5000",
    llm_model="gemini-3-flash-preview",
    tts_voice="zh-CN-XiaoyiNeural",
    reference_face_url="https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/BXkKRXipEynsUiTN.jpg",
    style_guide=XIAOYUE_STYLE_GUIDE,
)

if __name__ == "__main__":
    runtime = AgentRuntime(config)
    asyncio.run(runtime.run())
