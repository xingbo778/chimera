"""
World Engine - 世界引擎 API 服务
一个跟现实时间1:1同步的世界模拟器，通过HTTP API暴露给外部agent。
"""

import hmac
import json
import time
import threading
import random
import os
import logging
from datetime import datetime
from functools import wraps
from flask import Flask, jsonify, request, abort

logger = logging.getLogger(__name__)
app = Flask(__name__)

# ============================================================
# 认证：通过环境变量 WORLD_AUTH_TOKEN 设置 token
# 未设置时仅允许 127.0.0.1 访问
# ============================================================

WORLD_AUTH_TOKEN = os.environ.get("WORLD_AUTH_TOKEN", "")


@app.before_request
def check_auth():
    client_ip = request.remote_addr or ""
    is_local = client_ip in ("127.0.0.1", "::1")
    if not is_local:
        if not WORLD_AUTH_TOKEN:
            abort(403, description="Remote access requires WORLD_AUTH_TOKEN")
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token or not hmac.compare_digest(token, WORLD_AUTH_TOKEN):
            abort(401, description="Invalid token")

# ============================================================
# 线程安全锁
# ============================================================

_world_lock = threading.Lock()      # 保护 world_state、locations、registered_agents
_event_lock = threading.Lock()      # 保护 event_log、agent_ack_ticks
_start_lock = threading.Lock()      # 保护 start_world 防止多线程启动
_tick_thread = None                 # 保存 tick_loop 线程引用
_inbox_lock = threading.Lock()       # 保护 agent 间消息信箱

# ============================================================
# Agent 间消息信箱
agent_inboxes = {}  # {agent_id: [{from, message, timestamp, tick}]}

# 持久化路径
# ============================================================

STATE_FILE = os.environ.get("WORLD_STATE_FILE", "world_state.json")

# ============================================================
# 世界状态
# ============================================================

TICK_INTERVAL = 60  # 每60秒一个tick（1分钟）

world_state = {
    "tick": 0,
    "running": False,
}

# 地点系统
locations = {
    "home_xiaoyue": {
        "id": "home_xiaoyue",
        "name": "小悦的公寓",
        "description": "南山区一间温馨的小公寓，阳台上种着几盆多肉植物。客厅有一张小书桌，上面摆着画笔和颜料。",
        "type": "home",
        "characters": [],
        "objects": ["画架", "颜料盒", "多肉植物", "猫咪抱枕"],
    },
    "home_tangtang": {
        "id": "home_tangtang",
        "name": "糖糖的宿舍",
        "description": "杭州某大学的女生宿舍，粉色床品，墙上挂着小灯串。桌上有画册和水彩笔，床上摆着好几个毛绒玩偶。",
        "type": "home",
        "characters": [],
        "objects": ["毛绒兔子", "画册", "小灯串", "粉色抱枕", "奶茶杯"],
    },
    "cafe_moli": {
        "id": "cafe_moli",
        "name": "茉莉咖啡馆",
        "description": "街角一家安静的咖啡馆，木质装修，暖黄灯光。老板是个爱聊天的中年大叔。常有文艺青年在这里看书写字。",
        "type": "cafe",
        "characters": ["npc_cafe_boss"],
        "objects": ["咖啡机", "书架", "小黑板菜单"],
    },
    "park_central": {
        "id": "park_central",
        "name": "中心公园",
        "description": "深圳市中心的一个大公园，有湖、有柳树、有跑道。早上很多人晨跑，傍晚有人遛狗、跳广场舞。",
        "type": "park",
        "characters": [],
        "objects": ["湖", "长椅", "柳树", "跑道"],
    },
    "studio_art": {
        "id": "studio_art",
        "name": "南山画室",
        "description": "一间开放式画室，墙上挂满了学员的作品。有石膏像、画布、各种颜料。苏老师每周末在这里教水彩。",
        "type": "studio",
        "characters": ["npc_su_teacher"],
        "objects": ["石膏像", "画布", "调色盘", "水彩颜料"],
    },
    "company_startup": {
        "id": "company_startup",
        "name": "星辰科技",
        "description": "南山科技园里的一家小型创业公司，做AI产品的。办公室不大但氛围很好，同事们都很年轻。",
        "type": "office",
        "characters": ["npc_lili", "npc_wang_boss"],
        "objects": ["电脑", "白板", "咖啡机", "零食柜"],
    },
    "market_street": {
        "id": "market_street",
        "name": "南头古城步行街",
        "description": "改造后的古城步行街，有很多文创小店、独立书店和特色餐厅。周末很热闹。",
        "type": "market",
        "characters": [],
        "objects": ["文创小店", "独立书店", "小吃摊"],
    },
    "library": {
        "id": "library",
        "name": "南山图书馆",
        "description": "安静的公共图书馆，有很大的落地窗。三楼有个不错的自习区，经常坐满了人。",
        "type": "library",
        "characters": [],
        "objects": ["书架", "自习桌", "落地窗"],
    },
}

