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

def skill_web_search(query, num_results=3):
    """用 DuckDuckGo 搜索信息"""
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
        if not combined and snippets:
            combined = [{"title": "", "url": "", "snippet": s} for s in snippets[:num_results]]

        return {"success": True, "query": query, "results": combined}
    except Exception as e:
        print(f"搜索失败: {e}")
        return {"success": False, "query": query, "error": str(e)}


def skill_fetch_url(url, max_chars=2000):
    """获取网页文本内容"""
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
        return {"success": True, "url": url, "content": text[:max_chars]}
    except Exception as e:
        return {"success": False, "url": url, "error": str(e)}


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


def skill_generate_selfie(scene="casual", custom_prompt=None,
                          output_dir="/home/ubuntu/chimera/selfies",
                          world_context=None):
    """
    两步法生成小悦的一致性自拍：
    1. FLUX/schnell 生成场景图（根据世界状态动态构建prompt）
    2. fal-ai/face-swap 将参考图的脸换上去

    world_context: dict with keys: location_id, hour, weather, activity
    """
    os.makedirs(output_dir, exist_ok=True)

    # 如果有世界上下文，动态构建prompt
    if world_context:
        full_prompt = build_selfie_prompt(
            location_id=world_context.get("location_id", "home_xiaoyue"),
            hour=world_context.get("hour", 14),
            weather=world_context.get("weather", "晴天"),
            activity=world_context.get("activity", ""),
            custom_prompt=custom_prompt,
        )
    else:
        # 降级：用简单的场景风格
        SIMPLE_STYLES = {
            "casual": "casual selfie, natural lighting, warm tones, phone camera close-up portrait",
            "mirror": "mirror selfie, full body shot, showing outfit, indoor lighting",
            "outdoor": "outdoor selfie, natural background, sunlight, blue sky",
            "cafe": "selfie in a cozy cafe, warm ambient lighting, coffee cup visible",
            "studio": "selfie in an art studio, paint supplies visible, creative atmosphere",
            "park": "selfie in a park, green trees, natural daylight, flowers",
            "night": "evening selfie, city lights bokeh in background, soft warm tones",
            "work": "selfie at modern office desk, computer monitor visible, daylight",
        }
        style = SIMPLE_STYLES.get(scene, SIMPLE_STYLES["casual"])
        full_prompt = f"{XIAOYUE_BASE_FACE} {custom_prompt + '. ' if custom_prompt else ''}{style}. Selfie, phone camera, portrait photo, realistic."

    headers = {
        "Authorization": f"Key {FAL_KEY}",
        "Content-Type": "application/json",
    }

    try:
        # Step 1: FLUX 生成场景图
        payload1 = {
            "prompt": full_prompt,
            "image_size": "portrait_4_3",
            "num_images": 1,
        }
        r1 = requests.post("https://fal.run/fal-ai/flux/schnell",
                          headers=headers, json=payload1, timeout=60)
        if r1.status_code != 200:
            return {"success": False, "error": f"FLUX生成失败: {r1.status_code}"}

        result1 = r1.json()
        images1 = result1.get("images", [])
        if not images1:
            return {"success": False, "error": "FLUX没有生成图片"}

        target_url = images1[0]["url"]

        # Step 2: Face-Swap 换脸
        payload2 = {
            "base_image_url": target_url,
            "swap_image_url": REFERENCE_FACE_URL,
        }
        r2 = requests.post("https://fal.run/fal-ai/face-swap",
                          headers=headers, json=payload2, timeout=60)
        if r2.status_code != 200:
            print(f"Face-swap失败({r2.status_code})，使用原始图")
            final_url = target_url
        else:
            result2 = r2.json()
            final_url = result2.get("image", {}).get("url", target_url)

        # 下载最终图片
        timestamp = int(time.time())
        filename = f"selfie_{scene}_{timestamp}.jpg"
        filepath = os.path.join(output_dir, filename)

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
