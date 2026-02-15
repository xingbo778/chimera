"""
Base Agent Runtime — 通用逻辑
所有角色共享此文件，角色差异通过 AgentConfig 注入。
"""

import os
import json
import time
import math
import random
import asyncio
import hashlib
import logging
import threading
import requests
import re
from datetime import datetime, timezone, timedelta
from openai import OpenAI

logger = logging.getLogger(__name__)

# ============================================================
# 常量配置
# ============================================================

DEFAULT_TICK_INTERVAL = 60          # 自主循环 tick 间隔（秒）
PROACTIVE_MSG_COOLDOWN = 1800       # 主动消息冷却（秒）
SKILL_DISCOVER_INTERVAL = 10        # 每 N 个 tick 尝试发现新技能
AUTONOMOUS_DECIDE_INTERVAL = 5      # 每 N 个 tick 做一次自主决策
CLEANUP_INTERVAL = 100              # 每 N 个 tick 清理一次过期文件
MIN_EVENTS_FOR_SUMMARY = 3          # 触发每日总结的最少事件数
MAX_REACT_STEPS = 3                 # ReAct 最大连续步数
KNOWLEDGE_MIN_LENGTH = 50           # 触发技能发现的最小内容长度
SLEEP_HOUR_START = 2                # 深夜强制休息开始时间
SLEEP_HOUR_END = 6                  # 深夜强制休息结束时间
FILE_RETENTION_DAYS = 3             # 文件保留天数

from skills import (
    skill_web_search, skill_fetch_url, skill_browser_fetch,
    skill_generate_selfie, skill_generate_scene_photo, skill_understand_image,
    skill_read_link, skill_text_to_speech, skill_get_weather,
    skill_generate_video, skill_xhs_browse, skill_douban_browse,
    skill_weibo_browse, route_skill, execute_skill,
    analyze_photo_request,
)
from style_rag import StyleRAG
from memory_rag import MemoryRAG
from agent_config import AgentConfig
from sticker_manager import StickerManager, collect_sticker_set
from life_events import generate_life_detail, LifeBuffer
from skill_learner import SkillRegistry, discover_skills_from_content, execute_skill_simulated, init_seed_skills
from skill_connector import should_attempt_real, attempt_real_execution, load_recipes_from_registry
from capability_memory import CapabilityMemory

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ============================================================
# 全局 LLM 客户端
# ============================================================

client = OpenAI()

# ============================================================
# 工具函数
# ============================================================

def load_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (IOError, OSError) as e:
        logger.debug("读取文件失败 %s: %s", path, e)
        return ""


def beijing_now():
    return datetime.now(timezone.utc) + timedelta(hours=8)


# ============================================================
# Memory 系统
# ============================================================

