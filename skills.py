"""
Skills 模块 - 小悦的能力系统
包含：上网搜索、自拍(fal.ai flux+face-swap)、读图/读链接、语音(TTS)、拍视频(veo3.1)
"""

import os
import json
import re
import time
import base64
import logging
import subprocess
import requests
from pathlib import Path
from openai import OpenAI

logger = logging.getLogger(__name__)
client = OpenAI()

FAL_KEY = os.environ.get("FAL_KEY", "")  # 必须通过环境变量设置，不硬编码
YUNWU_API_KEY = os.environ.get("YUNWU_API_KEY", "")

# 小悦的参考图（上传后的公开URL）
REFERENCE_FACE_URL = "https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/BXkKRXipEynsUiTN.jpg"

# ============================================================
# Skill 1: 上网搜索
# ============================================================

def skill_web_search(query, num_results=5):
    """用 ddgs 库搜索信息（比手动解析DuckDuckGo HTML好很多）"""
    try:
        from ddgs import DDGS
        ddgs = DDGS()
        results = ddgs.text(query, region='cn-zh', max_results=num_results)
        combined = []
        for r in results:
            combined.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })
        return {"success": True, "query": query, "results": combined}
    except Exception as e:
        print(f"ddgs搜索失败: {e}，回退到DuckDuckGo HTML")
        # 回退方案：手动解析DuckDuckGo HTML
        try:
            headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
            params = {"q": query, "kl": "cn-zh"}
            r = requests.get("https://lite.duckduckgo.com/lite/", params=params,
                            headers=headers, timeout=15)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for link in soup.find_all("a", class_="result-link"):
                title = link.get_text(strip=True)
                url = link.get("href", "")
                if title and url:
                    results.append({"title": title, "url": url})
                    if len(results) >= num_results:
                        break
            snippets = []
            for td in soup.find_all("td", class_="result-snippet"):
                text = td.get_text(strip=True)
                if text:
                    snippets.append(text)
            combined = []
            for i in range(min(len(results), len(snippets))):
                combined.append({
                    "title": results[i]["title"],
                    "url": results[i]["url"],
                    "snippet": snippets[i] if i < len(snippets) else "",
                })
            return {"success": True, "query": query, "results": combined}
        except Exception as e2:
            print(f"回退搜索也失败: {e2}")
            return {"success": False, "query": query, "error": str(e2)}


def skill_fetch_url(url, max_chars=3000):
    """获取网页文本内容。先用requests，如果内容太少则用Playwright MCP抓取JS渲染页面"""
    # 第一步：尝试requests（快）
    text = ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = r.apparent_encoding
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        text = "\n".join(lines)
    except Exception as e:
        logger.debug("requests 拓取失败: %s", e)

    # 如果requests拿到了足够内容，直接返回
    if len(text) > 100:
        return {"success": True, "url": url, "content": text[:max_chars]}

    # 第二步：用Playwright MCP抓取JS渲染页面
    try:
        text = skill_browser_fetch(url, max_chars=max_chars)
        if text and len(text) > 50:
            return {"success": True, "url": url, "content": text}
    except Exception as e:
        print(f"Playwright抓取也失败: {e}")

    return {"success": False, "url": url, "error": "无法获取内容"}


def skill_browser_fetch(url, max_chars=3000):
    """用Playwright MCP抓取JS渲染页面的文本内容"""
    try:
        # 导航到页面
        result = subprocess.run(
            ["manus-mcp-cli", "tool", "call", "browser_navigate",
             "--server", "playwright", "--input", json.dumps({"url": url})],
            capture_output=True, text=True, timeout=30
        )
        # 等待页面加载
        time.sleep(2)
        # 提取文本
        js_code = f"() => {{ const el = document.querySelector('article') || document.querySelector('.article-content') || document.querySelector('.opus-module-content') || document.querySelector('.bili-rich-text') || document.querySelector('main') || document.body; return el.innerText.substring(0, {max_chars}); }}"
        result = subprocess.run(
            ["manus-mcp-cli", "tool", "call", "browser_evaluate",
             "--server", "playwright", "--input", json.dumps({"function": js_code})],
            capture_output=True, text=True, timeout=15
        )
        # 解析输出
        output = result.stdout
        # 找到 ### Result 后的内容
        if '### Result' in output:
            content = output.split('### Result')[1].split('### Ran')[0].strip()
            # 去掉引号
            if content.startswith('"') and content.endswith('"'):
                content = content[1:-1]
            # 解码\n
            content = content.replace('\\n', '\n').replace('\\t', ' ')
            return content.strip()
        return ""
    except Exception as e:
        print(f"Playwright抓取异常: {e}")
        return ""


