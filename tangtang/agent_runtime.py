"""
Agent Runtime - 糖糖 v1
开放式决策 + 数字生活 + 自主能力系统
"""

import os
import sys
import json
import time
import random
import asyncio
import threading
import requests
import re
from datetime import datetime, date, timezone, timedelta
from openai import OpenAI

# 添加父目录到路径，复用skills和browser_pool
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Skills
from skills import (
    skill_web_search, skill_fetch_url, skill_browser_fetch,
    skill_generate_selfie, skill_understand_image,
    skill_read_link, skill_text_to_speech, skill_get_weather,
    skill_generate_video, skill_xhs_browse, skill_douban_browse,
    skill_weibo_browse, route_skill, execute_skill,
)
import skills
# 覆盖脸部参考图为糖糖的
skills.REFERENCE_FACE_URL = "https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/ppjvnlFxEajcanTQ.png"

# ============================================================
# 配置
# ============================================================

WORLD_ENGINE_URL = "http://localhost:5000"
AGENT_ID = "tangtang"
AGENT_NAME = "糖糖"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN_TT", "8470327596:AAHuFjXkkiOtlxfVpGFUXPWOPS_CzuDsBCM")
TICK_INTERVAL = 60  # 60秒一个tick

# LLM
client = OpenAI()
LLM_MODEL = "gemini-2.5-flash"

BASE_DIR = "/home/ubuntu/chimera/tangtang"

# ============================================================
# 从文件加载 SOUL 和 STYLE
# ============================================================

def load_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return ""

SOUL = load_text_file(os.path.join(BASE_DIR, "SOUL.md"))
STYLE = load_text_file(os.path.join(BASE_DIR, "few_shot.md"))

# ============================================================
# 工具函数
# ============================================================

def beijing_now():
    return datetime.now(timezone.utc) + timedelta(hours=8)

# ============================================================
# Memory 系统 v3 —— 增加知识库
# ============================================================

