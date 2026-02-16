#!/usr/bin/env python3
"""
v3 数据清洗 + RAG 重建
修复两大问题：
1. 同一人连续多条消息合并为一条
2. 保留完整的多轮对话上下文
"""
import json
import shutil
from pathlib import Path
from collections import Counter

EXTRACTED_FILE = Path("/home/ubuntu/chimera/extracted_dialogs.json")
OUTPUT_DIR = Path("/home/ubuntu/chimera/new_rag_data_v3")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NEW_RAG_DIR = Path("/home/ubuntu/chimera/chroma_style_db_v3")

def load_extracted():
    with open(EXTRACTED_FILE) as f:
        return json.load(f)

def clean_message(text):
    """清洗单条消息"""
    if not text or not isinstance(text, str):
        return ""
    text = text.strip()
    if len(text) < 1:
        return ""
    # 纯系统消息过滤
    if text in ("[图片]", "[语音]", "[视频]", "[红包]", "[转账]"):
        return ""
    # 纯标点
    if all(c in "。？！，、；：""''（）【】…—" for c in text):
        return ""
    return text

def merge_consecutive_messages(messages):
    """
    合并同一人连续发送的多条消息为一条
    例如：
      男: "宝宝 如果以后我们的孩子不孝顺的话"
      男: "我们临s前就对他说"
      男: "我们有5,000,000"
    合并为：
      男: "宝宝 如果以后我们的孩子不孝顺的话\n我们临s前就对他说\n我们有5,000,000"
    """
    if not messages:
        return []
    
    merged = []
    current_sender = messages[0].get("sender", "")
    current_texts = []
    
    for msg in messages:
        sender = msg.get("sender", "")
        text = clean_message(msg.get("text", ""))
        
        if not text:
            # 跳过空消息但不中断合并
            continue
        
        if sender == current_sender:
            current_texts.append(text)
        else:
            # 换人了，保存之前的合并结果
            if current_texts:
                merged.append({
                    "sender": current_sender,
                    "text": "\n".join(current_texts)
                })
            current_sender = sender
            current_texts = [text]
    
    # 最后一组
    if current_texts:
        merged.append({
            "sender": current_sender,
            "text": "\n".join(current_texts)
        })
    
    return merged

def classify_gender(sender, participants):
    """根据sender标签推断性别"""
    sender = sender.strip()
    
    male_keywords = ("男", "男A", "男B", "男生", "男方", "男朋友", "老公", "他", "男1", "男2")
    female_keywords = ("女", "女A", "女B", "女生", "女方", "女朋友", "老婆", "她", "女1", "女2")
    
    if sender in male_keywords or "男" in sender:
        return "male"
    if sender in female_keywords or "女" in sender:
        return "female"
    
    # 通过participants映射
    left = participants.get("left", "")
    right = participants.get("right", "")
    
    if sender == left:
        if "男" in left: return "male"
        if "女" in left: return "female"
    if sender == right:
        if "男" in right: return "male"
        if "女" in right: return "female"
    
    return "unknown"

def extract_pairs_v3(dialog_data):
    """
    v3 清洗逻辑：
    1. 先合并同一人连续消息
    2. 合并后逐对配对（保证每对都是完整的一问一答）
    3. 同时生成带上下文的多轮版本
    """
    messages = dialog_data.get("messages", [])
    if len(messages) < 2:
        return []
    
    chat_type = dialog_data.get("chat_type", "其他")
    participants = dialog_data.get("participants", {})
    source = dialog_data.get("file", "unknown")
    
    # Step 1: 合并同一人连续消息
    merged = merge_consecutive_messages(messages)
    
    if len(merged) < 2:
        return []
    
    pairs = []
    
    # Step 2: 逐对配对（合并后每条都是不同人说的）
    for i in range(len(merged) - 1):
        msg_user = merged[i]
        msg_asst = merged[i + 1]
        
        user_gender = classify_gender(msg_user["sender"], participants)
        asst_gender = classify_gender(msg_asst["sender"], participants)
        
        # 收集之前的上下文（最多3轮）
        context = []
        for j in range(max(0, i - 4), i):
            ctx_msg = merged[j]
            ctx_gender = classify_gender(ctx_msg["sender"], participants)
            role = "user" if ctx_gender == user_gender else "assistant"
            context.append({
                "role": role,
                "text": ctx_msg["text"]
            })
        
        pair = {
            "user_msg": msg_user["text"],
            "assistant_msg": msg_asst["text"],
            "user_gender": user_gender,
            "assistant_gender": asst_gender,
            "chat_type": chat_type,
            "source": source,
            "context": context,  # 之前的对话上下文
            "turn_index": i,     # 在原对话中的位置
            "total_turns": len(merged) - 1,  # 总轮数
        }
        pairs.append(pair)
    
    return pairs

def quality_filter(pair):
    """质量过滤"""
    user_msg = pair["user_msg"]
    assistant_msg = pair["assistant_msg"]
    
    # 过滤纯表情回复
    if assistant_msg.replace("[表情]", "").replace("\n", "").strip() == "":
        return False
    
    # 过滤太长的（超过300字可能不是聊天风格）
    if len(assistant_msg) > 300:
        return False
    
    # 过滤完全相同的问答
    if user_msg == assistant_msg:
        return False
    
    return True