# NPC系统
npcs = {
    "npc_lili": {
        "name": "丽丽",
        "description": "小悦的同事兼好朋友，性格开朗爱聊天，经常一起吃午饭。",
        "default_location": "company_startup",
        "location": "company_startup",
    },
    "npc_wang_boss": {
        "name": "王总",
        "description": "公司老板，人不错但有时会突然加需求。",
        "default_location": "company_startup",
        "location": "company_startup",
    },
    "npc_su_teacher": {
        "name": "苏老师",
        "description": "画室的水彩老师，温和有耐心，画技很好。",
        "default_location": "studio_art",
        "location": "studio_art",
    },
    "npc_cafe_boss": {
        "name": "老陈",
        "description": "咖啡馆老板，中年大叔，爱聊天，咖啡做得不错。",
        "default_location": "cafe_moli",
        "location": "cafe_moli",
    },
}

# BUG-L: NPC 日程表——让 NPC 在不同时段出现在不同地点
_NPC_SCHEDULES = {
    "npc_lili": {
        # hour_range: location_id
        (9, 12): "company_startup",
        (12, 13): "cafe_moli",        # 午饭去咖啡馆
        (13, 18): "company_startup",
        (18, 20): "park_central",      # 下班去公园散步
        (20, 23): "market_street",     # 晚上逛街
    },
    "npc_su_teacher": {
        (9, 12): "studio_art",
        (12, 14): "cafe_moli",         # 中午去喝咖啡
        (14, 18): "studio_art",
        (18, 20): "park_central",      # 傍晚去公园写生
    },
    "npc_cafe_boss": {
        (7, 22): "cafe_moli",          # 老陈基本全天在咖啡馆
    },
    "npc_wang_boss": {
        (9, 19): "company_startup",
        (19, 21): "cafe_moli",         # 晚上偶尔去咖啡馆
    },
}

# NPC 行为随机池（按地点类型）
_NPC_BEHAVIORS = {
    "cafe": [
        "{name}在擦吧台", "{name}给客人推荐了一杯手冲", "{name}在看手机",
        "{name}和客人聊了几句", "{name}在整理咖啡豆",
    ],
    "office": [
        "{name}在开会", "{name}在看电脑", "{name}站起来伸了个懒腰",
        "{name}去茶水间倒了杯水", "{name}在打电话",
    ],
    "studio": [
        "{name}在示范水彩技法", "{name}在点评学员作品", "{name}在调色",
        "{name}在画布前沉思", "{name}在整理画具",
    ],
    "park": [
        "{name}在散步", "{name}坐在长椅上看风景", "{name}在拍照",
        "{name}在跑步", "{name}在看湖里的鱼",
    ],
    "market": [
        "{name}在逛小店", "{name}在吃小吃", "{name}在看文创产品",
    ],
    "default": [
        "{name}在忙自己的事", "{name}哼着歌", "{name}看了看窗外",
    ],
}


