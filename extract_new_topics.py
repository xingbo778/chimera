"""
从新采集的弱势话题图片中提取对话，并清洗合并所有数据
"""
import json
import os
import glob
import base64
import asyncio
import time
from openai import AsyncOpenAI

# 使用 gemini-2.5-flash 视觉模型
client = AsyncOpenAI()

EXTRACT_PROMPT = """你是一个微信聊天截图分析专家。请仔细观察这张图片，提取其中的微信聊天对话。

要求：
1. 只提取真实的微信聊天对话（有明确的发送方和接收方）
2. 区分"我方"（右侧绿色气泡）和"对方"（左侧白色气泡）
3. 判断对话双方的性别（根据头像、称呼、说话风格推断）
4. 判断对话的话题类别
5. 如果图片不是微信聊天截图，返回空数组

请以JSON格式返回，格式如下：
```json
{
  "is_chat": true,
  "pairs": [
    {
      "user_msg": "对方说的话（可以是多条合并，用\\n分隔）",
      "assistant_msg": "我方的回复（可以是多条合并，用\\n分隔）",
      "user_gender": "male/female/unknown",
      "assistant_gender": "male/female/unknown",
      "topic": "话题类别"
    }
  ]
}
```

话题类别只能是以下之一：日常、情感、工作、穿搭、健身、旅行、美食、学习、娱乐、宠物、颜值

注意：
- 每个pair是一组"对方发言→我方回复"的配对
- 如果对方连续发了多条消息，合并为一个user_msg
- 如果我方连续回复了多条，合并为一个assistant_msg，用\\n分隔
- 只提取有实际内容的对话，忽略系统消息、红包、转账等
- [表情]标记表情包
"""

async def extract_from_image(image_path: str, topic_hint: str) -> dict:
    """从单张图片提取对话"""
    with open(image_path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode()
    
    # Determine media type
    ext = os.path.splitext(image_path)[1].lower()
    media_type = "image/webp" if ext == ".webp" else "image/jpeg"
    
    try:
        resp = await client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": EXTRACT_PROMPT + f"\n\n提示：这张图片可能与「{topic_hint}」话题相关。"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{img_data}"
                            }
                        }
                    ]
                }
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        
        content = resp.choices[0].message.content.strip()
        # Extract JSON from response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        result = json.loads(content)
        result["source"] = os.path.basename(image_path)
        return result
    except Exception as e:
        print(f"  Error processing {image_path}: {e}")
        return {"is_chat": False, "pairs": [], "source": os.path.basename(image_path)}

async def process_topic_folder(folder: str, topic: str) -> list:
    """处理一个话题文件夹的所有图片"""
    images = sorted(glob.glob(os.path.join(folder, "*.webp")))
    if not images:
        return []
    
    print(f"\n处理 {topic} 话题: {len(images)} 张图片")
    
    all_pairs = []
    # Process in batches of 5 to avoid rate limits
    batch_size = 5
    for i in range(0, len(images), batch_size):
        batch = images[i:i+batch_size]
        tasks = [extract_from_image(img, topic) for img in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for j, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"  Error: {result}")
                continue
            if result.get("is_chat") and result.get("pairs"):
                for pair in result["pairs"]:
                    pair["source"] = result["source"]
                    if not pair.get("topic"):
                        pair["topic"] = topic
                    all_pairs.append(pair)
        
        print(f"  Batch {i//batch_size + 1}: 提取了 {sum(1 for r in results if not isinstance(r, Exception) and r.get('is_chat') and r.get('pairs'))} 张有效图片")
        
        if i + batch_size < len(images):
            await asyncio.sleep(1)  # Rate limit
    
    print(f"  {topic} 总计: {len(all_pairs)} 条对话对")
    return all_pairs

async def main():
    base_dir = "/home/ubuntu/chimera/wechat_screenshots"
    
    topic_folders = {
        "工作": os.path.join(base_dir, "topic_work"),
        "穿搭": os.path.join(base_dir, "topic_fashion"),
        "健身": os.path.join(base_dir, "topic_fitness"),
        "旅行": os.path.join(base_dir, "topic_travel"),
        "美食": os.path.join(base_dir, "topic_food"),
        "学习": os.path.join(base_dir, "topic_study"),
    }
    
    all_new_pairs = []
    
    for topic, folder in topic_folders.items():
        if os.path.exists(folder):
            pairs = await process_topic_folder(folder, topic)
            all_new_pairs.extend(pairs)
        else:
            print(f"文件夹不存在: {folder}")
    
    # Save results
    output_path = "/home/ubuntu/chimera/new_topic_pairs.json"
    with open(output_path, "w") as f:
        json.dump(all_new_pairs, f, ensure_ascii=False, indent=2)
    
    print(f"\n总计提取: {len(all_new_pairs)} 条新对话对")
    print(f"保存到: {output_path}")
    
    # Topic distribution
    from collections import Counter
    topics = Counter(p.get("topic", "unknown") for p in all_new_pairs)
    print("\n话题分布:")
    for t, c in topics.most_common():
        print(f"  {t}: {c}")

if __name__ == "__main__":
    asyncio.run(main())
