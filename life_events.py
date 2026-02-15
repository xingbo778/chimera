"""
生活事件生成器 - 让 agent 的每个行动都产生具体的微小生活体验

核心理念：真人的一天充满了小事，这些小事才是聊天的素材。
不是"我在休息"，而是"刚泡了杯热可可，窗外在下雨"。
不是"做了点创作"，而是"画了一只歪歪扭扭的猫，越看越像我家那只"。
"""

import random
import time

# ============================================================
# 按行动类型 × 地点 × 时间段 的微小生活事件池
# 每个事件都是一个具体的、可以拿来聊天的小体验
# ============================================================

LIFE_EVENTS = {
    "rest": {
        "morning": [
            "赖床赖了好久，被阳光晃醒的",
            "醒来发现头发炸成鸟窝了",
            "迷迷糊糊看了眼手机，差点又睡过去",
            "起来喝了杯温水，胃暖暖的",
            "窗帘没拉好，一大早就被太阳晒醒",
            "做了个奇怪的梦，梦到自己在飞",
            "闹钟响了三次才起来",
        ],
        "afternoon": [
            "躺沙发上发呆，看天花板看了好久",
            "午睡睡过头了，醒来有点懵",
            "泡了杯茶，坐窗边看外面的人来人往",
            "翻了翻手机相册，看到以前的照片笑了半天",
            "抱着抱枕发呆，脑子里什么都没想",
            "听着雨声发呆，突然觉得很安静很舒服",
            "吃了个冰淇淋，幸福感爆棚",
        ],
        "evening": [
            "洗了个热水澡，整个人都舒服了",
            "敷了个面膜，躺着听歌",
            "窝在被子里看手机，不想动",
            "点了个外卖，等的时候无聊得要命",
            "吹头发的时候对着镜子做鬼脸",
            "泡了杯热可可，窗外在下雨",
            "把房间收拾了一下，心情好了很多",
        ],
        "night": [
            "躺在床上翻来覆去睡不着",
            "半夜饿了，翻冰箱找吃的",
            "听着白噪音准备睡觉",
            "看了会儿星星，今晚月亮好圆",
            "突然想起一件尴尬的事，在被窝里缩成一团",
        ],
    },
    "create": {
        "default": [
            "画了一只歪歪扭扭的猫，越看越像隔壁那只",
            "写了几句话，删了又写，写了又删",
            "调色调了半天，终于调出想要的那个蓝",
            "画着画着走神了，回过神来发现画了个奇怪的东西",
            "拍了张窗外的照片，光线特别好",
            "折腾了半天滤镜，最后还是用了原图",
            "写了一段日记，写着写着笑了",
            "画了个小头像，准备换头像用",
            "试着画水彩，结果水放多了糊成一团",
            "录了一小段弹吉他的视频，虽然弹错了好几个音",
            "做了个手账，贴了好多贴纸",
            "画了今天吃的那碗面，口水都要流下来了",
            "写了首小诗，自己觉得还挺有意境的",
            "拼了个乐高，花了一下午终于拼完了",
        ],
    },
    "scroll_feed": {
        "default": [
            # 这些是 scroll_feed 失败时的 fallback
            # 成功时会用真实的小红书/微博内容
            "刷到一个超搞笑的视频，笑到肚子疼",
            "看到一个穿搭博主，她那件外套好好看",
            "刷到一家看起来超好吃的店，离我好远",
            "看到有人晒猫，又想养猫了",
            "刷到一个旅行vlog，好想去海边",
            "看到一个化妆教程，手好巧",
            "刷到以前同学的动态，她居然去了日本",
            "看到一个超可爱的柯基屁股，存了",
        ],
    },
    "explore": {
        "cafe_moli": [
            "点了杯拿铁，拉花是个小熊",
            "找了个靠窗的位置坐下，外面的树影很好看",
            "闻到隔壁桌的蛋糕好香，忍不住也点了一块",
            "咖啡馆在放爵士乐，氛围好好",
            "遇到一只咖啡馆的猫，它跳到我腿上了",
        ],
        "park_central": [
            "在湖边坐了会儿，看鸭子游来游去",
            "捡了一片好看的叶子",
            "看到有人在遛一只超大的金毛",
            "公园里的花开了，拍了好多照片",
            "买了根烤肠，边走边吃",
            "在长椅上坐着晒太阳，差点睡着",
        ],
        "market_street": [
            "逛到一家很有意思的饰品店，买了个耳环",
            "吃了一碗超好吃的牛肉面",
            "在古城里迷路了，但发现了一条很漂亮的小巷",
            "买了杯柠檬茶，酸酸甜甜的",
            "看到一个街头艺人在弹吉他，驻足听了好久",
            "闻到烤红薯的香味，买了一个",
        ],
        "library": [
            "找了个角落的位置坐下，特别安静",
            "翻到一本很有意思的摄影集",
            "在书架间走来走去，闻到书的味道好舒服",
            "看了一下午书，脖子有点酸",
            "借了两本小说，准备回去慢慢看",
        ],
        "studio_art": [
            "今天画室人不多，特别安静",
            "试了一种新的颜料，颜色好漂亮",
            "看到旁边的人画得好好，偷偷学了一下",
            "不小心把颜料蹭到脸上了，同学笑死了",
            "画了一幅小风景画，老师说构图不错",
        ],
        "company_startup": [
            "今天开了个无聊的会",
            "午饭和同事一起吃的，她推荐了一家新店",
            "下午茶时间，同事带了蛋糕来分",
            "改了三版方案，终于过了",
            "和同事吐槽了一下午，心情好了很多",
        ],
        "default": [
            "在路上走着，风吹得头发乱飞",
            "等红绿灯的时候看到一只流浪猫",
            "路过一家面包店，香味飘出来了",
            "坐公交的时候看窗外发呆",
            "走了好多路，腿有点酸",
        ],
    },
    "learn": {
        "default": [
            "看了一篇很有意思的文章，讲色彩心理学的",
            "学了一个新的画画技巧，手还不太熟练",
            "看了个纪录片，讲深海生物的，好神奇",
            "翻了翻一本设计书，里面的排版好好看",
            "听了个播客，讲的是一个旅行故事",
            "学了几个新单词，但过一会儿就忘了",
            "看了个TED演讲，讲创造力的，挺有启发",
            "研究了一下咖啡豆的种类，原来有这么多讲究",
        ],
    },
}