def update_npc_locations():
    """BUG-L: 根据日程表更新 NPC 位置"""
    hour = get_current_hour()
    with _world_lock:
        for npc_id, schedule in _NPC_SCHEDULES.items():
            if npc_id not in npcs:
                continue
            new_loc = npcs[npc_id].get("default_location", "")
            for (h_start, h_end), loc_id in schedule.items():
                if h_start <= hour < h_end:
                    new_loc = loc_id
                    break
            old_loc = npcs[npc_id]["location"]
            if new_loc != old_loc and new_loc in locations:
                # 从旧地点移除
                if old_loc in locations and npc_id in locations[old_loc]["characters"]:
                    locations[old_loc]["characters"].remove(npc_id)
                # 添加到新地点
                if npc_id not in locations[new_loc]["characters"]:
                    locations[new_loc]["characters"].append(npc_id)
                npcs[npc_id]["location"] = new_loc


# 天气系统
WEATHER_OPTIONS = ["晴天", "多云", "阴天", "小雨", "大雨", "雾"]
WEATHER_WEIGHTS = [35, 25, 20, 12, 5, 3]

# 当前天气（每天更新一次）
current_weather = {
    "weather": "晴天",
    "temperature": 22,
    "last_update_date": None,
}

# Agent注册
registered_agents = {}

# 事件系统
event_log = []
# BUG-B: ACK 机制——记录每个 agent 已消费到的 tick
agent_ack_ticks = {}
# 事件过期时间（秒）
EVENT_TTL = 600  # 10 分钟


def get_real_time():
    """获取北京时间"""
    from datetime import timezone, timedelta
    utc_now = datetime.now(timezone.utc)
    beijing = utc_now + timedelta(hours=8)
    return beijing


def get_current_hour():
    """获取当前北京时间的小时"""
    return get_real_time().hour


def get_current_date():
    """获取当前北京时间的日期"""
    return get_real_time().strftime("%Y-%m-%d")


def get_time_of_day(hour=None):
    """根据小时返回时段描述"""
    if hour is None:
        hour = get_current_hour()
    if 5 <= hour < 8:
        return "清晨"
    elif 8 <= hour < 12:
        return "上午"
    elif 12 <= hour < 14:
        return "中午"
    elif 14 <= hour < 18:
        return "下午"
    elif 18 <= hour < 21:
        return "傍晚"
    elif 21 <= hour < 24:
        return "晚上"
    else:
        return "深夜"


def update_weather():
    """每天更新一次天气"""
    today = get_current_date()
    if current_weather["last_update_date"] != today:
        current_weather["weather"] = random.choices(WEATHER_OPTIONS, weights=WEATHER_WEIGHTS, k=1)[0]
        current_weather["temperature"] = random.randint(15, 30)
        current_weather["last_update_date"] = today


# ============================================================
# 持久化
# ============================================================

def save_world_state():
    """BUG-B: 持久化世界状态到磁盘"""
    data = {
        "tick": world_state["tick"],
        "weather": current_weather.copy(),
        "registered_agents": dict(registered_agents),
        "agent_ack_ticks": dict(agent_ack_ticks),
        "npc_locations": {npc_id: npc["location"] for npc_id, npc in npcs.items()},
    }
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 保存世界状态失败: {e}")