def skill_get_weather(city="深圳"):
    """获取真实天气"""
    try:
        r = requests.get(f"https://wttr.in/{city}?format=j1", timeout=10)
        data = r.json()
        current = data.get("current_condition", [{}])[0]
        weather_desc = current.get("lang_zh", [{}])
        if weather_desc:
            desc = weather_desc[0].get("value", current.get("weatherDesc", [{}])[0].get("value", ""))
        else:
            desc = current.get("weatherDesc", [{}])[0].get("value", "")
        return {
            "success": True, "city": city,
            "temperature": current.get("temp_C", "?"),
            "feels_like": current.get("FeelsLikeC", "?"),
            "description": desc,
            "humidity": current.get("humidity", "?"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# Skill 2: 自拍（fal.ai FLUX + Face-Swap 两步法）
# ============================================================

# 小悦的基础外貌描述
XIAOYUE_BASE_FACE = (
    "A young Chinese woman, 23 years old, with long dark hair in twin tails tied with ribbon bows, "
    "straight bangs, soft delicate features, warm brown eyes, gentle natural smile, "
    "clear skin, slim build, natural beauty without heavy makeup. "
)

# 根据地点映射环境描述
LOCATION_TO_ENV = {
    "home_xiaoyue": {
        "env": "cozy small apartment, warm indoor lighting, potted succulents on windowsill, small desk with painting supplies, cat pillow on sofa",
        "objects": ["painting easel", "watercolor palette", "succulent plants", "cat pillow"],
    },
    "home_tangtang": {
        "env": "cute college dorm room, pink bedding, fairy lights on wall, plush toys on bed, small desk with sketchbook and watercolors, warm cozy atmosphere",
        "objects": ["plush bunny", "sketchbook", "fairy lights", "pink pillow", "matcha latte"],
    },
    "cafe_moli": {
        "env": "cozy wooden cafe interior, warm amber lighting, wooden tables, chalkboard menu on wall, coffee machine in background",
        "objects": ["coffee cup", "latte art", "pastry plate", "book on table"],
    },
    "park_central": {
        "env": "beautiful city park, green trees, lake in background, willow trees, jogging path, natural sunlight",
        "objects": ["park bench", "flowers", "lake", "trees"],
    },
    "studio_art": {
        "env": "open art studio, canvases on walls, paint-splattered tables, plaster busts, colorful creative atmosphere",
        "objects": ["paintbrush in hand", "canvas", "color palette", "paint-stained apron"],
    },
    "company_startup": {
        "env": "modern startup office, computer monitors, whiteboard with notes, young team atmosphere, daylight from large windows",
        "objects": ["laptop", "whiteboard", "coffee mug", "sticky notes"],
    },
    "market_street": {
        "env": "busy shopping district, colorful storefronts, bubble tea shops, clothing stores, lively street atmosphere",
        "objects": ["bubble tea cup", "shopping bags", "neon signs"],
    },
    "library": {
        "env": "quiet modern library, tall bookshelves, large floor-to-ceiling windows, study desks, peaceful atmosphere",
        "objects": ["open book", "reading glasses", "notebook"],
    },
}

# 根据时间映射光线和氛围
TIME_TO_LIGHTING = {
    "early_morning": "soft golden morning light, sunrise glow, dewy fresh atmosphere",
    "morning": "bright natural morning light, clear and energetic atmosphere",
    "noon": "bright midday sunlight, warm and vibrant",
    "afternoon": "warm afternoon golden hour light, soft shadows",
    "evening": "warm sunset orange-pink light, golden hour glow",
    "night": "soft warm indoor lighting, city lights bokeh in background, cozy night atmosphere",
    "late_night": "dim warm lamp light, quiet night atmosphere, soft shadows",
}

# 根据时间和场景映射衣服
OUTFIT_MAP = {
    ("work", "morning"): "wearing a casual white blouse and light cardigan, simple necklace, professional but relaxed",
    ("work", "afternoon"): "wearing a casual white blouse and light cardigan, sleeves slightly rolled up",
    ("home", "morning"): "wearing a cozy oversized t-shirt and shorts, hair slightly messy, just woke up look",
    ("home", "evening"): "wearing a soft hoodie and comfortable pants, relaxed at-home look",
    ("home", "night"): "wearing cute pajamas with a blanket nearby, cozy bedtime look",
    ("cafe", "any"): "wearing a nice knit sweater and jeans, casual chic, small crossbody bag",
    ("studio", "any"): "wearing a paint-stained apron over a simple t-shirt, hair tied back, creative messy look",
    ("park", "any"): "wearing a light casual dress or t-shirt with shorts, sneakers, sporty fresh look",
    ("outdoor", "any"): "wearing a light jacket and jeans, comfortable walking outfit, small backpack",
    ("night_out", "any"): "wearing a nice blouse and skirt, light makeup, going-out look",
    ("default", "any"): "wearing casual stylish clothes, natural comfortable look",
}

# 天气对照片的影响
WEATHER_TO_PHOTO = {
    "晴天": "clear blue sky, bright sunlight, vivid colors",
    "多云": "overcast sky, soft diffused light, muted tones",
    "阴天": "grey sky, flat lighting, moody atmosphere",
    "小雨": "light rain, wet surfaces, umbrella, raindrops, reflections",
    "大雨": "heavy rain, holding umbrella, rain streaks, wet hair",
    "雾": "misty foggy atmosphere, soft dreamy look, low visibility",
}


def _get_time_period(hour):
    """将小时转换为时间段"""
    if 5 <= hour < 7:
        return "early_morning"
    elif 7 <= hour < 12:
        return "morning"
    elif 12 <= hour < 14:
        return "noon"
    elif 14 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 21:
        return "evening"
    elif 21 <= hour < 24:
        return "night"
    else:
        return "late_night"


def _get_outfit(location_type, time_period):
    """根据地点类型和时间段选择衣服"""
    # 精确匹配
    key = (location_type, time_period)
    if key in OUTFIT_MAP:
        return OUTFIT_MAP[key]
    # 模糊匹配（any时间）
    key_any = (location_type, "any")
    if key_any in OUTFIT_MAP:
        return OUTFIT_MAP[key_any]
    # 默认
    return OUTFIT_MAP[("default", "any")]


def _location_type_from_id(location_id):
    """从location_id推断地点类型"""
    mapping = {
        "home_xiaoyue": "home",
        "home_tangtang": "home",
        "cafe_moli": "cafe",
        "park_central": "park",
        "studio_art": "studio",
        "company_startup": "work",
        "market_street": "outdoor",
        "library": "cafe",  # 图书馆的穿着类似咖啡馆
    }
    return mapping.get(location_id, "default")


def build_selfie_prompt(location_id="home_xiaoyue", hour=14, weather="晴天",
                        activity="", custom_prompt=None):
    """
    根据世界状态动态构建自拍prompt。
    考虑：衣服、环境、时间光线、天气、正在做的事。
    """
    time_period = _get_time_period(hour)
    loc_type = _location_type_from_id(location_id)

    # 环境
    env_info = LOCATION_TO_ENV.get(location_id, {"env": "indoor setting", "objects": []})
    env_desc = env_info["env"]

    # 光线
    lighting = TIME_TO_LIGHTING.get(time_period, TIME_TO_LIGHTING["afternoon"])

    # 衣服
    outfit = _get_outfit(loc_type, time_period)

    # 天气（只在户外场景影响）
    weather_desc = ""
    if loc_type in ["park", "outdoor"] and weather in WEATHER_TO_PHOTO:
        weather_desc = WEATHER_TO_PHOTO[weather]

    # 关键元素：从环境物品中随机选1-2个
    import random
    objects = env_info.get("objects", [])
    if objects:
        chosen_objects = random.sample(objects, min(2, len(objects)))
        objects_desc = ", ".join(chosen_objects) + " visible in frame"
    else:
        objects_desc = ""

    # 活动描述
    activity_desc = ""
    if activity:
        activity_desc = f"She is {activity}. "

    # 自定义描述（用户请求翻译成英文图片描述）
    custom_desc = ""
    if custom_prompt:
        try:
            translated = client.chat.completions.create(
                model="gemini-3-flash-preview",
                messages=[
                    {"role": "system", "content": "Translate the user's photo request into a short English description for image generation. Focus on outfit, pose, and setting. Keep it under 30 words. If the request is about swimsuit/bikini, describe a tasteful swimsuit photo. If about specific clothing, describe that clothing."},
                    {"role": "user", "content": custom_prompt},
                ],
                max_tokens=60,
                temperature=0.3,
            )
            custom_desc = translated.choices[0].message.content.strip() + ". "
            # 如果用户要求特定服装，覆盖默认outfit
            clothing_keywords = ["swimsuit", "bikini", "dress", "skirt", "uniform", "pajama", "hoodie"]
            if any(kw in custom_desc.lower() for kw in clothing_keywords):
                outfit = custom_desc  # 用用户要求的服装覆盖默认
                custom_desc = ""  # 已经在outfit里了
        except Exception as e:
            print(f"翻译custom_prompt失败: {e}")
            custom_desc = f"{custom_prompt}. "

    # 组装完整prompt
    full_prompt = (
        f"{XIAOYUE_BASE_FACE} "
        f"{outfit}. "
        f"{activity_desc}"
        f"{custom_desc}"
        f"Setting: {env_desc}. "
        f"Lighting: {lighting}. "
        f"{weather_desc + '. ' if weather_desc else ''}"
        f"{objects_desc + '. ' if objects_desc else ''}"
        f"Selfie, phone camera perspective, looking at camera, portrait photo, high quality, realistic."
    )

    return full_prompt


# 场景参考图CDN URLs
SCENE_REF_URLS = {
    "home_bedroom": "https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/iQZPUTzXjbuGhlai.jpg",
    "home_livingroom": "https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/pyOgdRNdXgESmPJs.jpg",
    "cafe_moli": "https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/bCYsFAhUpIcLPiEw.jpg",
    "park_central": "https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/AMAXgIiTALLbLGpa.jpg",
    "studio_art": "https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/evJmkoRyRKqlmLgj.jpg",
    "company_office": "https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/uhwRlcCbJspfqfda.jpg",
    "market_street": "https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/lZDoAAiHRnlpmmwB.jpg",
    "library": "https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/nghslngmZTKjkuxa.jpg",
}


def _get_scene_ref_url(location_id, hour):
    """根据地点和时间选择场景参考图"""
    if location_id in ("home_xiaoyue", "home_tangtang"):
        if hour >= 21 or hour < 7:
            return SCENE_REF_URLS["home_bedroom"]
        else:
            return SCENE_REF_URLS["home_livingroom"]
    mapping = {
        "cafe_moli": "cafe_moli", "park_central": "park_central",
        "studio_art": "studio_art", "company_startup": "company_office",
        "market_street": "market_street", "library": "library",
    }
    key = mapping.get(location_id, "home_livingroom")
    return SCENE_REF_URLS.get(key, SCENE_REF_URLS["home_livingroom"])


def _get_makeup_desc(hour):
    """根据时间判断妆容"""
    if hour >= 21 or hour < 7:
        return "no makeup, bare face, natural skin, slightly messy hair"
    if 7 <= hour < 9:
        return "no makeup, bare face, just woke up, slightly puffy eyes, messy hair"
    return "light natural makeup, subtle lip tint"


def analyze_photo_request(desc, current_hour=None, current_location="home_xiaoyue"):
    """用LLM分析照片描述，判断拍照类型、推断时间/场景、生成标签"""
    if current_hour is None:
        from datetime import datetime, timezone, timedelta
        current_hour = (datetime.now(timezone.utc) + timedelta(hours=8)).hour
    try:
        result = client.chat.completions.create(
            model="gemini-3-flash-preview",
            messages=[
                {"role": "system", "content": """Analyze a photo description from a chat. Return JSON with:
- photo_type (str): one of "selfie", "mirror", "scene".
  - "selfie": front-facing camera self-portrait, face visible, no phone in frame. For: "自拍", "发张照片" (of self), "看看你", "你的照片", "拍个照片".
  - "mirror": mirror selfie, full body visible, phone visible in hand, reflected in mirror. For: "对镜自拍", "穿搭照", "OOTD", "全身照", "照镜子".
  - "scene": rear camera photo of something else (scenery, food, artwork, pets, other people, objects). For: "窗外风景", "拍一下周围", "我画的画", "拍食物", "拍猫咪".
- hour (int 0-23): what time of day the photo depicts. If the description mentions a time (e.g. "早上"=8, "中午"=12, "下午"=15, "晚上"=20, "化妆"=8, "上班"=9, "刚起床"=7), use that time. Only use the current_hour hint if no time is implied at all.
- location_id (str): one of home_xiaoyue, home_tangtang, cafe_moli, park_central, studio_art, company_startup, market_street, library. Use the hint if not clear.
- scene_desc (str): short English description of what the photo shows (under 20 words).
- tag (str): a short Chinese tag, e.g. "自拍", "对镜自拍", "水彩画", "窗外风景", "咖啡", "猫咪", "穿搭"
- is_reusable (bool): whether this is a specific artwork/creation that should look the same if asked again (e.g. a painting, a craft, a pet). False for selfies, scenery, random moments.
Return ONLY valid JSON, no markdown."""},
                {"role": "user", "content": f"Photo description: {desc}\nCurrent hour hint: {current_hour}\nCurrent location hint: {current_location}"},
            ],
            max_tokens=150, temperature=0.2,
        )
        import json as _json
        raw = result.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = _json.loads(raw)
        photo_type = parsed.get("photo_type", "selfie")
        if photo_type not in ("selfie", "mirror", "scene"):
            photo_type = "selfie"  # 安全默认
        return {
            "photo_type": photo_type,
            "hour": parsed.get("hour", current_hour),
            "location_id": parsed.get("location_id", current_location),
            "scene_desc": parsed.get("scene_desc", desc),
            "tag": parsed.get("tag", "照片"),
            "is_reusable": parsed.get("is_reusable", False),
        }
    except Exception as e:
        print(f"analyze_photo_request失败: {e}")
        return {
            "photo_type": "selfie", "hour": current_hour,
            "location_id": current_location, "scene_desc": desc,
            "tag": "自拍", "is_reusable": False,
        }


def skill_take_photo(desc, photo_type="scene", output_dir="/home/ubuntu/chimera/selfies",
                     world_context=None, override_hour=None):
    """
    统一的拍照函数。
    photo_type:
    - "selfie": 前置摄像头自拍，需要人脸参考图，不出现手机
    - "mirror": 对镜自拍，需要人脸参考图，手机可见，全身可见
    - "scene": 拍其他东西（风景/物品/别人/食物等），不需要人脸参考图
    """
    os.makedirs(output_dir, exist_ok=True)
    headers = {
        "Authorization": f"Key {FAL_KEY}",
        "Content-Type": "application/json",
    }

    # 从 world_context 获取信息
    location_id = "home_xiaoyue"
    hour = 14
    weather = "晴天"
    activity = ""
    if world_context:
        location_id = world_context.get("location_id", "home_xiaoyue")
        hour = world_context.get("hour", 14)
        weather = world_context.get("weather", "晴天")
        activity = world_context.get("activity", "")
    if override_hour is not None:
        hour = override_hour

    # 翻译描述为英文
    try:
        translate_instruction = (
            "Translate this photo description into a detailed English prompt for image generation. "
            "Describe the subject, setting, lighting, style, and mood. Keep it under 50 words. "
            "Output ONLY the English prompt."
        )
        translated = client.chat.completions.create(
            model="gemini-3-flash-preview",
            messages=[
                {"role": "system", "content": translate_instruction},
                {"role": "user", "content": desc},
            ],
            max_tokens=80, temperature=0.3,
        )
        en_desc = translated.choices[0].message.content.strip()
    except Exception:
        en_desc = desc

    if photo_type == "selfie":
        return _take_selfie(en_desc, location_id, hour, weather, activity, output_dir, headers)
    elif photo_type == "mirror":
        return _take_mirror_selfie(en_desc, location_id, hour, weather, activity, output_dir, headers)
    else:
        return _take_scene_photo(en_desc, output_dir, headers)


def _take_scene_photo(en_desc, output_dir, headers):
    """非自拍：拍风景/物品/别人/食物等，后置摄像头视角"""
    full_prompt = (
        f"{en_desc}. "
        f"Taken with a smartphone rear camera, realistic photo, natural lighting, "
        f"candid feel, high quality, no watermark."
    )
    print(f"[Photo/Scene] prompt: {full_prompt}")

    try:
        payload = {
            "prompt": full_prompt,
            "image_size": "landscape_4_3",
            "num_images": 1,
        }
        r = requests.post("https://fal.run/fal-ai/flux/schnell",
                         headers=headers, json=payload, timeout=60)
        if r.status_code == 200:
            images = r.json().get("images", [])
            if images:
                img_url = images[0]["url"]
                timestamp = int(time.time())
                filepath = os.path.join(output_dir, f"photo_{timestamp}.jpg")
                img_r = requests.get(img_url, timeout=60)
                with open(filepath, "wb") as f:
                    f.write(img_r.content)
                return {"success": True, "filepath": filepath, "url": img_url, "prompt_used": full_prompt}
        return {"success": False, "error": f"FLUX失败: {r.status_code}"}
    except Exception as e:
        print(f"场景照片生成失败: {e}")
        return {"success": False, "error": str(e)}


def _take_mirror_selfie(en_desc, location_id, hour, weather, activity, output_dir, headers):
    """对镜自拍：后置摄像头对镜子，全身可见，手机可见，需要人脸参考图"""
    scene_ref_url = _get_scene_ref_url(location_id, hour)
    image_urls = [REFERENCE_FACE_URL, scene_ref_url]

    time_descs = [
        (5, 7, "early morning, soft dawn light"),
        (7, 12, "morning, bright natural light"),
        (12, 14, "midday, bright sunlight"),
        (14, 18, "afternoon, warm golden light"),
        (18, 21, "evening, warm sunset light"),
        (21, 24, "night, warm indoor lamp light"),
        (0, 5, "late night, dim warm light"),
    ]
    time_desc = "afternoon, warm light"
    for start, end, td in time_descs:
        if start <= hour < end:
            time_desc = td
            break

    makeup = _get_makeup_desc(hour)
    loc_type = _location_type_from_id(location_id)
    is_night = hour >= 21 or hour < 7
    outfit_map = {
        ("home", True): "wearing oversized t-shirt and shorts, cozy at-home look",
        ("home", False): "wearing casual comfortable clothes, relaxed",
        ("cafe", False): "wearing a nice knit sweater and jeans, casual chic",
        ("park", False): "wearing light casual dress or t-shirt with shorts, sneakers",
        ("studio", False): "wearing paint-stained apron over simple t-shirt, hair tied back",
        ("work", False): "wearing casual white blouse and light cardigan",
        ("outdoor", False): "wearing light jacket and jeans, small backpack",
        ("indoor", False): "wearing comfortable casual clothes",
    }
    outfit = outfit_map.get((loc_type, is_night), outfit_map.get((loc_type, False), "wearing casual clothes"))

    clothing_kw = ["swimsuit", "bikini", "dress", "skirt", "uniform", "pajama", "hoodie", "wearing", "outfit"]
    if any(kw in en_desc.lower() for kw in clothing_kw):
        outfit = en_desc
        en_desc = ""

    prompt = (
        f"A young Chinese woman taking a mirror selfie in a full-length mirror. {makeup}. {outfit}. "
        f"{en_desc + '. ' if en_desc else ''}"
        f"{time_desc}. "
        f"Full body visible in mirror reflection, holding smartphone to take the photo, "
        f"phone visible in hand, natural relaxed pose, "
        f"high quality photo, realistic, candid feel."
    )
    print(f"[Photo/Mirror] prompt: {prompt}")
    print(f"[Photo/Mirror] scene ref: {scene_ref_url}")

    try:
        payload = {
            "prompt": prompt,
            "image_urls": image_urls,
            "image_size": "portrait_4_3",
            "num_images": 1,
            "safety_tolerance": 5,
        }
        r = requests.post("https://fal.run/fal-ai/nano-banana-pro/edit",
                         headers=headers, json=payload, timeout=120)

        if r.status_code == 200:
            result = r.json()
            images = result.get("images", [])
            if images:
                final_url = images[0]["url"]
                timestamp = int(time.time())
                filepath = os.path.join(output_dir, f"mirror_{location_id}_{timestamp}.jpg")
                img_r = requests.get(final_url, timeout=60)
                with open(filepath, "wb") as f:
                    f.write(img_r.content)
                return {"success": True, "filepath": filepath, "url": final_url, "prompt_used": prompt}

        # Fallback到FLUX+face-swap
        print(f"[Photo/Mirror] Nano Banana Pro失败({r.status_code})，fallback到FLUX")
        full_prompt = (
            f"A young Chinese woman, 23 years old, taking a mirror selfie. {makeup}. {outfit}. "
            f"{en_desc + '. ' if en_desc else ''}{time_desc}. "
            f"Full body visible in mirror reflection, holding smartphone, natural pose, realistic."
        )
        payload1 = {"prompt": full_prompt, "image_size": "portrait_4_3", "num_images": 1}
        r1 = requests.post("https://fal.run/fal-ai/flux/schnell",
                          headers=headers, json=payload1, timeout=60)
        if r1.status_code != 200:
            return {"success": False, "error": f"FLUX也失败: {r1.status_code}"}
        target_url = r1.json().get("images", [{}])[0].get("url")
        if not target_url:
            return {"success": False, "error": "FLUX没有生成图片"}
        r2 = requests.post("https://fal.run/fal-ai/face-swap",
                          headers=headers, json={"base_image_url": target_url, "swap_image_url": REFERENCE_FACE_URL},
                          timeout=60)
        final_url = target_url
        if r2.status_code == 200:
            final_url = r2.json().get("image", {}).get("url", target_url)
        timestamp = int(time.time())
        filepath = os.path.join(output_dir, f"mirror_fallback_{timestamp}.jpg")
        img_r = requests.get(final_url, timeout=60)
        with open(filepath, "wb") as f:
            f.write(img_r.content)
        return {"success": True, "filepath": filepath, "url": final_url, "prompt_used": full_prompt}

    except Exception as e:
        print(f"对镜自拍生成失败: {e}")
        return {"success": False, "error": str(e)}


def _take_selfie(en_desc, location_id, hour, weather, activity, output_dir, headers):
    """自拍：前置摄像头视角，用Nano Banana Pro + 人脸参考图"""
    # 场景参考图
    scene_ref_url = _get_scene_ref_url(location_id, hour)
    image_urls = [REFERENCE_FACE_URL, scene_ref_url]

    # 时间描述
    time_descs = [
        (5, 7, "early morning, soft dawn light"),
        (7, 12, "morning, bright natural light"),
        (12, 14, "midday, bright sunlight"),
        (14, 18, "afternoon, warm golden light"),
        (18, 21, "evening, warm sunset light"),
        (21, 24, "night, warm indoor lamp light"),
        (0, 5, "late night, dim warm light"),
    ]
    time_desc = "afternoon, warm light"
    for start, end, td in time_descs:
        if start <= hour < end:
            time_desc = td
            break

    # 妆容
    makeup = _get_makeup_desc(hour)

    # 衣着
    loc_type = _location_type_from_id(location_id)
    is_night = hour >= 21 or hour < 7
    outfit_map = {
        ("home", True): "wearing oversized t-shirt and shorts, cozy at-home look",
        ("home", False): "wearing casual comfortable clothes, relaxed",
        ("cafe", False): "wearing a nice knit sweater and jeans, casual chic",
        ("park", False): "wearing light casual dress or t-shirt with shorts, sneakers",
        ("studio", False): "wearing paint-stained apron over simple t-shirt, hair tied back",
        ("work", False): "wearing casual white blouse and light cardigan",
        ("outdoor", False): "wearing light jacket and jeans, small backpack",
        ("indoor", False): "wearing comfortable casual clothes",
    }
    outfit = outfit_map.get((loc_type, is_night), outfit_map.get((loc_type, False), "wearing casual clothes"))

    # 检查en_desc是否包含衣着描述，如果是则覆盖默认
    clothing_kw = ["swimsuit", "bikini", "dress", "skirt", "uniform", "pajama", "hoodie", "wearing", "outfit"]
    if any(kw in en_desc.lower() for kw in clothing_kw):
        outfit = en_desc
        en_desc = ""  # 已经在outfit里了

    # 组装prompt：前置摄像头视角，不出现手机
    prompt = (
        f"A young Chinese woman taking a selfie. {makeup}. {outfit}. "
        f"{en_desc + '. ' if en_desc else ''}"
        f"{time_desc}. "
        f"Front-facing camera point of view, looking directly at camera, "
        f"natural relaxed expression, upper body and face visible, "
        f"no phone visible in frame, no hand holding phone, "
        f"high quality portrait photo, realistic, candid feel."
    )
    print(f"[Photo/Selfie] prompt: {prompt}")
    print(f"[Photo/Selfie] scene ref: {scene_ref_url}")

    try:
        # Nano Banana Pro/edit
        payload = {
            "prompt": prompt,
            "image_urls": image_urls,
            "image_size": "portrait_4_3",
            "num_images": 1,
            "safety_tolerance": 5,
        }
        r = requests.post("https://fal.run/fal-ai/nano-banana-pro/edit",
                         headers=headers, json=payload, timeout=120)

        if r.status_code == 200:
            result = r.json()
            images = result.get("images", [])
            if images:
                final_url = images[0]["url"]
                timestamp = int(time.time())
                filepath = os.path.join(output_dir, f"selfie_{location_id}_{timestamp}.jpg")
                img_r = requests.get(final_url, timeout=60)
                with open(filepath, "wb") as f:
                    f.write(img_r.content)
                return {"success": True, "filepath": filepath, "url": final_url, "prompt_used": prompt}

        # Fallback到FLUX+face-swap
        print(f"[Photo/Selfie] Nano Banana Pro失败({r.status_code})，fallback到FLUX")
        full_prompt = build_selfie_prompt(
            location_id=location_id, hour=hour, weather=weather,
            activity=activity, custom_prompt=en_desc if en_desc else None,
        )
        payload1 = {"prompt": full_prompt, "image_size": "portrait_4_3", "num_images": 1}
        r1 = requests.post("https://fal.run/fal-ai/flux/schnell",
                          headers=headers, json=payload1, timeout=60)
        if r1.status_code != 200:
            return {"success": False, "error": f"FLUX也失败: {r1.status_code}"}
        target_url = r1.json().get("images", [{}])[0].get("url")
        if not target_url:
            return {"success": False, "error": "FLUX没有生成图片"}
        # face-swap
        r2 = requests.post("https://fal.run/fal-ai/face-swap",
                          headers=headers, json={"base_image_url": target_url, "swap_image_url": REFERENCE_FACE_URL},
                          timeout=60)
        final_url = target_url
        if r2.status_code == 200:
            final_url = r2.json().get("image", {}).get("url", target_url)
        timestamp = int(time.time())
        filepath = os.path.join(output_dir, f"selfie_fallback_{timestamp}.jpg")
        img_r = requests.get(final_url, timeout=60)
        with open(filepath, "wb") as f:
            f.write(img_r.content)
        return {"success": True, "filepath": filepath, "url": final_url, "prompt_used": full_prompt}

    except Exception as e:
        print(f"自拍生成失败: {e}")
        return {"success": False, "error": str(e)}


def skill_generate_selfie(scene="casual", custom_prompt=None,
                          output_dir="/home/ubuntu/chimera/selfies",
                          world_context=None, override_hour=None):
    """兼容入口：内部调用 skill_take_photo(photo_type='selfie')"""
    desc = custom_prompt or scene or "casual selfie"
    return skill_take_photo(desc, photo_type="selfie", output_dir=output_dir,
                            world_context=world_context, override_hour=override_hour)


def skill_generate_scene_photo(prompt_desc, output_dir="/home/ubuntu/chimera/selfies",
                               world_context=None):
    """兼容入口：内部调用 skill_take_photo(photo_type='scene')"""
    return skill_take_photo(prompt_desc, photo_type="scene", output_dir=output_dir,
                            world_context=world_context)


# ============================================================
# Skill 3: 读图 / 读链接（多模态理解）
# ============================================================

def skill_understand_image(image_path_or_url, question="这张图片里有什么？请用中文描述。"):
    """用 GPT-4.1-mini vision 理解图片"""
    try:
        content = [{"type": "text", "text": question}]

        if image_path_or_url.startswith("http"):
            content.append({
                "type": "image_url",
                "image_url": {"url": image_path_or_url},
            })
        else:
            with open(image_path_or_url, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")
            ext = os.path.splitext(image_path_or_url)[1].lower()
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                    ".gif": "image/gif", ".webp": "image/webp"}.get(ext, "image/jpeg")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{img_data}"},
            })

        response = client.chat.completions.create(
            model="gemini-3-flash-preview",
            messages=[{"role": "user", "content": content}],
            max_tokens=500,
        )
        return {"success": True, "description": response.choices[0].message.content}
    except Exception as e:
        return {"success": False, "error": str(e)}