class Memory:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.memory_dir = os.path.join(base_dir, "memory")
        self.knowledge_dir = os.path.join(base_dir, "knowledge")
        self.long_term_path = os.path.join(base_dir, "MEMORY.md")
        os.makedirs(self.memory_dir, exist_ok=True)
        os.makedirs(self.knowledge_dir, exist_ok=True)

        self.emotional_state = {
            "happiness": 55,
            "energy": 65,
            "stress": 35,
            "loneliness": 45,
            "creativity": 50,
        }
        self.current_activity = "刚醒来"
        self.current_location = "home_tangtang"
        self.user_chat_history = []
        self.pending_stories = []
        self.user_name = None
        self.relationships = {}
        self._today_events = []
        # 数字生活：最近看过/学过的东西
        self.recent_browsing = []  # [{topic, summary, source, time}]
        self.interests_queue = []  # 想搜/想看的东西

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
            "time": now.isoformat(),
            "event": event_text,
            "importance": importance,
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
        """保存学到的知识"""
        now = beijing_now()
        filename = f"{now.strftime('%Y%m%d_%H%M')}_{topic[:20].replace(' ', '_')}.md"
        filepath = os.path.join(self.knowledge_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {topic}\n\n")
            f.write(f"来源: {source}\n")
            f.write(f"时间: {now.strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write(content + "\n")
        self.recent_browsing.append({
            "topic": topic,
            "summary": content[:200],
            "source": source,
            "time": now.isoformat(),
        })
        # 只保留最近20条
        self.recent_browsing = self.recent_browsing[-20:]

    def get_recent_knowledge(self, n=3):
        """获取最近学到的东西"""
        return self.recent_browsing[-n:]

    def search_knowledge(self, query, max_results=3):
        """搜索知识库"""
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
        h = self.emotional_state["happiness"]
        e = self.emotional_state["energy"]
        s = self.emotional_state["stress"]
        l = self.emotional_state["loneliness"]
        if e < 25: return "很累"
        if s > 70: return "压力大"
        if h > 75: return "心情很好"
        if h < 30: return "心情低落"
        if l > 75: return "有点孤独"
        return "平常"

    def get_emotion_description(self):
        h = self.emotional_state["happiness"]
        e = self.emotional_state["energy"]
        s = self.emotional_state["stress"]
        l = self.emotional_state["loneliness"]
        parts = []
        if h > 70: parts.append("心情很好")
        elif h > 40: parts.append("心情还行")
        else: parts.append("心情有点低落")
        if e < 30: parts.append("有点累")
        if s > 60: parts.append("压力有点大")
        if l > 70: parts.append("有点想找人聊天")
        return "，".join(parts) if parts else "状态平平"

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
            self.current_location = data.get("current_location", "home_tangtang")
            self.user_chat_history = data.get("user_chat_history", [])
            self.pending_stories = data.get("pending_stories", [])
            self.user_name = data.get("user_name", None)
            self.relationships = data.get("relationships", {})
            self._today_events = data.get("_today_events", [])
            self.recent_browsing = data.get("recent_browsing", [])
            self.interests_queue = data.get("interests_queue", [])


memory = Memory(BASE_DIR)

# ============================================================
# World Engine 客户端
# ============================================================

class WorldClient:
    def __init__(self, base_url):
        self.base_url = base_url
        # 初始化时获取当前tick，避免重启后拉取所有历史事件
        self.last_event_tick = self._get_current_tick()

    def _get_current_tick(self):
        """获取world engine当前tick，重启时从当前开始而非从0"""
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
                "agent_id": AGENT_ID, "name": AGENT_NAME, "start_location": "home_tangtang",
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
            r = requests.post(f"{self.base_url}/v1/agents/{AGENT_ID}/act", json=action)
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


world = WorldClient(WORLD_ENGINE_URL)

# ============================================================
# LLM 调用
# ============================================================

def call_llm(system_prompt, user_prompt, max_tokens=500, temperature=0.9):
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
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


def call_llm_multi(system_prompt, messages, max_tokens=300, temperature=0.9):
    try:
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=full_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"LLM调用失败: {e}")
        return None


def call_llm_json(system_prompt, user_prompt, max_tokens=500, temperature=0.7):
    """调用LLM并期望返回JSON"""
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        # gemini有时会用```json ... ```包裹
        if raw and raw.strip().startswith('```'):
            raw = raw.strip()
            # 去掉开头的```json和结尾的```
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
# TTS (edge-tts)
# ============================================================

async def tts_edge(text, output_dir="/home/ubuntu/chimera/voice"):
    import edge_tts
    os.makedirs(output_dir, exist_ok=True)
    timestamp = int(time.time())
    filepath = os.path.join(output_dir, f"voice_{timestamp}.mp3")
    try:
        communicate = edge_tts.Communicate(text, "zh-CN-XiaoyiNeural")
        await communicate.save(filepath)
        return {"success": True, "filepath": filepath}
    except Exception as e:
        print(f"TTS失败: {e}")
        return {"success": False, "error": str(e)}


# ============================================================
# 地点名称映射
# ============================================================

LOCATION_NAMES = {
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
# 开放式自主决策系统
# ============================================================

def build_life_context():
    """构建当前生活上下文"""
    now = beijing_now()
    hour = now.hour
    ws = world.get_world_state()
    weather = ws.get("weather", "晴天") if ws else "晴天"
    location_name = LOCATION_NAMES.get(memory.current_location, memory.current_location)
    recent = memory.get_today_events(5)
    recent_knowledge = memory.get_recent_knowledge(2)
    emotion = memory.get_emotion_tag()

    ctx = f"""现在是{now.strftime('%H:%M')}，{weather}。
你在{location_name}。{emotion}。
精力：{memory.emotional_state['energy']}/100。

今天做过的事：
{chr(10).join('- ' + e for e in recent) if recent else '- 还没做什么'}"""

    if recent_knowledge:
        ctx += "\n\n最近看过/学过的：\n"
        for k in recent_knowledge:
            ctx += f"- {k['topic']}（{k.get('source', '')}）\n"

    if memory.interests_queue:
        ctx += f"\n想看的东西：{', '.join(memory.interests_queue[:3])}"

    user_name = memory.user_name
    if user_name:
        ctx += f"\n\n朋友{user_name}的信息：\n"
        lt = memory.get_long_term()
        if "## 关于用户" in lt:
            user_section = lt.split("## 关于用户")[1].split("## ")[0].strip()
            if user_section and user_section != "（还不了解）":
                ctx += user_section

    return ctx


def autonomous_decide():
    """
    完全开放的自主决策。
    返回一个action字典：{type, ...具体参数}
    type可以是：
    - "physical": 物理世界活动（移动、做事）
    - "browse": 上网浏览/搜索
    - "message_user": 主动给用户发消息
    - "selfie": 自拍
    - "voice": 发语音
    - "rest": 休息/睡觉
    - "think": 思考/发呆
    """
    life_ctx = build_life_context()
    now = beijing_now()
    hour = now.hour

    # 深夜强制睡觉（0-6点）
    if 0 <= hour < 7:
        memory.current_activity = "睡觉"
        memory.emotional_state["energy"] = min(100, memory.emotional_state["energy"] + 3)
        return {"type": "rest", "desc": "睡觉"}

    # 获取上次action的反馈
    last = getattr(memory, '_last_action', None)
    last_feedback = ""
    if last:
        last_feedback = f"\n\n你刚才在{last['desc']}。感觉：{last['feedback']}。"
        # 如果连续发呆，强调无聊
        if last['type'] == 'activity' and '无聊' in last.get('feedback', ''):
            last_feedback += "\n（你已经发呆一阵子了，是不是该做点别的？刷刷手机、出去走走、或者找朋友聊聊？）"

    system = f"""{SOUL}

你是一个活生生的人。现在你要决定接下来做什么。{last_feedback}

你可以做的事情：
1. 去某个地方（家里、咖啡馆、公园、画室、公司、南头古城、图书馆）
2. 在当前地方做事（画画、工作、看书、吃东西、追剧...）
3. 上网（刷小红书、看B站视频、搜水彩教程、看新闻、逛豆瓣、搜好吃的餐厅、刷聊天记录...）
4. 给朋友发消息（分享有趣的事、聊天、发照片、发语音）
5. 休息、散步、听音乐
6. 任何你想做的事

注意：不要一直做同样的事！如果刚才在发呆就换个事做。生活要有变化。

用JSON回复，格式：
{{"type": "类型", "desc": "简短描述你在做什么", ...其他参数}}

type的值：
- "move": 去某个地方。加 "location": "地点id"
- "activity": 在当前地方做事。
- "browse": 上网搜东西。加 "query": "搜什么"
- "scroll_feed": 刷社交媒体（小红书/豆瓣/微博）。加 "platform": "xhs"/"douban"/"weibo", "keyword": "可选关键词"
- "message_user": 想找朋友聊天。加 "reason": "为什么想聊"
- "selfie": 想拍张照。加 "reason": "为什么想拍"
- "voice": 想发语音。加 "text": "想说什么"
- "rest": 休息。

地点id: home_tangtang, cafe_moli, park_central, studio_art, company_startup, market_street, library"""

    result = call_llm_json(system, life_ctx, max_tokens=200, temperature=1.0)

    if not result:
        return {"type": "activity", "desc": "发呆"}

    return result


def execute_autonomous_action(action, loop):
    """执行自主决策的结果"""
    action_type = action.get("type", "activity")
    desc = action.get("desc", "")

    if action_type == "move":
        target = action.get("location", "")
        if target in ALL_LOCATIONS and target != memory.current_location:
            memory.current_location = target
            world.act({"tool": "move", "target_location_id": target})
            location_name = LOCATION_NAMES.get(target, target)
            memory.current_activity = f"去{location_name}"
            memory.log_event(f"去了{location_name}", importance=3)
            print(f"🚶 移动到 {location_name}")
        else:
            memory.current_activity = desc or "在路上"

    elif action_type == "browse":
        query = action.get("query", "")
        if query:
            print(f"🌐 上网搜索: {query}")
            full_content = ""  # 收集所有抓取到的内容
            try:
                result = skill_web_search(query)
                if result.get("success") and result.get("results"):
                    # 提取搜索结果摘要
                    snippets = []
                    for r in result["results"][:5]:
                        snippet = r.get("snippet", r.get("title", ""))
                        if snippet:
                            snippets.append(snippet)

                    if snippets:
                        search_summary = "\n".join(snippets)
                        full_content += search_summary

                        # 尝试抓取第一个可用的URL获取更多内容
                        urls = [r.get("url", "") for r in result["results"][:3] if r.get("url")]
                        for url in urls:
                            try:
                                page = skill_fetch_url(url, max_chars=3000)
                                if page.get("success") and page.get("content") and len(page["content"]) > 100:
                                    full_content += f"\n---\n{page['content']}"
                                    print(f"  📄 抓取了: {url[:60]}")
                                    break
                            except:
                                continue

                        # 让LLM从搜索结果中提取有用信息
                        knowledge = call_llm(
                            "从以下搜索结果中提取有用的信息，用2-3句话总结。如果没什么有用的就说'没什么有用的'。",
                            f"搜索：{query}\n\n结果：\n{search_summary}",
                            max_tokens=150, temperature=0.3,
                        )

                        if knowledge and "没什么有用" not in knowledge:
                            memory.add_knowledge(query, knowledge, source="网上搜的")
                            memory.log_event(f"上网搜了「{query}」", importance=4)
                            print(f"📚 学到: {knowledge[:80]}...")
                        else:
                            memory.log_event(f"搜了「{query}」但没什么有用的", importance=2)
                    else:
                        memory.log_event(f"搜了「{query}」没搜到什么", importance=2)
                else:
                    memory.log_event(f"搜了「{query}」没搜到什么", importance=2)
            except Exception as e:
                print(f"搜索失败: {e}")
                memory.log_event(f"想搜「{query}」但网不好", importance=2)

            # 通用学习机制：从浏览内容中自动检测并提取对话风格
            if full_content and len(full_content) > 200:
                try:
                    _try_learn_style_from_content(full_content)
                except Exception as e:
                    print(f"风格学习异常: {e}")

            memory.current_activity = desc or f"在看关于{query}的东西"

    elif action_type == "scroll_feed":
        platform = action.get("platform", "xhs")
        keyword = action.get("keyword", None)
        platform_names = {"xhs": "小红书", "douban": "豆瓣", "weibo": "微博"}
        platform_name = platform_names.get(platform, platform)
        print(f"📱 刷{platform_name}: {keyword or '随便看看'}")

        try:
            if platform == "xhs":
                result = skill_xhs_browse(keyword)
            elif platform == "douban":
                result = skill_douban_browse(keyword)  # keyword这里当group_id用
            elif platform == "weibo":
                result = skill_weibo_browse(keyword)
            else:
                result = skill_xhs_browse(keyword)

            if result.get("success") and result.get("content"):
                content = result["content"]
                # 存知识库
                knowledge = call_llm(
                    "从以下社交媒体内容中提取有趣的信息，用2-3句话总结。如果没什么有用的就说'没什么有用的'。",
                    f"平台: {platform_name}\n内容:\n{content[:2000]}",
                    max_tokens=150, temperature=0.3,
                )
                if knowledge and "没什么有用" not in knowledge:
                    memory.add_knowledge(f"刷{platform_name}", knowledge, source=platform_name)
                    memory.log_event(f"刷了会儿{platform_name}", importance=3)
                    print(f"📚 看到: {knowledge[:80]}...")
                else:
                    memory.log_event(f"刷了会儿{platform_name}，没看到什么有趣的", importance=2)

                # 通用风格学习：从浏览内容中自动提取对话风格
                if len(content) > 200:
                    try:
                        _try_learn_style_from_content(content)
                    except Exception as e:
                        print(f"风格学习异常: {e}")
            else:
                error = result.get("error", "没加载出来")
                memory.log_event(f"想刷{platform_name}但{error}", importance=2)
                print(f"刷{platform_name}失败: {error}")

        except Exception as e:
            print(f"刷{platform_name}异常: {e}")
            memory.log_event(f"想刷{platform_name}但网不好", importance=2)

        memory.current_activity = desc or f"在刷{platform_name}"

    elif action_type == "message_user":
        reason = action.get("reason", "")
        if authorized_chat_id and telegram_app:
            msg = generate_proactive_message(reason)
            if msg:
                asyncio.run_coroutine_threadsafe(
                    send_proactive_message(telegram_app, authorized_chat_id, msg),
                    loop
                )
                memory.log_event(f"给{memory.user_name or '朋友'}发了消息", importance=4)

    elif action_type == "selfie":
        if authorized_chat_id and telegram_app:
            ws = world.get_world_state()
            world_context = {
                "location_id": memory.current_location,
                "hour": beijing_now().hour,
                "weather": ws.get("weather", "晴天") if ws else "晴天",
                "activity": memory.current_activity,
            }
            result = skill_generate_selfie("casual", world_context=world_context)
            if result.get("success") and result.get("filepath"):
                asyncio.run_coroutine_threadsafe(
                    send_proactive_photo(telegram_app, authorized_chat_id,
                                        result["filepath"], action.get("reason", "")),
                    loop
                )
                memory.log_event("拍了张照片发给朋友", importance=5)

    elif action_type == "voice":
        voice_text = action.get("text", "")
        if voice_text and authorized_chat_id and telegram_app:
            asyncio.run_coroutine_threadsafe(
                send_proactive_voice(telegram_app, authorized_chat_id, voice_text),
                loop
            )
            memory.log_event("发了条语音给朋友", importance=4)

    elif action_type == "rest":
        memory.current_activity = desc or "休息"
        memory.emotional_state["energy"] = min(100, memory.emotional_state["energy"] + 5)

    else:
        # activity 或其他
        memory.current_activity = desc or "在做自己的事"

    if desc and action_type not in ("rest", "move"):
        memory.current_activity = desc
        importance = 3
        if any(kw in desc for kw in ["完成", "发现", "遇到", "第一次", "特别", "画"]):
            importance = 6
        memory.log_event(desc, importance)

    # === 情绪反馈：action执行后的感受 ===
    feedback = ""
    if action_type == "activity":
        boring_words = ["发呆", "无聊", "躺", "什么都不想"]
        if any(w in desc for w in boring_words):
            memory.emotional_state["loneliness"] = min(100, memory.emotional_state["loneliness"] + 5)
            memory.emotional_state["energy"] = max(0, memory.emotional_state["energy"] - 2)
            feedback = "有点无聊"
        else:
            memory.emotional_state["happiness"] = min(100, memory.emotional_state["happiness"] + 2)
            feedback = "还行"
    elif action_type == "browse":
        # 检查是否有新知识被添加
        recent_k = memory.get_recent_knowledge(1)
        if recent_k and recent_k[0].get('topic'):
            memory.emotional_state["happiness"] = min(100, memory.emotional_state["happiness"] + 5)
            feedback = f"看到了有意思的东西：{recent_k[0].get('topic', '')}"
        else:
            feedback = "随便刷了刷"
    elif action_type == "scroll_feed":
        platform_name = {"xhs": "小红书", "douban": "豆瓣", "weibo": "微博"}.get(action.get("platform", ""), "手机")
        memory.emotional_state["happiness"] = min(100, memory.emotional_state["happiness"] + 3)
        memory.emotional_state["energy"] = max(0, memory.emotional_state["energy"] - 2)
        feedback = f"刷了会儿{platform_name}"
    elif action_type == "message_user":
        memory.emotional_state["loneliness"] = max(0, memory.emotional_state["loneliness"] - 10)
        memory.emotional_state["happiness"] = min(100, memory.emotional_state["happiness"] + 3)
        feedback = "跟朋友聊了会儿天"
    elif action_type == "rest":
        feedback = "休息了一下"

    # 记录上次action和反馈，供下次决策用
    memory._last_action = {"type": action_type, "desc": desc, "feedback": feedback}

    print(f"🎯 [{beijing_now().strftime('%H:%M')}] {action_type}: {desc} → {feedback}")


# ============================================================
# 主动联系用户
# ============================================================

def generate_proactive_message(reason=None):
    recent = memory.get_today_events(3)
    user_name = memory.user_name or "你"
    emotion = memory.get_emotion_tag()
    recent_knowledge = memory.get_recent_knowledge(1)

    context_parts = [f"心情：{emotion}", f"在做：{memory.current_activity}"]
    if recent:
        context_parts.append(f"最近：{'; '.join(recent[-2:])}")
    if recent_knowledge:
        k = recent_knowledge[0]
        context_parts.append(f"刚看到：{k['topic']} - {k['summary'][:60]}")

    context = "\n".join(context_parts)

    if reason:
        prompt = f"""{context}

想跟{user_name}说：{reason}
写一条微信消息。"""
    else:
        prompt = f"""{context}

想找{user_name}聊几句。写一条微信消息。"""

    msg = call_llm(SOUL + "\n\n" + STYLE, prompt, max_tokens=100, temperature=0.9)
    return msg


async def send_proactive_message(app, chat_id, message):
    try:
        await app.bot.send_chat_action(chat_id=chat_id, action="typing")
        await asyncio.sleep(random.uniform(1.0, 3.0))
        await app.bot.send_message(chat_id=chat_id, text=message)
        print(f"📤 主动发送: {message}")
        memory.user_chat_history.append({"role": "assistant", "content": message})
    except Exception as e:
        print(f"主动发送失败: {e}")


async def send_proactive_photo(app, chat_id, filepath, caption=""):
    try:
        # 先发一条文字（如果有caption）
        if caption:
            msg = call_llm(SOUL + "\n\n" + STYLE,
                          f"刚拍了张照片想发给朋友。原因：{caption}\n写一句配图的话。",
                          max_tokens=50, temperature=0.9)
            if msg:
                await app.bot.send_message(chat_id=chat_id, text=msg)
                memory.user_chat_history.append({"role": "assistant", "content": msg})
                await asyncio.sleep(random.uniform(0.5, 1.5))

        await app.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
        with open(filepath, "rb") as photo_file:
            await app.bot.send_photo(chat_id=chat_id, photo=photo_file)
        print(f"📸 主动发送照片")
    except Exception as e:
        print(f"主动发送照片失败: {e}")


async def send_proactive_voice(app, chat_id, text):
    try:
        tts_result = await tts_edge(text)
        if tts_result.get("success") and tts_result.get("filepath"):
            await app.bot.send_chat_action(chat_id=chat_id, action="record_voice")
            await asyncio.sleep(random.uniform(1.0, 2.0))
            with open(tts_result["filepath"], "rb") as voice_file:
                await app.bot.send_voice(chat_id=chat_id, voice=voice_file)
            memory.user_chat_history.append({"role": "assistant", "content": f"[语音] {text}"})
            print(f"🎙️ 主动发送语音: {text[:30]}")
    except Exception as e:
        print(f"主动发送语音失败: {e}")


# ============================================================
# 用户聊天处理
# ============================================================

def build_chat_system_prompt():
    emotion = memory.get_emotion_tag()
    recent = memory.get_today_events(3)
    long_term = memory.get_long_term()
    user_name = memory.user_name or "朋友"
    now = beijing_now()
    hour = now.hour
    location_name = LOCATION_NAMES.get(memory.current_location, memory.current_location)
    recent_knowledge = memory.get_recent_knowledge(2)

    life_context = ""
    if recent:
        life_context = "\n最近发生的事：\n" + "\n".join(f"- {e}" for e in recent[-2:])

    knowledge_context = ""
    if recent_knowledge:
        knowledge_context = "\n最近看过的：\n" + "\n".join(
            f"- {k['topic']}: {k['summary'][:80]}" for k in recent_knowledge
        )

    style_guide = """# 说话风格
你说话像真人微信聊天。短句、口语化、甜甜的。
绝对不要用书面语、长句、排比句。
可以用语气词（呀、嘛、啦、喔喔、嘻嘻、哈），让说话显得可爱。
喜欢反问和撩人，会撞娇而不显假。
不要每句都加语气词，自然一点。

# 风格参考（模仿这种感觉）
对方: 你在干嘴
你: 在宿舍躞着嘻嘻
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
你: 才不是呢 哼

对方: 好无聊啊
你: 我也是呀
你: 要不要一起看剧
你: 我发现一个超好看的"""

    system = f"""{SOUL}

{style_guide}
---
现在是{now.strftime('%H:%M')}。{emotion}。
在{location_name}。{memory.current_activity}。
{life_context}
{knowledge_context}

{f'关于{user_name}：' + long_term if long_term.strip() else ''}

跟{user_name}在微信上聊天。"""

    return system


# ============================================================
# Telegram Bot
# ============================================================

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

authorized_chat_id = None
telegram_app = None

# 消息合并缓冲区
message_buffer = []
_buffer_lock = threading.Lock()
_pending_reply_task = None


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global authorized_chat_id
    authorized_chat_id = update.effective_chat.id
    await update.message.reply_text("嗨")
    memory.log_event("认识了一个新朋友", importance=8)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """收到消息后放入缓冲区，等待合并"""
    global authorized_chat_id, _pending_reply_task
    if authorized_chat_id is None:
        authorized_chat_id = update.effective_chat.id

    chat_id = update.effective_chat.id
    has_photo = bool(update.message.photo)
    user_text = update.message.text or update.message.caption or ""
    image_path = None

    if has_photo:
        try:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            image_path = f"/home/ubuntu/chimera/user_photos/{photo.file_id}.jpg"
            os.makedirs(os.path.dirname(image_path), exist_ok=True)
            await file.download_to_drive(image_path)
        except Exception as e:
            print(f"下载图片失败: {e}")
            has_photo = False

    print(f"📩 用户: {user_text}")

    with _buffer_lock:
        message_buffer.append({
            "text": user_text,
            "has_photo": has_photo,
            "image_path": image_path,
            "update": update,
            "context": context,
            "chat_id": chat_id,
            "time": time.time(),
        })

    if _pending_reply_task and not _pending_reply_task.done():
        _pending_reply_task.cancel()

    _pending_reply_task = asyncio.create_task(_delayed_reply())


async def _delayed_reply():
    """等待后处理所有缓冲消息"""
    await asyncio.sleep(2.5)
    print(f"⏰ _delayed_reply 触发，buffer大小: {len(message_buffer)}")

    with _buffer_lock:
        if not message_buffer:
            return
        msgs = list(message_buffer)
        message_buffer.clear()

    last_msg = msgs[-1]
    update = last_msg["update"]
    context = last_msg["context"]
    chat_id = last_msg["chat_id"]

    user_texts = [m["text"] for m in msgs if m["text"]]
    has_photo = any(m["has_photo"] for m in msgs)
    image_path = next((m["image_path"] for m in msgs if m.get("image_path")), None)

    if not user_texts and not has_photo:
        return

    if len(user_texts) == 1:
        user_input = user_texts[0]
    else:
        user_input = "\n".join(user_texts)

    # 路由skill（用合并文本判断）
    combined_text = "\n".join(user_texts)
    skill_params = route_skill(combined_text, has_photo=has_photo)
    skill_name = skill_params.get("skill", "none")

    # 世界上下文
    ws = world.get_world_state()
    world_context = {
        "location_id": memory.current_location,
        "hour": beijing_now().hour,
        "weather": ws.get("weather", "晴天") if ws else "晴天",
        "activity": memory.current_activity,
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
    replies = await _generate_natural_reply(user_input, user_texts)

    if not replies:
        print(f"🤫 选择不回复: {combined_text[:30]}")
        memory.user_chat_history.append({"role": "user", "content": user_input})
        memory.save()
        return
    
    print(f"📝 准备回复 {len(replies)} 条: {replies}")

    memory.user_chat_history.append({"role": "user", "content": user_input})
    memory.emotional_state["loneliness"] = max(0, memory.emotional_state["loneliness"] - 20)
    memory.emotional_state["happiness"] = min(100, memory.emotional_state["happiness"] + 2)

    for i, reply_text in enumerate(replies):
        if i == 0:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            # 打字时间跟消息长度相关
            typing_time = min(0.5 + len(reply_text) * 0.08, 4.0)
            await asyncio.sleep(typing_time)
        else:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(random.uniform(0.5, 1.5))

        await context.bot.send_message(chat_id=chat_id, text=reply_text)
        print(f"💬 糖糖: {reply_text}")

    full_response = "\n".join(replies)
    memory.user_chat_history.append({"role": "assistant", "content": full_response})
    memory.log_event(f"跟{memory.user_name or '朋友'}聊天", importance=4)

    # 自拍和语音在文字回复之后发
    if skill_name == "selfie":
        await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
        result = execute_skill(skill_params, world_context=world_context)
        if result.get("success") and result.get("filepath"):
            try:
                with open(result["filepath"], "rb") as photo_file:
                    await context.bot.send_photo(chat_id=chat_id, photo=photo_file)
            except Exception as e:
                print(f"发送图片失败: {e}")

    elif skill_name == "voice":
        voice_text = full_response
        tts_result = await tts_edge(voice_text)
        if tts_result.get("success") and tts_result.get("filepath"):
            try:
                with open(tts_result["filepath"], "rb") as voice_file:
                    await context.bot.send_voice(chat_id=chat_id, voice=voice_file)
            except Exception as e:
                print(f"发送语音失败: {e}")

    # 记住用户名字
    if memory.user_name is None and any(kw in combined_text for kw in ["我叫", "我是", "叫我"]):
        for kw in ["我叫", "我是", "叫我"]:
            if kw in combined_text:
                idx = combined_text.index(kw) + len(kw)
                name = combined_text[idx:idx+10].strip().split()[0] if idx < len(combined_text) else None
                if name and len(name) <= 5:
                    memory.user_name = name
                    memory.update_long_term("关于用户", f"名字叫{name}。")
                    break

    # 定期提取用户信息
    if len(memory.user_chat_history) % 20 == 0:
        _extract_user_info_async(memory.user_chat_history[-20:])

    memory.save()


# Few-shot对话示例，注入到messages中让LLM学习风格
def load_few_shot_from_style():
    few_shot_messages = []
    if STYLE:
        lines = STYLE.strip().split('\n\n')
        for block in lines:
            parts = block.strip().split('\n- ')
            if len(parts) < 2:
                continue
            user_part = parts[0].replace('- user: ', '').strip()
            assistant_parts = [p.replace('assistant: ', '').strip() for p in parts[1:]]
            few_shot_messages.append({"role": "user", "content": user_part})
            few_shot_messages.append({"role": "assistant", "content": "\n".join(assistant_parts)})
    return few_shot_messages

FEW_SHOT_EXAMPLES = load_few_shot_from_style()

def reload_few_shot():
    """动态重载few-shot示例（学到新风格后调用）"""
    global STYLE, FEW_SHOT_EXAMPLES
    STYLE = load_text_file(os.path.join(BASE_DIR, "few_shot.md"))
    FEW_SHOT_EXAMPLES = load_few_shot_from_style()
    print(f"🔄 Few-shot重载完成，当前 {len(FEW_SHOT_EXAMPLES)//2} 组示例")


def _try_learn_style_from_content(content, few_shot_path=None):
    """
    通用学习机制：从任意浏览内容中自动检测并提取对话风格示例。
    就像真人刷小红书、看帖子，潜移默化地受影响。
    """
    if few_shot_path is None:
        few_shot_path = os.path.join(BASE_DIR, "few_shot.md")

    # 第一步：快速检测内容中是否有对话特征
    dialogue_markers = ["男：", "女：", "男生：", "女生：", "我：", "他：", "她：",
                        "聊天记录", "对话", "聊天截图", "微信聊天",
                        "“", "”", "「", "」",
                        "哈哈哈", "嘿嘿嘿", "喔喔", "啊啊",
                        "回复", "聊天技巧", "聊天示例", "聊天话术",
                        "她说", "他说", "我说", "你说",
                        "开场白", "套路", "撑妈",
                        "呢", "啦", "嘛", "啊", "呀"]
    marker_count = sum(1 for m in dialogue_markers if m in content)
    if marker_count < 2:
        # 内容中对话特征不够，跳过
        return

    print("🎓 检测到对话内容，尝试提取风格示例...")

    # 第二步：用LLM提取对话示例
    extract_prompt = """你是一个对话风格分析专家。从以下网页内容中，提取自然的中文微信聊天对话示例。

要提取的是朋友之间的日常聊天，不是撑妇套路。

严格过滤：
- 不要“你猜我属什么”“你是什么血型”这类套路撩妇话术
- 不要“我怎么感觉最近怪怪的”“我总感觉今天缺点什么”这类土味情话
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
5. 找不到自然日常对话就回复"无"，宁缺毻滥"""

    try:
        extracted = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {"role": "system", "content": extract_prompt},
                {"role": "user", "content": f"以下是浏览到的内容：\n\n{content[:4000]}"},
            ],
            max_tokens=600,
            temperature=0.3,
        ).choices[0].message.content
    except Exception as e:
        print(f"🎓 LLM提取失败: {e}")
        return

    if not extracted or extracted.strip() == "无" or len(extracted.strip()) < 20:
        print("🎓 没提取到有用的对话")
        return

    # 第三步：验证和清洗
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

    # 第四步：去重
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

    # 每次最多学5组
    new_blocks = new_blocks[:5]

    # 检查总量上限（50组）
    existing_count = existing.count("- user:")
    if existing_count >= 50:
        print(f"🎓 few-shot已有{existing_count}组，达到上限，跳过")
        return

    # 第五步：追加到few-shot文件
    with open(few_shot_path, "a", encoding="utf-8") as f:
        for block in new_blocks:
            f.write("\n" + block + "\n")

    # 重载
    reload_few_shot()

    learned_count = len(new_blocks)
    memory.log_event(f"刷网页时学到了{learned_count}组新的说话方式", importance=5)
    memory.emotional_state["creativity"] = min(100, memory.emotional_state["creativity"] + 3)
    print(f"🎓 从浏览内容中学到了 {learned_count} 组新对话！")
    for b in new_blocks:
        print(f"  📝 {b[:60]}...")

# 旧的硬编码示例
#FEW_SHOT_EXAMPLES = [
#    {"role": "user", "content": "你还在深圳吗"},
#    {"role": "assistant", "content": "在呢\n明天回去了\n我这周请假了 我妈让我休息一下\n下周要去坐牢了哈哈\n出不来"},
#    {"role": "user", "content": "好吧 要去多久"},
#    {"role": "assistant", "content": "不知道呢\n半个月吧差不多\n之前就住了半个月"},
#    {"role": "user", "content": "感觉也挺好的哈哈 很轻松"},
#    {"role": "assistant", "content": "嗯嗯 就养老呗\n做完治疗就没什么事了 所以比较闲\n我有在坚持背单词"},
#    {"role": "user", "content": "很忙呀 感觉更忙了"},
#    {"role": "assistant", "content": "辛苦呢"},
#    {"role": "user", "content": "项目进入到深水区"},
#    {"role": "assistant", "content": "你别太焦虑啦"},
#    {"role": "user", "content": "厉害👍 别沉迷"},
#    {"role": "assistant", "content": "不会啦\n消磨时间而已\n我不太会玩的\n我一直乖乖的呢"},
#    {"role": "user", "content": "忙疯了 你怎么样"},
#    {"role": "assistant", "content": "周六出院了\n然后我十八号回深圳\n摸摸你"},
#    {"role": "user", "content": "那就好呀～ 等你来深圳见哈哈"},
#    {"role": "assistant", "content": "嗯呐\n好呀\n你工作辛苦也要注意身体"},
#    {"role": "user", "content": "新年快乐呀 我被抓到北京封闭开发了哈哈哈"},
#    {"role": "assistant", "content": "诶呦\n这么忙\n辛苦你啦\n我说你最近怎么都不理我\n还以为你把我忘了～"},
#    {"role": "user", "content": "还行吧 就很干燥"},
#    {"role": "assistant", "content": "是呢\n反正我觉得北方都呆的很难受\n还是南方比较舒服"},
#    {"role": "user", "content": "明天见？"},
#    {"role": "assistant", "content": "OK\n几点"},
#    {"role": "user", "content": "那就出门吧"},
#    {"role": "assistant", "content": "不是下午吗"},
#    {"role": "user", "content": "好的 我以为你要出门了呢"},
#    {"role": "assistant", "content": "并没有\n起不了那么早......"},
#    {"role": "user", "content": "不过周二吧 明天我要写ppt..."},
#    {"role": "assistant", "content": "好\n辛苦捏"},
#    {"role": "user", "content": "哈哈哈哈 是吗～ 南山那家吗"},
#    {"role": "assistant", "content": "对对对\n就那家\n世界好小哈哈"},
#    {"role": "user", "content": "你在干嘛呢"},
#    {"role": "assistant", "content": "我跟你说 我的多肉开啦 哈哈哈 超好看"},
#    {"role": "user", "content": "想看你泳衣照"},
#    {"role": "assistant", "content": "滚\n你有病？"},
    # {"role": "user", "content": "你是不是喜欢我"},
    # {"role": "assistant", "content": "你想多了"}
#]


async def _generate_natural_reply(user_input, user_texts):
    """让LLM自己决定回不回、回几条、每条什么内容"""
    system = build_chat_system_prompt()

    # 先放few-shot示例，再放真实对话历史
    messages = list(FEW_SHOT_EXAMPLES)

    for msg in memory.user_chat_history[-20:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    if len(user_texts) > 1:
        formatted = "\n".join([f"[{i+1}] {t}" for i, t in enumerate(user_texts)])
        messages.append({"role": "user", "content": formatted})
    else:
        messages.append({"role": "user", "content": user_input})

    reply_instruction = """\n\n每条消息占一行。回几条看情况。不回就写[不回]。"""

    full_system = system + reply_instruction

    try:
        full_messages = [{"role": "system", "content": full_system}] + messages
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=full_messages,
            max_tokens=150,
            temperature=1.0,
        )
        raw = response.choices[0].message.content
    except Exception as e:
        print(f"LLM调用失败: {e}")
        import traceback
        traceback.print_exc()
        return ["嗯"]

    if not raw:
        return ["嗯"]

    raw = raw.strip()

    if raw == "[不回]" or raw == "[不回复]" or raw.strip() == "":
        return []

    lines = [l.strip() for l in raw.split("\n") if l.strip()]
    replies = []
    for line in lines:
        cleaned = line
        if len(line) > 2 and line[0].isdigit() and line[1] in ".）)":
            cleaned = line[2:].strip()
        elif len(line) > 3 and line[0] == "[" and line[2] == "]":
            cleaned = line[3:].strip()
        if cleaned and cleaned != "[不回]":
            replies.append(cleaned)

    return replies[:4]


def _extract_user_info_async(recent_chat):
    try:
        chat_text = "\n".join([f"{'用户' if m['role']=='user' else '糖糖'}: {m['content']}" for m in recent_chat])
        result = call_llm(
            "从以下对话中提取关于用户的关键信息（名字、喜好、工作、重要的事）。如果没有新信息就回复'无'。用简短的要点列出。",
            chat_text, max_tokens=150, temperature=0.3,
        )
        if result and result.strip() != "无":
            current = memory.get_long_term()
            section = current.split("## 关于用户")[-1].split("## ")[0] if "## 关于用户" in current else ""
            memory.update_long_term("关于用户", section.strip() + "\n" + result.strip())
    except Exception as e:
        print(f"记忆提取失败: {e}")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = beijing_now()
    ws = world.get_world_state()
    location_name = LOCATION_NAMES.get(memory.current_location, memory.current_location)
    recent_knowledge = memory.get_recent_knowledge(2)

    status = f"""{now.strftime('%H:%M')} {ws.get('weather', '?') if ws else '?'}
{memory.current_activity} @ {location_name}
{memory.get_emotion_description()}"""

    if recent_knowledge:
        status += "\n\n最近看过："
        for k in recent_knowledge:
            status += f"\n- {k['topic']}"

    await update.message.reply_text(status)


# ============================================================
# 自主循环
# ============================================================

def autonomous_loop(loop):
    print("🧠 自主循环启动...")

    result = world.register()
    print(f"📝 注册结果: {result}")

    world.start_world()
    print("🌍 世界已启动（实时同步模式）")

    tick_count = 0

    while True:
        try:
            ws = world.get_world_state()
            if not ws:
                time.sleep(5)
                continue

            # 处理世界事件
            events = world.get_events()
            for event in events:
                if event.get("event_type") == "random_event":
                    desc = event.get("description", "")
                    mood = event.get("mood", "neutral")
                    if event.get("location_id") == memory.current_location:
                        memory.log_event(desc, importance=6 if mood == "positive" else 4)
                        memory.update_emotion(mood)

            # 每5个tick（约5分钟）做一次自主决策
            if tick_count % 5 == 0:
                action = autonomous_decide()
                if action:
                    execute_autonomous_action(action, loop)
                    memory.save()  # 每次自主行为后立即保存

            # 每10个tick也保存一次（兜底）
            if tick_count % 10 == 0:
                memory.save()

            # 自然的精力/情绪变化
            hour = beijing_now().hour
            if 7 <= hour < 23:
                memory.emotional_state["energy"] = max(0, memory.emotional_state["energy"] - 0.5)
                memory.emotional_state["loneliness"] = min(100, memory.emotional_state["loneliness"] + 0.3)

            tick_count += 1
            time.sleep(TICK_INTERVAL)

        except Exception as e:
            print(f"自主循环错误: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)


# ============================================================
# 主入口
# ============================================================

async def main():
    global telegram_app

    print("=" * 50)
    print("🌟 糖糖 Agent Runtime v1 启动中...")
    print("  开放式决策 + 数字生活 + 自主能力")
    print("=" * 50)

    memory.load()
    print("📚 记忆加载完成")
    print(f"📝 SOUL: {len(SOUL)} chars")
    print(f"📝 STYLE: {len(STYLE)} chars")
    print(f"📚 知识库: {len(os.listdir(memory.knowledge_dir))} 条")

    telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CommandHandler("status", status_command))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    telegram_app.add_handler(MessageHandler(filters.PHOTO, handle_message))

    loop = asyncio.get_event_loop()

    auto_thread = threading.Thread(target=autonomous_loop, args=(loop,), daemon=True)
    auto_thread.start()
    print("🧠 自主循环已启动")

    print(f"🤖 Telegram Bot 启动: @nico2_bot")
    print("=" * 50)

    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(drop_pending_updates=True)

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n正在关闭...")
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