def load_world_state():
    """BUG-B: 从磁盘恢复世界状态"""
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        world_state["tick"] = data.get("tick", 0)
        saved_weather = data.get("weather", {})
        if saved_weather:
            current_weather.update(saved_weather)

        # 恢复 agent 注册信息
        saved_agents = data.get("registered_agents", {})
        for agent_id, agent_info in saved_agents.items():
            registered_agents[agent_id] = agent_info
            loc = agent_info.get("location", "")
            if loc in locations:
                # 先清理所有地点中的该 agent（防止重复）
                for l in locations.values():
                    if agent_id in l["characters"]:
                        l["characters"].remove(agent_id)
                locations[loc]["characters"].append(agent_id)

        # 恢复 ACK ticks
        saved_acks = data.get("agent_ack_ticks", {})
        agent_ack_ticks.update(saved_acks)

        # 恢复 NPC 位置
        saved_npc_locs = data.get("npc_locations", {})
        for npc_id, loc in saved_npc_locs.items():
            if npc_id in npcs and loc in locations:
                npcs[npc_id]["location"] = loc

        print(f"✅ 世界状态已恢复: tick={world_state['tick']}, agents={len(registered_agents)}")
    except Exception as e:
        print(f"⚠️ 加载世界状态失败: {e}")


# ============================================================
# 随机事件生成
# ============================================================

LOCATION_EVENTS = {
    "home_xiaoyue": [
        {"event": "窗外传来鸟叫声", "mood": "positive", "weight": 3},
        {"event": "邻居在装修，有点吵", "mood": "negative", "weight": 2},
        {"event": "多肉植物开花了", "mood": "positive", "weight": 1},
        {"event": "快递到了", "mood": "positive", "weight": 3},
        {"event": "外面开始下雨了", "mood": "neutral", "weight": 2},
    ],
    "home_tangtang": [
        {"event": "室友带了奶茶回来", "mood": "positive", "weight": 3},
        {"event": "隔壁宿舍在放音乐，有点吵", "mood": "negative", "weight": 2},
        {"event": "快递到了，是之前买的小裙子", "mood": "positive", "weight": 3},
        {"event": "室友在看搞笑视频，笑死了", "mood": "positive", "weight": 2},
        {"event": "外面下雨了，好适合睡觉", "mood": "neutral", "weight": 2},
    ],
    "cafe_moli": [
        {"event": "老陈推荐了一款新的手冲咖啡", "mood": "positive", "weight": 3},
        {"event": "隔壁桌的人在大声打电话", "mood": "negative", "weight": 2},
        {"event": "窗外走过一只很可爱的柯基", "mood": "positive", "weight": 2},
        {"event": "咖啡馆放了一首很好听的歌", "mood": "positive", "weight": 3},
    ],
    "park_central": [
        {"event": "湖边有人在放风筝", "mood": "positive", "weight": 3},
        {"event": "看到一对老夫妻在散步", "mood": "positive", "weight": 2},
        {"event": "有个小孩摔倒了在哭", "mood": "neutral", "weight": 1},
        {"event": "夕阳把湖面染成了金色", "mood": "positive", "weight": 2},
    ],
    "studio_art": [
        {"event": "苏老师夸了我的配色", "mood": "positive", "weight": 2},
        {"event": "不小心把颜料弄到衣服上了", "mood": "negative", "weight": 2},
        {"event": "画了一幅很满意的画", "mood": "positive", "weight": 1},
        {"event": "看到旁边同学画得特别好，有点羡慕", "mood": "neutral", "weight": 2},
    ],
    "company_startup": [
        {"event": "丽丽带了自己做的蛋糕来分享", "mood": "positive", "weight": 2},
        {"event": "王总又改需求了", "mood": "negative", "weight": 3},
        {"event": "项目终于过了评审", "mood": "positive", "weight": 1},
        {"event": "午休时间和丽丽聊了会八卦", "mood": "positive", "weight": 3},
        {"event": "加班到很晚", "mood": "negative", "weight": 1},
    ],
    "market_street": [
        {"event": "发现了一家很有意思的文创小店", "mood": "positive", "weight": 3},
        {"event": "买了一本二手画册", "mood": "positive", "weight": 2},
        {"event": "人太多了有点挤", "mood": "negative", "weight": 2},
    ],
    "library": [
        {"event": "找到了一本很好看的书", "mood": "positive", "weight": 3},
        {"event": "图书馆很安静，看了一下午书", "mood": "positive", "weight": 2},
        {"event": "旁边有人在小声讲电话", "mood": "negative", "weight": 1},
    ],
}


