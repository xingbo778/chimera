"""
快速积累小红书评论风格到 style RAG。
按话题领域定向刷，确保工作/美食/娱乐/宠物/学习/旅行等都有覆盖。
"""
import sys, os, time, random
sys.path.insert(0, os.path.dirname(__file__))

from openai import OpenAI
client = OpenAI()

# 评测中表现差的 6 个领域 + 表现好的 4 个领域，每个领域 3 个关键词
TARGETED_TOPICS = {
    "工作": ["职场吐槽", "加班日常", "上班摸鱼"],
    "美食": ["今天吃什么", "探店打卡", "深夜放毒"],
    "娱乐": ["追剧推荐", "电影安利", "综艺笑死"],
    "宠物": ["养猫日常", "猫咪搞笑", "铲屎官日常"],
    "学习": ["考研日记", "期末复习", "学习打卡"],
    "旅行": ["旅行攻略", "citywalk", "周末去哪玩"],
    "穿搭": ["今日穿搭", "显瘦穿搭", "换季穿搭"],
    "颜值": ["发型推荐", "护肤分享", "化妆教程"],
    "日常": ["独居日常", "下班后的生活", "今天的快乐"],
    "健身": ["减肥打卡", "健身日常", "减脂心得"],
}

def call_llm(system, user, max_tokens=600, temperature=0.7):
    try:
        return client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens, temperature=temperature,
        ).choices[0].message.content
    except Exception as e:
        print(f"  LLM 调用失败: {e}")
        return None

def extract_and_add_to_rag(rag, content, topic_name):
    """从内容中提取评论风格并写入 RAG"""
    comments = []
    
    if "评论:" in content:
        comment_section = content.split("评论:")[-1]
        for line in comment_section.split("\n"):
            line = line.strip().lstrip("- ").strip()
            if line and len(line) > 2 and len(line) < 150:
                if ": " in line and line.index(": ") < 15:
                    line = line.split(": ", 1)[1]
                comments.append(line)
    
    if "正文:" in content:
        body = content.split("正文:")[-1].split("评论:")[0] if "评论:" in content else content.split("正文:")[-1]
        for line in body.split("\n"):
            line = line.strip()
            if line and len(line) > 5 and len(line) < 80:
                comments.append(line)
    
    if len(comments) < 1:
        print(f"  内容太少 ({len(comments)} 条)，跳过")
        return 0
    
    extract_prompt = f"""你是一个语言风格分析专家。以下是小红书关于「{topic_name}」话题的帖子内容和评论：

{chr(10).join(comments[:25])}

从中提取有特色的口语化表达，转化为朋友聊天对话格式。

规则：
1. 提取口语化、有特色的表达（如"救命这也太好看了吧""绝了""谁懂啊""真的会谢""笑不活了""太绝了姐妹"）
2. 也提取有态度的短评（如"这谁顶得住""直接种草""我先冲了""太真实了"）
3. 对话的 user 问句要贴合「{topic_name}」这个话题
4. 不要纯广告、纯表情、无意义内容
5. 每组对话格式：
- user: 模拟一个关于{topic_name}的自然问句或话题
- assistant: 用评论中的口语化表达回复（可以多条，每条不超过 40 字）
6. 尽量多提取，最多 5 组
7. 如果实在没有好的口语化表达，回复"无"

示例（{topic_name}相关）：
- user: 你觉得这个怎么样
- assistant: 绝了真的绝了
- assistant: 我直接冲了"""
    
    extracted = call_llm(extract_prompt, "请提取")
    
    if not extracted or extracted.strip() == "无" or len(extracted.strip()) < 15:
        print("  没提取到有用的口语化表达")
        return 0
    
    blocks = extracted.strip().split("\n\n")
    valid_blocks = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        has_user = any(l.strip().startswith("- user:") for l in lines)
        has_assistant = any(l.strip().startswith("- assistant:") for l in lines)
        if has_user and has_assistant:
            assistant_lines = [l for l in lines if l.strip().startswith("- assistant:")]
            all_short = all(len(l.replace("- assistant:", "").strip()) <= 50 for l in assistant_lines)
            if all_short:
                valid_blocks.append(block)
    
    if not valid_blocks:
        print("  验证后没有合格的对话")
        return 0
    
    added = rag.add_examples_from_text("\n\n".join(valid_blocks[:5]))
    return added


def main():
    from style_rag import StyleRAG
    from skills import skill_xhs_browse
    
    rag = StyleRAG(persist_dir='style_rag_db', few_shot_path='final_few_shot.md')
    baseline = rag.count()
    print(f"=== 定向话题积累 ===")
    print(f"RAG 基线: {baseline} 条")
    print(f"目标领域: {list(TARGETED_TOPICS.keys())}\n")
    
    total_added = 0
    topic_stats = {}
    
    # 每个领域刷 3 轮（每轮一个关键词）
    for topic_name, keywords in TARGETED_TOPICS.items():
        topic_added = 0
        print(f"\n{'='*50}")
        print(f"📂 领域: {topic_name} (关键词: {keywords})")
        print(f"{'='*50}")
        
        for i, keyword in enumerate(keywords):
            print(f"\n  --- {topic_name} [{i+1}/3]: {keyword} ---")
            try:
                result = skill_xhs_browse(keyword=keyword)
                if not result or "content" not in result:
                    print(f"  浏览失败，跳过")
                    continue
                
                content = result["content"]
                comment_count = content.count("\n") if "评论:" in content else 0
                print(f"  💬 评论区约 {comment_count} 行")
                
                added = extract_and_add_to_rag(rag, content, topic_name)
                topic_added += added
                total_added += added
                print(f"  ✅ 新增 {added} 条 (领域累计: {topic_added}, 总新增: {total_added})")
                
            except Exception as e:
                print(f"  ❌ 异常: {e}")
            
            time.sleep(3)
        
        topic_stats[topic_name] = topic_added
        print(f"\n  📊 {topic_name} 小计: +{topic_added}")
    
    print(f"\n{'='*50}")
    print(f"=== 积累完成 ===")
    print(f"RAG: {baseline} → {rag.count()} (新增: {total_added})")
    print(f"\n各领域统计:")
    for topic, count in sorted(topic_stats.items(), key=lambda x: -x[1]):
        bar = "█" * count + "░" * (10 - min(count, 10))
        print(f"  {topic:6s}: +{count:2d} {bar}")


if __name__ == "__main__":
    main()