def skill_read_link(url):
    """读取链接内容并总结"""
    fetch_result = skill_fetch_url(url, max_chars=3000)
    if not fetch_result["success"]:
        return {"success": False, "error": fetch_result.get("error", "获取失败")}

    try:
        response = client.chat.completions.create(
            model="gemini-3-flash-preview",
            messages=[
                {"role": "system", "content": "你是一个阅读助手。请用中文简要总结以下网页内容，2-3句话即可。"},
                {"role": "user", "content": f"请总结这个网页的内容：\n\n{fetch_result['content']}"},
            ],
            max_tokens=300,
        )
        return {"success": True, "url": url, "summary": response.choices[0].message.content}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# Skill 4: 语音（TTS）
# ============================================================

def skill_text_to_speech(text, output_dir="/home/ubuntu/chimera/voice", voice="zh-CN-XiaoxiaoNeural"):
    """用 edge-tts 生成自然中文语音。
    
    可选 voice:
    - zh-CN-XiaoxiaoNeural: 温暖自然的年轻女声（默认）
    - zh-CN-XiaoyiNeural: 活泼的年轻女声
    - zh-CN-YunxiNeural: 年轻男声
    """
    import asyncio
    import edge_tts

    os.makedirs(output_dir, exist_ok=True)
    timestamp = int(time.time())
    # edge-tts 输出 mp3，Telegram 可以直接发送
    filename = f"voice_{timestamp}.mp3"
    filepath = os.path.join(output_dir, filename)

    try:
        # 清理文本中的 emoji 和特殊符号（TTS 不需要读出来）
        import re as _re
        clean_text = _re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0000FE00-\U0000FE0F\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000026FF]', '', text)
        clean_text = clean_text.strip()
        if not clean_text:
            return {"success": False, "error": "文本清理后为空"}

        async def _generate():
            communicate = edge_tts.Communicate(clean_text, voice)
            await communicate.save(filepath)

        # 兼容已有事件循环的情况
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                loop.run_in_executor(pool, lambda: asyncio.run(_generate()))
                # 同步等待
                import threading
                done = threading.Event()
                async def _run_and_signal():
                    await _generate()
                    done.set()
                asyncio.ensure_future(_run_and_signal())
                done.wait(timeout=30)
        except RuntimeError:
            # 没有事件循环，直接 run
            asyncio.run(_generate())

        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return {"success": True, "filepath": filepath}
        else:
            return {"success": False, "error": "生成的音频文件为空"}
    except Exception as e:
        print(f"TTS失败: {e}")
        # 降级到 OpenAI TTS
        try:
            ogg_path = filepath.replace('.mp3', '.ogg')
            response = client.audio.speech.create(
                model="tts-1",
                voice="nova",
                input=text,
                response_format="opus",
            )
            response.stream_to_file(ogg_path)
            return {"success": True, "filepath": ogg_path}
        except Exception as e2:
            print(f"TTS降级也失败: {e2}")
            return {"success": False, "error": str(e)}