def generate_random_event(location_id):
    events = LOCATION_EVENTS.get(location_id, [])
    if not events:
        return None
    weights = [e["weight"] for e in events]
    chosen = random.choices(events, weights=weights, k=1)[0]
    return chosen


# ============================================================
# Action 处理（同步执行，不再用队列）
# ============================================================

def process_action(action):
    """BUG-B/E: 同步处理 action，立即返回结果"""
    agent_id = action.get("agent_id")
    tool = action.get("tool")
    result = {"success": True, "message": "", "events": []}

    if tool == "move":
        target = action.get("target_location_id")
        with _world_lock:
            if target in locations:
                # 先从所有地点移除该 agent
                for loc in locations.values():
                    if agent_id in loc["characters"]:
                        loc["characters"].remove(agent_id)
                locations[target]["characters"].append(agent_id)
                if agent_id in registered_agents:
                    registered_agents[agent_id]["location"] = target
                result["message"] = f"移动到{locations[target]['name']}"
            else:
                result["success"] = False
                result["message"] = f"地点不存在: {target}"

    elif tool == "interact":
        result["message"] = f"互动: {action.get('interaction', '')}"

    elif tool == "rest":
        result["message"] = "休息中"

    return result


def broadcast_event(event):
    hour = get_current_hour()
    event["tick"] = world_state["tick"]
    event["world_time"] = f"{hour}:00"
    event["timestamp"] = time.time()  # 用 unix timestamp 方便过期计算
    with _event_lock:
        event_log.append(event)


def cleanup_expired_events():
    """BUG-B: 清理过期事件和已被所有 agent ACK 的事件"""
    now = time.time()
    with _event_lock:
        # 找到所有 agent 的最小 ACK tick
        if agent_ack_ticks:
            min_ack = min(agent_ack_ticks.values())
        else:
            min_ack = 0

        # 移除：已过期 OR 所有 agent 都已 ACK
        event_log[:] = [
            e for e in event_log
            if (now - e.get("timestamp", 0) < EVENT_TTL) and (e.get("tick", 0) > min_ack)
        ]


# ============================================================
# 世界主循环
# ============================================================

def tick_loop():
    save_counter = 0
    while world_state["running"]:
        world_state["tick"] += 1

        # 更新天气
        update_weather()

        # BUG-L: 更新 NPC 位置
        update_npc_locations()

        # 为有agent的地点生成随机事件（每5分钟约10%概率）
        with _world_lock:
            for loc_id, loc in locations.items():
                agent_chars = [c for c in loc["characters"] if c in registered_agents]
                if agent_chars and random.random() < 0.1:
                    event = generate_random_event(loc_id)
                    if event:
                        broadcast_event({
                            "event_type": "random_event",
                            "location_id": loc_id,
                            "location_name": loc["name"],
                            "description": event["event"],
                            "mood": event["mood"],
                        })

        # NPC行为（使用行为池）
        hour = get_current_hour()
        with _world_lock:
            for npc_id, npc in npcs.items():
                if random.random() < 0.03:
                    loc_id = npc["location"]
                    loc_type = locations.get(loc_id, {}).get("type", "default")
                    behaviors = _NPC_BEHAVIORS.get(loc_type, _NPC_BEHAVIORS["default"])
                    action_text = random.choice(behaviors).format(name=npc["name"])
                    broadcast_event({
                        "event_type": "npc_action",
                        "npc_id": npc_id,
                        "npc_name": npc["name"],
                        "location_id": loc_id,
                        "action": action_text,
                    })

        # BUG-B: 定期清理过期事件
        cleanup_expired_events()

        # BUG-B: 定期持久化（每 10 tick）
        save_counter += 1
        if save_counter % 10 == 0:
            save_world_state()

        time.sleep(TICK_INTERVAL)


# ============================================================
# Flask API
# ============================================================

