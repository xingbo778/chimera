"""
评测脚本 v5：消融实验
在旧版distilled基础上做最小改动，找到最优配置

方案：
A. distilled_old: 旧RAG 2-shot + 旧prompt（基线 8.82）
B. old_3shot: 旧RAG 3-shot + 旧prompt
C. new_rag_2shot: 新RAG(话题匹配) 2-shot + 旧prompt
D. new_rag_3shot: 新RAG(话题匹配) 3-shot + 旧prompt
E. old_temp08: 旧RAG 2-shot + 旧prompt + temp=0.8
"""

import asyncio
import json
import os
import sys
import time

from openai import AsyncOpenAI

# ── 测试用例 ──
TEST_CASES = [
    {"topic": "穿搭", "msg": "你觉得这件衣服好看吗"},
    {"topic": "穿搭", "msg": "今天穿什么出门好"},
    {"topic": "美食", "msg": "晚上吃什么好纠结"},
    {"topic": "美食", "msg": "你会做饭吗"},
    {"topic": "工作", "msg": "今天上班好累啊"},
    {"topic": "工作", "msg": "老板又让我加班了"},
    {"topic": "娱乐", "msg": "最近有什么好看的电影"},
    {"topic": "娱乐", "msg": "密室逃脱好不好玩"},
    {"topic": "宠物", "msg": "我家猫把杯子打翻了"},
    {"topic": "宠物", "msg": "你看它这个表情是不是在生气"},
    {"topic": "学习", "msg": "你有什么好的学习方法吗"},
    {"topic": "学习", "msg": "这道题怎么都做不出来"},
    {"topic": "旅行", "msg": "周末去哪玩比较好"},
    {"topic": "旅行", "msg": "你去过最好玩的地方是哪"},
    {"topic": "颜值", "msg": "眼影怎么画才好看"},
    {"topic": "颜值", "msg": "素颜出门会不会太邋遢"},
    {"topic": "日常", "msg": "你觉得早起难还是晚睡难"},
    {"topic": "日常", "msg": "好无聊啊有什么好玩的"},
    {"topic": "健身", "msg": "健身的时候听什么音乐好"},
    {"topic": "健身", "msg": "健身卡办了但是不想去"},
]

# ── SOUL prompt ──
SOUL_FILE = os.path.join(os.path.dirname(__file__), "SOUL.md")
with open(SOUL_FILE, "r") as f:
    SOUL_PROMPT = f.read()

STYLE_RULES = """## 说话风格指南（从真实微信聊天中提炼）

你说话的风格是：情绪外露且直接，善用反问、质问和戏谑，语言口语化、碎片化，高频使用表情符号和网络用语。你擅长用夸张、自嘲或"互怼"来制造幽默感，并积极接梗、抛梗，营造强互动性。你的回复长短灵活，但即使是短回复也充满情绪。你绝不会使用正式、书面化、过度客套或冗长的表达，也从不回避冲突或隐藏真实想法，而是直接反击或给出有趣的回复。"""

STYLE_NOTE = "\n\n【风格参考】以下对话仅供参考说话风格和语气，不要模仿其内容或长度。你的回复应该自然展开，不受示例长度限制。\n"

# ── RAG 加载 ──
sys.path.insert(0, os.path.dirname(__file__))
from style_rag_v3 import StyleRAGv3
from style_rag import StyleRAG

rag_new = StyleRAGv3(persist_dir=os.path.join(os.path.dirname(__file__), "chroma_style_v3_db"))
rag_old = StyleRAG(persist_dir=os.path.join(os.path.dirname(__file__), "chroma_style_db"))

client = AsyncOpenAI()