# ============================================================
# Skill 5: 拍视频（veo3.1）
# ============================================================

YUNWU_BASE_URL = "https://yunwu.ai"


def skill_generate_video(prompt, image_path=None, output_dir="/home/ubuntu/chimera/videos",
                         aspect_ratio="9:16"):
    """用 veo3.1-fast 生成短视频。如果没有image_path，先生成一张自拍作为起始帧。"""
    os.makedirs(output_dir, exist_ok=True)

    if not YUNWU_API_KEY:
        return {"success": False, "error": "视频功能暂不可用（需要YUNWU_API_KEY）"}

    # 如果没有起始帧，先生成一张
    if not image_path:
        selfie = skill_generate_selfie("casual", prompt)
        if not selfie.get("success"):
            return {"success": False, "error": "无法生成起始帧"}
        image_path = selfie["filepath"]

    # 上传图片
    try:
        result = subprocess.run(
            ["manus-upload-file", image_path],
            capture_output=True, text=True, timeout=120
        )
        urls = re.findall(r'https?://[^\s]+', result.stdout.strip())
        if not urls:
            return {"success": False, "error": "图片上传失败"}
        image_url = urls[-1]
    except Exception as e:
        return {"success": False, "error": f"上传异常: {e}"}

    # 创建任务
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {YUNWU_API_KEY}"
    }
    payload = {
        "model": "veo3.1-fast",
        "prompt": prompt,
        "images": [image_url],
        "enhance_prompt": True,
        "enable_upsample": True,
        "aspect_ratio": aspect_ratio,
    }

    try:
        r = requests.post(f"{YUNWU_BASE_URL}/v1/video/create",
                         headers=headers, json=payload, timeout=60)
        result = r.json()
        if not result.get("id"):
            return {"success": False, "error": f"任务创建失败: {result}"}
        task_id = result["id"]
    except Exception as e:
        return {"success": False, "error": f"API调用失败: {e}"}

    # 轮询（最多5分钟）
    for _ in range(20):
        time.sleep(15)
        try:
            r = requests.get(f"{YUNWU_BASE_URL}/v1/video/query",
                           headers=headers, params={"id": task_id}, timeout=30)
            info = r.json()
            status = info.get("status", "unknown")

            if status == "completed":
                video_url = info.get("video_url") or info.get("url")
                if video_url:
                    filepath = os.path.join(output_dir, f"video_{int(time.time())}.mp4")
                    vid_r = requests.get(video_url, stream=True, timeout=300)
                    with open(filepath, "wb") as f:
                        for chunk in vid_r.iter_content(chunk_size=8192):
                            f.write(chunk)
                    return {"success": True, "filepath": filepath, "task_id": task_id}
                return {"success": False, "error": "完成但无视频URL"}
            elif status in ["failed", "error"]:
                return {"success": False, "error": f"生成失败: {info}"}
        except Exception as e:
            print(f"轮询异常: {e}")

    return {"success": False, "error": "超时（5分钟）"}


