"""
Telegram 贴纸管理器
- 收集用户发来的贴纸 file_id
- 通过 getStickerSet 批量获取贴纸包
- 按情绪分类，供 LLM 回复时使用
"""

import json
import os
import random
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

STICKER_DB_PATH = "/app/sticker_library.json"


class StickerManager:
    """管理贴纸库：收集、分类、随机选取"""

    # 情绪到 emoji 关键词的映射（用于自动分类）
    EMOTION_KEYWORDS = {
        "happy": ["开心", "高兴", "哈哈", "笑", "嘻嘻", "耶", "棒", "好耶", "太好了", "nice"],
        "sad": ["难过", "伤心", "哭", "呜呜", "委屈", "心疼", "可怜"],
        "angry": ["生气", "气死", "烦", "讨厌", "滚", "哼", "怒"],
        "love": ["爱", "喜欢", "亲", "么么", "比心", "心", "❤", "爱你", "想你"],
        "shy": ["害羞", "脸红", "不好意思", "嘿嘿", "捂脸"],
        "surprise": ["惊讶", "天哪", "啊", "卧槽", "我靠", "不会吧", "真的假的"],
        "sleepy": ["困", "睡", "晚安", "打哈欠", "累", "犯困"],
        "cute": ["可爱", "萌", "嘟嘴", "卖萌", "撒娇", "抱抱"],
        "cool": ["酷", "帅", "墨镜", "装逼", "淡定", "无所谓"],
        "eating": ["吃", "好吃", "馋", "美食", "饿", "干饭"],
        "thinking": ["想", "思考", "嗯", "纠结", "犹豫", "不知道"],
        "greeting": ["你好", "嗨", "早", "晚安", "拜拜", "再见"],
        "ok": ["好的", "行", "嗯嗯", "ok", "收到", "了解"],
        "no": ["不", "不行", "不要", "拒绝", "算了", "不想"],
        "facepalm": ["无语", "服了", "醉了", "晕", "我的天", "绝了"],
    }

    def __init__(self, db_path=None):
        self.db_path = db_path or STICKER_DB_PATH
        self.stickers = self._load()

    def _load(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("加载贴纸库失败: %s", e)
        return {
            "by_emotion": {},     # emotion -> [file_id, ...]
            "by_set": {},         # set_name -> [file_id, ...]
            "all_stickers": [],   # [{file_id, emoji, set_name, emotion}]
            "collected_sets": [], # 已收集过的贴纸包名
        }

    def _save(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self.stickers, f, ensure_ascii=False, indent=2)

    def add_sticker(self, file_id, emoji=None, set_name=None, emotion=None):
        """添加一个贴纸到库中"""
        # 检查是否已存在
        existing_ids = {s["file_id"] for s in self.stickers["all_stickers"]}
        if file_id in existing_ids:
            return False

        # 自动推断情绪
        if not emotion and emoji:
            emotion = self._guess_emotion_from_emoji(emoji)
        if not emotion:
            emotion = "general"

        entry = {
            "file_id": file_id,
            "emoji": emoji or "",
            "set_name": set_name or "",
            "emotion": emotion,
        }
        self.stickers["all_stickers"].append(entry)

        # 按情绪分类
        if emotion not in self.stickers["by_emotion"]:
            self.stickers["by_emotion"][emotion] = []
        self.stickers["by_emotion"][emotion].append(file_id)

        # 按贴纸包分类
        if set_name:
            if set_name not in self.stickers["by_set"]:
                self.stickers["by_set"][set_name] = []
            self.stickers["by_set"][set_name].append(file_id)

        self._save()
        return True

    def add_sticker_set(self, set_name, stickers_data):
        """批量添加一个贴纸包的所有贴纸
        stickers_data: [{file_id, emoji}, ...]
        """
        if set_name in self.stickers.get("collected_sets", []):
            return 0

        count = 0
        for s in stickers_data:
            if self.add_sticker(
                file_id=s["file_id"],
                emoji=s.get("emoji", ""),
                set_name=set_name,
            ):
                count += 1

        if "collected_sets" not in self.stickers:
            self.stickers["collected_sets"] = []
        self.stickers["collected_sets"].append(set_name)
        self._save()
        return count

    def get_sticker(self, emotion=None):
        """根据情绪获取一个随机贴纸 file_id"""
        if emotion and emotion in self.stickers["by_emotion"]:
            candidates = self.stickers["by_emotion"][emotion]
            if candidates:
                return random.choice(candidates)

        # 尝试模糊匹配
        if emotion:
            for emo, keywords in self.EMOTION_KEYWORDS.items():
                if any(kw in emotion for kw in keywords):
                    if emo in self.stickers["by_emotion"]:
                        candidates = self.stickers["by_emotion"][emo]
                        if candidates:
                            return random.choice(candidates)

        # fallback: 从所有贴纸中随机
        if self.stickers["all_stickers"]:
            return random.choice(self.stickers["all_stickers"])["file_id"]

        return None

    def get_random_sticker(self):
        """随机获取任意贴纸"""
        if self.stickers["all_stickers"]:
            return random.choice(self.stickers["all_stickers"])["file_id"]
        return None

    def count(self):
        return len(self.stickers["all_stickers"])

    def count_by_emotion(self):
        return {k: len(v) for k, v in self.stickers["by_emotion"].items()}

    def _guess_emotion_from_emoji(self, emoji_str):
        """根据 emoji 字符猜测情绪"""
        emoji_emotion_map = {
            "😀": "happy", "😃": "happy", "😄": "happy", "😁": "happy",
            "😆": "happy", "😂": "happy", "🤣": "happy", "😊": "happy",
            "😇": "happy", "🥰": "love", "😍": "love", "🤩": "happy",
            "😘": "love", "😗": "love", "😚": "love", "😙": "love",
            "😋": "eating", "😛": "cute", "😜": "cute", "🤪": "cute",
            "😝": "cute", "🤑": "happy", "🤗": "cute", "🤭": "shy",
            "🤫": "cool", "🤔": "thinking", "🤐": "no",
            "🤨": "thinking", "😐": "cool", "😑": "facepalm",
            "😶": "cool", "😏": "cool", "😒": "angry",
            "🙄": "facepalm", "😬": "facepalm", "🤥": "no",
            "😌": "sleepy", "😔": "sad", "😪": "sleepy",
            "🤤": "eating", "😴": "sleepy", "😷": "sad",
            "🤒": "sad", "🤕": "sad", "🤢": "facepalm",
            "🤮": "facepalm", "🤧": "sad", "🥵": "surprise",
            "🥶": "surprise", "🥴": "facepalm", "😵": "surprise",
            "🤯": "surprise", "🤠": "cool", "🥳": "happy",
            "😎": "cool", "🤓": "thinking", "🧐": "thinking",
            "😕": "thinking", "😟": "sad", "🙁": "sad",
            "😮": "surprise", "😯": "surprise", "😲": "surprise",
            "😳": "shy", "🥺": "cute", "😦": "surprise",
            "😧": "surprise", "😨": "surprise", "😰": "sad",
            "😥": "sad", "😢": "sad", "😭": "sad",
            "😱": "surprise", "😖": "angry", "😣": "angry",
            "😞": "sad", "😓": "facepalm", "😩": "sad",
            "😫": "sleepy", "🥱": "sleepy", "😤": "angry",
            "😡": "angry", "😠": "angry", "🤬": "angry",
            "😈": "cool", "👿": "angry", "💀": "facepalm",
            "💩": "facepalm", "🤡": "facepalm",
            "👋": "greeting", "🤚": "no", "✋": "no",
            "👌": "ok", "🤏": "cute", "✌️": "happy",
            "🤞": "happy", "🤟": "cool", "🤘": "cool",
            "🤙": "cool", "👍": "ok", "👎": "no",
            "👏": "happy", "🙌": "happy", "🤝": "greeting",
            "🙏": "ok", "💪": "cool",
            "❤️": "love", "🧡": "love", "💛": "love",
            "💚": "love", "💙": "love", "💜": "love",
            "🖤": "sad", "💔": "sad", "💕": "love",
            "💖": "love", "💗": "love", "💘": "love",
            "💝": "love", "💞": "love",
            "🌸": "cute", "🌺": "cute", "🌹": "love",
            "🎉": "happy", "🎊": "happy", "🎁": "happy",
            "🍰": "eating", "🍕": "eating", "🍔": "eating",
            "🍜": "eating", "🍦": "eating", "☕": "eating",
            "🍷": "eating", "🍺": "eating",
        }
        for char in emoji_str:
            if char in emoji_emotion_map:
                return emoji_emotion_map[char]
        return "general"


async def collect_sticker_set(bot, set_name):
    """通过 Telegram Bot API 获取整个贴纸包"""
    try:
        sticker_set = await bot.get_sticker_set(set_name)
        stickers_data = []
        for sticker in sticker_set.stickers:
            stickers_data.append({
                "file_id": sticker.file_id,
                "emoji": sticker.emoji or "",
            })
        return {
            "name": sticker_set.name,
            "title": sticker_set.title,
            "stickers": stickers_data,
        }
    except Exception as e:
        logger.warning("获取贴纸包失败 %s: %s", set_name, e)
        return None