async def generate_reply(user_msg: str, mode: str, topic: str = None) -> tuple:
    """Generate reply for different configurations"""
    
    if mode == "A":  # distilled_old: 旧RAG 2-shot + 旧prompt
        results = rag_old.query(user_msg, n_results=2)
        few_shot = []
        for ex in results:
            few_shot.append({"role": "user", "content": ex["user"]})
            few_shot.append({"role": "assistant", "content": ex["assistant"]})
        messages = [
            {"role": "system", "content": SOUL_PROMPT + "\n\n" + STYLE_RULES + STYLE_NOTE},
            *few_shot,
            {"role": "user", "content": user_msg},
        ]
        resp = await client.chat.completions.create(model="gpt-4.1-mini", messages=messages, temperature=0.85, max_tokens=300)
        return resp.choices[0].message.content.strip(), results
    
    elif mode == "B":  # old_3shot: 旧RAG 3-shot + 旧prompt
        results = rag_old.query(user_msg, n_results=3)
        few_shot = []
        for ex in results:
            few_shot.append({"role": "user", "content": ex["user"]})
            few_shot.append({"role": "assistant", "content": ex["assistant"]})
        messages = [
            {"role": "system", "content": SOUL_PROMPT + "\n\n" + STYLE_RULES + STYLE_NOTE},
            *few_shot,
            {"role": "user", "content": user_msg},
        ]
        resp = await client.chat.completions.create(model="gpt-4.1-mini", messages=messages, temperature=0.85, max_tokens=300)
        return resp.choices[0].message.content.strip(), results
    
    elif mode == "C":  # new_rag_2shot: 新RAG(话题匹配) 2-shot + 旧prompt
        results = rag_new.query(user_msg, n_results=2, topic=topic)
        few_shot = []
        for ex in results:
            few_shot.append({"role": "user", "content": ex["user"]})
            few_shot.append({"role": "assistant", "content": ex["assistant"]})
        messages = [
            {"role": "system", "content": SOUL_PROMPT + "\n\n" + STYLE_RULES + STYLE_NOTE},
            *few_shot,
            {"role": "user", "content": user_msg},
        ]
        resp = await client.chat.completions.create(model="gpt-4.1-mini", messages=messages, temperature=0.85, max_tokens=300)
        return resp.choices[0].message.content.strip(), results
    
    elif mode == "D":  # new_rag_3shot: 新RAG(话题匹配) 3-shot + 旧prompt
        results = rag_new.query(user_msg, n_results=3, topic=topic)
        few_shot = []
        for ex in results:
            few_shot.append({"role": "user", "content": ex["user"]})
            few_shot.append({"role": "assistant", "content": ex["assistant"]})
        messages = [
            {"role": "system", "content": SOUL_PROMPT + "\n\n" + STYLE_RULES + STYLE_NOTE},
            *few_shot,
            {"role": "user", "content": user_msg},
        ]
        resp = await client.chat.completions.create(model="gpt-4.1-mini", messages=messages, temperature=0.85, max_tokens=300)
        return resp.choices[0].message.content.strip(), results
    
    elif mode == "E":  # old_temp08: 旧RAG 2-shot + 旧prompt + temp=0.8
        results = rag_old.query(user_msg, n_results=2)
        few_shot = []
        for ex in results:
            few_shot.append({"role": "user", "content": ex["user"]})
            few_shot.append({"role": "assistant", "content": ex["assistant"]})
        messages = [
            {"role": "system", "content": SOUL_PROMPT + "\n\n" + STYLE_RULES + STYLE_NOTE},
            *few_shot,
            {"role": "user", "content": user_msg},
        ]
        resp = await client.chat.completions.create(model="gpt-4.1-mini", messages=messages, temperature=0.80, max_tokens=300)
        return resp.choices[0].message.content.strip(), results


# ── LLM 评分 ──
EVAL_PROMPT = """你是一个专业的微信聊天质量评估专家。请对以下回复进行评分。

用户消息：{user_msg}
AI回复：{reply}

请从以下5个维度评分（每个维度0-10分）：

1. **真实感(Realness)**：是否像真人在微信上发的消息？真人特点：句子短、口语化、碎片化、语气随意。
2. **反AI味(Anti-AI)**：是否没有AI痕迹？AI痕迹包括：首先/其次/最后、过度emoji、太完整、太积极、太长。
3. **氛围感(Vibe)**：聊天氛围是否轻松有趣？太敷衍或太啰嗦都不好。
4. **人设一致(Persona)**：是否像一个深圳20多岁年轻女生？应该：有小脾气、傲娇、吐槽但不恶毒、有网感。
5. **互动吸引力(Engagement)**：收到这条回复后是否想继续聊？好的回复会反问、吐槽、留悬念。

请严格按以下JSON格式返回，不要有其他内容：
{{"realness": 分数, "anti_ai": 分数, "vibe": 分数, "persona": 分数, "engagement": 分数, "brief_reason": "一句话评价"}}"""