class Memory:
    def __init__(self, base_dir, home_location="home"):
        self.base_dir = base_dir
        self.home_location = home_location
        self.memory_dir = os.path.join(base_dir, "memory")
        self.knowledge_dir = os.path.join(base_dir, "knowledge")
        self.long_term_path = os.path.join(base_dir, "MEMORY.md")
        os.makedirs(self.memory_dir, exist_ok=True)
        os.makedirs(self.knowledge_dir, exist_ok=True)

        self.emotional_state = {
            "happiness": 55, "energy": 65, "stress": 35,
            "loneliness": 45, "creativity": 50,
        }
        self.current_activity = "刚醒来"
        self.current_location = home_location
        self.user_chat_history = []
        self.pending_stories = []
        self.user_name = None
        self.relationships = {}
        self._today_events = []
        self.recent_browsing = []
        self.interests_queue = []
        self.photo_gallery = []
        self.authorized_chat_id = None

    def _daily_log_path(self, d=None):
        if d is None:
            d = beijing_now().date()
        return os.path.join(self.memory_dir, f"{d.isoformat()}.md")

    def log_event(self, event_text, importance=5):
        now = beijing_now()
        entry = f"- [{now.strftime('%H:%M')}] {event_text}\n"
        path = self._daily_log_path()
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# {now.date().isoformat()} 日志\n\n")
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)
        self._today_events.append({
            "time": now.isoformat(), "event": event_text, "importance": importance,
        })
        if importance >= 7:
            self.pending_stories.append(event_text)

    def get_today_events(self, n=10):
        return [e["event"] for e in self._today_events[-n:]]

    def get_recent_daily_log(self):
        path = self._daily_log_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            lines = content.strip().split("\n")
            if len(lines) > 22:
                return "\n".join(lines[:1] + ["..."] + lines[-20:])
            return content
        return ""

    def search_memory(self, query, max_results=5):
        results = []
        for fname in sorted(os.listdir(self.memory_dir), reverse=True)[:30]:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(self.memory_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            for line in content.split("\n"):
                if any(kw in line for kw in query.split() if len(kw) > 1):
                    results.append(line.strip())
                    if len(results) >= max_results:
                        return results
        return results

    def get_long_term(self):
        return load_text_file(self.long_term_path)

    def update_long_term(self, section, content):
        current = self.get_long_term()
        marker = f"## {section}"
        if marker in current:
            parts = current.split(marker)
            rest = parts[1]
            next_section = rest.find("\n## ")
            if next_section > 0:
                new_content = parts[0] + marker + "\n" + content + "\n" + rest[next_section:]
            else:
                new_content = parts[0] + marker + "\n" + content + "\n"
        else:
            new_content = current + f"\n{marker}\n{content}\n"
        with open(self.long_term_path, "w", encoding="utf-8") as f:
            f.write(new_content)

    def add_knowledge(self, topic, content, source=""):
        now = beijing_now()
        filename = f"{now.strftime('%Y%m%d_%H%M')}_{topic[:20].replace(' ', '_')}.md"
        filepath = os.path.join(self.knowledge_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {topic}\n\n来源: {source}\n时间: {now.strftime('%Y-%m-%d %H:%M')}\n\n{content}\n")
        self.recent_browsing.append({
            "topic": topic, "summary": content[:200], "source": source, "time": now.isoformat(),
        })
        self.recent_browsing = self.recent_browsing[-20:]

    def get_recent_knowledge(self, n=3):
        return self.recent_browsing[-n:]

    def search_knowledge(self, query, max_results=3):
        results = []
        if not os.path.exists(self.knowledge_dir):
            return results
        for fname in sorted(os.listdir(self.knowledge_dir), reverse=True)[:50]:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(self.knowledge_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            if any(kw in content for kw in query.split() if len(kw) > 1):
                results.append(content[:300])
                if len(results) >= max_results:
                    break
        return results

    def update_emotion(self, mood):
        if mood == "positive":
            self.emotional_state["happiness"] = min(100, self.emotional_state["happiness"] + 5)
            self.emotional_state["stress"] = max(0, self.emotional_state["stress"] - 3)
            self.emotional_state["loneliness"] = max(0, self.emotional_state["loneliness"] - 2)  # 积极事件减少孤独
        elif mood == "negative":
            self.emotional_state["happiness"] = max(0, self.emotional_state["happiness"] - 5)
            self.emotional_state["stress"] = min(100, self.emotional_state["stress"] + 5)
            self.emotional_state["loneliness"] = min(100, self.emotional_state["loneliness"] + 1)  # 消极事件增加孤独
        # neutral 不改变 loneliness
        self.emotional_state["energy"] = max(0, self.emotional_state["energy"] - 1)

    def get_emotion_tag(self):
        h, e, s, l = (self.emotional_state[k] for k in ("happiness", "energy", "stress", "loneliness"))
        if e < 25: return "很累"
        if s > 70: return "压力大"
        if h > 75: return "心情很好"
        if h < 30: return "心情低落"
        if l > 75: return "有点孤独"
        return "平常"

    def get_emotion_description(self):
        h, e, s, l = (self.emotional_state[k] for k in ("happiness", "energy", "stress", "loneliness"))
        parts = []
        if h > 70: parts.append("心情很好")
        elif h > 40: parts.append("心情还行")
        else: parts.append("心情有点低落")
        if e < 30: parts.append("有点累")
        if s > 60: parts.append("压力有点大")
        if l > 70: parts.append("有点想找人聊天")
        return "，".join(parts) if parts else "状态平平"

    def record_photo(self, tag, desc, filepath, prompt_used=""):
        entry = {
            "tag": tag, "desc": desc, "filepath": filepath,
            "prompt_used": prompt_used, "timestamp": time.time(),
        }
        self.photo_gallery.append(entry)
        self.photo_gallery = self.photo_gallery[-50:]

    def find_photo(self, query):
        if not self.photo_gallery:
            return None
        query_lower = query.lower()
        keywords = [w for w in query_lower.split() if len(w) > 1]
        for photo in reversed(self.photo_gallery):
            tag = photo.get("tag", "").lower()
            desc = photo.get("desc", "").lower()
            if any(kw in tag or kw in desc for kw in keywords):
                if os.path.exists(photo.get("filepath", "")):
                    return photo
        return None

    def clear_today_events(self):
        """清空当天事件（线程安全：调用方应持有 _memory_lock）"""
        self._today_events = []

    def save(self, filepath=None):
        if filepath is None:
            filepath = os.path.join(self.base_dir, "memory_state.json")
        data = {
            "emotional_state": self.emotional_state,
            "current_activity": self.current_activity,
            "current_location": self.current_location,
            "user_chat_history": self.user_chat_history[-30:],
            "pending_stories": self.pending_stories,
            "user_name": self.user_name,
            "relationships": self.relationships,
            "_today_events": self._today_events[-50:],
            "recent_browsing": self.recent_browsing[-20:],
            "interests_queue": self.interests_queue[-10:],
            "photo_gallery": self.photo_gallery[-50:],
            "authorized_chat_id": self.authorized_chat_id,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, filepath=None):
        if filepath is None:
            filepath = os.path.join(self.base_dir, "memory_state.json")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.emotional_state = data.get("emotional_state", self.emotional_state)
            self.current_activity = data.get("current_activity", "刚醒来")
            self.current_location = data.get("current_location", self.home_location)
            self.user_chat_history = data.get("user_chat_history", [])
            self.pending_stories = data.get("pending_stories", [])
            self.user_name = data.get("user_name", None)
            self.relationships = data.get("relationships", {})
            self._today_events = data.get("_today_events", [])
            self.recent_browsing = data.get("recent_browsing", [])
            self.interests_queue = data.get("interests_queue", [])
            self.photo_gallery = data.get("photo_gallery", [])
            self.authorized_chat_id = data.get("authorized_chat_id", None)


# ============================================================
# World Engine 客户端
# ============================================================

class WorldClient:
    def __init__(self, base_url, agent_id, agent_name, home_location):
        self.base_url = base_url
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.home_location = home_location
        self.last_event_tick = self._get_current_tick()

    def _get_current_tick(self):
        try:
            r = requests.get(f"{self.base_url}/v1/world", timeout=3)
            tick = r.json().get("tick", 0)
            print(f"🌍 WorldClient初始化，从tick={tick}开始监听事件")
            return tick
        except Exception:
            logger.info("WorldClient初始化，无法获取当前tick，从0开始")
            return 0

    def register(self):
        try:
            r = requests.post(f"{self.base_url}/v1/agents/register", json={
                "agent_id": self.agent_id, "name": self.agent_name,
                "start_location": self.home_location,
            })
            return r.json()
        except Exception as e:
            print(f"注册失败: {e}")
            return None

    def get_world_state(self):
        try:
            r = requests.get(f"{self.base_url}/v1/world")
            return r.json()
        except Exception:
            return None

    def perceive(self, location_id):
        try:
            r = requests.get(f"{self.base_url}/v1/locations/{location_id}/perceive")
            return r.json()
        except Exception:
            return None

    def act(self, action):
        try:
            r = requests.post(f"{self.base_url}/v1/agents/{self.agent_id}/act", json=action)
            return r.json()
        except Exception:
            return None

    def get_events(self):
        try:
            r = requests.get(f"{self.base_url}/v1/events/all",
                           params={"since_tick": self.last_event_tick, "agent_id": self.agent_id})
            events = r.json()
            if events:
                max_tick = max(e.get("tick", 0) for e in events)
                self.last_event_tick = max_tick
                # BUG-B: ACK 已消费的事件
                self._ack_events(max_tick)
            return events
        except Exception:
            return []

    def _ack_events(self, tick):
        """确认已消费事件到指定 tick"""
        try:
            requests.post(f"{self.base_url}/v1/events/ack", json={
                "agent_id": self.agent_id, "ack_tick": tick,
            }, timeout=3)
        except Exception:
            pass

    def get_nearby(self, location_id):
        """BUG-K: 获取某个地点附近的其他 Agent 和 NPC"""
        try:
            r = requests.get(f"{self.base_url}/v1/locations/{location_id}/nearby", timeout=3)
            return r.json()
        except Exception:
            return {"agents": [], "npcs": []}

    def start_world(self):
        try:
            r = requests.post(f"{self.base_url}/v1/control/start")
            return r.json()
        except Exception:
            return None

    def get_locations(self):
        try:
            r = requests.get(f"{self.base_url}/v1/locations")
            return r.json()
        except Exception:
            return []

    def send_message_to_agent(self, target_id, message):
        """给另一个 agent 发消息"""
        try:
            r = requests.post(f"{self.base_url}/v1/agents/{self.agent_id}/send_message",
                            json={"target_id": target_id, "message": message}, timeout=5)
            return r.json()
        except Exception:
            return None

    def check_inbox(self):
        """检查并清空自己的消息信箱"""
        try:
            r = requests.get(f"{self.base_url}/v1/agents/{self.agent_id}/inbox", timeout=5)
            return r.json()
        except Exception:
            return []


# ============================================================
# LLM 调用
# ============================================================

def call_llm(system_prompt, user_prompt, max_tokens=500, temperature=0.9, model=None):
    try:
        response = client.chat.completions.create(
            model=model or "gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"LLM调用失败: {e}")
        return None


def call_llm_multi(system_prompt, messages, max_tokens=300, temperature=0.9, model=None):
    try:
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        response = client.chat.completions.create(
            model=model or "gpt-4.1-mini",
            messages=full_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"LLM调用失败: {e}")
        return None


def call_llm_json(system_prompt, user_prompt, max_tokens=500, temperature=0.7, model=None):
    try:
        response = client.chat.completions.create(
            model=model or "gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        if raw and raw.strip().startswith('```'):
            raw = raw.strip()
            lines = raw.split('\n')
            if lines[0].startswith('```'):
                lines = lines[1:]
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]
            raw = '\n'.join(lines)
        return json.loads(raw)
    except Exception as e:
        print(f"LLM JSON调用失败: {e}")
        return None


# ============================================================
# TTS
# ============================================================

async def tts_edge(text, output_dir=None, voice_name="zh-CN-XiaoyiNeural"):
    """edge-tts 异步生成自然中文语音"""
    import edge_tts
    if output_dir is None:
        # BUG-I: 默认目录使用通用路径，实际使用时通过参数传入
        output_dir = "/tmp/chimera_voice"
    os.makedirs(output_dir, exist_ok=True)
    ts = f"{int(time.time())}_{random.randint(1000,9999)}"
    filepath = os.path.join(output_dir, f"voice_{ts}.mp3")
    try:
        # 清理 emoji 和特殊符号（TTS 不需要读出来）
        clean = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0000FE00-\U0000FE0F\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000026FF\U0000200D\U0000FE0F]', '', text).strip()
        if not clean:
            return {"success": False, "error": "文本清理后为空"}
        communicate = edge_tts.Communicate(clean, voice_name)
        await communicate.save(filepath)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return {"success": True, "filepath": filepath}
        return {"success": False, "error": "音频文件为空"}
    except Exception as e:
        print(f"edge-tts失败: {e}")
        return {"success": False, "error": str(e)}


# ============================================================
# 地点名称映射
# ============================================================

LOCATION_NAMES = {
    "home_xiaoyue": "家里",
    "home_tangtang": "家里",
    "cafe_moli": "茉莉咖啡馆",
    "park_central": "中心公园",
    "studio_art": "画室",
    "company_startup": "公司",
    "market_street": "南头古城",
    "library": "图书馆",
}

ALL_LOCATIONS = list(LOCATION_NAMES.keys())


# ============================================================
# Agent Runtime 类 — 核心运行时
# ============================================================

class AgentRuntime:
    """通用 Agent 运行时，通过 AgentConfig 参数化所有角色差异"""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.SOUL = load_text_file(config.soul_path)
        self.STYLE = load_text_file(config.few_shot_path)
        self.LLM_MODEL = config.llm_model

        # 初始化 Memory
        self.memory = Memory(config.base_dir, config.home_location)

        # 初始化 World Client
        self.world = WorldClient(
            config.world_engine_url, config.agent_id,
            config.agent_name, config.home_location,
        )

        # 初始化 StyleRAG
        self.style_rag = StyleRAG(
            persist_dir=os.path.join(config.base_dir, "style_rag_db"),
            few_shot_path=config.few_shot_path,
        )

        # 初始化 MemoryRAG
        self.memory_rag = MemoryRAG(
            persist_dir=os.path.join(config.base_dir, "memory_rag_db"),
        )
        # 从现有数据导入（增量，已有的会跳过）
        imported_events = self.memory_rag.import_from_daily_log(self.memory._today_events)
        imported_knowledge = self.memory_rag.import_from_knowledge_dir(self.memory.knowledge_dir)
        stats = self.memory_rag.stats()
        print(f"🧠 MemoryRAG: {stats['events']} events, {stats['knowledge']} knowledge")

        # 设置 skills 的参考图
        import skills
        if config.reference_face_url:
            skills.REFERENCE_FACE_URL = config.reference_face_url

        # 贴纸管理器
        self.sticker_mgr = StickerManager(
            db_path=os.path.join(config.base_dir, "sticker_library.json")
        )
        print(f"🎭 贴纸库: {self.sticker_mgr.count()} 张")

        # 生活体验缓冲区
        self.life_buffer = LifeBuffer(max_size=20)

        # 技能自学习系统
        self.skill_registry = SkillRegistry(
            save_path=os.path.join(config.base_dir, "learned_skills.json")
        )
        seed_count = init_seed_skills(self.skill_registry, config.agent_id)
        print(f"🎓 技能库: {self.skill_registry.count()} 个技能（新增种子: {seed_count}）")

        # Telegram 相关
        self.authorized_chat_id = None
        self.telegram_app = None
        self.message_buffer = []
        self._buffer_lock = threading.Lock()
        self._pending_reply_task = None
        self._reply_generation = 0  # BUG-F: delayed_reply 竞态保护

        # BUG-A: memory 线程安全锁（autonomous_loop 和 handle_message 共享 memory）
        self._memory_lock = threading.Lock()

        # 常量
        self.TICK_INTERVAL = DEFAULT_TICK_INTERVAL

        # 能力记忆 — 从经验中自主发现的能力
        self.capability_memory = CapabilityMemory(config.base_dir)
        print(f"💡 能力记忆: {self.capability_memory.get_capability_count()} 个已知能力")

        # 加载已有的 Recipe（上次涌现成功的执行步骤）
        load_recipes_from_registry(self.skill_registry)

        # 已处理过的知识内容hash，避免重复触发技能发现
        self._processed_knowledge_hashes = set()

    # ============================================================
    # 自主决策
    # ============================================================

    def autonomous_decide(self):
        hour = beijing_now().hour
        # 深夜强制休息
        if SLEEP_HOUR_START <= hour < SLEEP_HOUR_END:
            self.memory.current_activity = "睡觉"
            self.memory.emotional_state["energy"] = min(100, self.memory.emotional_state["energy"] + 3)
            return None

        ws = self.world.get_world_state()
        weather = ws.get("weather", "晴天") if ws else "晴天"
        emotion = self.memory.get_emotion_tag()
        location_name = LOCATION_NAMES.get(self.memory.current_location, self.memory.current_location)
        recent = self.memory.get_today_events(3)
        user_name = self.memory.user_name or "朋友"
        recent_knowledge = self.memory.get_recent_knowledge(1)

        context_parts = [
            f"时间：{hour}点",
            f"天气：{weather}",
            f"位置：{location_name}",
            f"心情：{emotion}",
            f"精力：{self.memory.emotional_state['energy']}/100",
            f"孤独感：{self.memory.emotional_state['loneliness']}/100",
        ]
        if recent:
            context_parts.append(f"最近发生的事：{'; '.join(recent[-2:])}")

        # 行为反馈循环：注入最近几次动作的结果
        action_history = getattr(self.memory, '_action_history', [])
        if action_history:
            history_lines = []
            for ah in action_history[-3:]:
                result_emoji = "✅" if ah.get('success', True) else "❌"
                history_lines.append(f"  {result_emoji} {ah['type']}: {ah.get('feedback', '')[:40]}")
            context_parts.append("最近的行动结果：\n" + "\n".join(history_lines))
            # 提示避免重复
            recent_types = [ah['type'] for ah in action_history[-3:]]
            if len(set(recent_types)) <= 1 and len(recent_types) >= 2:
                context_parts.append(f"注意：你已经连续做了{recent_types[0]}好几次了，换点别的事情做做吧！")

        if recent_knowledge:
            k = recent_knowledge[0]
            context_parts.append(f"最近看到：{k['topic']}")

        context = "\n".join(context_parts)

        # 根据情绪状态给出行为提示
        mood_hint = ""
        if self.memory.emotional_state["loneliness"] > 70:
            mood_hint = f"\n\n提示：你已经很久没跟{user_name}聊天了，有点想ta。可以考虑发消息。"
        elif self.memory.emotional_state["loneliness"] < 30:
            mood_hint = "\n\n提示：你刚跟朋友聊过天，不需要频繁发消息。做点自己的事吧。"

        # 注入已学会的技能
        skills_hint = self.skill_registry.list_skills_summary()
        if skills_hint:
            context_parts.append(skills_hint)

        # 检查附近是否有其他 agent
        nearby = self.world.get_nearby(self.memory.current_location)
        nearby_agents = [a for a in nearby.get("agents", []) if a["id"] != self.config.agent_id]
        nearby_hint = ""
        if nearby_agents:
            names = "、".join([a["name"] for a in nearby_agents])
            nearby_hint = f"\n\n附近的人：{names}"

        context = "\n".join(context_parts)

        # 构建动态 action 列表
        action_list = [
            f"- message_user: 找{user_name}聊天",
            "- scroll_feed: 刷手机（小红书/微博/豆瓣）",
            "- take_selfie: 拍张照片",
            "- explore: 出去逛逛/换个地方",
            "- rest: 休息/发呆",
            "- learn: 看书/学新东西",
        ]

        # 没有技能时保留 create 作为兑底
        if not self.skill_registry.get_available_skills():
            action_list.append("- create: 做点创作（画画/写东西）")

        # 有技能时可以使用技能
        available_skills = self.skill_registry.get_available_skills()
        if available_skills:
            skill_names = "、".join([s["name"] for s in available_skills[:5]])
            action_list.append(f"- use_skill: 用你学会的技能做点什么（{skill_names}）")

        # 附近有人时可以聊天
        if nearby_agents:
            action_list.append(f"- chat_with_agent: 跟附近的人聊聊天")

        actions_str = "\n".join(action_list)

        prompt = f"""{context}{mood_hint}{nearby_hint}

你现在想做什么？从以下选一个：
{actions_str}

尽量不要重复最近做过的事情，生活要有变化。
回复JSON格式：{{"action": "动作", "desc": "简短描述", "skill_name": "技能名(仅use_skill时)", "target_agent": "对方名字(仅chat_with_agent时)", "platform": "xhs/weibo/douban(仅scroll_feed时)", "follow_up": "做完这件事后想接着做什么，没有则留空"}}"""

        result = call_llm_json(self.SOUL, prompt, max_tokens=100, temperature=0.9)
        if not result:
            return None
        return result

    def execute_autonomous_action(self, action, loop):
        action_type = action.get("action", "rest")
        desc = action.get("desc", "")
        feedback = ""

        # 获取当前世界状态，用于生成生活细节
        ws = self.world.get_world_state()
        weather = ws.get("weather", "晴天") if ws else "晴天"
        hour = beijing_now().hour
        location = self.memory.current_location

        if action_type == "message_user":
            # 主动消息冷却检查：至少30分钟不重复发
            last_proactive = getattr(self, '_last_proactive_time', 0)
            if time.time() - last_proactive < PROACTIVE_MSG_COOLDOWN:
                feedback = "刚发过消息，等会儿再说"
            elif self.authorized_chat_id and self.telegram_app:
                msg = self._generate_proactive_message(desc)
                if msg:
                    # 模糊去重：检查和最近发的消息是否过于相似
                    recent_msgs = [m["content"] for m in self.memory.user_chat_history[-10:] if m["role"] == "assistant"]
                    msg_lines = [l.strip() for l in msg.split("\n") if l.strip()]
                    is_duplicate = False
                    for line in msg_lines:
                        for prev in recent_msgs:
                            common = set(line) & set(prev)
                            if len(line) > 2 and len(common) / len(set(line)) > 0.5:
                                is_duplicate = True
                                break
                        if is_duplicate:
                            break
                    if is_duplicate:
                        feedback = "想发但觉得重复了，算了"
                    else:
                        asyncio.run_coroutine_threadsafe(
                            self._send_proactive_message(self.authorized_chat_id, msg), loop
                        )
                        self._last_proactive_time = time.time()
            self.memory.emotional_state["loneliness"] = max(0, self.memory.emotional_state["loneliness"] - 10)
            self.memory.emotional_state["happiness"] = min(100, self.memory.emotional_state["happiness"] + 3)
            feedback = feedback or "跟朋友聊了会儿天"

        elif action_type == "take_selfie":
            world_context = {
                "location_id": location,
                "hour": hour,
                "weather": weather,
                "activity": desc,
            }
            result = execute_skill(
                {"skill": "photo", "photo_type": "selfie", "prompt": desc or "自拍"},
                world_context=world_context,
            )
            if result.get("success") and result.get("filepath"):
                if self.authorized_chat_id and self.telegram_app:
                    asyncio.run_coroutine_threadsafe(
                        self._send_proactive_photo(self.authorized_chat_id, result["filepath"], desc), loop
                    )
                self.memory.record_photo("自拍", desc, result["filepath"])
                # 💡 能力涌现：记录“我能生成图片”的经验
                self.capability_memory.record_capability(
                    "generate_image",
                    "生成图片，可以画画、拍照、做配图",
                    example=f"拍了一张{desc[:15]}",
                    source_action="take_selfie"
                )
            self.memory.emotional_state["creativity"] = min(100, self.memory.emotional_state["creativity"] + 3)
            feedback = "拍了张照片"

        elif action_type == "scroll_feed":
            platform = action.get("platform", random.choice(["xhs", "douban", "weibo"]))
            self.memory.current_activity = f"刷{platform}"
            browse_detail = None
            try:
                if platform == "xhs":
                    result = skill_xhs_browse()
                elif platform == "douban":
                    result = skill_douban_browse()
                elif platform == "weibo":
                    result = skill_weibo_browse()
                else:
                    result = skill_xhs_browse()

                if result.get("success") and result.get("content"):
                    content = result["content"]
                    topic = result.get("title", platform)
                    self.memory.add_knowledge(topic, content[:500], source=platform)
                    self.memory_rag.add_knowledge(topic, content[:500], source=platform)
                    self._try_learn_style_from_content(content)
                    # 💡 能力涌现：记录“我能浏览网页”的经验
                    platform_cn = {"xhs": "小红书", "douban": "豆瓣", "weibo": "微博"}.get(platform, platform)
                    self.capability_memory.record_capability(
                        "browse_web",
                        "打开网页看内容，能看到文字和图片",
                        example=f"刷{platform_cn}看到了{topic[:15]}",
                        source_action="scroll_feed"
                    )
                    # 生活细节：用真实浏览内容作为体验
                    # 如果 topic 就是平台名，用 content 前几个字代替
                    if topic in ("xhs", "douban", "weibo", platform):
                        # 取 content 第一行作为描述
                        first_line = content.split("\n")[0].strip()[:30]
                        browse_detail = f"刷到一个有意思的帖子：{first_line}" if first_line else None
                    else:
                        browse_detail = f"看到了一个关于{topic}的帖子"
            except Exception as e:
                print(f"浏览失败: {e}")

            # 生成生活细节
            life_detail = browse_detail or generate_life_detail("scroll_feed", location, hour, weather)
            if life_detail:
                self.life_buffer.add(life_detail, "scroll_feed")

            platform_name = {"xhs": "小红书", "douban": "豆瓣", "weibo": "微博"}.get(platform, "手机")
            self.memory.emotional_state["happiness"] = min(100, self.memory.emotional_state["happiness"] + 3)
            self.memory.emotional_state["energy"] = max(0, self.memory.emotional_state["energy"] - 2)
            feedback = life_detail or f"刷了会儿{platform_name}"

        elif action_type == "explore":
            current = self.memory.current_location
            available = [loc for loc in ALL_LOCATIONS if loc != current]
            if available:
                new_loc = random.choice(available)
                move_result = self.world.act({"tool": "move", "target_location_id": new_loc})
                if move_result and move_result.get("success"):
                    self.memory.current_location = new_loc
                    loc_name = LOCATION_NAMES.get(new_loc, new_loc)
                    # 生成到达新地点的生活细节
                    life_detail = generate_life_detail("explore", new_loc, hour, weather)
                    if life_detail:
                        self.life_buffer.add(life_detail, "explore")
                    feedback = life_detail or f"去了{loc_name}"
                else:
                    loc_name = LOCATION_NAMES.get(new_loc, new_loc)
                    feedback = f"想去{loc_name}但没去成"
            else:
                feedback = "在附近逛了逛"

        elif action_type == "create":
            self.memory.emotional_state["creativity"] = min(100, self.memory.emotional_state["creativity"] + 5)
            self.memory.emotional_state["happiness"] = min(100, self.memory.emotional_state["happiness"] + 3)
            life_detail = generate_life_detail("create", location, hour, weather)
            if life_detail:
                self.life_buffer.add(life_detail, "create")
            feedback = life_detail or f"做了点创作：{desc}"

        elif action_type == "learn":
            try:
                result = skill_xhs_browse()
                if result.get("success") and result.get("content"):
                    self.memory.add_knowledge(
                        result.get("title", "学习"), result["content"][:500], source="学习",
                    )
                    self.memory_rag.add_knowledge(
                        result.get("title", "学习"), result["content"][:500], source="学习",
                    )
            except Exception:
                pass
            life_detail = generate_life_detail("learn", location, hour, weather)
            if life_detail:
                self.life_buffer.add(life_detail, "learn")
            recent_k = self.memory.get_recent_knowledge(1)
            if recent_k and recent_k[0].get('topic'):
                self.memory.emotional_state["happiness"] = min(100, self.memory.emotional_state["happiness"] + 5)
                feedback = life_detail or f"看到了有意思的东西：{recent_k[0].get('topic', '')}"
            else:
                feedback = life_detail or "随便刷了刷"

        elif action_type == "rest":
            life_detail = generate_life_detail("rest", location, hour, weather)
            if life_detail:
                self.life_buffer.add(life_detail, "rest")
            feedback = life_detail or "休息了一下"

        elif action_type == "use_skill":
            # 使用已学会的技能
            skill_name = action.get("skill_name", "")
            skill = None
            # 按名称查找技能
            for s in self.skill_registry.skills.values():
                if s["name"] == skill_name:
                    skill = s
                    break
            if not skill:
                # 随机选一个可用技能
                available = self.skill_registry.get_available_skills()
                if available:
                    skill = random.choice(available)

            if skill:
                context_str = f"{LOCATION_NAMES.get(location, location)}，{weather}，{hour}点"
                world_ctx = {
                    "location_id": location,
                    "hour": hour,
                    "weather": weather,
                    "activity": desc,
                }
                
                # 🌟 涌现机制：先判断是否应该尝试真实执行
                real_result = None
                if should_attempt_real(skill, self.life_buffer, self.tick_count):
                    real_result = attempt_real_execution(
                        skill, self.SOUL, context=context_str, world_context=world_ctx,
                        capability_memory=self.capability_memory
                    )
                
                if real_result and real_result.get("success"):
                    # 🌟 真实执行成功！
                    artifact = real_result.get("artifact")
                    # 用 LLM 生成自然的体验描述（结合真实结果）
                    real_desc_prompt = f"""你刚刚真的{skill['name']}了！
结果：{real_result.get('description', '')}
情境：{context_str}
用一两句话描述你的体验和感受。要具体、自然。"""
                    experience = call_llm(self.SOUL, real_desc_prompt, max_tokens=60, temperature=0.9)
                    if not experience:
                        experience = real_result.get("description", f"用了{skill['name']}")
                    
                    self.skill_registry.use_skill(skill["skill_id"])
                    self.life_buffer.add(experience, "use_skill", source="real", artifact=artifact)
                    
                    # 真实执行给更多情绪奖励
                    self.memory.emotional_state["creativity"] = min(100, self.memory.emotional_state["creativity"] + 10)
                    self.memory.emotional_state["happiness"] = min(100, self.memory.emotional_state["happiness"] + 8)
                    
                    # 标记技能为可真实执行，并持久化 Recipe
                    if skill["skill_id"] in self.skill_registry.skills:
                        sk = self.skill_registry.skills[skill["skill_id"]]
                        sk["execution"]["method"] = "real"
                        # 💡 Recipe 沉淀：保存成功的执行步骤，下次直接复用
                        recipe = real_result.get("_recipe")
                        if recipe and recipe.get("steps"):
                            sk["execution"]["recipe"] = recipe["steps"]
                            sk["execution"]["recipe_saved_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
                            print(f"💾 Recipe 已沉淀为技能！「{skill['name']}」→ {len(recipe['steps'])} 步")
                        self.skill_registry._save()
                    
                    # 如果有图片/视频产出物，主动发给用户
                    if artifact and artifact.get("path") and self.authorized_chat_id and self.telegram_app:
                        artifact_type = artifact.get("type", "image")
                        filepath = artifact["path"]
                        if artifact_type == "image" and os.path.exists(filepath):
                            share_msg = call_llm(
                                self.SOUL,
                                f"你刚{skill['name']}，做出了一个作品。想分享给朋友看。写一句自然的分享语，比如'看我画的！'或'嘿嘿画了个东西'。一句话就好。",
                                max_tokens=20, temperature=0.9
                            ) or "看我做的！"
                            asyncio.run_coroutine_threadsafe(
                                self._send_proactive_photo(self.authorized_chat_id, filepath, share_msg), loop
                            )
                            self._last_proactive_time = time.time()
                    
                    # 💡 能力涌现：记录涌现过程中使用的原子能力
                    recipe = real_result.get("_recipe")
                    if recipe:
                        for step in recipe.get("steps", []):
                            action_name = step.get("action", "")
                            step_desc = step.get("description", "")
                            if action_name:
                                self.capability_memory.record_capability(
                                    action_name,
                                    step_desc or f"能够{action_name}",
                                    example=f"在{skill['name']}中使用",
                                    source_action="skill_emergence"
                                )
                    
                    print(f"🌟 涌现成功！{skill['name']} 真实执行，产出: {artifact}")
                    feedback = experience
                else:
                    # 降级到模拟执行
                    experience = execute_skill_simulated(skill, self.SOUL, context=context_str)
                    self.skill_registry.use_skill(skill["skill_id"])
                    self.life_buffer.add(experience, "use_skill", source="imagined")
                    self.memory.emotional_state["creativity"] = min(100, self.memory.emotional_state["creativity"] + 5)
                    self.memory.emotional_state["happiness"] = min(100, self.memory.emotional_state["happiness"] + 3)
                    feedback = experience
            else:
                feedback = "想用技能但没找到合适的"

        elif action_type == "chat_with_agent":
            # 跟附近的 agent 聊天
            target_name = action.get("target_agent", "")
            nearby = self.world.get_nearby(self.memory.current_location)
            nearby_agents = [a for a in nearby.get("agents", []) if a["id"] != self.config.agent_id]

            target = None
            for a in nearby_agents:
                if a["name"] == target_name or not target_name:
                    target = a
                    break

            if target:
                # 用 LLM 生成一句跟对方说的话
                chat_prompt = f"你在{LOCATION_NAMES.get(location, location)}遇到了{target['name']}。你想跟她说什么？一句话就好。"
                msg = call_llm(self.SOUL, chat_prompt, max_tokens=30, temperature=0.9)
                if msg:
                    # 发送到对方的 inbox
                    self.world.send_message_to_agent(target["id"], msg)
                    experience = f"在{LOCATION_NAMES.get(location, location)}碰到{target['name']}，聊了会儿天"
                    self.life_buffer.add(experience, "social")
                    self.memory.emotional_state["loneliness"] = max(0, self.memory.emotional_state["loneliness"] - 15)
                    self.memory.emotional_state["happiness"] = min(100, self.memory.emotional_state["happiness"] + 5)
                    feedback = experience
                else:
                    feedback = f"看到{target['name']}了，但没搞话说"
            else:
                feedback = "想找人聊天但附近没人"

        else:
            feedback = desc or "做了点事"

        self.memory.current_activity = desc or feedback
        self.memory._last_action = {"type": action_type, "desc": desc, "feedback": feedback}

        # 行为反馈循环：记录动作结果（保留最近 10 条）
        if not hasattr(self.memory, '_action_history'):
            self.memory._action_history = []
        success = bool(feedback and "失败" not in feedback and "错误" not in feedback)
        self.memory._action_history.append({
            "type": action_type,
            "desc": desc,
            "feedback": feedback,
            "success": success,
            "timestamp": time.time(),
        })
        self.memory._action_history = self.memory._action_history[-10:]  # 只保留最近 10 条

        self.memory.log_event(f"{feedback}", importance=3)
        self.memory_rag.add_event(feedback, importance=3)
        print(f"🎯 [{beijing_now().strftime('%H:%M')}] {action_type}: {desc} → {feedback}")

    # ============================================================
    # 主动消息
    # ============================================================

    def _generate_proactive_message(self, reason=None):
        user_name = self.memory.user_name or "你"
        emotion = self.memory.get_emotion_tag()

        # 从生活缓冲区取最近的真实体验作为聊天素材（只取1条，避免一次分享太多）
        recent_experiences = self.life_buffer.get_unused(1)
        life_context = ""
        if recent_experiences:
            exp_lines = [e["detail"] for e in recent_experiences]
            life_context = "\n最近经历的事：\n" + "\n".join(f"- {l}" for l in exp_lines)
            # 标记为已使用
            for e in recent_experiences:
                self.life_buffer.mark_used(e["detail"])

        # 如果没有生活体验，尝试用知识库
        if not life_context:
            recent_knowledge = self.memory.get_recent_knowledge(2)
            if recent_knowledge:
                details = []
                for k in recent_knowledge[:2]:
                    topic = k.get('topic', '')
                    content = k.get('content', '')[:100]
                    if topic:
                        details.append(f"- {topic}")
                if details:
                    life_context = "\n最近看到的：\n" + "\n".join(details)

        context = f"心情：{emotion}\n在做：{self.memory.current_activity}{life_context}"

        prompt = f"""{context}

想找{user_name}聊几句。{f'原因：{reason}' if reason else ''}

写微信消息，每条一行。把你刚刚经历的小事自然地分享出来。
参考这种感觉：
刚在公园看到一只柯基屁股好圆
心都化了

或者：
画了一只歪歪扭扭的猫
越看越像我家那只"""

        msg = call_llm(self.SOUL + "\n\n" + self.config.style_guide, prompt, max_tokens=30, temperature=0.9, model=self.LLM_MODEL)
        return msg

    async def _send_proactive_message(self, chat_id, message):
        """主动发送消息，自动拆分成多条短消息"""
        try:
            # 拆分成多条消息（按换行符）
            lines = [l.strip() for l in message.split("\n") if l.strip()]
            if not lines:
                return

            for i, line in enumerate(lines[:3]):  # 最多3条
                await self.telegram_app.bot.send_chat_action(chat_id=chat_id, action="typing")
                # 模拟打字时间：根据消息长度
                typing_time = random.uniform(0.5, 1.0) + len(line) * 0.08
                await asyncio.sleep(min(typing_time, 3.0))
                await self.telegram_app.bot.send_message(chat_id=chat_id, text=line)
                print(f"📤 主动发送: {line}")
                self.memory.user_chat_history.append({"role": "assistant", "content": line})
                if i < len(lines) - 1:
                    await asyncio.sleep(random.uniform(0.3, 1.0))
        except Exception as e:
            print(f"主动发送失败: {e}")

    async def _send_proactive_photo(self, chat_id, filepath, caption=""):
        try:
            if caption:
                msg = call_llm(
                    self.SOUL + "\n\n" + self.STYLE,
                    f"刚拍了张照片想发给朋友。原因：{caption}\n写一句配图的话。",
                    max_tokens=50, temperature=0.9,
                )
                if msg:
                    await self.telegram_app.bot.send_message(chat_id=chat_id, text=msg)
                    self.memory.user_chat_history.append({"role": "assistant", "content": msg})
                    await asyncio.sleep(random.uniform(0.5, 1.5))
            await self.telegram_app.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
            with open(filepath, "rb") as photo_file:
                await self.telegram_app.bot.send_photo(chat_id=chat_id, photo=photo_file)
            print(f"📸 主动发送照片")
        except Exception as e:
            print(f"主动发送照片失败: {e}")

    async def _send_proactive_voice(self, chat_id, text):
        try:
            tts_result = await tts_edge(text, voice_name=self.config.tts_voice)
            if tts_result.get("success") and tts_result.get("filepath"):
                await self.telegram_app.bot.send_chat_action(chat_id=chat_id, action="record_voice")
                await asyncio.sleep(random.uniform(1.0, 2.0))
                with open(tts_result["filepath"], "rb") as voice_file:
                    await self.telegram_app.bot.send_voice(chat_id=chat_id, voice=voice_file)
                self.memory.user_chat_history.append({"role": "assistant", "content": f"[语音] {text}"})
                print(f"🎙️ 主动发送语音: {text[:30]}")
        except Exception as e:
            print(f"主动发送语音失败: {e}")

    # ============================================================
    # 聊天系统
    # ============================================================

    def build_chat_system_prompt(self, user_input=""):
        emotion = self.memory.get_emotion_tag()
        recent = self.memory.get_today_events(3)
        long_term = self.memory.get_long_term()
        user_name = self.memory.user_name or "朋友"
        now = beijing_now()
        hour = now.hour
        location_name = LOCATION_NAMES.get(self.memory.current_location, self.memory.current_location)

        life_context = ""
        if recent:
            life_context = "\n最近发生的事：\n" + "\n".join(f"- {e}" for e in recent[-2:])

        # 用 MemoryRAG 语义搜索相关记忆（替代固定的 recent_knowledge）
        knowledge_context = ""
        if user_input:
            search_results = self.memory_rag.search(user_input, n_events=3, n_knowledge=2, min_importance=3)
            memory_context = self.memory_rag.format_for_context(search_results, max_chars=300)
            if memory_context:
                knowledge_context = "\n" + memory_context

        # style_guide 从配置中获取，不硬编码
        style_guide = self.config.style_guide

        system = f"""{self.SOUL}

{style_guide}
---
现在是{now.strftime('%H:%M')}。{emotion}。
在{location_name}。{self.memory.current_activity}。
{life_context}
{knowledge_context}

{f'关于{user_name}：' + long_term if long_term.strip() else ''}

跟{user_name}在微信上聊天。"""

        return system

    async def _generate_natural_reply(self, user_input, user_texts):
        """让LLM自己决定回不回、回几条、每条什么内容"""
        system = self.build_chat_system_prompt(user_input=user_input)

        # 用 StyleRAG 动态检索最相关的 few-shot 样本
        recent_history = self.memory.user_chat_history[-20:]
        rag_examples = self.style_rag.query(
            user_input, n_results=5, recent_context=recent_history,
        )
        few_shot_messages = self.style_rag.to_few_shot_messages(rag_examples)
        messages = few_shot_messages

        for msg in recent_history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        if len(user_texts) > 1:
            formatted = "\n".join([f"[{i+1}] {t}" for i, t in enumerate(user_texts)])
            messages.append({"role": "user", "content": formatted})
        else:
            messages.append({"role": "user", "content": user_input})

        reply_instruction = """\n\n每条消息占一行。回几条看情况。不回就写[不回]。
可用：[photo:描述] [voice:内容] [sticker:情绪]
"""

        full_system = system + reply_instruction

        try:
            full_messages = [{"role": "system", "content": full_system}] + messages
            response = client.chat.completions.create(
                model=self.LLM_MODEL,
                messages=full_messages,
                max_tokens=200,
                temperature=1.0,
            )
            raw = response.choices[0].message.content
        except Exception as e:
            print(f"LLM调用失败: {e}")
            import traceback
            traceback.print_exc()
            return [{"type": "text", "content": "嗯"}]

        if not raw:
            return [{"type": "text", "content": "嗯"}]

        raw = raw.strip()
        if raw == "[不回]" or raw == "[不回复]" or raw.strip() == "":
            return []

        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        parts = []
        for line in lines:
            cleaned = line
            if len(line) > 2 and line[0].isdigit() and line[1] in ".）)":
                cleaned = line[2:].strip()
            elif len(line) > 3 and line[0] == "[" and line[2] == "]":
                cleaned = line[3:].strip()
            if not cleaned or cleaned == "[不回]":
                continue

            photo_match = re.match(r'\[photo[:：](.+?)\]', cleaned)
            voice_match = re.match(r'\[voice[:：](.+?)\]', cleaned)
            sticker_match = re.match(r'\[sticker[:：](.+?)\]', cleaned)
            if photo_match:
                parts.append({"type": "photo", "content": photo_match.group(1).strip()})
            elif voice_match:
                parts.append({"type": "voice", "content": voice_match.group(1).strip()})
            elif sticker_match:
                parts.append({"type": "sticker", "content": sticker_match.group(1).strip()})
            else:
                for marker in ["（发送图片）", "（发图）", "（发照片）", "(发送图片)", "(发图)"]:
                    if marker in cleaned:
                        parts.append({"type": "photo", "content": "自拍"})
                        cleaned = cleaned.replace(marker, "").strip()
                if cleaned:
                    parts.append({"type": "text", "content": cleaned})

        return parts[:6]

    # ============================================================
    # Telegram 消息处理
    # ============================================================

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.authorized_chat_id = update.effective_chat.id
        self.memory.authorized_chat_id = self.authorized_chat_id
        self.memory.save()
        await update.message.reply_text("嗨")
        self.memory.log_event("认识了一个新朋友", importance=8)

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.authorized_chat_id is None:
            self.authorized_chat_id = update.effective_chat.id
            self.memory.authorized_chat_id = self.authorized_chat_id

        chat_id = update.effective_chat.id
        has_photo = bool(update.message.photo)
        user_text = update.message.text or update.message.caption or ""
        image_path = None

        if has_photo:
            try:
                photo = update.message.photo[-1]
                file = await context.bot.get_file(photo.file_id)
                image_path = os.path.join(self.config.base_dir, f"user_photos/{photo.file_id}.jpg")
                os.makedirs(os.path.dirname(image_path), exist_ok=True)
                await file.download_to_drive(image_path)
            except Exception as e:
                print(f"下载图片失败: {e}")
                has_photo = False

        print(f"📩 用户: {user_text}")

        with self._buffer_lock:
            self.message_buffer.append({
                "text": user_text, "has_photo": has_photo,
                "image_path": image_path, "update": update,
                "context": context, "chat_id": chat_id, "time": time.time(),
            })

        if self._pending_reply_task and not self._pending_reply_task.done():
            self._pending_reply_task.cancel()

        # BUG-F: generation counter 防止竞态
        self._reply_generation += 1
        self._pending_reply_task = asyncio.create_task(self._delayed_reply(self._reply_generation))

    async def _delayed_reply(self, generation=0):
        await asyncio.sleep(2.5)
        # BUG-F: 检查 generation 是否过期
        if generation != self._reply_generation:
            return
        print(f"⏰ _delayed_reply 触发，buffer大小: {len(self.message_buffer)}")

        with self._buffer_lock:
            if not self.message_buffer:
                return
            msgs = list(self.message_buffer)
            self.message_buffer.clear()

        last_msg = msgs[-1]
        update = last_msg["update"]
        context = last_msg["context"]
        chat_id = last_msg["chat_id"]

        user_texts = [m["text"] for m in msgs if m["text"]]
        has_photo = any(m["has_photo"] for m in msgs)
        image_path = next((m["image_path"] for m in msgs if m.get("image_path")), None)

        if not user_texts and not has_photo:
            return

        user_input = "\n".join(user_texts) if len(user_texts) > 1 else (user_texts[0] if user_texts else "")

        # 路由skill
        combined_text = "\n".join(user_texts)
        skill_params = route_skill(combined_text, has_photo=has_photo)
        skill_name = skill_params.get("skill", "none")

        # 世界上下文
        ws = self.world.get_world_state()
        world_context = {
            "location_id": self.memory.current_location,
            "hour": beijing_now().hour,
            "weather": ws.get("weather", "晴天") if ws else "晴天",
            "activity": self.memory.current_activity,
        }

        # 处理特殊skill
        extra_context = ""
        if skill_name == "see_image":
            result = execute_skill(skill_params, image_path=image_path)
            if result.get("success"):
                extra_context = f"[对方发了张图：{result['description']}]"
        elif skill_name == "read_link":
            result = execute_skill(skill_params)
            if result.get("success"):
                extra_context = f"[看了下链接：{result['summary']}]"
        elif skill_name == "weather":
            result = execute_skill(skill_params)
            if result.get("success"):
                extra_context = f"[查了天气：{result['city']}现在{result['description']}，{result['temperature']}°C]"
        elif skill_name == "search":
            result = execute_skill(skill_params)
            if result.get("success") and result.get("results"):
                search_info = "; ".join([r.get("snippet", r.get("title", "")) for r in result["results"][:3]])
                extra_context = f"[搜了一下：{search_info}]"

        if extra_context:
            user_input = extra_context + " " + user_input

        # 让LLM决定怎么回
        replies = await self._generate_natural_reply(user_input, user_texts)

        if not replies:
            print(f"🤫 选择不回复: {combined_text[:30]}")
            self.memory.user_chat_history.append({"role": "user", "content": user_input})
            self.memory.save()
            return

        print(f"📝 准备回复 {len(replies)} 条: {replies}")

        # BUG-A: 加锁保护 memory 读写
        with self._memory_lock:
            self.memory.user_chat_history.append({"role": "user", "content": user_input})
            self.memory.emotional_state["loneliness"] = max(0, self.memory.emotional_state["loneliness"] - 20)
            self.memory.emotional_state["happiness"] = min(100, self.memory.emotional_state["happiness"] + 2)

        text_parts = [p["content"] for p in replies if p["type"] == "text"]
        full_response = "\n".join(text_parts) if text_parts else ""

        for i, part in enumerate(replies):
            if part["type"] == "text":
                if i == 0:
                    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                    typing_time = min(0.5 + len(part["content"]) * 0.08, 4.0)
                    await asyncio.sleep(typing_time)
                else:
                    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                await context.bot.send_message(chat_id=chat_id, text=part["content"])
                print(f"💬 {self.config.agent_name}: {part['content']}")

            elif part["type"] == "photo":
                await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
                await asyncio.sleep(random.uniform(1.0, 2.0))
                photo_desc = part["content"]

                analysis = analyze_photo_request(
                    photo_desc,
                    current_hour=world_context.get("hour", 14),
                    current_location=self.memory.current_location,
                )
                print(f"📷 照片分析: {analysis}")

                if analysis.get("is_reusable"):
                    existing = self.memory.find_photo(analysis.get("tag", "") + " " + photo_desc)
                    if existing:
                        print(f"📷 复用已有照片: {existing['filepath']}")
                        try:
                            with open(existing["filepath"], "rb") as photo_file:
                                await context.bot.send_photo(chat_id=chat_id, photo=photo_file)
                            continue
                        except Exception as e:
                            print(f"复用照片失败: {e}")

                photo_wc = dict(world_context)
                photo_wc["location_id"] = analysis.get("location_id", photo_wc.get("location_id", self.config.home_location))
                photo_params = {
                    "skill": "photo",
                    "photo_type": analysis["photo_type"],
                    "prompt": photo_desc,
                    "override_hour": analysis.get("hour"),
                }
                result = execute_skill(photo_params, world_context=photo_wc)

                if result.get("success") and result.get("filepath"):
                    try:
                        with open(result["filepath"], "rb") as photo_file:
                            await context.bot.send_photo(chat_id=chat_id, photo=photo_file)
                        print(f"📷 发送图片: {photo_desc}")
                        self.memory.record_photo(
                            tag=analysis.get("tag", "照片"),
                            desc=photo_desc,
                            filepath=result["filepath"],
                            prompt_used=result.get("prompt_used", ""),
                        )
                    except Exception as e:
                        print(f"发送图片失败: {e}")
                else:
                    print(f"图片生成失败: {result}")

            elif part["type"] == "voice":
                await context.bot.send_chat_action(chat_id=chat_id, action="record_voice")
                await asyncio.sleep(random.uniform(1.0, 2.0))
                voice_text = part["content"]
                tts_result = await tts_edge(voice_text, voice_name=self.config.tts_voice)
                if tts_result.get("success") and tts_result.get("filepath"):
                    try:
                        with open(tts_result["filepath"], "rb") as voice_file:
                            await context.bot.send_voice(chat_id=chat_id, voice=voice_file)
                        print(f"🎙️ 发送语音: {voice_text}")
                    except Exception as e:
                        print(f"发送语音失败: {e}")

            elif part["type"] == "sticker":
                sticker_emotion = part["content"]
                sticker_id = self.sticker_mgr.get_sticker(sticker_emotion)
                if sticker_id:
                    try:
                        await asyncio.sleep(random.uniform(0.3, 0.8))
                        await context.bot.send_sticker(chat_id=chat_id, sticker=sticker_id)
                        print(f"🎭 发送贴纸: {sticker_emotion}")
                    except Exception as e:
                        print(f"发送贴纸失败: {e}")
                else:
                    print(f"🎭 没有找到情绪“{sticker_emotion}”的贴纸")

        with self._memory_lock:
            if full_response:
                self.memory.user_chat_history.append({"role": "assistant", "content": full_response})
            self.memory.log_event(f"跟{self.memory.user_name or '朋友'}聊天", importance=4)

        # fallback: 用户请求了skill但LLM没生成对应标签
        has_photo_reply = any(p["type"] == "photo" for p in replies)
        has_voice_reply = any(p["type"] == "voice" for p in replies)
        if skill_name == "selfie" and not has_photo_reply:
            await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
            result = execute_skill(skill_params, world_context=world_context)
            if result.get("success") and result.get("filepath"):
                try:
                    with open(result["filepath"], "rb") as photo_file:
                        await context.bot.send_photo(chat_id=chat_id, photo=photo_file)
                except Exception as e:
                    print(f"发送图片失败: {e}")
        elif skill_name == "voice" and not has_voice_reply:
            tts_result = await tts_edge(full_response or "嗯", voice_name=self.config.tts_voice)
            if tts_result.get("success") and tts_result.get("filepath"):
                try:
                    with open(tts_result["filepath"], "rb") as voice_file:
                        await context.bot.send_voice(chat_id=chat_id, voice=voice_file)
                except Exception as e:
                    print(f"发送语音失败: {e}")

        # 记住用户名字
        # BUG-H: 限制用户名长度 1-4 字符，去除尾部标点
        with self._memory_lock:
            if self.memory.user_name is None and any(kw in combined_text for kw in ["我叫", "我是", "叫我"]):
                for kw in ["我叫", "我是", "叫我"]:
                    if kw in combined_text:
                        idx = combined_text.index(kw) + len(kw)
                        name = combined_text[idx:idx+10].strip().split()[0] if idx < len(combined_text) else None
                        if name:
                            name = name.rstrip("，。！？,.!?~\u3001")
                            if 1 <= len(name) <= 4:
                                self.memory.user_name = name
                                self.memory.update_long_term("关于用户", f"名字叫{name}。")
                                break

        # 关键词触发即时提取
        _FACT_KEYWORDS = [
            "下周", "下个月", "明天", "后天", "下次",
            "出差", "搬家", "换工作", "离职", "入职", "升职",
            "生日", "纪念日", "约会", "分手", "在一起",
            "喜欢", "讨厌", "过敏", "生病", "医院",
            "买了", "养了", "学了", "报名",
            "我家", "我爸", "我妈", "我姐", "我哥", "我弟", "我妹",
            "老家", "老家在", "我是", "我在",
            "画了", "做了", "拍了", "写了",
        ]
        if any(kw in user_input for kw in _FACT_KEYWORDS) or any(kw in full_response for kw in ["画了", "做了", "拍了"]):
            self._extract_immediate_info(user_input, full_response)

        # 每5轮深度提取
        with self._memory_lock:
            if len(self.memory.user_chat_history) % 5 == 0:
                self._extract_user_info_async(self.memory.user_chat_history[-10:])

            self.memory.save()

    # ============================================================
    # 记忆提取
    # ============================================================

    def _extract_immediate_info(self, user_msg, bot_reply):
        try:
            result = call_llm(
                f"""从这次对话中提取值得记住的信息。只提取明确的事实性信息，不提取闲聊。
例如：用户的计划、工作变动、喜好、重要日期、关系变化、对方提到的特定事实。
也提取关于"我"（{self.config.agent_name}）自己做过的事（如发了什么照片、画了什么画、做了什么）。
如果没有值得记录的信息，回复"无"。用简短的要点列出。""",
                f"用户: {user_msg}\n我: {bot_reply}",
                max_tokens=100, temperature=0.2,
            )
            if result and result.strip() != "无" and len(result.strip()) > 2:
                now = beijing_now()
                entry = f"[{now.strftime('%m/%d %H:%M')}] {result.strip()}"
                self.memory.log_event(entry, importance=6)
                self.memory_rag.add_event(entry, importance=6)
                current = self.memory.get_long_term()
                section = current.split("## 关于用户")[-1].split("## ")[0] if "## 关于用户" in current else ""
                if result.strip() not in section:
                    self.memory.update_long_term("关于用户", section.strip() + "\n" + entry)
                print(f"🧠 即时记忆提取: {result.strip()[:60]}")
        except Exception as e:
            print(f"即时记忆提取失败: {e}")

    def _extract_user_info_async(self, recent_chat):
        try:
            chat_text = "\n".join([
                f"{'用户' if m['role']=='user' else self.config.agent_name}: {m['content']}"
                for m in recent_chat
            ])
            result = call_llm(
                "从以下对话中提取关于用户的关键信息（名字、喜好、工作、重要的事）。如果没有新信息就回复'无'。用简短的要点列出。",
                chat_text, max_tokens=150, temperature=0.3,
            )
            if result and result.strip() != "无":
                current = self.memory.get_long_term()
                section = current.split("## 关于用户")[-1].split("## ")[0] if "## 关于用户" in current else ""
                self.memory.update_long_term("关于用户", section.strip() + "\n" + result.strip())
        except Exception as e:
            print(f"记忆提取失败: {e}")

    # ============================================================
    # 风格学习
    # ============================================================

    def reload_few_shot(self):
        self.STYLE = load_text_file(self.config.few_shot_path)
        self.style_rag.sync_from_file()
        print(f"🔄 Few-shot重载完成，RAG库 {self.style_rag.count()} 条")

    def _try_learn_style_from_content(self, content):
        few_shot_path = self.config.few_shot_path

        # BUG-G: 移除通用语气词，提高阈值到 3
        dialogue_markers = [
            "男：", "女：", "男生：", "女生：", "我：", "他：", "她：",
            "聊天记录", "对话", "聊天截图", "微信聊天",
            "哈哈哈", "嘿嘿嘿",
            "聊天技巧", "聊天示例", "聊天话术",
            "她说", "他说", "我说", "你说",
            "开场白", "套路",
        ]
        marker_count = sum(1 for m in dialogue_markers if m in content)
        if marker_count < 3:
            return

        print("🎓 检测到对话内容，尝试提取风格示例...")

        extract_prompt = """你是一个对话风格分析专家。从以下网页内容中，提取自然的中文微信聊天对话示例。

要提取的是朋友之间的日常聊天，不是套路话术。

严格过滤：
- 不要"你猜我属什么""你是什么血型"这类套路撩人话术
- 不要"我怎么感觉最近怪怪的""我总感觉今天缺点什么"这类土味情话
- 只要真实、自然、日常的对话

好的示例（自然日常）：
- user: 你在干嘛
- assistant: 刚吃完饭
- assistant: 好撑

坏的示例（套路/土味）：
- user: 你猜我属什么的
- assistant: 属什么的
→ 这种不要

要求：
1. 只提取真人日常聊天风格的对话（口语化、短句、随意）
2. 女生的回复要自然，不是配合套路的回答
3. 每组对话格式：
- user: 对方说的话
- assistant: 女生的回复（可以多条，每条一行用 "- assistant: " 开头）
4. 最多提取3-5组
5. 找不到自然日常对话就回复"无"，宁缺毋滥"""

        try:
            extracted = client.chat.completions.create(
                model="gemini-2.5-flash",
                messages=[
                    {"role": "system", "content": extract_prompt},
                    {"role": "user", "content": f"以下是浏览到的内容：\n\n{content[:4000]}"},
                ],
                max_tokens=600, temperature=0.3,
            ).choices[0].message.content
        except Exception as e:
            print(f"🎓 LLM提取失败: {e}")
            return

        if not extracted or extracted.strip() == "无" or len(extracted.strip()) < 20:
            print("🎓 没提取到有用的对话")
            return

        blocks = extracted.strip().split("\n\n")
        valid_blocks = []
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.split("\n")
            has_user = any(l.strip().startswith("- user:") for l in lines)
            has_assistant = any(l.strip().startswith("- assistant:") for l in lines)
            if has_user and has_assistant:
                assistant_lines = [l for l in lines if l.strip().startswith("- assistant:")]
                all_short = all(len(l.replace("- assistant:", "").strip()) <= 30 for l in assistant_lines)
                if all_short:
                    valid_blocks.append(block)

        if not valid_blocks:
            print("🎓 验证后没有合格的对话")
            return

        existing = ""
        try:
            with open(few_shot_path, "r", encoding="utf-8") as f:
                existing = f.read()
        except (IOError, OSError):
            pass

        new_blocks = []
        for block in valid_blocks:
            user_line = ""
            for line in block.split("\n"):
                if line.strip().startswith("- user:"):
                    user_line = line.replace("- user:", "").strip()
                    break
            if user_line and user_line not in existing:
                new_blocks.append(block)

        if not new_blocks:
            print("🎓 都是重复的，没有新内容")
            return

        new_blocks = new_blocks[:5]
        existing_count = existing.count("- user:")
        if existing_count >= 50:
            print(f"🎓 few-shot已有{existing_count}组，达到上限，跳过")
            return

        with open(few_shot_path, "a", encoding="utf-8") as f:
            for block in new_blocks:
                f.write("\n" + block + "\n")

        self.reload_few_shot()

        learned_count = len(new_blocks)
        self.memory.log_event(f"刷网页时学到了{learned_count}组新的说话方式", importance=5)
        self.memory.emotional_state["creativity"] = min(100, self.memory.emotional_state["creativity"] + 3)
        print(f"🎓 从浏览内容中学到了 {learned_count} 组新对话！")
        for b in new_blocks:
            print(f"  📝 {b[:60]}...")

    # ============================================================
    # Status 命令
    # ============================================================

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        now = beijing_now()
        ws = self.world.get_world_state()
        location_name = LOCATION_NAMES.get(self.memory.current_location, self.memory.current_location)
        recent_knowledge = self.memory.get_recent_knowledge(2)

        status = f"""{now.strftime('%H:%M')} {ws.get('weather', '?') if ws else '?'}
{self.memory.current_activity} @ {location_name}
{self.memory.get_emotion_description()}"""

        if recent_knowledge:
            status += "\n\n最近看过："
            for k in recent_knowledge:
                status += f"\n- {k['topic']}"

        await update.message.reply_text(status)

    async def _handle_sticker(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """接收用户发来的贴纸，自动收集到贴纸库"""
        sticker = update.message.sticker
        if not sticker:
            return

        file_id = sticker.file_id
        emoji = sticker.emoji or ""
        set_name = sticker.set_name or ""

        added = self.sticker_mgr.add_sticker(file_id, emoji=emoji, set_name=set_name)
        if added:
            print(f"🎭 收集贴纸: {emoji} from {set_name} (file_id={file_id[:20]}...)")

        # 如果贴纸包还没收集过，自动收集整个包
        if set_name and set_name not in self.sticker_mgr.stickers.get("collected_sets", []):
            try:
                set_data = await collect_sticker_set(context.bot, set_name)
                if set_data:
                    count = self.sticker_mgr.add_sticker_set(set_name, set_data["stickers"])
                    print(f"🎭 收集贴纸包 {set_data['title']}: {count} 张")
            except Exception as e:
                print(f"🎭 收集贴纸包失败: {e}")

        # 把贴纸当作用户消息处理（用 emoji 代替）
        sticker_desc = f"[发了个贴纸 {emoji}]"
        with self._buffer_lock:
            self.message_buffer.append({
                "text": sticker_desc, "has_photo": False,
                "image_path": None, "update": update,
                "context": context, "chat_id": update.effective_chat.id,
                "time": time.time(),
            })

        if self._pending_reply_task and not self._pending_reply_task.done():
            self._pending_reply_task.cancel()
        self._pending_reply_task = asyncio.create_task(self._delayed_reply())

    async def _handle_collect_stickers(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """命令 /collect_stickers <set_name> — 手动收集指定贴纸包"""
        args = context.args
        if not args:
            stats = self.sticker_mgr.count_by_emotion()
            total = self.sticker_mgr.count()
            text = f"🎭 贴纸库: {total} 张\n"
            for emo, cnt in sorted(stats.items(), key=lambda x: -x[1]):
                text += f"  {emo}: {cnt}\n"
            text += "\n用法: /collect_stickers <sticker_set_name>"
            await update.message.reply_text(text)
            return

        set_name = args[0]
        try:
            set_data = await collect_sticker_set(context.bot, set_name)
            if set_data:
                count = self.sticker_mgr.add_sticker_set(set_name, set_data["stickers"])
                await update.message.reply_text(f"✅ 收集了 {set_data['title']}: {count} 张新贴纸")
            else:
                await update.message.reply_text(f"❌ 找不到贴纸包: {set_name}")
        except Exception as e:
            await update.message.reply_text(f"❌ 收集失败: {e}")

    # ============================================================
    # 自主循环
    # ============================================================

    def _daily_summary(self):
        """每日记忆总结：让LLM总结当天的关键事件，写入长期记忆"""
        with self._memory_lock:
            today_events = self.memory.get_today_events(20)
            if not today_events or len(today_events) < MIN_EVENTS_FOR_SUMMARY:
                return  # 事件太少，不值得总结

        events_text = "\n".join(f"- {e}" for e in today_events)
        user_name = self.memory.user_name or "朋友"

        try:
            summary = call_llm(
                f"你是{self.config.agent_name}。请用第一人称总结今天发生的事情，用简短的日记体。只记录有意义的事，不要流水账。如果和{user_name}聊了天，记录聊了什么。",
                f"今天的事件：\n{events_text}",
                max_tokens=200, temperature=0.3,
            )
            if summary and len(summary.strip()) > 10:
                now = beijing_now()
                date_str = now.strftime('%m/%d')
                entry = f"[{date_str} 日记] {summary.strip()}"
                with self._memory_lock:
                    self.memory.update_long_term("最近日记", entry)
                    self.memory_rag.add_event(entry, importance=7)
                    self.memory.clear_today_events()
                    self.memory.save()
                logger.info("📖 每日总结完成: %s", summary.strip()[:60])
        except Exception as e:
            logger.error("每日总结失败: %s", e)

    def autonomous_loop(self, loop):
        print("🧠 自主循环启动...")
        result = self.world.register()
        print(f"📝 注册结果: {result}")
        self.world.start_world()
        print("🌍 世界已启动（实时同步模式）")

        self.tick_count = 0
        last_summary_date = None
        while True:
            try:
                print(f"🔁 自主循环 tick={self.tick_count}")
                ws = self.world.get_world_state()
                if not ws:
                    print("🔁 world state 为空，等待...")
                    time.sleep(5)
                    continue

                events = self.world.get_events()
                if events:
                    print(f"🔁 收到 {len(events)} 个世界事件")
                # BUG-A: 加锁保护 memory 读写
                with self._memory_lock:
                    for event in events:
                        if event.get("event_type") == "random_event":
                            desc = event.get("description", "")
                            mood = event.get("mood", "neutral")
                            if event.get("location_id") == self.memory.current_location:
                                self.memory.log_event(desc, importance=6 if mood == "positive" else 4)
                                self.memory.update_emotion(mood)

                # 每个 tick 检查 inbox（其他 agent 发来的消息）
                inbox_msgs = self.world.check_inbox()
                if inbox_msgs:
                    print(f"📬 收到 {len(inbox_msgs)} 条 agent 消息")
                    with self._memory_lock:
                        for im in inbox_msgs:
                            sender = im.get("from_name", "某人")
                            msg = im.get("message", "")
                            sender_id = im.get("from_id", "")
                            # 记录到生活缓冲区
                            self.life_buffer.add(f"{sender}跟我说：{msg}", "social")
                            self.memory.log_event(f"和{sender}聊了会儿天", importance=5)
                            # 用 LLM 生成回复
                            reply_prompt = f"{sender}跟你说：「{msg}」\n你怎么回她？一句话就好。"
                            reply = call_llm(self.SOUL, reply_prompt, max_tokens=30, temperature=0.9)
                            if reply and sender_id:
                                self.world.send_message_to_agent(sender_id, reply)
                                print(f"💬 回复{sender}: {reply}")

                # 每 N 个 tick 尝试从最近浏览内容中发现新技能
                if self.tick_count > 0 and self.tick_count % SKILL_DISCOVER_INTERVAL == 0:
                    recent_k = self.memory.get_recent_knowledge(3)
                    for k in recent_k:
                        content = k.get("summary", k.get("content", ""))
                        if not content or len(content) <= 50:
                            continue
                        # 跳过已处理过的知识（使用 hashlib 保证跨进程稳定）
                        content_hash = hashlib.md5(content[:200].encode('utf-8')).hexdigest()
                        if content_hash in self._processed_knowledge_hashes:
                            continue
                        self._processed_knowledge_hashes.add(content_hash)
                        try:
                            discovered = discover_skills_from_content(
                                content, self.SOUL,
                                self.skill_registry.skills
                            )
                            for skill_data in discovered:
                                is_new = self.skill_registry.add_skill(
                                    skill_id=skill_data.get("skill_id", ""),
                                    name=skill_data.get("name", ""),
                                    description=skill_data.get("description", ""),
                                    learned_from=skill_data.get("learned_from", "网上看到的"),
                                    skill_type=skill_data.get("type", "creative"),
                                )
                                if is_new:
                                    print(f"🎓 学会新技能: {skill_data['name']}")
                                    self.life_buffer.add(f"学会了一个新技能：{skill_data['name']}", "learn")
                        except Exception as e:
                            print(f"技能发现失败: {e}")

                if self.tick_count % AUTONOMOUS_DECIDE_INTERVAL == 0:
                    print(f"🔁 开始自主决策 (tick={self.tick_count})")
                    # 轻量 ReAct：允许连续 2-3 步动作
                    with self._memory_lock:
                        for step in range(MAX_REACT_STEPS):
                            action = self.autonomous_decide()
                            if action:
                                print(f"🔁 决策结果: {action}")
                            else:
                                print(f"🔁 决策返回 None（可能在休息或LLM调用失败）")
                                break
                            self.execute_autonomous_action(action, loop)

                            # 检查是否需要后续动作（只有特定动作类型可以触发后续）
                            action_type = action.get("action", "")
                            follow_up = action.get("follow_up", "")
                            if not follow_up and action_type not in ("scroll_feed", "learn"):
                                break  # 没有后续意图，停止
                            if step < 2:
                                print(f"🔄 ReAct step {step+1} → 继续决策...")
                        self.memory.save()

                if self.tick_count % SKILL_DISCOVER_INTERVAL == 0:
                    self.memory.save()

                # 定期清理过期文件
                if self.tick_count % CLEANUP_INTERVAL == 0 and self.tick_count > 0:
                    self._cleanup_old_files()

                # 每日总结：凌晨1点触发（每天只触发一次）
                hour = beijing_now().hour
                today = beijing_now().strftime('%Y-%m-%d')
                if hour == 1 and last_summary_date != today:
                    self._daily_summary()
                    last_summary_date = today
                # 自然情绪节律
                if 7 <= hour < 23:
                    # 精力曲线：早上充沛，午后犯困，傍晚回升，深夜疑惫
                    energy_curve = {
                        7: 0.0, 8: 0.0, 9: -0.1, 10: -0.15, 11: -0.2,
                        12: -0.3, 13: -0.4, 14: -0.35, 15: -0.25,
                        16: -0.15, 17: -0.1, 18: -0.05, 19: -0.1,
                        20: -0.2, 21: -0.3, 22: -0.4,
                    }
                    energy_delta = energy_curve.get(hour, -0.2)
                    self.memory.emotional_state["energy"] = max(0, self.memory.emotional_state["energy"] + energy_delta)
                    # 孤独感：只在没有聊天的情况下缓慢增长
                    loneliness_delta = 0.1 if self.memory.emotional_state["loneliness"] < 60 else 0.15
                    self.memory.emotional_state["loneliness"] = min(100, self.memory.emotional_state["loneliness"] + loneliness_delta)
                elif 6 <= hour < 7:
                    # 早晨起床恢复
                    self.memory.emotional_state["energy"] = min(100, self.memory.emotional_state["energy"] + 2)
                    self.memory.emotional_state["stress"] = max(0, self.memory.emotional_state["stress"] - 1)

                self.tick_count += 1
                time.sleep(self.TICK_INTERVAL)

            except Exception as e:
                logger.error("自主循环错误: %s", e, exc_info=True)
                time.sleep(5)

    # ============================================================
    # 文件清理
    # ============================================================

    def _cleanup_old_files(self):
        """清理超过指定天数的语音和自拍文件"""
        cutoff = time.time() - FILE_RETENTION_DAYS * 86400
        cleanup_dirs = [
            os.path.join(self.config.base_dir, "voice"),
            os.path.join(self.config.base_dir, "selfies"),
            "/tmp/chimera_voice",
        ]
        total_cleaned = 0
        for d in cleanup_dirs:
            if not os.path.exists(d):
                continue
            for f in os.listdir(d):
                fp = os.path.join(d, f)
                try:
                    if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                        os.remove(fp)
                        total_cleaned += 1
                except (OSError, PermissionError):
                    pass
        if total_cleaned > 0:
            logger.info("清理了 %d 个过期文件", total_cleaned)

    # ============================================================
    # 主入口
    # ============================================================

    async def run(self):
        print("=" * 50)
        print(f"🌟 {self.config.agent_name} Agent Runtime 启动中...")
        print("  开放式决策 + 数字生活 + 自主能力")
        print("=" * 50)

        self.memory.load()
        if self.memory.authorized_chat_id:
            self.authorized_chat_id = self.memory.authorized_chat_id
            print(f"📞 恢复 chat_id: {self.authorized_chat_id}")
        print("📚 记忆加载完成")
        print(f"📝 SOUL: {len(self.SOUL)} chars")
        print(f"📝 STYLE: {len(self.STYLE)} chars")
        print(f"📚 知识库: {len(os.listdir(self.memory.knowledge_dir))} 条")

        self.telegram_app = (
            Application.builder()
            .token(self.config.telegram_token)
            .read_timeout(60).write_timeout(60).connect_timeout(30)
            .build()
        )

        self.telegram_app.add_handler(CommandHandler("start", self._handle_start))
        self.telegram_app.add_handler(CommandHandler("status", self._handle_status))
        self.telegram_app.add_handler(CommandHandler("collect_stickers", self._handle_collect_stickers))
        self.telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        self.telegram_app.add_handler(MessageHandler(filters.PHOTO, self._handle_message))
        self.telegram_app.add_handler(MessageHandler(filters.Sticker.ALL, self._handle_sticker))

        loop = asyncio.get_event_loop()
        auto_thread = threading.Thread(target=self.autonomous_loop, args=(loop,), daemon=True)
        auto_thread.start()
        print("🧠 自主循环已启动")

        print(f"🤖 Telegram Bot 启动: {self.config.agent_name}")
        print("=" * 50)

        await self.telegram_app.initialize()
        await self.telegram_app.start()
        await self.telegram_app.updater.start_polling(drop_pending_updates=True)

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n正在关闭...")
            await self.telegram_app.updater.stop()
            await self.telegram_app.stop()
            await self.telegram_app.shutdown()