# 天气相关的生活细节
WEATHER_DETAILS = {
    "晴天": [
        "阳光好好，晒得暖暖的",
        "天好蓝，拍了张天空的照片",
        "太阳晒得有点热，想吃冰的",
    ],
    "多云": [
        "天阴阴的，有点想睡觉",
        "云好多，像棉花糖一样",
    ],
    "小雨": [
        "下雨了，空气里有泥土的味道",
        "雨滴打在窗户上，滴答滴答的",
        "忘带伞了，在屋檐下等雨停",
        "雨天好适合窝在家里",
    ],
    "大雨": [
        "雨好大，外面白茫茫一片",
        "打雷了，吓了一跳",
        "哪儿都去不了，只能待在家",
    ],
    "阴天": [
        "天灰灰的，心情也有点灰",
        "没有太阳，有点冷",
    ],
}


def generate_life_detail(action_type, location=None, hour=None, weather=None):
    """
    根据行动类型、地点、时间、天气，生成一个具体的生活细节。
    返回一个字符串，描述 agent 在这个行动中具体经历了什么。
    """
    # 确定时间段
    if hour is None:
        hour = 12
    if hour < 10:
        time_period = "morning"
    elif hour < 14:
        time_period = "afternoon"
    elif hour < 19:
        time_period = "afternoon"
    elif hour < 23:
        time_period = "evening"
    else:
        time_period = "night"

    events = LIFE_EVENTS.get(action_type, {})

    # 优先用 地点特定 > 时间段特定 > default
    candidates = []
    if location and location in events:
        candidates = events[location]
    elif time_period in events:
        candidates = events[time_period]
    elif "default" in events:
        candidates = events["default"]

    detail = random.choice(candidates) if candidates else None

    # 偶尔附加天气细节（30%概率）
    if weather and random.random() < 0.3:
        weather_events = WEATHER_DETAILS.get(weather, [])
        if weather_events:
            weather_detail = random.choice(weather_events)
            if detail:
                detail = f"{detail}。{weather_detail}"
            else:
                detail = weather_detail

    return detail


# ============================================================
# 生活体验缓冲区 - 记录最近的生活细节，供主动消息使用
# ============================================================

class LifeBuffer:
    """
    维护一个最近生活体验的缓冲区。
    agent 每次行动后把体验存进来，主动消息时从这里取素材。
    """

    def __init__(self, max_size=20):
        self.experiences = []  # [{"detail": str, "action": str, "time": float, "used": bool}]
        self.max_size = max_size

    def add(self, detail, action_type="", source="imagined", artifact=None):
        """添加一条生活体验
        source: 'real' / 'world' / 'imagined'
        artifact: 真实产出物 {'type': 'image'/'video'/'voice', 'path': filepath}
        """
        if not detail:
            return
        entry = {
            "detail": detail,
            "action": action_type,
            "time": time.time(),
            "used": False,
            "source": source,
        }
        if artifact:
            entry["artifact"] = artifact
        self.experiences.append(entry)
        # 保持缓冲区大小
        if len(self.experiences) > self.max_size:
            self.experiences = self.experiences[-self.max_size:]

    def get_unused(self, n=3):
        """获取最近 n 条未使用过的体验"""
        unused = [e for e in self.experiences if not e["used"]]
        return unused[-n:]

    def get_recent(self, n=5):
        """获取最近 n 条体验（不管是否使用过）"""
        return self.experiences[-n:]

    def mark_used(self, detail):
        """标记某条体验为已使用"""
        for e in self.experiences:
            if e["detail"] == detail:
                e["used"] = True

    def get_shareable(self):
        """
        获取最适合分享的一条体验：
        - 优先有真实产出物的（可以发图片/视频）
        - 优先未使用过的
        - 优先最近的
        """
        unused = [e for e in self.experiences if not e["used"]]
        # 优先有真实产出物的
        real_unused = [e for e in unused if e.get("artifact")]
        if real_unused:
            chosen = real_unused[-1]
            chosen["used"] = True
            return chosen["detail"], chosen.get("artifact")
        if unused:
            chosen = unused[-1]
            chosen["used"] = True
            return chosen["detail"], None
        return None, None

    def get_recent_artifacts(self, n=5):
        """获取最近的真实产出物"""
        artifacts = []
        for e in reversed(self.experiences):
            if e.get("artifact") and e["artifact"].get("path"):
                artifacts.append({
                    "detail": e["detail"],
                    "artifact": e["artifact"],
                    "time": e["time"],
                })
                if len(artifacts) >= n:
                    break
        return artifacts

    def has_real_artifact_for(self, keyword):
        """检查是否有与关键词相关的真实产出物"""
        for e in reversed(self.experiences):
            if e.get("artifact") and keyword in e.get("detail", ""):
                return e["artifact"]
        return None
