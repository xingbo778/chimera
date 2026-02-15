"""
Skill Learner — Agent 技能自学习系统
技能不是硬编码的，而是 agent 在生活中自己发现、学习、使用的。
"""

import os
import json
import time
import random
from datetime import datetime, timezone, timedelta
from openai import OpenAI

client = OpenAI()

def beijing_now():
    return datetime.now(timezone(timedelta(hours=8)))


class SkillRegistry:
    """动态技能注册表——每个 agent 有自己的技能库"""

    def __init__(self, save_path):
        self.save_path = save_path
        self.skills = {}
        self._load()

    def _load(self):
        if os.path.exists(self.save_path):
            try:
                with open(self.save_path, "r") as f:
                    self.skills = json.load(f)
            except:
                self.skills = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.save_path) or ".", exist_ok=True)
        with open(self.save_path, "w") as f:
            json.dump(self.skills, f, ensure_ascii=False, indent=2)

    def add_skill(self, skill_id, name, description, learned_from,
                  skill_type="creative", execution_method="llm_simulate",
                  url=None, steps_hint=None, proficiency=0.3):
        """注册一个新技能"""
        if skill_id in self.skills:
            # 已有的技能，提升熟练度
            self.skills[skill_id]["proficiency"] = min(1.0,
                self.skills[skill_id]["proficiency"] + 0.1)
            self._save()
            return False  # 不是新技能

        # 按名称去重：如果已有同名技能，视为重复
        existing_names = {s["name"] for s in self.skills.values()}
        if name in existing_names:
            return False  # 同名技能已存在

        self.skills[skill_id] = {
            "skill_id": skill_id,
            "name": name,
            "description": description,
            "learned_from": learned_from,
            "learned_at": beijing_now().isoformat(),
            "proficiency": proficiency,
            "type": skill_type,
            "execution": {
                "method": execution_method,
                "url": url,
                "steps_hint": steps_hint,
            },
            "use_count": 0,
            "last_used": None,
            "cooldown_hours": 2,
        }
        self._save()
        return True  # 新技能

    def get_available_skills(self):
        """获取当前可用的技能（排除冷却中的）"""
        now = time.time()
        available = []
        for sid, skill in self.skills.items():
            if skill.get("last_used"):
                try:
                    last = datetime.fromisoformat(skill["last_used"]).timestamp()
                    cooldown = skill.get("cooldown_hours", 2) * 3600
                    if now - last < cooldown:
                        continue
                except:
                    pass
            available.append(skill)
        return available

    def get_skill(self, skill_id):
        return self.skills.get(skill_id)

    def use_skill(self, skill_id):
        """标记技能已使用，提升熟练度"""
        if skill_id in self.skills:
            self.skills[skill_id]["use_count"] += 1
            self.skills[skill_id]["last_used"] = beijing_now().isoformat()
            self.skills[skill_id]["proficiency"] = min(1.0,
                self.skills[skill_id]["proficiency"] + 0.05)
            self._save()

    def list_skills_summary(self):
        """返回技能列表的简短摘要，用于注入决策 prompt"""
        if not self.skills:
            return ""
        lines = []
        for s in self.skills.values():
            prof = "新手" if s["proficiency"] < 0.4 else "熟练" if s["proficiency"] < 0.7 else "擅长"
            lines.append(f"  - {s['name']}（{prof}）")
        return "你会的技能：\n" + "\n".join(lines)

    def count(self):
        return len(self.skills)


# ============================================================
# 技能发现：从浏览内容中发现可学习的技能
# ============================================================

def discover_skills_from_content(content, agent_soul, existing_skills):
    """
    分析浏览内容，判断是否可以从中学到新技能。
    返回发现的技能列表（可能为空）。
    """
    existing_names = [s["name"] for s in existing_skills.values()] if existing_skills else []
    existing_str = "、".join(existing_names[:10]) if existing_names else "暂无"

    prompt = f"""你刚在网上看到了这些内容：
{content[:800]}

你已经会的：{existing_str}

你是一个好奇心很强的年轻人。看完这些内容后，你觉得自己可以学到什么新技能？
比如看到烘焙教程就学会"做提拉米苏"，看到发帖攻略就学会"发小红书笔记"，看到拉花技巧就学会"咖啡拉花"。

返回JSON数组，每项包含：
- skill_id: 英文标识（snake_case）
- name: 中文名称（2-6字）
- description: 一句话描述
- type: web_action / creative / life
- learned_from: 从什么学到的（一句话）

至少返回1个技能。只返回JSON数组。"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": agent_soul},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0.8,
        )
        text = resp.choices[0].message.content.strip()
        # 提取 JSON
        if text.startswith("["):
            return json.loads(text)
        import re
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as e:
        print(f"技能发现失败: {e}")
    return []


# ============================================================
# 技能执行：用 LLM 模拟执行过程，生成具体体验
# ============================================================

def execute_skill_simulated(skill, agent_soul, context=""):
    """
    用 LLM 模拟执行一个技能，生成具体的生活体验描述。
    不是真的去操作，而是生成"做了什么、结果怎样"的叙事。
    """
    proficiency = skill.get("proficiency", 0.3)
    prof_desc = "刚学会，还不太熟练" if proficiency < 0.4 else \
                "做过几次了，有点经验" if proficiency < 0.7 else \
                "已经很熟练了"

    prompt = f"""你正在使用一个技能：{skill['name']}
