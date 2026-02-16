"""
快速数据清洗：用规则而非LLM标注
- 基于文本特征判断话题
- 基于长度/格式判断质量
- 基于碎片化程度判断是否适合few-shot
"""
import json
import re
from collections import Counter

# Topic keywords mapping
TOPIC_KEYWORDS = {
    "工作": ["上班", "加班", "老板", "同事", "工资", "辞职", "跳槽", "开会", "项目", "甲方", "下班", "摸鱼", "打工", "KPI", "绩效", "领导", "公司", "办公", "请假", "出差"],
    "穿搭": ["衣服", "裙子", "裤子", "鞋", "穿", "搭配", "好看", "颜色", "外套", "T恤", "卫衣", "牛仔", "风格", "显瘦", "时尚", "款式", "码", "尺码"],
    "健身": ["健身", "运动", "跑步", "瑜伽", "减肥", "体重", "肌肉", "锻炼", "训练", "卡路里", "蛋白", "增肌", "有氧", "撸铁", "keep", "腹肌", "马甲线"],
    "旅行": ["旅行", "旅游", "出去玩", "景点", "酒店", "机票", "攻略", "打卡", "拍照", "风景", "海边", "山", "度假", "民宿", "自驾", "飞机"],
    "美食": ["吃", "饭", "火锅", "奶茶", "外卖", "好吃", "餐厅", "做饭", "烧烤", "甜品", "蛋糕", "零食", "夜宵", "饿", "点餐", "菜", "螺蛳粉", "炸鸡"],
    "学习": ["学习", "考试", "考研", "考公", "作业", "上课", "老师", "成绩", "分数", "复习", "背书", "图书馆", "论文", "毕业", "学校", "大学"],
    "娱乐": ["电影", "电视", "综艺", "游戏", "追剧", "音乐", "歌", "演唱会", "密室", "剧本杀", "KTV", "玩", "好看", "好玩"],
    "宠物": ["猫", "狗", "宠物", "喵", "汪", "铲屎", "猫粮", "狗粮", "养", "毛", "爪", "可爱"],
    "颜值": ["化妆", "护肤", "口红", "眼影", "面膜", "素颜", "好看", "丑", "帅", "美", "发型", "头发", "染", "指甲", "防晒", "粉底"],
    "情感": ["喜欢", "爱", "分手", "暧昧", "表白", "男朋友", "女朋友", "老公", "老婆", "想你", "亲", "抱", "心疼", "吃醋", "撩"],
}

def classify_topic(user_msg, assistant_msg, existing_topic=None):
    """基于关键词分类话题"""
    text = (user_msg + " " + assistant_msg).lower()
    
    scores = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[topic] = score
    
    if scores:
        best_topic = max(scores, key=scores.get)
        if scores[best_topic] >= 1:
            return best_topic
    
    # If existing topic is provided and valid, use it
    if existing_topic and existing_topic in TOPIC_KEYWORDS:
        return existing_topic
    
    return "日常"

def assess_quality(user_msg, assistant_msg):
    """基于规则评估质量"""
    score = 3  # Default
    
    asst_clean = assistant_msg.replace("[表情]", "").replace("[图片]", "").strip()
    user_clean = user_msg.replace("[表情]", "").replace("[图片]", "").strip()
    
    # Positive signals (碎片化、口语化)
    if "\n" in assistant_msg:  # 多条消息
        score += 0.5
    if len(asst_clean) < 30:  # 短回复
        score += 0.3
    if any(w in assistant_msg for w in ["哈哈", "啊", "呢", "吧", "嘛", "呀", "哦", "嗯"]):
        score += 0.2
    if "[表情]" in assistant_msg:
        score += 0.1
    
    # Negative signals
    if len(asst_clean) > 100:  # 太长
        score -= 0.5
    if len(asst_clean) < 2:  # 太短
        score -= 1
    if "首先" in assistant_msg or "其次" in assistant_msg or "最后" in assistant_msg:
        score -= 1  # AI味
    if len(user_clean) < 2:  # 用户消息太短
        score -= 0.3
    
    return max(1, min(4, round(score)))