@app.route("/v1/world", methods=["GET"])
def get_world_state_api():
    """获取世界全局状态——使用真实北京时间"""
    hour = get_current_hour()
    return jsonify({
        "tick": world_state["tick"],
        "world_time_hour": hour,
        "time_of_day": get_time_of_day(hour),
        "world_date": get_current_date(),
        "weather": current_weather["weather"],
        "temperature": current_weather["temperature"],
        "running": world_state["running"],
    })


@app.route("/v1/status", methods=["GET"])
def get_status():
    hour = get_current_hour()
    return jsonify({
        "world": {
            "running": world_state["running"],
            "tick": world_state["tick"],
            "world_time_hour": hour,
            "time_of_day": get_time_of_day(hour),
            "world_date": get_current_date(),
            "weather": current_weather["weather"],
            "temperature": current_weather["temperature"],
        },
        "locations": len(locations),
        "npcs": len(npcs),
        "registered_agents": len(registered_agents),
        "events_count": len(event_log),
    })


@app.route("/v1/locations", methods=["GET"])
def get_locations():
    with _world_lock:
        return jsonify([{
            "id": loc_id,
            "name": loc["name"],
            "type": loc["type"],
            "characters": loc["characters"],
        } for loc_id, loc in locations.items()])


@app.route("/v1/locations/<location_id>/perceive", methods=["GET"])
def perceive_location(location_id):
    with _world_lock:
        if location_id not in locations:
            return jsonify({"error": "地点不存在"}), 404

        loc = locations[location_id]
        chars = []
        for char_id in loc["characters"]:
            if char_id in npcs:
                chars.append({"id": char_id, "name": npcs[char_id]["name"],
                             "description": npcs[char_id]["description"]})
            elif char_id in registered_agents:
                # BUG-K: 返回其他 Agent 的信息，让 Agent 能看到彼此
                chars.append({"id": char_id, "name": registered_agents[char_id]["name"],
                             "type": "agent"})

    return jsonify({
        "location_id": location_id,
        "name": loc["name"],
        "description": loc["description"],
        "type": loc["type"],
        "characters": chars,
        "objects": loc["objects"],
        "weather": current_weather["weather"],
        "temperature": current_weather["temperature"],
        "time_of_day": get_time_of_day(),
        "hour": get_current_hour(),
    })


@app.route("/v1/agents/register", methods=["POST"])
def register_agent():
    data = request.json
    agent_id = data.get("agent_id")
    name = data.get("name", agent_id)
    start_location = data.get("start_location", "home_xiaoyue")

    with _world_lock:
        registered_agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "location": start_location,
            "registered_at": datetime.now().isoformat(),
        }

        # BUG-B: 先清理所有地点中的该 agent，防止重复出现
        for loc in locations.values():
            if agent_id in loc["characters"]:
                loc["characters"].remove(agent_id)

        if start_location in locations:
            locations[start_location]["characters"].append(agent_id)

    with _event_lock:
        # 初始化 ACK tick 为当前 tick（不拉取历史事件）
        agent_ack_ticks[agent_id] = world_state["tick"]

    return jsonify({"success": True, "agent_id": agent_id, "message": f"{name}已注册"})


@app.route("/v1/agents/<agent_id>/act", methods=["POST"])
def agent_act(agent_id):
    """BUG-E: 同步处理 action，立即返回结果"""
    if agent_id not in registered_agents:
        return jsonify({"error": "agent未注册", "success": False}), 404

    action = request.json
    action["agent_id"] = agent_id
    result = process_action(action)
    return jsonify(result)


@app.route("/v1/events/all", methods=["GET"])
def get_all_events():
    """BUG-B: 返回该 agent 尚未 ACK 的事件"""
    agent_id = request.args.get("agent_id", "")
    since_tick = request.args.get("since_tick", 0, type=int)

    with _event_lock:
        # 如果有 agent_id，使用 ACK tick；否则使用 since_tick
        if agent_id and agent_id in agent_ack_ticks:
            effective_since = max(agent_ack_ticks[agent_id], since_tick)
        else:
            effective_since = since_tick

        filtered = [e for e in event_log if e.get("tick", 0) > effective_since]

    return jsonify(filtered)