def main():
    print("=== v3 数据清洗 + RAG 重建 ===\n")
    
    # 1. 加载
    data = load_extracted()
    chats = [d for d in data if d.get("is_chat")]
    print(f"聊天截图总数: {len(chats)}")
    
    # 2. 提取对话对（新逻辑）
    all_pairs = []
    for dialog in chats:
        pairs = extract_pairs_v3(dialog)
        all_pairs.extend(pairs)
    print(f"合并+配对后: {len(all_pairs)}")
    
    # 3. 质量过滤
    filtered = [p for p in all_pairs if quality_filter(p)]
    print(f"过滤后: {len(filtered)}")
    
    # 4. 去重
    seen = set()
    unique = []
    for p in filtered:
        key = f"{p['user_msg']}||{p['assistant_msg']}"
        if key not in seen:
            seen.add(key)
            unique.append(p)
    print(f"去重后: {len(unique)}")
    
    # 5. 统计
    gender_dist = Counter(p["assistant_gender"] for p in unique)
    type_dist = Counter(p["chat_type"] for p in unique)
    
    # 统计合并效果
    has_multiline_user = sum(1 for p in unique if "\n" in p["user_msg"])
    has_multiline_asst = sum(1 for p in unique if "\n" in p["assistant_msg"])
    has_context = sum(1 for p in unique if p["context"])
    avg_asst_len = sum(len(p["assistant_msg"]) for p in unique) / len(unique)
    
    print(f"\n=== 统计 ===")
    print(f"性别分布: {dict(gender_dist.most_common())}")
    print(f"类型分布: {dict(type_dist.most_common())}")
    print(f"用户消息含多段: {has_multiline_user} ({has_multiline_user/len(unique)*100:.1f}%)")
    print(f"回复含多段: {has_multiline_asst} ({has_multiline_asst/len(unique)*100:.1f}%)")
    print(f"有上下文: {has_context} ({has_context/len(unique)*100:.1f}%)")
    print(f"平均回复长度: {avg_asst_len:.1f} 字")
    
    # 6. 保存
    with open(OUTPUT_DIR / "cleaned_pairs_v3.json", 'w') as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)
    
    # 按性别保存
    for gender in ["male", "female", "unknown"]:
        gp = [p for p in unique if p["assistant_gender"] == gender]
        if gp:
            with open(OUTPUT_DIR / f"{gender}_pairs.json", 'w') as f:
                json.dump(gp, f, ensure_ascii=False, indent=2)
            print(f"  {gender}: {len(gp)} 对")
    
    # 7. 展示对比：旧清洗 vs 新清洗
    print(f"\n=== 样本展示（合并效果）===")
    multi_samples = [p for p in unique if "\n" in p["assistant_msg"]][:10]
    for s in multi_samples:
        print(f"\n[{s['chat_type']}] {s['assistant_gender']}")
        print(f"  User: {s['user_msg'][:80]}")
        print(f"  Asst: {s['assistant_msg'][:120]}")
        if s['context']:
            print(f"  Context: {len(s['context'])} 轮")
    
    # 8. 生成 few_shot.md
    with open(OUTPUT_DIR / "new_few_shot_v3.md", 'w') as f:
        for p in unique:
            gender_tag = f" [{p['assistant_gender']}]" if p['assistant_gender'] != 'unknown' else ""
            f.write(f"- user: {p['user_msg']}\n")
            f.write(f"- assistant: {p['assistant_msg']}{gender_tag}\n\n")
    
    # 9. 重建RAG
    print(f"\n=== 重建 RAG ===")
    if NEW_RAG_DIR.exists():
        shutil.rmtree(NEW_RAG_DIR)
    
    import sys
    sys.path.insert(0, '/home/ubuntu/chimera')
    from style_rag import StyleRAG
    rag = StyleRAG(persist_dir=str(NEW_RAG_DIR))
    
    # 转换格式并添加
    examples = []
    for p in unique:
        examples.append((p["user_msg"], p["assistant_msg"], p.get("assistant_gender", "unknown")))
    
    added = rag._add_examples_with_gender(examples)
    print(f"添加: {added}")
    print(f"总量: {rag.count()}")
    print(f"性别分布: {rag.count_by_gender()}")
    
    # 10. 测试查询
    print(f"\n=== 测试查询 ===")
    tests = [
        ("你在干嘛", None),
        ("想你了", "female"),
        ("想你了", "male"),
        ("今天好累啊", None),
        ("我生气了", "female"),
        ("哈哈哈哈", None),
    ]
    for query, gender in tests:
        results = rag.query(query, n_results=3, gender=gender)
        label = f"[{gender or 'all'}]"
        print(f"\n{label} \"{query}\":")
        for r in results:
            g = r.get('gender', '?')
            print(f"  [{g}] U: {r['user'][:40]}")
            print(f"       A: {r['assistant'][:80]}")
    
    print(f"\n✅ 完成！新RAG保存在 {NEW_RAG_DIR}")

if __name__ == "__main__":
    main()