# ============================================================
# Skill 7: 多平台浏览（小红书/豆瓣/微博）
# 通过 CDP 连接真实 Chromium 浏览器，cookie 由 user-data-dir 持久化
# ============================================================

try:
    from browser_pool import get_context as _get_browser_context
    from browser_pool import new_page as _new_page
    from browser_pool import start_browser as _start_browser
except ImportError:
    _get_browser_context = None
    _new_page = None
    _start_browser = None

try:
    from browser_login import get_login_status as _get_login_status
    from browser_login import is_waiting_for_input as _is_waiting_for_input
except ImportError:
    _get_login_status = None
    _is_waiting_for_input = None

# 小红书话题库：女生日常、生活、情感类
XHS_TOPICS = [
    "女生日常", "闺蜜日常", "大学生日常", "打工人日常",
    "今日碎碎念", "生活碎片", "日常吐槽", "emo了",
    "恋爱日常", "单身日常", "室友日常", "下班后的生活",
    "今天的快乐", "深夜emo", "周末日常", "独居日常",
]

# 豆瓣小组：女生聚集的生活/情感小组
DOUBAN_GROUPS = [
    "652046",   # 豆瓣劝分小组 (37万)
    "blabla",   # 人间情侣观察 (26万)
    "711632",   # 今天我没有生气 (26万)
    "694182",   # 我今天遇到一个crush (18万)
    "711767",   # 内在力量研究中心 (19万)
    "738593",   # 友谊的小船 (8万)
]

