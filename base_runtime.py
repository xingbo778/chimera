"""
Base Agent Runtime — 通用逻辑
所有角色共享此文件，角色差异通过 AgentConfig 注入。
"""

import os
import json
import time
import random
import asyncio
import threading
import requests
import re
from datetime import datetime, timezone, timedelta
from openai import OpenAI

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
    except:
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
        elif mood == "negative":
            self.emotional_state["happiness"] = max(0, self.emotional_state["happiness"] - 5)
            self.emotional_state["stress"] = min(100, self.emotional_state["stress"] + 5)
        self.emotional_state["energy"] = max(0, self.emotional_state["energy"] - 1)
        self.emotional_state["loneliness"] = min(100, self.emotional_state["loneliness"] + 1)

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
        except:
            print("🌍 WorldClient初始化，无法获取当前tick，从0开始")
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
        except:
            return None

    def perceive(self, location_id):
        try:
            r = requests.get(f"{self.base_url}/v1/locations/{location_id}/perceive")
            return r.json()
        except:
            return None

    def act(self, action):
        try:
            r = requests.post(f"{self.base_url}/v1/agents/{self.agent_id}/act", json=action)
            return r.json()
        except:
            return None

    def get_events(self):
        try:
            r = requests.get(f"{self.base_url}/v1/events/all",
                           params={"since_tick": self.last_event_tick})
            events = r.json()
            if events:
                self.last_event_tick = max(e.get("tick", 0) for e in events)
            return events
        except:
            return []

    def start_world(self):
        try:
            r = requests.post(f"{self.base_url}/v1/control/start")
            return r.json()
        except:
            return None

    def get_locations(self):
        try:
            r = requests.get(f"{self.base_url}/v1/locations")
            return r.json()
        except:
            return []


# ============================================================
# LLM 调用
# ============================================================