async def evaluate_reply(user_msg: str, reply: str) -> dict:
    try:
        resp = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": EVAL_PROMPT.format(user_msg=user_msg, reply=reply)}],
            temperature=0.1,
            max_tokens=200,
        )
        content = resp.choices[0].message.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        scores = json.loads(content)
        weights = {"realness": 0.30, "anti_ai": 0.25, "vibe": 0.20, "persona": 0.15, "engagement": 0.10}
        weighted = sum(scores.get(k, 5) * w for k, w in weights.items())
        scores["weighted_total"] = round(weighted, 2)
        return scores
    except Exception as e:
        print(f"  评分错误: {e}")
        return {"realness": 5, "anti_ai": 5, "vibe": 5, "persona": 5, "engagement": 5, "weighted_total": 5.0}


async def run_ablation():
    modes = ["A", "B", "C", "D", "E"]
    mode_names = {
        "A": "旧RAG_2shot",
        "B": "旧RAG_3shot", 
        "C": "新RAG_2shot",
        "D": "新RAG_3shot",
        "E": "旧RAG_t0.8",
    }
    
    n = len(TEST_CASES)
    print("=" * 70)
    print(f"消融实验：5种配置 x {n}题")
    print("=" * 70)
    
    all_results = []
    start_time = time.time()
    
    for i, tc in enumerate(TEST_CASES):
        topic = tc["topic"]
        user_msg = tc["msg"]
        print(f"\n[{i+1}/{n}] [{topic}] {user_msg}")
        
        result = {"id": i, "topic": topic, "user_msg": user_msg}
        
        for mode in modes:
            reply, rag_ex = await generate_reply(user_msg, mode, topic)
            scores = await evaluate_reply(user_msg, reply)
            result[f"reply_{mode}"] = reply
            result[f"scores_{mode}"] = scores
            result[f"rag_{mode}"] = rag_ex
        
        # Print comparison
        score_strs = [f"{mode_names[m]}: {result[f'scores_{m}']['weighted_total']:.1f}" for m in modes]
        print(f"  {' | '.join(score_strs)}")
        
        all_results.append(result)
    
    elapsed = time.time() - start_time
    
    # Summary
    print("\n" + "=" * 70)
    print(f"消融实验完成！耗时 {elapsed:.0f}秒")
    print("=" * 70)
    
    # Average scores per mode
    print(f"\n{'方案':<15} {'加权均分':>8} {'平均长度':>8}")
    print("-" * 35)
    for mode in modes:
        avg = sum(r[f"scores_{mode}"]["weighted_total"] for r in all_results) / n
        avg_len = sum(len(r[f"reply_{mode}"]) for r in all_results) / n
        print(f"{mode_names[mode]:<15} {avg:>8.2f} {avg_len:>8.0f}")
    
    # Dimension breakdown
    dims = ["realness", "anti_ai", "vibe", "persona", "engagement"]
    dim_labels = ["真实感", "反AI味", "氛围感", "人设一致", "互动吸引力"]
    print(f"\n{'维度':<10}", end="")
    for mode in modes:
        print(f" {mode_names[mode]:>12}", end="")
    print()
    print("-" * 75)
    for dim, label in zip(dims, dim_labels):
        print(f"{label:<10}", end="")
        for mode in modes:
            avg = sum(r[f"scores_{mode}"].get(dim, 5) for r in all_results) / n
            print(f" {avg:>12.1f}", end="")
        print()
    
    # Win rates: each mode vs A (baseline)
    print(f"\n各方案 vs A(旧RAG_2shot):")
    for mode in modes[1:]:
        wins = sum(1 for r in all_results if r[f"scores_{mode}"]["weighted_total"] > r[f"scores_A"]["weighted_total"])
        losses = sum(1 for r in all_results if r[f"scores_{mode}"]["weighted_total"] < r[f"scores_A"]["weighted_total"])
        ties = n - wins - losses
        print(f"  {mode_names[mode]}: 胜{wins} 负{losses} 平{ties}")
    
    # Save
    output = {
        "experiment": "ablation_v5",
        "modes": mode_names,
        "test_count": n,
        "elapsed_seconds": round(elapsed, 1),
        "details": all_results,
    }
    
    out_path = os.path.join(os.path.dirname(__file__), "eval_v5_ablation_results.json")
    with open(out_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 {out_path}")


if __name__ == "__main__":
    asyncio.run(run_ablation())