# 微博话题
WEIBO_TOPICS = [
    "女生日常", "闺蜜聊天", "今日份快乐", "打工人吐槽",
    "恋爱脑", "单身狗日常", "大学生日常",
]


def _safe_goto(page, url, timeout=30000, retries=2):
    """
    安全的页面导航：支持重试、多种等待策略。
    优先用 commit（首字节到达），失败后降级到 domcontentloaded。
    """
    last_err = None
    for attempt in range(retries):
        try:
            page.goto(url, timeout=timeout, wait_until='commit')
            # commit 后等待关键内容渲染
            page.wait_for_timeout(3000)
            return True
        except Exception as e:
            last_err = e
            logger.warning("导航尝试 %d/%d 失败 (%s): %s", attempt + 1, retries, url, e)
            # 如果页面已经部分加载了（URL 变了），也算成功
            try:
                if page.url and page.url != 'about:blank' and page.url != url:
                    page.wait_for_timeout(2000)
                    return True
            except Exception:
                pass
            if attempt < retries - 1:
                page.wait_for_timeout(2000)
    logger.error("导航最终失败 (%s): %s", url, last_err)
    return False


def _get_or_create_page(ctx):
    """
    复用已有空白标签页，或创建新标签页。
    同时清理多余的标签页（保留最多 3 个）。
    """
    pages = ctx.pages
    # 清理多余标签页（保留最多 3 个）
    while len(pages) > 3:
        try:
            pages[0].close()
            pages = ctx.pages
        except Exception:
            break
    # 尝试复用空白页
    for p in pages:
        try:
            if p.url in ('about:blank', 'chrome://newtab/', ''):
                return p
        except Exception:
            continue
    # 没有空白页，创建新的
    return ctx.new_page()


def skill_xhs_browse(keyword=None):
    """刷小红书：用 CDP 浏览器直接浏览小红书 explore 页，点进笔记看详情+评论"""
    import random as _random
    if not keyword:
        keyword = _random.choice(XHS_TOPICS)

    print(f"📱 刷小红书: {keyword}")
    content_parts = []

    if not _get_browser_context:
        return _xhs_fallback_search(keyword)

    page = None
    try:
        ctx = _get_browser_context()
        page = _get_or_create_page(ctx)

        # 直接访问 explore 页
        if not _safe_goto(page, 'https://www.xiaohongshu.com/explore', timeout=30000, retries=2):
            # 导航失败但页面可能已部分加载，检查一下
            try:
                current_url = page.url
                if 'xiaohongshu.com' not in current_url:
                    return _xhs_fallback_search(keyword)
            except Exception:
                return _xhs_fallback_search(keyword)

        # 等待笔记卡片出现（最多 10 秒）
        try:
            page.wait_for_selector('section.note-item, [class*="note-item"], .feeds-container a', timeout=10000)
        except Exception:
            logger.warning("小红书笔记卡片未出现，尝试提取页面文本")

        # 从 explore 页提取笔记列表
        notes = page.evaluate("""
            () => {
                const items = [];
                // 多种选择器兼容不同版本的小红书页面
                const noteEls = document.querySelectorAll('section.note-item, [class*="note-item"]');
                noteEls.forEach(el => {
                    const text = el.textContent?.trim() || '';
                    const links = el.querySelectorAll('a[href*="/explore/"], a[href*="/search_result/"], a[href*="/discovery/item/"]');
                    let link = '';
                    for (const a of links) {
                        if (a.href.includes('xsec_token')) { link = a.href; break; }
                        if (!link) link = a.href;
                    }
                    if (text && text.length > 3) {
                        items.push({title: text.substring(0, 100), link});
                    }
                });
                // 降级：从 feeds-container 中提取
                if (items.length === 0) {
                    document.querySelectorAll('.feeds-container a[href*="/explore/"]').forEach(a => {
                        const text = a.textContent?.trim() || '';
                        if (text.length > 3) items.push({title: text.substring(0, 100), link: a.href});
                    });
                }
                return items;
            }
        """)

        if notes and len(notes) > 0:
            note = _random.choice(notes[:8])
            print(f"  📝 看笔记: {note.get('title', '')[:40]}")

            link = note.get('link', '')
            if link:
                try:
                    if not _safe_goto(page, link, timeout=20000, retries=2):
                        content_parts.append(f"标题: {note.get('title', '')}")
                    else:
                        # 等待正文出现
                        try:
                            page.wait_for_selector('#detail-title, [class*="title"], .note-text', timeout=8000)
                        except Exception:
                            pass
                        # 滚动触发懒加载
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
                        page.wait_for_timeout(1500)
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.8)")
                        page.wait_for_timeout(1500)

                        detail = page.evaluate("""
                            () => {
                                const title = document.querySelector('#detail-title')?.textContent?.trim()
                                    || document.querySelector('[class*="title"]')?.textContent?.trim() || '';
                                const desc = document.querySelector('#detail-desc')?.textContent?.trim()
                                    || document.querySelector('[class*="desc"]')?.textContent?.trim()
                                    || document.querySelector('.note-text')?.textContent?.trim() || '';
                                const comments = [];
                                const seen = new Set();
                                document.querySelectorAll('.parent-comment > .comment-item, .comment-item:not(.comment-item-sub)').forEach(el => {
                                    const inner = el.querySelector('.comment-inner-container');
                                    if (!inner) return;
                                    const author = el.querySelector('.author-wrapper .name')?.textContent?.trim() || '';
                                    const contentEl = inner.querySelector('.content, .comment-content');
                                    let commentText = '';
                                    if (contentEl) {
                                        commentText = contentEl.textContent?.trim();
                                    } else {
                                        commentText = inner.textContent?.trim()
                                            .replace(/[0-9]+天前|[0-9]+小时前|昨天|[0-9]+分钟前/g, '')
                                            .replace(/赞|回复|作者|置顶评论/g, '')
                                            .replace(/\s+/g, ' ').trim();
                                    }
                                    if (commentText && commentText.length > 2 && !seen.has(commentText)) {
                                        seen.add(commentText);
                                        comments.push(author ? `${author}: ${commentText}` : commentText);
                                    }
                                });
                                if (comments.length === 0) {
                                    document.querySelectorAll('.comment-item').forEach(el => {
                                        const text = el.innerText?.trim();
                                        if (text && text.length > 5 && text.length < 500 && !seen.has(text)) {
                                            seen.add(text);
                                            comments.push(text.substring(0, 200));
                                        }
                                    });
                                }
                                return { title, content: desc.substring(0, 1500), comments: comments.slice(0, 15) };
                            }
                        """)

                        if detail.get('title'):
                            content_parts.append(f"标题: {detail['title']}")
                        if detail.get('content'):
                            content_parts.append(f"正文: {detail['content']}")
                        if detail.get('comments'):
                            content_parts.append("评论:")
                            for c in detail['comments']:
                                content_parts.append(f"  - {c}")
                except Exception as e:
                    logger.warning("详情页抓取失败: %s", e)
                    content_parts.append(f"标题: {note.get('title', '')}")
            else:
                content_parts.append(f"标题: {note.get('title', '')}")

        # 如果还是没内容，抓页面纯文本
        if not content_parts:
            text = page.evaluate("() => document.body.innerText.substring(0, 1500)")
            if text and len(text) > 50:
                content_parts.append(text)

    except Exception as e:
        logger.error("小红书浏览异常: %s", e)
        return _xhs_fallback_search(keyword)
    finally:
        try:
            if page:
                page.close()
        except Exception:
            pass

    content = "\n".join(content_parts)
    return {"success": bool(content), "content": content, "source": "xiaohongshu", "keyword": keyword}


