"""
Skills 模块 - 小悦的能力系统
包含：上网搜索、自拍(fal.ai flux+face-swap)、读图/读链接、语音(TTS)、拍视频(veo3.1)
"""

import os
import json
import re
import time
import base64
import subprocess
import requests
from pathlib import Path
from openai import OpenAI

client = OpenAI()

FAL_KEY = os.environ.get("FAL_KEY", "b6d0f15a-4115-468e-b74b-70a8b038a7ff:27058454565d68bb1c0bf79982b25a24")
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
    except:
        pass

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
                model="gpt-4.1-nano",
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


def skill_generate_selfie(scene="casual", custom_prompt=None,
                          output_dir="/home/ubuntu/chimera/selfies",
                          world_context=None):
    """
    用 Nano Banana Pro/edit 生成小悦的自拍。
    传入：脸部参考图 + 场景参考图 → 一步生成一致性照片。
    如果失败，fallback到FLUX+face-swap。
    """
    os.makedirs(output_dir, exist_ok=True)

    # 从world_context获取信息
    location_id = "home_xiaoyue"
    hour = 14
    weather = "晴天"
    activity = ""
    if world_context:
        location_id = world_context.get("location_id", "home_xiaoyue")
        hour = world_context.get("hour", 14)
        weather = world_context.get("weather", "晴天")
        activity = world_context.get("activity", "")

    # 选择场景参考图
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
    for start, end, desc in time_descs:
        if start <= hour < end:
            time_desc = desc
            break

    # 妆容
    makeup = _get_makeup_desc(hour)

    # 衣着
    loc_type = {
        "home_xiaoyue": "home", "home_tangtang": "home", "cafe_moli": "cafe", "park_central": "park",
        "studio_art": "studio", "company_startup": "work",
        "market_street": "outdoor", "library": "indoor",
    }.get(location_id, "home")
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

    # 自定义描述（用户请求翻译成英文）
    custom_desc = ""
    if custom_prompt:
        try:
            translated = client.chat.completions.create(
                model="gpt-4.1-nano",
                messages=[
                    {"role": "system", "content": "Translate the user's photo request into a short English description for image generation. Focus on outfit, pose, and setting. Keep it under 30 words."},
                    {"role": "user", "content": custom_prompt},
                ],
                max_tokens=60, temperature=0.3,
            )
            custom_desc = translated.choices[0].message.content.strip()
            clothing_kw = ["swimsuit", "bikini", "dress", "skirt", "uniform", "pajama", "hoodie", "wearing"]
            if any(kw in custom_desc.lower() for kw in clothing_kw):
                outfit = custom_desc
                custom_desc = ""
        except Exception as e:
            print(f"翻译custom_prompt失败: {e}")

    # 组装prompt
    prompt = (
        f"A selfie photo of a young Chinese woman, 23 years old. "
        f"{makeup}. {outfit}. "
        f"{custom_desc + '. ' if custom_desc else ''}"
        f"{time_desc}. "
        f"Phone camera selfie perspective, looking at camera, natural pose, "
        f"high quality portrait photo, realistic, candid feel."
    )
    print(f"[Selfie] Nano Banana Pro prompt: {prompt}")
    print(f"[Selfie] Scene ref: {scene_ref_url}")

    headers = {
        "Authorization": f"Key {FAL_KEY}",
        "Content-Type": "application/json",
    }

    try:
        # 尝试 Nano Banana Pro/edit
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
                filename = f"selfie_{location_id}_{timestamp}.jpg"
                filepath = os.path.join(output_dir, filename)
                img_r = requests.get(final_url, timeout=60)
                with open(filepath, "wb") as f:
                    f.write(img_r.content)
                return {"success": True, "filepath": filepath, "url": final_url, "prompt_used": prompt}

        # Nano Banana Pro失败，fallback到FLUX+face-swap
        print(f"[Selfie] Nano Banana Pro失败({r.status_code})，fallback到FLUX")
        full_prompt = build_selfie_prompt(
            location_id=location_id, hour=hour, weather=weather,
            activity=activity, custom_prompt=custom_prompt,
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
            model="gpt-4.1-mini",
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
            model="gpt-4.1-mini",
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

def skill_text_to_speech(text, output_dir="/home/ubuntu/chimera/voice", voice="nova"):
    """用 OpenAI TTS 生成语音，voice=nova（年轻女性）"""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = int(time.time())
    filename = f"voice_{timestamp}.ogg"
    filepath = os.path.join(output_dir, filename)

    try:
        response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            response_format="opus",
        )
        response.stream_to_file(filepath)
        return {"success": True, "filepath": filepath}
    except Exception as e:
        print(f"TTS失败: {e}")
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
# 用 browser_pool 管理 Playwright 浏览器实例，复用 Chromium cookie
# ============================================================

