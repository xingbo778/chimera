#!/usr/bin/env python3
"""
从1186条真实微信聊天素材中，用LLM提炼出说话风格规则。
分批喂给LLM，最后汇总成一段简洁的风格描述。
"""
import json, os, random
from openai import OpenAI

client = OpenAI()  # 使用预配置的API

# 加载素材
with open('/home/ubuntu/chimera/new_rag_data_v3/cleaned_pairs_v3.json') as f:
    all_pairs = json.load(f)

print(f"总素材: {len(all_pairs)} 条")

# 按性别分组
female = [p for p in all_pairs if p['assistant_gender'] == 'female']
male = [p for p in all_pairs if p['assistant_gender'] == 'male']
unknown = [p for p in all_pairs if p['assistant_gender'] == 'unknown']

print(f"女: {len(female)}, 男: {len(male)}, 未知: {len(unknown)}")

def format_samples(pairs, n=50):
    """随机抽取n条，格式化为文本"""
    sampled = random.sample(pairs, min(n, len(pairs)))
    lines = []
    for p in sampled:
        lines.append(f"对方: {p['user_msg']}")
        lines.append(f"回复: {p['assistant_msg']}")
        lines.append("")
    return "\n".join(lines)

def distill_batch(samples_text, batch_label):
    """让LLM从一批样本中提炼风格特征"""
    prompt = f"""以下是从真实微信聊天截图中提取的对话片段（{batch_label}）。
请仔细分析这些回复的说话风格，提炼出具体的、可操作的风格规则。

注意：
- 关注语气、句式、用词习惯、标点使用、表情符号使用
- 关注回复长度模式（什么时候短回复，什么时候长一点）
- 关注幽默/吐槽/撒娇/冷淡等情绪表达方式
- 关注口头禅、语气词、特殊用法
- 不要泛泛而谈，要给出具体的、有辨识度的特征

对话样本：
{samples_text}

请输出：
1. 核心风格特征（5-8条，每条一句话，具体且有辨识度）
2. 常用句式/表达（列举5-10个典型的说话模式）
3. 禁忌（什么是这种风格绝对不会做的）"""

    resp = client.chat.completions.create(
        model="gemini-2.5-flash",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500,
        temperature=0.3,
    )
    return resp.choices[0].message.content

# 分3批提炼（每批50条，不同随机种子）
random.seed(42)
results = []

for i in range(3):
    random.seed(42 + i * 10)
    # 混合各性别的样本
    batch_samples = format_samples(all_pairs, n=60)
    print(f"\n--- 第{i+1}批蒸馏 ---")
    result = distill_batch(batch_samples, f"第{i+1}批，60条混合样本")
    results.append(result)
    print(result[:200] + "...")

# 最终汇总
print("\n\n--- 最终汇总 ---")
summary_prompt = f"""以下是从1186条真实微信聊天中分3批提炼出的风格分析。
请将它们汇总成一段**简洁、可直接用于AI prompt的风格指导**。

要求：
- 总长度控制在300字以内
- 只保留最有辨识度、最核心的特征
- 写成"你说话的风格是..."的格式，可以直接放进system prompt
- 要具体，不要"自然""随意"这种空话
- 包含正面指导（该怎么说）和负面约束（不该怎么说）

批次1的分析：
{results[0]}

批次2的分析：
{results[1]}

批次3的分析：
{results[2]}"""

final = client.chat.completions.create(
    model="gemini-2.5-flash",
    messages=[{"role": "user", "content": summary_prompt}],
    max_tokens=800,
    temperature=0.3,
)
style_rules = final.choices[0].message.content

print(style_rules)

# 保存
with open('/home/ubuntu/chimera/distilled_style_rules.md', 'w') as f:
    f.write("# 蒸馏出的说话风格规则\n\n")
    f.write("来源：1186条真实微信聊天截图 → 3批LLM分析 → 汇总\n\n")
    f.write("## 最终风格规则（用于system prompt）\n\n")
    f.write(style_rules)
    f.write("\n\n---\n\n## 原始分析\n\n")
    for i, r in enumerate(results):
        f.write(f"### 第{i+1}批\n\n{r}\n\n")

print(f"\n✅ 保存到 distilled_style_rules.md")