def _xhs_fallback_search(keyword):
    """小红书降级方案：用ddgs搜索"""
    content_parts = []
    try:
        query = f"site:xiaohongshu.com {keyword}"
        results = skill_web_search(query, num_results=5)
        if not results.get("success") or not results.get("results"):
            results = skill_web_search(f"小红书 {keyword}", num_results=5)
        if results.get("results"):
            for r in results["results"][:3]:
                title = r.get("title", "")
                body = r.get("snippet", "")
                if title:
                    content_parts.append(f"标题: {title}")
                if body:
                    content_parts.append(f"内容: {body}")
                content_parts.append("")
    except Exception as e:
        print(f"小红书搜索降级也失败: {e}")
    content = "\n".join(content_parts)
    return {"success": bool(content), "content": content, "source": "xiaohongshu", "keyword": keyword}


def skill_douban_browse(group_id=None):
    """刷豆瓣：从讨论精选页抽帖子，提取正文+评论"""
    import random as _random
    print(f"📚 刷豆瓣")
    content_parts = []

    if not _get_browser_context:
        return {"success": False, "content": "", "source": "douban", "error": "browser_pool 不可用"}

    page = None
    try:
        ctx = _get_browser_context()
        page = _get_or_create_page(ctx)

        # 第一步：访问讨论精选页
        if not _safe_goto(page, 'https://www.douban.com/group/explore', timeout=25000, retries=2):
            logger.warning("豆瓣导航失败，降级到搜索")
            results = skill_web_search("豆瓣小组 女生日常", num_results=5)
            if results.get("results"):
                for r in results["results"][:3]:
                    if r.get("title"): content_parts.append(f"标题: {r['title']}")
                    if r.get("snippet"): content_parts.append(f"内容: {r['snippet']}")
                    content_parts.append("")
            content = "\n".join(content_parts)
            return {"success": bool(content), "content": content, "source": "douban"}

        # 第二步：提取帖子链接
        topics = page.evaluate("""
            () => {
                return [...document.querySelectorAll('a[href*="/group/topic/"]')]
                    .map(a => ({title: a.textContent.trim(), url: a.href}))
                    .filter(l => l.title.length > 4 && l.url.includes('/group/topic/'))
                    .slice(0, 20);
            }
        """)

        if not topics:
            print("  ❌ explore页没找到帖子")
            # 降级：用ddgs搜索
            results = skill_web_search("豆瓣小组 女生日常", num_results=5)
            if results.get("results"):
                for r in results["results"][:3]:
                    if r.get("title"): content_parts.append(f"标题: {r['title']}")
                    if r.get("body"): content_parts.append(f"内容: {r['body']}")
                    content_parts.append("")
            content = "\n".join(content_parts)
            return {"success": bool(content), "content": content, "source": "douban"}

        # 随机选一个帖子
        topic = _random.choice(topics[:8])
        print(f"  📝 看帖子: {topic['title'][:30]}")

        # 第三步：访问帖子
        _safe_goto(page, topic['url'], timeout=20000, retries=2)

        # 第四步：提取帖子正文 + 评论
        data = page.evaluate("""
            () => {
                const post = document.querySelector('.topic-richtext, .topic-content, .rich-content')?.innerText || '';
                const comments = [];
                const seen = new Set();
                document.querySelectorAll('.reply-content, .comment-item .reply-content, li[id] .reply-doc, .reply-doc .reply-content').forEach(el => {
                    const text = el.innerText?.trim();
                    if (text && text.length > 2 && text.length < 500 && !seen.has(text)) {
                        seen.add(text);
                        comments.push(text);
                    }
                });
                // 如果以上都没抓到，用body全文
                const bodyText = document.body?.innerText?.substring(0, 3000) || '';
                return {post: post.substring(0, 1500), comments: comments.slice(0, 30), title: document.title, bodyText};
            }
        """)

        if data.get('post'):
            content_parts.append(f"帖子: {data.get('title', '')[:50]}")
            content_parts.append(data['post'])
        if data.get('comments'):
            content_parts.append(f"\n评论区 ({len(data['comments'])}条):")
            for c in data['comments']:
                content_parts.append(f"  - {c}")
        # 兆底
        if not content_parts and data.get('bodyText'):
            content_parts.append(f"页面内容: {data['bodyText'][:1500]}")

    except Exception as e:
        print(f"豆瓣浏览异常: {e}")
    finally:
        if page:
            try: page.close()
            except Exception: pass

    content = "\n".join(content_parts)
    return {"success": bool(content), "content": content, "source": "douban"}