try:
    from browser_pool import get_context as _get_browser_context
except ImportError:
    _get_browser_context = None

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


def skill_xhs_browse(keyword=None):
    """刷小红书：用ddgs搜索小红书公开内容（headless被反爬拦截，降级方案）"""
    import random as _random
    if not keyword:
        keyword = _random.choice(XHS_TOPICS)

    print(f"📱 刷小红书: {keyword}")
    content_parts = []

    try:
        # 用ddgs搜索小红书内容
        query = f"site:xiaohongshu.com {keyword}"
        results = skill_web_search(query, num_results=5)
        if not results.get("success") or not results.get("results"):
            # 备用：不限制site
            results = skill_web_search(f"小红书 {keyword}", num_results=5)

        if results.get("results"):
            content_parts.append(f"小红书搜索\"{keyword}\"结果:")
            for r in results["results"][:3]:
                title = r.get("title", "")
                body = r.get("body", "")
                if title:
                    content_parts.append(f"  标题: {title}")
                if body:
                    content_parts.append(f"  内容: {body}")
                content_parts.append("")

                # 尝试抓取完整内容
                url = r.get("href", "")
                if url and "xiaohongshu.com" in url:
                    try:
                        fetched = skill_fetch_url(url)
                        if fetched.get("success") and len(fetched.get("content", "")) > 100:
                            content_parts.append(f"  详细内容: {fetched['content'][:800]}")
                    except:
                        pass

    except Exception as e:
        print(f"小红书搜索异常: {e}")

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
        page = ctx.new_page()

        # 第一步：访问讨论精选页（不需要登录，内容丰富）
        page.goto('https://www.douban.com/group/explore', timeout=15000, wait_until='domcontentloaded')
        page.wait_for_timeout(3000)

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
        page.goto(topic['url'], timeout=15000, wait_until='domcontentloaded')
        page.wait_for_timeout(3000)

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
            except: pass

    content = "\n".join(content_parts)
    return {"success": bool(content), "content": content, "source": "douban"}


def skill_weibo_browse(keyword=None):
    """刷微博：用 browser_pool 看热搜页面，提取微博内容"""
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
        page = ctx.new_page()

        # 用微博热搜页面（不需要登录，内容丰富）
        page.goto('https://weibo.com/hot/search', timeout=15000, wait_until='domcontentloaded')
        page.wait_for_timeout(4000)

        # 提取微博内容：热搜页面的微博内容
        posts = page.evaluate("""
            () => {
                const posts = [];
                const seen = new Set();
                // 热搜页面的微博内容
                const selectors = [
                    '.card-wrap .content .txt',
                    '.card .txt',
                    '[class*="Feed_body"] [class*="detail"]',
                    '.wbpro-feed-content',
                    '[class*="text"]',
                ];
                for (const sel of selectors) {
                    document.querySelectorAll(sel).forEach(el => {
                        const text = el.innerText?.trim();
                        if (text && text.length > 15 && text.length < 500 && !seen.has(text)) {
                            seen.add(text);
                            posts.push(text);
                        }
                    });
                }
                // 如果上面都没抓到，用更宽泛的选择器
                if (posts.length === 0) {
                    const body = document.body.innerText;
                    // 按换行分割，取有意义的段落
                    body.split('\\n').forEach(line => {
                        const text = line.trim();
                        if (text.length > 20 && text.length < 500 && !seen.has(text)) {
                            seen.add(text);
                            posts.push(text);
                        }
                    });
                }
                return posts.slice(0, 20);
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
            except: pass

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
    elif skill == "selfie":
        return skill_generate_selfie(
            skill_params.get("scene", "casual"),
            skill_params.get("custom_prompt"),
            world_context=world_context)
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

    return {"skill": "none"}
