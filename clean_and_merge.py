"""
数据清洗和合并：
1. 清洗现有 2023 条数据（删除垃圾数据）
2. 合并新提取的 290+ 条弱势话题数据
3. 用 LLM 给所有数据打话题标签和质量评分
4. 输出最终的高质量数据集
"""
import json
import asyncio
import os
from collections import Counter
from openai import AsyncOpenAI

client = AsyncOpenAI()

def load_data():
    """加载所有数据"""
    # 现有数据
    with open("/home/ubuntu/chimera/new_rag_data/cleaned_pairs.json") as f:
        existing = json.load(f)
    
    # 新提取的弱势话题数据
    with open("/home/ubuntu/chimera/new_topic_pairs.json") as f:
        new_pairs = json.load(f)
    
    return existing, new_pairs

def basic_clean(pairs):
    """基础清洗：删除明显的垃圾数据"""
    cleaned = []
    removed = 0
    
    for p in pairs:
        user_msg = p.get("user_msg", "")
        assistant_msg = p.get("assistant_msg", "")
        
        if not user_msg or not assistant_msg:
            removed += 1
            continue
        
        # 过滤太短的（纯表情或单字）
        user_clean = user_msg.replace("[表情]", "").replace("[图片]", "").strip()
        asst_clean = assistant_msg.replace("[表情]", "").replace("[图片]", "").strip()
        
        if len(user_clean) < 2 and len(asst_clean) < 2:
            removed += 1
            continue
        
        # 过滤系统消息
        skip_keywords = ["红包", "转账", "以上是打赏", "该消息已撤回", "你已添加", 
                         "以下为新消息", "消息已发出", "对方已读", "通话时长",
                         "拍了拍", "邀请你加入", "修改了群名"]
        if any(kw in user_msg for kw in skip_keywords) or any(kw in assistant_msg for kw in skip_keywords):
            removed += 1
            continue
        
        # 过滤纯图片/语音
        if user_msg.strip() in ["[图片]", "[语音]", "[视频]"] and asst_clean == "":
            removed += 1
            continue
        
        cleaned.append(p)
    
    print(f"基础清洗: {len(pairs)} -> {len(cleaned)} (删除 {removed})")
    return cleaned

async def batch_annotate(pairs, batch_size=30):
    """用 LLM 批量标注话题和质量"""
    
    ANNOTATE_PROMPT = """你是一个数据标注专家。请对以下微信聊天对话进行标注。

对每条对话，请判断：
1. **topic**（话题类别）：日常、情感、工作、穿搭、健身、旅行、美食、学习、娱乐、宠物、颜值 中的一个
2. **quality**（质量评分 1-4）：
   - 4分：非常自然、有个性、碎片化、像真人微信聊天
   - 3分：比较自然，有一定口语感
   - 2分：一般，有些生硬或不太自然
   - 1分：垃圾数据，不像真人聊天
3. **good_fewshot**（是否适合作为 few-shot 示例）：true/false
   - 适合的标准：回复短小精悍、口语化、有个性、碎片化

请以JSON数组格式返回，每个元素包含 topic, quality, good_fewshot 三个字段。
数组长度必须与输入对话数量一致。

对话列表：
"""
    
    all_annotations = []
    
    for i in range(0, len(pairs), batch_size):
        batch = pairs[i:i+batch_size]
        
        # Build input text
        dialog_text = ""
        for j, p in enumerate(batch):
            dialog_text += f"\n{j+1}. 用户: {p.get('user_msg', '')[:100]}\n   回复: {p.get('assistant_msg', '')[:100]}\n"
        
        try:
            resp = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": ANNOTATE_PROMPT},
                    {"role": "user", "content": dialog_text}
                ],
                temperature=0.1,
                max_tokens=3000,
            )
            
            content = resp.choices[0].message.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            annotations = json.loads(content)
            
            # Ensure correct length
            if len(annotations) != len(batch):
                print(f"  Warning: batch {i//batch_size} got {len(annotations)} annotations for {len(batch)} pairs")
                # Pad or truncate
                while len(annotations) < len(batch):
                    annotations.append({"topic": "日常", "quality": 2, "good_fewshot": False})
                annotations = annotations[:len(batch)]
            
            all_annotations.extend(annotations)
            
        except Exception as e:
            print(f"  Error in batch {i//batch_size}: {e}")
            # Default annotations
            for _ in batch:
                all_annotations.append({"topic": "日常", "quality": 2, "good_fewshot": False})
        
        if i % 90 == 0:
            print(f"  标注进度: {i}/{len(pairs)}")
        
        await asyncio.sleep(0.5)
    
    return all_annotations