@app.route("/v1/events/ack", methods=["POST"])
def ack_events():
    """BUG-B: Agent 确认已消费事件到某个 tick"""
    data = request.json
    agent_id = data.get("agent_id", "")
    ack_tick = data.get("ack_tick", 0)

    if not agent_id:
        return jsonify({"error": "缺少 agent_id"}), 400

    with _event_lock:
        current_ack = agent_ack_ticks.get(agent_id, 0)
        if ack_tick > current_ack:
            agent_ack_ticks[agent_id] = ack_tick

    return jsonify({"success": True, "ack_tick": ack_tick})


# BUG-K: 新增 API——获取某个地点附近的其他 Agent 和 NPC
@app.route("/v1/locations/<location_id>/nearby", methods=["GET"])
def get_nearby(location_id):
    """返回某个地点的所有角色（Agent + NPC）"""
    if location_id not in locations:
        return jsonify({"error": "地点不存在"}), 404

    with _world_lock:
        loc = locations[location_id]
        result = {"agents": [], "npcs": []}
        for char_id in loc["characters"]:
            if char_id in registered_agents:
                result["agents"].append({
                    "id": char_id,
                    "name": registered_agents[char_id]["name"],
                })
            elif char_id in npcs:
                result["npcs"].append({
                    "id": char_id,
                    "name": npcs[char_id]["name"],
                    "description": npcs[char_id]["description"],
                })

    return jsonify(result)


# ============================================================
# Agent 间消息系统
# ============================================================

@app.route("/v1/agents/<agent_id>/send_message", methods=["POST"])
def send_agent_message(agent_id):
    """一个 agent 给另一个 agent 发消息"""
    data = request.json
    target_id = data.get("target_id")
    message = data.get("message", "")

    if not target_id or not message:
        return jsonify({"error": "缺少 target_id 或 message"}), 400

    if agent_id not in registered_agents:
        return jsonify({"error": f"发送者 {agent_id} 未注册"}), 404

    sender_name = registered_agents.get(agent_id, {}).get("name", agent_id)

    with _inbox_lock:
        if target_id not in agent_inboxes:
            agent_inboxes[target_id] = []
        agent_inboxes[target_id].append({
            "from_id": agent_id,
            "from_name": sender_name,
            "message": message,
            "timestamp": time.time(),
            "tick": world_state["tick"],
        })

    return jsonify({"success": True, "message": f"消息已发送给 {target_id}"})


@app.route("/v1/agents/<agent_id>/inbox", methods=["GET"])
def get_agent_inbox(agent_id):
    """获取并清空 agent 的消息信箱"""
    with _inbox_lock:
        messages = agent_inboxes.pop(agent_id, [])
    return jsonify(messages)


@app.route("/v1/control/start", methods=["POST"])
def start_world():
    """BUG-B: 加锁防止多线程启动"""
    global _tick_thread
    with _start_lock:
        if not world_state["running"] or (_tick_thread is not None and not _tick_thread.is_alive()):
            world_state["running"] = True
            update_weather()
            update_npc_locations()
            _tick_thread = threading.Thread(target=tick_loop, daemon=True)
            _tick_thread.start()
            return jsonify({"success": True, "message": "世界已启动（实时同步模式）"})
    return jsonify({"success": True, "message": "世界已在运行"})


@app.route("/v1/control/stop", methods=["POST"])
def stop_world():
    world_state["running"] = False
    save_world_state()
    return jsonify({"success": True, "message": "世界已停止"})


if __name__ == "__main__":
    print("🌍 World Engine starting (real-time sync mode)...")
    load_world_state()
    app.run(host="0.0.0.0", port=5000, debug=False)