def skill_weibo_browse(keyword=None):
    """刷微博：用 CDP 浏览器看热搜页面，提取微博内容"""
    import random as _random
    if not keyword:
        keyword = _random.choice(WEIBO_TOPICS)

    print(f"📰 刷微博: {keyword}")
    content_parts = []

    if not _get_browser_context:
        return {"success": False, "content": "", "source": "weibo", "error": "browser_pool 不可用"}

    page = None
    try:
        ctx = _get_browser_context()
        page = _get_or_create_page(ctx)

        # 微博热搜页面（JS 较重，用 domcontentloaded + 更长等待）
        try:
            page.goto('https://weibo.com/hot/search', timeout=30000, wait_until='domcontentloaded')
        except Exception as nav_err:
            logger.warning("微博导航异常: %s，检查页面状态", nav_err)
            try:
                if 'weibo.com' not in page.url:
                    return {"success": False, "content": "", "source": "weibo", "error": "导航失败"}
            except Exception:
                return {"success": False, "content": "", "source": "weibo", "error": "导航失败"}

        # 微博 JS 渲染较慢，等待内容元素出现
        try:
            page.wait_for_selector('[class*="Feed"], .card-wrap, [class*="hot-topic"], .wbpro-feed, [node-type="feed_list"]', timeout=15000)
        except Exception:
            logger.warning("微博内容元素未出现，尝试滚动触发渲染")
        # 滚动触发懒加载
        page.evaluate("window.scrollTo(0, 500)")
        page.wait_for_timeout(3000)
        page.evaluate("window.scrollTo(0, 1000)")
        page.wait_for_timeout(2000)

        # 提取微博热搜内容
        # 微博热搜页的 DOM 结构是纯文本列表，直接从 body text 中提取
        posts = page.evaluate("""
            () => {
                const posts = [];
                const seen = new Set();
                const noise = ['Video Player', 'modal window', 'dialog window', 'Opacity',
                    'ColorWhite', 'Semi-Transparent', 'Close Modal', 'Beginning of',
                    'End of dialog', 'is loading', 'Escape will cancel', '\u65e0\u969c\u788d',
                    '\u5173\u6ce8', '\u6362\u4e00\u6362', '\u521b\u4f5c\u8005\u4e2d\u5fc3', '\u5e2e\u52a9\u4e2d\u5fc3',
                    '\u5fae\u535a\u5ba2\u670d', '\u5f00\u653e\u5e73\u53f0', '\u4e3e\u62a5\u4e2d\u5fc3', 'Copyright',
                    '\u8425\u4e1a\u6267\u7167', '\u7f51\u7ad9\u5907\u6848', '\u5fae\u535a\u62db\u8058',
                    '没有更多内容了', '你可能感兴趣的人', '微博原创视频博主',
                    '客户端下载', '微博隐私', '合作热线', '自助服务中心',
                    '违规投诉', '处理大厅', '舞弊举报', 'About Weibo',
                    '数据中心', '内容管理', '收益中心', '私信管理',
                    '进入创作者中心', '常见问题', '微博营销', '扮演者'];
                function isNoise(text) {
                    return noise.some(n => text.includes(n));
                }
                
                // \u65b9\u6848 1\uff1a\u5c1d\u8bd5\u4ece\u5217\u8868\u5143\u7d20\u4e2d\u63d0\u53d6
                const listSelectors = [
                    '[class*="HotTopic"] [class*="title"]',
                    '[class*="hot"] [class*="title"]',
                    '.card-wrap .content .txt',
                    '.wbpro-feed-content',
                ];
                for (const sel of listSelectors) {
                    document.querySelectorAll(sel).forEach(el => {
                        const text = el.innerText?.trim();
                        if (text && text.length > 4 && text.length < 200 && !seen.has(text) && !isNoise(text)) {
                            const chineseCount = (text.match(/[\u4e00-\u9fff]/g) || []).length;
                            if (chineseCount >= 2) {
                                seen.add(text);
                                posts.push(text);
                            }
                        }
                    });
                }
                
                // \u65b9\u6848 2\uff1a\u4ece body \u6587\u672c\u4e2d\u63d0\u53d6\u70ed\u641c\u6761\u76ee\uff08\u5fae\u535a\u70ed\u641c\u9875\u662f\u7eaf\u6587\u672c\u5217\u8868\uff09
                if (posts.length < 5) {
                    const body = document.body.innerText;
                    const lines = body.split(String.fromCharCode(10));
                    // 页脚截断标志 — 这些内容之后都是推荐博主和底部链接
                    const footerMarkers = ['换一换', '创作者中心', '帮助中心', '微博客服'];
                    let hitFooter = false;
                    for (const line of lines) {
                        const text = line.trim();
                        if (!text) continue;
                        // 检查是否到达页脚区域
                        if (footerMarkers.some(m => text.includes(m))) { hitFooter = true; break; }
                        if (text.length < 4 || text.length > 200) continue;
                        if (seen.has(text) || isNoise(text)) continue;
                        const chineseCount = (text.match(/[一-鿿]/g) || []).length;
                        const isNumber = /^[\d,]+$/.test(text);
                        const isNav = ['推荐', '热门推荐', '热门榜单', '微博热搜', '我的', '热搜', '文娱', '生活', '社会'].includes(text);
                        if (chineseCount >= 2 && !isNumber && !isNav) {
                            seen.add(text);
                            posts.push(text);
                        }
                    }
                }
                return posts.slice(0, 30);
            }
        """)

        if posts:
            content_parts.append(f"微博热搜内容 ({len(posts)}条):")
            for p in posts:
                content_parts.append(f"  - {p}")
        else:
            # 兆底：直接取页面文本
            body = page.evaluate("() => document.body.innerText.substring(0, 2000)")
            if body and len(body) > 50:
                content_parts.append(f"微博页面内容:\n{body}")

    except Exception as e:
        print(f"微博浏览异常: {e}")
    finally:
        if page:
            try: page.close()
            except Exception: pass

    content = "\n".join(content_parts)
    return {"success": bool(content), "content": content, "source": "weibo", "keyword": keyword}


# ============================================================
# Skill 路由器
# ============================================================

def route_skill(user_message, agent_context="", has_photo=False):
    """判断是否需要使用skill——基于规则快速匹配"""
    msg = user_message.lower().strip()

    # 用户发了图片
    if has_photo:
        return {"skill": "see_image", "question": "这张图片里有什么？请用中文描述。"}

    # URL检测
    url_match = re.search(r'https?://\S+', user_message)
    if url_match:
        return {"skill": "read_link", "url": url_match.group()}

    # 天气关键词
    if any(kw in msg for kw in ["天气", "气温", "下雨", "温度", "多少度"]):
        city = "深圳"
        for c in ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "重庆", "西安"]:
            if c in msg:
                city = c
                break
        return {"skill": "weather", "city": city}

    # 自拍关键词
    if any(kw in msg for kw in ["自拍", "照片", "发张照", "看看你", "发个照", "拍张照",
                                  "发张图", "你的照片", "发个图", "拍个照", "看你",
                                  "你在哪拍", "发一张", "泳衣", "穿裙子", "穿什么"]):
        scene = "casual"
        custom = None
        if any(kw in msg for kw in ["咖啡", "cafe"]):
            scene = "cafe"
        elif any(kw in msg for kw in ["画室", "画画"]):
            scene = "studio"
        elif any(kw in msg for kw in ["公园", "户外", "外面"]):
            scene = "park" if "公园" in msg else "outdoor"
        elif any(kw in msg for kw in ["晚上", "夜"]):
            scene = "night"
        elif any(kw in msg for kw in ["上班", "工作", "办公"]):
            scene = "work"
        elif any(kw in msg for kw in ["穿搭", "衣服", "outfit", "全身", "泳衣", "穿裙子", "穿什么"]):
            scene = "mirror"
        # 把用户的原始请求作为custom_prompt传给图片生成
        custom = user_message
        return {"skill": "selfie", "scene": scene, "custom_prompt": custom}

    # 语音关键词
    if any(kw in msg for kw in ["语音", "说给我听", "用声音", "发个语音", "想听你说", "听你的声音"]):
        return {"skill": "voice", "text": ""}

    # 视频关键词
    if any(kw in msg for kw in ["视频", "拍个视频", "录个视频", "vlog", "拍个vlog"]):
        return {"skill": "video", "prompt": user_message}

    # 搜索关键词
    if any(kw in msg for kw in ["搜一下", "搜索", "查一下", "帮我查", "帮我搜"]):
        return {"skill": "search", "query": user_message}

    # 默认不使用skill
    return {"skill": "none"}


def execute_skill(skill_params, image_path=None, world_context=None):
    """执行skill调用"""
    skill = skill_params.get("skill", "none")

    if skill == "search":
        return skill_web_search(skill_params.get("query", ""))
    elif skill in ("selfie", "scene_photo", "photo", "mirror"):
        desc = skill_params.get("prompt") or skill_params.get("custom_prompt") or skill_params.get("scene", "casual selfie")
        # 确定 photo_type：优先用显式传入的，否则从 skill 名推断
        photo_type = skill_params.get("photo_type")
        if not photo_type:
            photo_type = {"selfie": "selfie", "mirror": "mirror", "scene_photo": "scene", "photo": "scene"}.get(skill, "scene")
        return skill_take_photo(
            desc, photo_type=photo_type,
            world_context=world_context,
            override_hour=skill_params.get("override_hour"))
    elif skill == "see_image":
        if image_path:
            return skill_understand_image(image_path, skill_params.get("question", "这张图片里有什么？请用中文描述。"))
        return {"success": False, "error": "没有收到图片"}
    elif skill == "read_link":
        return skill_read_link(skill_params.get("url", ""))
    elif skill == "voice":
        return skill_text_to_speech(skill_params.get("text", ""))
    elif skill == "video":
        return skill_generate_video(skill_params.get("prompt", ""))
    elif skill == "weather":
        return skill_get_weather(skill_params.get("city", "深圳"))
    elif skill == "browse_xhs":
        return skill_xhs_browse(skill_params.get("keyword"))
    elif skill == "browse_douban":
        return skill_douban_browse(skill_params.get("group_id"))
    elif skill == "browse_weibo":
        return skill_weibo_browse(skill_params.get("keyword"))
    elif skill == "check_login":
        if _get_login_status:
            return {"success": True, "status": _get_login_status()}
        return {"success": False, "error": "登录模块未加载"}

    return {"skill": "none"}
