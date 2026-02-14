"""
World Engine - 世界引擎 API 服务
一个跟现实时间1:1同步的世界模拟器，通过HTTP API暴露给外部agent。
"""

import json
import time
import threading
import random
import os
from datetime import datetime
from flask import Flask, jsonify, request

app = Flask(__name__)

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
        "location": "company_startup",
    },
    "npc_wang_boss": {
        "name": "王总",
        "description": "公司老板，人不错但有时会突然加需求。",
        "location": "company_startup",
    },
    "npc_su_teacher": {
        "name": "苏老师",
        "description": "画室的水彩老师，温和有耐心，画技很好。",
        "location": "studio_art",
    },
    "npc_cafe_boss": {
        "name": "老陈",
        "description": "咖啡馆老板，中年大叔，爱聊天，咖啡做得不错。",
        "location": "cafe_moli",
    },
}

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
# Action 处理队列
# ============================================================

action_queue = []
action_results = {}


def process_action(action):
    agent_id = action.get("agent_id")
    tool = action.get("tool")
    result = {"success": True, "message": "", "events": []}

    if tool == "move":
        target = action.get("target_location_id")
        if target in locations:
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
    event["timestamp"] = datetime.now().isoformat()
    event_log.append(event)
    if len(event_log) > 500:
        event_log.pop(0)


# ============================================================
# 世界主循环
# ============================================================

def tick_loop():
    while world_state["running"]:
        world_state["tick"] += 1

        # 更新天气
        update_weather()

        # 处理action队列
        while action_queue:
            action = action_queue.pop(0)
            result = process_action(action)
            action_id = action.get("action_id", "")
            if action_id:
                action_results[action_id] = result

        # 为有agent的地点生成随机事件（每5分钟约10%概率）
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

        # NPC行为
        hour = get_current_hour()
        for npc_id, npc in npcs.items():
            if random.random() < 0.03:
                broadcast_event({
                    "event_type": "npc_action",
                    "npc_id": npc_id,
                    "npc_name": npc["name"],
                    "location_id": npc["location"],
                    "action": random.choice([
                        f"{npc['name']}在忙自己的事",
                        f"{npc['name']}哼着歌",
                        f"{npc['name']}看了看窗外",
                    ]),
                })

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
        "action_queue_size": len(action_queue),
    })


@app.route("/v1/locations", methods=["GET"])
def get_locations():
    return jsonify([{
        "id": loc_id,
        "name": loc["name"],
        "type": loc["type"],
        "characters": loc["characters"],
    } for loc_id, loc in locations.items()])


@app.route("/v1/locations/<location_id>/perceive", methods=["GET"])
def perceive_location(location_id):
    if location_id not in locations:
        return jsonify({"error": "地点不存在"}), 404

    loc = locations[location_id]
    chars = []
    for char_id in loc["characters"]:
        if char_id in npcs:
            chars.append({"id": char_id, "name": npcs[char_id]["name"],
                         "description": npcs[char_id]["description"]})
        elif char_id in registered_agents:
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

    registered_agents[agent_id] = {
        "id": agent_id,
        "name": name,
        "location": start_location,
        "registered_at": datetime.now().isoformat(),
    }

    if start_location in locations:
        if agent_id not in locations[start_location]["characters"]:
            locations[start_location]["characters"].append(agent_id)

    return jsonify({"success": True, "agent_id": agent_id, "message": f"{name}已注册"})


@app.route("/v1/agents/<agent_id>/act", methods=["POST"])
def agent_act(agent_id):
    if agent_id not in registered_agents:
        return jsonify({"error": "agent未注册"}), 404

    action = request.json
    action["agent_id"] = agent_id
    action["action_id"] = f"{agent_id}_{world_state['tick']}"

    action_queue.append(action)
    return jsonify({"success": True, "action_id": action["action_id"]})


@app.route("/v1/events/all", methods=["GET"])
def get_all_events():
    since_tick = request.args.get("since_tick", 0, type=int)
    filtered = [e for e in event_log if e.get("tick", 0) > since_tick]
    return jsonify(filtered)


@app.route("/v1/control/start", methods=["POST"])
def start_world():
    if not world_state["running"]:
        world_state["running"] = True
        update_weather()
        t = threading.Thread(target=tick_loop, daemon=True)
        t.start()
        return jsonify({"success": True, "message": "世界已启动（实时同步模式）"})
    return jsonify({"success": True, "message": "世界已在运行"})


@app.route("/v1/control/stop", methods=["POST"])
def stop_world():
    world_state["running"] = False
    return jsonify({"success": True, "message": "世界已停止"})


if __name__ == "__main__":
    print("🌍 World Engine starting (real-time sync mode)...")
    app.run(host="0.0.0.0", port=5000, debug=False)