def is_good_fewshot(user_msg, assistant_msg, quality):
    """判断是否适合作为few-shot示例"""
    if quality < 3:
        return False
    
    asst_clean = assistant_msg.replace("[表情]", "").replace("[图片]", "").strip()
    user_clean = user_msg.replace("[表情]", "").replace("[图片]", "").strip()
    
    # Good few-shot: 短、碎片化、口语化
    if len(asst_clean) > 60:
        return False
    if len(user_clean) < 3:
        return False
    if len(asst_clean) < 3:
        return False
    
    # Has personality
    personality_signals = ["哈哈", "啊", "吧", "呢", "嘛", "呀", "？", "！", "...", 
                          "不是", "怎么", "为什么", "干嘛", "算了", "行吧", "得了",
                          "[表情]", "笑死", "绝了", "离谱", "无语"]
    has_personality = any(s in assistant_msg for s in personality_signals)
    
    return has_personality

def main():
    # Load data
    with open("/home/ubuntu/chimera/new_rag_data/cleaned_pairs.json") as f:
        existing = json.load(f)
    
    with open("/home/ubuntu/chimera/new_topic_pairs.json") as f:
        new_pairs = json.load(f)
    
    # Basic clean
    skip_keywords = ["红包", "转账", "以上是打赏", "该消息已撤回", "你已添加", 
                     "以下为新消息", "消息已发出", "对方已读", "通话时长",
                     "拍了拍", "邀请你加入", "修改了群名"]
    
    all_pairs = []
    
    for p in existing + new_pairs:
        user_msg = p.get("user_msg", "")
        assistant_msg = p.get("assistant_msg", "")
        
        if not user_msg or not assistant_msg:
            continue
        
        user_clean = user_msg.replace("[表情]", "").replace("[图片]", "").strip()
        asst_clean = assistant_msg.replace("[表情]", "").replace("[图片]", "").strip()
        
        if len(user_clean) < 2 and len(asst_clean) < 2:
            continue
        
        if any(kw in user_msg for kw in skip_keywords) or any(kw in assistant_msg for kw in skip_keywords):
            continue
        
        # Classify and score
        existing_topic = p.get("topic")
        topic = classify_topic(user_msg, assistant_msg, existing_topic)
        quality = assess_quality(user_msg, assistant_msg)
        good_fewshot = is_good_fewshot(user_msg, assistant_msg, quality)
        
        all_pairs.append({
            "user_msg": user_msg,
            "assistant_msg": assistant_msg,
            "user_gender": p.get("user_gender", "unknown"),
            "assistant_gender": p.get("assistant_gender", "unknown"),
            "chat_type": p.get("chat_type", "其他"),
            "topic": topic,
            "quality": quality,
            "good_fewshot": good_fewshot,
            "source": p.get("source", "unknown"),
        })
    
    # Deduplicate by user_msg + assistant_msg
    seen = set()
    deduped = []
    for p in all_pairs:
        key = p["user_msg"][:50] + "||" + p["assistant_msg"][:50]
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    
    print(f"总数据: {len(all_pairs)} -> 去重后: {len(deduped)}")
    
    # Stats
    print(f"\n质量分布:")
    quality_dist = Counter(p["quality"] for p in deduped)
    for q in sorted(quality_dist.keys()):
        print(f"  质量 {q}: {quality_dist[q]} 条")
    
    print(f"\n话题分布:")
    topic_dist = Counter(p["topic"] for p in deduped)
    for t, c in topic_dist.most_common():
        print(f"  {t}: {c} 条")
    
    high_quality = [p for p in deduped if p["quality"] >= 3]
    fewshot_ready = [p for p in deduped if p["good_fewshot"]]
    
    print(f"\n高质量(>=3): {len(high_quality)} 条")
    print(f"适合few-shot: {len(fewshot_ready)} 条")
    
    # Few-shot topic distribution
    print(f"\nFew-shot 话题分布:")
    fs_topic_dist = Counter(p["topic"] for p in fewshot_ready)
    for t, c in fs_topic_dist.most_common():
        print(f"  {t}: {c} 条")
    
    # Save
    with open("/home/ubuntu/chimera/final_all_pairs.json", "w") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)
    with open("/home/ubuntu/chimera/final_high_quality.json", "w") as f:
        json.dump(high_quality, f, ensure_ascii=False, indent=2)
    with open("/home/ubuntu/chimera/final_fewshot_ready.json", "w") as f:
        json.dump(fewshot_ready, f, ensure_ascii=False, indent=2)
    
    print(f"\n保存完成!")

if __name__ == "__main__":
    main()
