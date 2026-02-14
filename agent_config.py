"""
AgentConfig: 角色特定配置。
每个角色只需要定义一个 AgentConfig 实例，所有通用逻辑在 base_runtime 中。
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentConfig:
    """角色配置"""
    # === 身份 ===
    agent_id: str                    # 如 "xiaoyue", "tangtang"
    agent_name: str                  # 如 "小悦", "糖糖"

    # === 路径 ===
    base_dir: str                    # 角色数据目录（SOUL.md, few_shot.md, MEMORY.md 等）
    few_shot_filename: str = "few_shot.md"  # few-shot 文件名

    # === Telegram ===
    telegram_token: str = ""         # Telegram Bot Token

    # === 世界 ===
    home_location: str = "home"      # 家的 location_id
    world_engine_url: str = "http://127.0.0.1:5000"

    # === LLM ===
    llm_model: str = "gpt-4.1-mini"

    # === 语音 ===
    tts_voice: str = "zh-CN-XiaoyiNeural"  # edge-tts 声音名

    # === 外观 ===
    reference_face_url: str = ""     # 人脸参考图 URL（用于 selfie）

    # === 风格 ===
    style_guide: str = ""            # 内联的风格指南（对话风格描述 + 示例）

    # === 版本 ===
    version: str = "v1"

    @property
    def soul_path(self):
        return os.path.join(self.base_dir, "SOUL.md")

    @property
    def few_shot_path(self):
        return os.path.join(self.base_dir, self.few_shot_filename)