async def main():
    existing, new_pairs = load_data()
    
    # Step 1: Basic clean
    print("=" * 50)
    print("Step 1: 基础清洗")
    existing_clean = basic_clean(existing)
    new_clean = basic_clean(new_pairs)
    
    # Step 2: Merge
    print("\n" + "=" * 50)
    print("Step 2: 合并数据")
    
    # Normalize new pairs to same format as existing
    for p in new_clean:
        if "user_gender" not in p:
            p["user_gender"] = "unknown"
        if "assistant_gender" not in p:
            p["assistant_gender"] = "unknown"
        if "chat_type" not in p:
            p["chat_type"] = "其他"
    
    all_pairs = existing_clean + new_clean
    print(f"合并后总计: {len(all_pairs)} 条")
    
    # Step 3: Annotate with topics and quality
    print("\n" + "=" * 50)
    print("Step 3: LLM 标注话题和质量")
    annotations = await batch_annotate(all_pairs)
    
    # Step 4: Merge annotations
    print("\n" + "=" * 50)
    print("Step 4: 合并标注结果")
    
    for i, p in enumerate(all_pairs):
        if i < len(annotations):
            ann = annotations[i]
            p["topic"] = ann.get("topic", "日常")
            p["quality"] = ann.get("quality", 2)
            p["good_fewshot"] = ann.get("good_fewshot", False)
    
    # Step 5: Filter by quality
    high_quality = [p for p in all_pairs if p.get("quality", 0) >= 3]
    fewshot_ready = [p for p in all_pairs if p.get("good_fewshot", False)]
    
    print(f"\n质量分布:")
    quality_dist = Counter(p.get("quality", 0) for p in all_pairs)
    for q in sorted(quality_dist.keys()):
        print(f"  质量 {q}: {quality_dist[q]} 条")
    
    print(f"\n话题分布:")
    topic_dist = Counter(p.get("topic", "unknown") for p in all_pairs)
    for t, c in topic_dist.most_common():
        print(f"  {t}: {c} 条")
    
    print(f"\n高质量(>=3): {len(high_quality)} 条")
    print(f"适合few-shot: {len(fewshot_ready)} 条")
    
    # Save
    output_all = "/home/ubuntu/chimera/final_all_pairs.json"
    output_hq = "/home/ubuntu/chimera/final_high_quality.json"
    output_fewshot = "/home/ubuntu/chimera/final_fewshot_ready.json"
    
    with open(output_all, "w") as f:
        json.dump(all_pairs, f, ensure_ascii=False, indent=2)
    with open(output_hq, "w") as f:
        json.dump(high_quality, f, ensure_ascii=False, indent=2)
    with open(output_fewshot, "w") as f:
        json.dump(fewshot_ready, f, ensure_ascii=False, indent=2)
    
    print(f"\n保存完成:")
    print(f"  全部数据: {output_all} ({len(all_pairs)} 条)")
    print(f"  高质量: {output_hq} ({len(high_quality)} 条)")
    print(f"  Few-shot: {output_fewshot} ({len(fewshot_ready)} 条)")

if __name__ == "__main__":
    asyncio.run(main())
