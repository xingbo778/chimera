#!/usr/bin/env python3
"""
用视觉大模型（gemini-2.5-flash）从微信聊天截图中提取对话
区分男女，输出结构化JSON
"""
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

import httpx

API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL = "gemini-2.5-flash"

IMG_DIR = Path("/home/ubuntu/chimera/wechat_screenshots")
OUTPUT_FILE = Path("/home/ubuntu/chimera/extracted_dialogs.json")
CHECKPOINT_FILE = Path("/home/ubuntu/chimera/extract_checkpoint.json")

PROMPT = """你是一个对话提取专家。请仔细观察这张微信/QQ聊天截图，提取其中的对话内容。

要求：
1. 识别每一条消息的发送者和内容
2. 根据气泡位置判断：右边（绿色气泡）是"我方"，左边（白色气泡）是"对方"
3. 根据上下文和笔记标题推断性别关系：
   - 如果是情侣聊天，标注"男"和"女"
   - 如果是闺蜜/姐妹聊天，标注"女A"和"女B"
   - 如果是兄弟聊天，标注"男A"和"男B"
   - 如果无法判断，标注"A"和"B"
4. 按消息顺序排列
5. 忽略表情包图片（但可以用[表情]标注）、系统消息、时间戳
6. 如果图片不是聊天截图（比如是风景照、自拍等），返回空数组

请以JSON格式返回，格式如下：
{
  "is_chat": true/false,
  "chat_type": "情侣"|"闺蜜"|"兄弟"|"朋友"|"家人"|"其他",
  "participants": {"left": "女/男/女A/男A", "right": "男/女/女B/男B"},
  "messages": [
    {"sender": "女", "text": "你在干嘛"},
    {"sender": "男", "text": "在想你啊"},
    ...
  ]
}

只返回JSON，不要其他文字。"""

# 加载checkpoint
def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"processed": {}, "results": []}

def save_checkpoint(data):
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def extract_one(client: httpx.AsyncClient, img_path: str, semaphore: asyncio.Semaphore):
    """提取单张图片的对话"""
    async with semaphore:
        try:
            # 读取图片并base64编码
            with open(img_path, 'rb') as f:
                img_data = base64.b64encode(f.read()).decode()
            
            # 判断格式
            ext = Path(img_path).suffix.lower()
            media_type = "image/webp" if ext == ".webp" else "image/jpeg"
            
            payload = {
                "model": MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{img_data}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 2000,
                "temperature": 0.1
            }
            
            resp = await client.post(
                f"{BASE_URL}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=60
            )
            
            if resp.status_code != 200:
                return {"file": os.path.basename(img_path), "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
            
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            
            # 解析JSON
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
            
            result = json.loads(content)
            result["file"] = os.path.basename(img_path)
            return result
            
        except json.JSONDecodeError as e:
            return {"file": os.path.basename(img_path), "error": f"JSON parse error: {str(e)[:100]}", "raw": content[:500] if 'content' in dir() else ""}
        except Exception as e:
            return {"file": os.path.basename(img_path), "error": str(e)[:200]}

async def main():
    # 加载图片列表
    with open("/home/ubuntu/chimera/valid_images.txt") as f:
        images = [line.strip() for line in f if line.strip()]
    
    print(f"共 {len(images)} 张有效图片")
    
    # 加载checkpoint
    checkpoint = load_checkpoint()
    processed = set(checkpoint["processed"].keys()) if checkpoint["processed"] else set()
    results = checkpoint["results"]
    
    # 过滤已处理的
    todo = [img for img in images if img not in processed]
    print(f"已处理: {len(processed)}, 待处理: {len(todo)}")
    
    if not todo:
        print("全部已处理完成！")
        return
    
    # 并发处理
    semaphore = asyncio.Semaphore(5)  # 5并发，避免限流
    
    async with httpx.AsyncClient() as client:
        batch_size = 30
        for i in range(0, len(todo), batch_size):
            batch = todo[i:i+batch_size]
            tasks = [
                extract_one(client, str(IMG_DIR / img), semaphore)
                for img in batch
            ]
            
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for img, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    result = {"file": img, "error": str(result)[:200]}
                
                results.append(result)
                checkpoint["processed"][img] = True
            
            # 保存checkpoint
            checkpoint["results"] = results
            save_checkpoint(checkpoint)
            
            done = len(processed) + i + len(batch)
            total = len(images)
            chats = sum(1 for r in results if r.get("is_chat"))
            errors = sum(1 for r in results if "error" in r)
            print(f"[{done}/{total}] 已提取 {chats} 个对话, {errors} 个错误")
            
            # 每批之间等待避免限流
            if i + batch_size < len(todo):
                print("等待10秒避免限流...")
                await asyncio.sleep(10)
    
    # 最终保存
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    # 统计
    chats = [r for r in results if r.get("is_chat")]
    non_chats = [r for r in results if r.get("is_chat") == False]
    errors = [r for r in results if "error" in r]
    
    print(f"\n=== 最终统计 ===")
    print(f"总图片: {len(results)}")
    print(f"聊天截图: {len(chats)}")
    print(f"非聊天图: {len(non_chats)}")
    print(f"错误: {len(errors)}")
    
    if chats:
        types = {}
        for c in chats:
            t = c.get("chat_type", "未知")
            types[t] = types.get(t, 0) + 1
        print(f"\n聊天类型分布:")
        for t, n in sorted(types.items(), key=lambda x: -x[1]):
            print(f"  {t}: {n}")
        
        total_msgs = sum(len(c.get("messages", [])) for c in chats)
        print(f"\n总消息条数: {total_msgs}")
        print(f"平均每张图: {total_msgs/len(chats):.1f} 条")

if __name__ == "__main__":
    asyncio.run(main())
