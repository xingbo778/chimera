"""
数据精细梳理脚本
用LLM对1186条数据做：
1. 话题分类（穿搭/工作/美食/旅行/学习/健身/宠物/日常/情感/娱乐）
2. 质量评分（1-5分）
3. 风格标签（搞笑/毒舌/撒娇/正经/敷衍）
4. 是否适合做few-shot示例
"""

import asyncio
import json
import os
import time
from openai import AsyncOpenAI

client = AsyncOpenAI()
SEM = asyncio.Semaphore(10)

CLASSIFY_PROMPT = """你是一个数据标注员。请对以下微信聊天对话进行标注。

对话：
用户: {user_msg}
回复: {assistant_msg}
{context_str}

请返回JSON格式（不要其他内容）：
{{
  "topic": "话题分类，从以下选一个：穿搭/工作/美食/旅行/学习/健身/宠物/日常/情感/娱乐/节日/转账",
  "quality": 质量评分1-5（1=纯垃圾如单字回复 2=太短无信息 3=普通但有点意思 4=好，有个性有情绪 5=非常好，适合做示例），
  "style": "风格标签，从以下选1-2个用/分隔：搞笑/毒舌/撒娇/温柔/正经/敷衍/互怼/调侃/关心/吐槽",
  "good_fewshot": true或false（是否适合做few-shot示例，要求：回复有个性、有情绪、像真人、不太短也不太长）
}}"""

async def classify_one(idx, pair):
    async with SEM:
        ctx_str = ""
        if pair.get("context") and len(pair["context"]) > 0:
            ctx_lines = []
            for c in pair["context"][-3:]:  # 最多3轮上下文
                ctx_lines.append(f"  {c.get('sender','?')}: {c.get('text','')[:50]}")
            ctx_str = f"上下文（之前的对话）:\n" + "\n".join(ctx_lines)
        
        prompt = CLASSIFY_PROMPT.format(
            user_msg=pair["user_msg"][:100],
            assistant_msg=pair["assistant_msg"][:150],
            context_str=ctx_str
        )
        
        try:
            resp = await client.chat.completions.create(
                model="gpt-4.1-nano",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=200,
            )
            text = resp.choices[0].message.content.strip()
            # 提取JSON
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            result = json.loads(text)
            return idx, result, None
        except Exception as e:
            return idx, None, str(e)

async def main():
    with open("new_rag_data_v3/cleaned_pairs_v3.json") as f:
        pairs = json.load(f)
    
    print(f"开始标注 {len(pairs)} 条数据...")
    t0 = time.time()
    
    # 检查checkpoint
    ckpt_path = "curate_checkpoint.json"
    done = {}
    if os.path.exists(ckpt_path):
        with open(ckpt_path) as f:
            done = json.load(f)
        print(f"从checkpoint恢复，已完成 {len(done)} 条")
    
    # 批量处理
    batch_size = 50
    total = len(pairs)
    
    for batch_start in range(0, total, batch_size):
        batch_end = min(batch_start + batch_size, total)
        tasks = []
        for i in range(batch_start, batch_end):
            if str(i) in done:
                continue
            tasks.append(classify_one(i, pairs[i]))
        
        if not tasks:
            continue
            
        results = await asyncio.gather(*tasks)
        
        errors = 0
        for idx, result, err in results:
            if err:
                errors += 1
                done[str(idx)] = {"topic": "日常", "quality": 3, "style": "普通", "good_fewshot": False, "error": err}
            else:
                done[str(idx)] = result
        
        # 保存checkpoint
        with open(ckpt_path, "w") as f:
            json.dump(done, f, ensure_ascii=False)
        
        elapsed = time.time() - t0
        print(f"  [{batch_end}/{total}] 完成，{errors}个错误，耗时{elapsed:.0f}秒")
    
    # 合并结果
    print(f"\n标注完成！总耗时 {time.time()-t0:.0f}秒")
    
    # 统计
    from collections import Counter
    topics = Counter()
    qualities = Counter()
    styles = Counter()
    good_count = 0
    
    curated_pairs = []
    for i, pair in enumerate(pairs):
        label = done.get(str(i), {})
        enriched = {**pair, **label}
        curated_pairs.append(enriched)
        
        topics[label.get("topic", "未知")] += 1
        qualities[label.get("quality", 0)] += 1
        for s in label.get("style", "").split("/"):
            if s:
                styles[s] += 1
        if label.get("good_fewshot"):
            good_count += 1
    
    print(f"\n话题分布:")
    for t, c in topics.most_common():
        print(f"  {t}: {c} ({c/len(pairs)*100:.1f}%)")
    
    print(f"\n质量分布:")
    for q in sorted(qualities.keys()):
        print(f"  {q}分: {qualities[q]} ({qualities[q]/len(pairs)*100:.1f}%)")
    
    print(f"\n风格分布:")
    for s, c in styles.most_common(15):
        print(f"  {s}: {c}")
    
    print(f"\n适合做few-shot: {good_count} ({good_count/len(pairs)*100:.1f}%)")
    
    # 保存
    with open("curated_pairs.json", "w") as f:
        json.dump(curated_pairs, f, ensure_ascii=False, indent=2)
    print(f"标注后数据已保存到 curated_pairs.json")

if __name__ == "__main__":
    asyncio.run(main())
