#!/usr/bin/env python3
"""
从提取的对话数据中清洗并重建 Style RAG 素材库
区分男女风格，生成高质量的对话对
"""
import json
import os
import shutil
from pathlib import Path
from collections import Counter

# 路径
EXTRACTED_FILE = Path("/home/ubuntu/chimera/extracted_dialogs.json")
OUTPUT_DIR = Path("/home/ubuntu/chimera/new_rag_data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 旧RAG数据库路径
OLD_RAG_DIR = Path("/home/ubuntu/chimera/chroma_style_db")
# 新RAG数据库路径
NEW_RAG_DIR = Path("/home/ubuntu/chimera/chroma_style_db_v2")

def load_extracted():
    with open(EXTRACTED_FILE) as f:
        return json.load(f)

def clean_message(text):
    """清洗单条消息"""
    if not text or not isinstance(text, str):
        return ""
    text = text.strip()
    # 过滤太短的
    if len(text) < 2:
        return ""
    # 过滤纯表情/系统消息
    if text in ("[表情]", "[图片]", "[语音]", "[视频]", "[红包]", "[转账]"):
        return ""
    # 过滤纯标点
    if all(c in "。？！，、；：""''（）【】…—" for c in text):
        return ""
    return text

def extract_dialog_pairs(dialog_data):
    """
    从一个对话中提取 (user_msg, assistant_msg) 对
    我们把"对方说的话"当作user（触发），"我方回复"当作assistant（风格参考）
    
    同时标注性别信息
    """
    messages = dialog_data.get("messages", [])
    if len(messages) < 2:
        return []
    
    chat_type = dialog_data.get("chat_type", "其他")
    participants = dialog_data.get("participants", {})
    
    # 确定角色性别
    left_gender = participants.get("left", "A")
    right_gender = participants.get("right", "B")
    
    pairs = []
    
    # 滑动窗口提取对话对
    for i in range(len(messages) - 1):
        msg1 = messages[i]
        msg2 = messages[i + 1]
        
        text1 = clean_message(msg1.get("text", ""))
        text2 = clean_message(msg2.get("text", ""))
        
        if not text1 or not text2:
            continue
        
        # 确保是不同人说的（一问一答）
        sender1 = msg1.get("sender", "")
        sender2 = msg2.get("sender", "")
        if sender1 == sender2:
            continue
        
        # 标注性别
        gender1 = classify_gender(sender1, left_gender, right_gender, participants)
        gender2 = classify_gender(sender2, left_gender, right_gender, participants)
        
        pairs.append({
            "user_msg": text1,
            "assistant_msg": text2,
            "user_gender": gender1,
            "assistant_gender": gender2,
            "chat_type": chat_type,
            "source": dialog_data.get("file", "unknown"),
        })
    
    # 也提取多轮连续对话（2-3条合并）
    for i in range(len(messages) - 2):
        msgs = messages[i:i+3]
        senders = [m.get("sender", "") for m in msgs]
        texts = [clean_message(m.get("text", "")) for m in msgs]
        
        if not all(texts):
            continue
        
        # A-B-A 模式：合并A的两条作为context
        if senders[0] == senders[2] and senders[0] != senders[1]:
            combined_user = f"{texts[0]}...{texts[2]}"
            gender_b = classify_gender(senders[1], left_gender, right_gender, participants)
            gender_a = classify_gender(senders[0], left_gender, right_gender, participants)
            pairs.append({
                "user_msg": combined_user,
                "assistant_msg": texts[1],
                "user_gender": gender_a,
                "assistant_gender": gender_b,
                "chat_type": chat_type,
                "source": dialog_data.get("file", "unknown"),
            })
    
    return pairs

def classify_gender(sender, left_gender, right_gender, participants):
    """根据sender标签推断性别"""
    sender = sender.strip()
    
    # 直接匹配
    if sender in ("男", "男A", "男B", "男生", "男方", "男朋友", "老公", "他"):
        return "male"
    if sender in ("女", "女A", "女B", "女生", "女方", "女朋友", "老婆", "她"):
        return "female"
    
    # 通过participants映射
    left = participants.get("left", "")
    right = participants.get("right", "")
    
    if sender == left:
        if "男" in left:
            return "male"
        if "女" in left:
            return "female"
    if sender == right:
        if "男" in right:
            return "male"
        if "女" in right:
            return "female"
    
    return "unknown"

def quality_filter(pair):
    """质量过滤"""
    user_msg = pair["user_msg"]
    assistant_msg = pair["assistant_msg"]
    
    # 过滤太短的回复（少于3字）
    if len(assistant_msg) < 3:
        return False
    
    # 过滤太长的（超过200字可能不是聊天风格）
    if len(assistant_msg) > 200:
        return False
    
    # 过滤重复
    if user_msg == assistant_msg:
        return False
    
    return True

def build_new_rag(pairs):
    """用清洗后的对话对重建RAG"""
    import sys
    sys.path.insert(0, '/home/ubuntu/chimera')
    
    # 备份旧数据库
    if OLD_RAG_DIR.exists():
        backup_dir = Path("/home/ubuntu/chimera/chroma_style_db_backup")
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(OLD_RAG_DIR, backup_dir)
        print(f"旧数据库已备份到 {backup_dir}")
    
    # 清除旧数据库，创建新的
    if NEW_RAG_DIR.exists():
        shutil.rmtree(NEW_RAG_DIR)
    
    from style_rag import StyleRAG
    rag = StyleRAG(persist_dir=str(NEW_RAG_DIR))
    
    # 按性别分组添加
    male_pairs = [(p["user_msg"], p["assistant_msg"]) for p in pairs if p["assistant_gender"] == "male"]
    female_pairs = [(p["user_msg"], p["assistant_msg"]) for p in pairs if p["assistant_gender"] == "female"]
    unknown_pairs = [(p["user_msg"], p["assistant_msg"]) for p in pairs if p["assistant_gender"] == "unknown"]
    
    print(f"\n添加样本到新RAG:")
    print(f"  男性风格: {len(male_pairs)}")
    print(f"  女性风格: {len(female_pairs)}")
    print(f"  未知性别: {len(unknown_pairs)}")
    
    # 先去重，再添加
    seen = set()
    unique_pairs = []
    for p in pairs:
        key = f"{p['user_msg']}||{p['assistant_msg']}"
        if key not in seen:
            seen.add(key)
            unique_pairs.append(p)
    print(f"  去重后: {len(unique_pairs)}")
    
    all_examples = [(p["user_msg"], p["assistant_msg"]) for p in unique_pairs]
    # 分批添加，每批500
    added = 0
    for i in range(0, len(all_examples), 500):
        batch = all_examples[i:i+500]
        added += rag._add_examples(batch)
    print(f"  实际添加: {added}")
    print(f"  RAG总量: {rag.count()}")
    
    return rag

def main():
    print("=== 重建 Style RAG 素材库 ===\n")
    
    # 1. 加载提取的对话
    data = load_extracted()
    chats = [d for d in data if d.get("is_chat")]
    print(f"聊天截图总数: {len(chats)}")
    
    # 2. 提取对话对
    all_pairs = []
    for dialog in chats:
        pairs = extract_dialog_pairs(dialog)
        all_pairs.extend(pairs)
    print(f"原始对话对: {len(all_pairs)}")
    
    # 3. 质量过滤
    filtered = [p for p in all_pairs if quality_filter(p)]
    print(f"过滤后: {len(filtered)}")
    
    # 4. 统计
    gender_dist = Counter(p["assistant_gender"] for p in filtered)
    type_dist = Counter(p["chat_type"] for p in filtered)
    
    print(f"\n=== 性别分布 ===")
    for g, n in gender_dist.most_common():
        print(f"  {g}: {n}")
    
    print(f"\n=== 聊天类型分布 ===")
    for t, n in type_dist.most_common():
        print(f"  {t}: {n}")
    
    # 5. 保存清洗后的数据
    output_file = OUTPUT_DIR / "cleaned_pairs.json"
    with open(output_file, 'w') as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)
    print(f"\n清洗后数据已保存到: {output_file}")
    
    # 6. 按性别分别保存
    for gender in ["male", "female", "unknown"]:
        gender_pairs = [p for p in filtered if p["assistant_gender"] == gender]
        if gender_pairs:
            with open(OUTPUT_DIR / f"{gender}_pairs.json", 'w') as f:
                json.dump(gender_pairs, f, ensure_ascii=False, indent=2)
            print(f"  {gender}: {len(gender_pairs)} 对 -> {gender}_pairs.json")
    
    # 7. 生成 few_shot.md 格式文件（兼容旧格式）
    with open(OUTPUT_DIR / "new_few_shot.md", 'w') as f:
        for p in filtered:
            gender_tag = f" [{p['assistant_gender']}]" if p['assistant_gender'] != 'unknown' else ""
            f.write(f"- user: {p['user_msg']}\n")
            f.write(f"- assistant: {p['assistant_msg']}{gender_tag}\n\n")
    print(f"\nnew_few_shot.md 已生成")
    
    # 8. 重建RAG
    print("\n--- 重建 RAG 数据库 ---")
    rag = build_new_rag(filtered)
    
    # 9. 测试查询
    print("\n=== 测试查询 ===")
    test_queries = [
        "你在干嘛",
        "今天好累啊",
        "想你了",
        "吃饭了吗",
        "哈哈哈哈",
    ]
    for q in test_queries:
        results = rag.query(q, n_results=3)
        print(f"\n查询: {q}")
        for r in results:
            print(f"  -> {r['user'][:30]} | {r['assistant'][:50]}")
    
    # 10. 样本展示
    print("\n=== 随机样本展示 ===")
    import random
    random.seed(42)
    samples = random.sample(filtered, min(10, len(filtered)))
    for s in samples:
        print(f"\n[{s['chat_type']}] {s['user_gender']}→{s['assistant_gender']}")
        print(f"  User: {s['user_msg'][:60]}")
        print(f"  Asst: {s['assistant_msg'][:60]}")

if __name__ == "__main__":
    main()