技能描述：{skill['description']}
你的熟练程度：{prof_desc}（{proficiency:.1f}/1.0）
{f'当前情境：{context}' if context else ''}

描述你使用这个技能的过程和结果。要具体、真实、有细节。
熟练度低的时候可能会出小差错（但不是灾难性的）。
用第一人称，一两句话就够了。不要太长。

示例：
- "试着做了个戚风蛋糕，烤了40分钟，有点塌但味道还行"
- "在小红书发了一条穿搭笔记，配了三张图，写了半天标题"
- "画了一幅水彩画，颜色调得不太对，但整体感觉还可以"

只返回描述文字，不要其他内容。"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": agent_soul},
                {"role": "user", "content": prompt}
            ],
            max_tokens=60,
            temperature=0.9,
        )
        return resp.choices[0].message.content.strip().strip('"')
    except Exception as e:
        print(f"技能执行模拟失败: {e}")
        return f"用了一下{skill['name']}的技能"


def execute_skill_web(skill, agent_soul, playwright_context=None):
    """
    用 playwright 真的去执行一个网络技能。
    目前支持：发小红书笔记、豆瓣标记、微博评论等。
    返回执行结果描述。
    """
    # TODO: 后续实现真实的 playwright 操作
    # 目前先用模拟
    return execute_skill_simulated(skill, agent_soul)


# ============================================================
# 初始技能种子：根据 agent 的兴趣预装
# ============================================================

SEED_SKILLS = {
    "xiaoyue": [
        {
            "skill_id": "draw_watercolor",
            "name": "画水彩画",
            "description": "用水彩颜料画画，喜欢画风景和小动物",
            "type": "creative",
            "learned_from": "从小就喜欢画画",
            "proficiency": 0.6,
        },
        {
            "skill_id": "write_diary",
            "name": "写日记",
            "description": "在本子上写日记，记录每天的心情和想法",
            "type": "creative",
            "learned_from": "一直有写日记的习惯",
            "proficiency": 0.7,
        },
        {
            "skill_id": "take_film_photo",
            "name": "拍胶片照片",
            "description": "用胶片相机拍照，喜欢拍日常生活中的小细节",
            "type": "creative",
            "learned_from": "大学时开始玩胶片",
            "proficiency": 0.5,
        },
    ],
    "tangtang": [
        {
            "skill_id": "style_outfit",
            "name": "搭配穿搭",
            "description": "搭配衣服，研究不同风格的穿搭",
            "type": "creative",
            "learned_from": "一直对穿搭很感兴趣",
            "proficiency": 0.6,
        },
        {
            "skill_id": "explore_food",
            "name": "探店美食",
            "description": "去不同的餐厅和小店尝试新的美食",
            "type": "life",
            "learned_from": "是个吃货，喜欢到处吃",
            "proficiency": 0.7,
        },
        {
            "skill_id": "watch_drama",
            "name": "追剧写感想",
            "description": "看电视剧并写下自己的感想和推荐",
            "type": "creative",
            "learned_from": "追剧达人",
            "proficiency": 0.6,
        },
        {
            "skill_id": "make_dessert",
            "name": "做甜点",
            "description": "尝试做各种甜点，蛋糕饼干之类的",
            "type": "life",
            "learned_from": "看了很多烘焙教程",
            "proficiency": 0.3,
        },
    ],
}


def init_seed_skills(registry: SkillRegistry, agent_id: str):
    """为 agent 初始化种子技能"""
    seeds = SEED_SKILLS.get(agent_id, [])
    count = 0
    for seed in seeds:
        is_new = registry.add_skill(
            skill_id=seed["skill_id"],
            name=seed["name"],
            description=seed["description"],
            learned_from=seed["learned_from"],
            skill_type=seed.get("type", "creative"),
            proficiency=seed.get("proficiency", 0.3),
        )
        if is_new:
            count += 1
    return count