def call_llm(system_prompt, user_prompt, max_tokens=500, temperature=0.9, model=None):
    try:
        response = client.chat.completions.create(
            model=model or "gemini-2.5-flash",
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
            model=model or "gemini-2.5-flash",
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
            model=model or "gemini-2.5-flash",
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
    import edge_tts
    if output_dir is None:
        output_dir = "/home/ubuntu/chimera/voice"
    os.makedirs(output_dir, exist_ok=True)
    timestamp = int(time.time())
    filepath = os.path.join(output_dir, f"voice_{timestamp}.mp3")
    try:
        communicate = edge_tts.Communicate(text, voice_name)
        await communicate.save(filepath)
        return {"success": True, "filepath": filepath}
    except Exception as e:
        print(f"TTS失败: {e}")
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

        # Telegram 相关
        self.authorized_chat_id = None
        self.telegram_app = None
        self.message_buffer = []
        self._buffer_lock = threading.Lock()
        self._pending_reply_task = None

        # 常量
        self.TICK_INTERVAL = 60

    # ============================================================
    # 自主决策
    # ============================================================

    def autonomous_decide(self):
        hour = beijing_now().hour
        # 深夜强制休息（缩短范围，只有2-6点）
        if 2 <= hour < 6:
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

        if recent_knowledge:
            k = recent_knowledge[0]
            context_parts.append(f"最近看到：{k['topic']}")

        context = "\n".join(context_parts)

        # 孤独值高时强制提示
        loneliness_hint = ""
        if self.memory.emotional_state["loneliness"] > 70:
            loneliness_hint = f"\n\n提示：你已经很久没跟{user_name}聊天了，有点想ta。可以考虑发消息。"

        prompt = f"""{context}{loneliness_hint}

你现在想做什么？从以下选一个：
- message_user: 找{user_name}聊天
- scroll_feed: 刷手机（小红书/微博/豆瓣）
- take_selfie: 拍张照片
- explore: 出去逛逛/换个地方
- create: 做点创作（画画/写东西）
- rest: 休息/发呆
- learn: 看书/学东西

回复JSON格式：{{"action": "动作", "desc": "简短描述", "platform": "xhs/weibo/douban(仅scroll_feed时)", "follow_up": "做完这件事后想接着做什么，没有则留空"}}"""

        result = call_llm_json(self.SOUL, prompt, max_tokens=100, temperature=0.9)
        if not result:
            return None
        return result

    def execute_autonomous_action(self, action, loop):
        action_type = action.get("action", "rest")
        desc = action.get("desc", "")
        feedback = ""

        if action_type == "message_user":
            if self.authorized_chat_id and self.telegram_app:
                msg = self._generate_proactive_message(desc)
                if msg:
                    asyncio.run_coroutine_threadsafe(
                        self._send_proactive_message(self.authorized_chat_id, msg), loop
                    )
            self.memory.emotional_state["loneliness"] = max(0, self.memory.emotional_state["loneliness"] - 10)
            self.memory.emotional_state["happiness"] = min(100, self.memory.emotional_state["happiness"] + 3)
            feedback = "跟朋友聊了会儿天"

        elif action_type == "take_selfie":
            ws = self.world.get_world_state()
            world_context = {
                "location_id": self.memory.current_location,
                "hour": beijing_now().hour,
                "weather": ws.get("weather", "晴天") if ws else "晴天",
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
            self.memory.emotional_state["creativity"] = min(100, self.memory.emotional_state["creativity"] + 3)
            feedback = "拍了张照片"

        elif action_type == "scroll_feed":
            platform = action.get("platform", random.choice(["xhs", "douban", "weibo"]))
            self.memory.current_activity = f"刷{platform}"
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
            except Exception as e:
                print(f"浏览失败: {e}")

            platform_name = {"xhs": "小红书", "douban": "豆瓣", "weibo": "微博"}.get(platform, "手机")
            self.memory.emotional_state["happiness"] = min(100, self.memory.emotional_state["happiness"] + 3)
            self.memory.emotional_state["energy"] = max(0, self.memory.emotional_state["energy"] - 2)
            feedback = f"刷了会儿{platform_name}"

        elif action_type == "explore":
            current = self.memory.current_location
            available = [loc for loc in ALL_LOCATIONS if loc != current]
            if available:
                new_loc = random.choice(available)
                self.memory.current_location = new_loc
                loc_name = LOCATION_NAMES.get(new_loc, new_loc)
                feedback = f"去了{loc_name}"
            else:
                feedback = "在附近逛了逛"

        elif action_type == "create":
            self.memory.emotional_state["creativity"] = min(100, self.memory.emotional_state["creativity"] + 5)
            self.memory.emotional_state["happiness"] = min(100, self.memory.emotional_state["happiness"] + 3)
            feedback = f"做了点创作：{desc}"

        elif action_type == "learn":
            # 浏览学习内容
            try:
                result = skill_xhs_browse()
                if result.get("success") and result.get("content"):
                    self.memory.add_knowledge(
                        result.get("title", "学习"), result["content"][:500], source="学习",
                    )
                    self.memory_rag.add_knowledge(
                        result.get("title", "学习"), result["content"][:500], source="学习",
                    )
            except:
                pass
            recent_k = self.memory.get_recent_knowledge(1)
            if recent_k and recent_k[0].get('topic'):
                self.memory.emotional_state["happiness"] = min(100, self.memory.emotional_state["happiness"] + 5)
                feedback = f"看到了有意思的东西：{recent_k[0].get('topic', '')}"
            else:
                feedback = "随便刷了刷"

        elif action_type == "rest":
            feedback = "休息了一下"

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
        recent = self.memory.get_today_events(3)
        user_name = self.memory.user_name or "你"
        emotion = self.memory.get_emotion_tag()
        recent_knowledge = self.memory.get_recent_knowledge(1)

        context_parts = [f"心情：{emotion}", f"在做：{self.memory.current_activity}"]
        if recent:
            context_parts.append(f"最近：{'; '.join(recent[-2:])}")
        if recent_knowledge:
            k = recent_knowledge[0]
            context_parts.append(f"刚看到：{k['topic']} - {k['summary'][:60]}")

        context = "\n".join(context_parts)

        if reason:
            prompt = f"""{context}\n\n想跟{user_name}说：{reason}\n写一条微信消息。"""
        else:
            prompt = f"""{context}\n\n想找{user_name}聊几句。写一条微信消息。"""

        msg = call_llm(self.SOUL + "\n\n" + self.STYLE, prompt, max_tokens=100, temperature=0.9)
        return msg

    async def _send_proactive_message(self, chat_id, message):
        try:
            await self.telegram_app.bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(random.uniform(1.0, 3.0))
            await self.telegram_app.bot.send_message(chat_id=chat_id, text=message)
            print(f"📤 主动发送: {message}")
            self.memory.user_chat_history.append({"role": "assistant", "content": message})
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
你可以发图片或语音，用以下格式：
- [photo:描述] — 发一张照片，描述你想发的内容，比如 [photo:自拍] [photo:窗外的风景] [photo:我画的水彩]
- [voice:内容] — 发一条语音，比如 [voice:晚安啊]
可以混合使用，比如先发文字再发图：
给你看看我今天拍的
[photo:自拍]
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
            if photo_match:
                parts.append({"type": "photo", "content": photo_match.group(1).strip()})
            elif voice_match:
                parts.append({"type": "voice", "content": voice_match.group(1).strip()})
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

        self._pending_reply_task = asyncio.create_task(self._delayed_reply())

    async def _delayed_reply(self):
        await asyncio.sleep(2.5)
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
        if self.memory.user_name is None and any(kw in combined_text for kw in ["我叫", "我是", "叫我"]):
            for kw in ["我叫", "我是", "叫我"]:
                if kw in combined_text:
                    idx = combined_text.index(kw) + len(kw)
                    name = combined_text[idx:idx+10].strip().split()[0] if idx < len(combined_text) else None
                    if name and len(name) <= 5:
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

        dialogue_markers = [
            "男：", "女：", "男生：", "女生：", "我：", "他：", "她：",
            "聊天记录", "对话", "聊天截图", "微信聊天",
            "\u201c", "\u201d", "\u300c", "\u300d",
            "哈哈哈", "嘿嘿嘿", "喔喔", "啊啊",
            "回复", "聊天技巧", "聊天示例", "聊天话术",
            "她说", "他说", "我说", "你说",
            "开场白", "套路",
            "呢", "啦", "嘛", "啊", "呀",
        ]
        marker_count = sum(1 for m in dialogue_markers if m in content)
        if marker_count < 2:
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
        except:
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

    # ============================================================
    # 自主循环
    # ============================================================

    def _daily_summary(self):
        """每日记忆总结：让LLM总结当天的关键事件，写入长期记忆"""
        today_events = self.memory.get_today_events(20)
        if not today_events or len(today_events) < 3:
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
                self.memory.update_long_term("最近日记", entry)
                self.memory_rag.add_event(entry, importance=7)
                self.memory._today_events = []  # 清空当天事件，已总结
                self.memory.save()
                print(f"📖 每日总结完成: {summary.strip()[:60]}")
        except Exception as e:
            print(f"每日总结失败: {e}")

    def autonomous_loop(self, loop):
        print("🧠 自主循环启动...")
        result = self.world.register()
        print(f"📝 注册结果: {result}")
        self.world.start_world()
        print("🌍 世界已启动（实时同步模式）")

        tick_count = 0
        last_summary_date = None
        while True:
            try:
                ws = self.world.get_world_state()
                if not ws:
                    time.sleep(5)
                    continue

                events = self.world.get_events()
                for event in events:
                    if event.get("event_type") == "random_event":
                        desc = event.get("description", "")
                        mood = event.get("mood", "neutral")
                        if event.get("location_id") == self.memory.current_location:
                            self.memory.log_event(desc, importance=6 if mood == "positive" else 4)
                            self.memory.update_emotion(mood)

                if tick_count % 5 == 0:
                    # 轻量 ReAct：允许连续 2-3 步动作
                    for step in range(3):
                        action = self.autonomous_decide()
                        if not action:
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

                if tick_count % 10 == 0:
                    self.memory.save()

                # 每日总结：凌晨1点触发（每天只触发一次）
                hour = beijing_now().hour
                today = beijing_now().strftime('%Y-%m-%d')
                if hour == 1 and last_summary_date != today:
                    self._daily_summary()
                    last_summary_date = today
                if 7 <= hour < 23:
                    self.memory.emotional_state["energy"] = max(0, self.memory.emotional_state["energy"] - 0.5)
                    self.memory.emotional_state["loneliness"] = min(100, self.memory.emotional_state["loneliness"] + 0.3)

                tick_count += 1
                time.sleep(self.TICK_INTERVAL)

            except Exception as e:
                print(f"自主循环错误: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(5)

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
        self.telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        self.telegram_app.add_handler(MessageHandler(filters.PHOTO, self._handle_message))

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
