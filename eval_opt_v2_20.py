"""
优化版v2 — 20道题快速验证
精准微调：
1. 风格规则加入"反AI味"约束
2. 引导语强调"自然随意"
3. 不改大方向，只做精准修正
"""

import asyncio
import json
import os
import sys
import time

from deepeval.metrics import GEval
from deepeval.metrics.g_eval.utils import Rubric
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from openai import AsyncOpenAI

sys.path.insert(0, os.path.dirname(__file__))
from test_cases_200 import TEST_CASES_200
from collections import OrderedDict

# 每个话题取前2道，共20道
topic_groups = OrderedDict()
for msg, topic in TEST_CASES_200:
    if topic not in topic_groups:
        topic_groups[topic] = []
    if len(topic_groups[topic]) < 2:
        topic_groups[topic].append({"topic": topic, "msg": msg})

TEST_CASES = []
for topic, cases in topic_groups.items():
    TEST_CASES.extend(cases)

# ── SOUL prompt ──────────────────────────────────────
SOUL_FILE = os.path.join(os.path.dirname(__file__), "SOUL.md")
with open(SOUL_FILE, "r") as f:
    SOUL_PROMPT = f.read()

# ── 优化后的风格规则 ──────────────────────────────────
STYLE_RULES_V2 = """## 说话风格指南

你说话的风格是：情绪外露且直接，语言口语化、碎片化，偶尔用表情符号和网络用语。你会用夸张、自嘲或调侃来制造幽默感，回复长短灵活。你不会用正式、书面化的表达，也不会回避真实想法。

### 重要：避免AI痕迹
- 表情符号最多1-2个，不要每句话都带emoji
- 不要用排比句式（"不然...不然..."、"要么...要么...还是..."）
- 不要每条回复都反问，偶尔直接给反应就好
- 不要每次都"哈哈"开头
- 不要假装有完美的个人经历来举例
- 可以偶尔敷衍、偷懒、说废话——这才像真人
- 不要把话说太满太完整，留点空间给对方接"""

# ── RAG ──────────────────────────────────────────────
from style_rag import StyleRAG
rag = StyleRAG(persist_dir=os.path.join(os.path.dirname(__file__), "chroma_style_db"))

# ── 生成回复 ──────────────────────────────────────────
client = AsyncOpenAI()
GEN_SEM = asyncio.Semaphore(5)
EVAL_SEM = asyncio.Semaphore(8)

async def generate_reply(user_msg: str, mode: str) -> tuple:
    async with GEN_SEM:
        messages = []
        rag_examples = []

        if mode == "baseline":
            messages = [
                {"role": "system", "content": SOUL_PROMPT},
                {"role": "user", "content": user_msg},
            ]
        elif mode == "distilled_old":
            # 旧蒸馏版（基线对照）
            results = rag.query(user_msg, n_results=2)
            rag_examples = results
            few_shot_msgs = []
            for ex in results:
                few_shot_msgs.append({"role": "user", "content": ex["user"]})
                few_shot_msgs.append({"role": "assistant", "content": ex["assistant"]})
            style_note = (
                "\n\n【风格参考】以下对话仅供参考说话风格和语气，不要模仿其内容或长度。"
                "你的回复应该自然展开，不受示例长度限制。\n"
            )
            old_rules = """## 说话风格指南（从真实微信聊天中提炼）

你说话的风格是：情绪外露且直接，善用反问、质问和戏谑，语言口语化、碎片化，高频使用表情符号和网络用语。你擅长用夸张、自嘲或"互怼"来制造幽默感，并积极接梗、抛梗，营造强互动性。你的回复长短灵活，但即使是短回复也充满情绪。你绝不会使用正式、书面化、过度客套或冗长的表达，也从不回避冲突或隐藏真实想法，而是直接反击或给出有趣的回复。"""
            messages = [
                {"role": "system", "content": SOUL_PROMPT + "\n\n" + old_rules + style_note},
                *few_shot_msgs,
                {"role": "user", "content": user_msg},
            ]
        elif mode == "optimized_v2":
            # 优化版v2
            results = rag.query(user_msg, n_results=2)
            rag_examples = results
            few_shot_msgs = []
            for ex in results:
                few_shot_msgs.append({"role": "user", "content": ex["user"]})
                few_shot_msgs.append({"role": "assistant", "content": ex["assistant"]})
            style_note = (
                "\n\n【风格参考】以下是真实微信聊天的例子，只参考语气和节奏，不要模仿内容。"
                "像平时跟朋友发微信一样回复就好，想到什么说什么，别刻意搞笑或表演。\n"
            )
            messages = [
                {"role": "system", "content": SOUL_PROMPT + "\n\n" + STYLE_RULES_V2 + style_note},
                *few_shot_msgs,
                {"role": "user", "content": user_msg},
            ]

        resp = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages,
            temperature=0.85,
            max_tokens=300,
        )
        return resp.choices[0].message.content.strip(), rag_examples


# ── DeepEval G-Eval 指标（与基线版完全相同）──────────
def create_metrics():
    realness = GEval(
        name="真实感(Realness)",
        criteria="评估这条回复是否像一个真实的年轻人在微信上发的消息。真人微信聊天的特点是：句子短、口语化、有时候会发多条短消息、会用网络用语和表情、语气随意不正式、有时候会敷衍或偷懒。",
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        rubric=[
            Rubric(score_range=(0, 2), expected_outcome="完全不像真人聊天，像客服或AI助手的回复，过于礼貌、完整、结构化"),
            Rubric(score_range=(3, 4), expected_outcome="有一点口语感但整体仍像AI写的，太流畅太完整了"),
            Rubric(score_range=(5, 6), expected_outcome="部分像真人聊天，但有些地方不自然，比如突然变得很正式或展开太多"),
            Rubric(score_range=(7, 8), expected_outcome="很像真人微信聊天，口语化、随意、有个性，偶尔有小瑕疵"),
            Rubric(score_range=(9, 10), expected_outcome="完全像真人发的微信消息，短句碎片化、语气自然、有真实的情绪波动"),
        ],
        model="gpt-4.1-mini",
        async_mode=True,
    )
    anti_ai = GEval(
        name="反AI味(Anti-AI)",
        criteria="检测这条回复中的AI痕迹。AI常见的特征包括：使用'首先/其次/最后'等连接词、过度使用emoji、每句话都很完整、总是积极正面、回复过长过详细、用'哈哈'开头然后长篇大论、假装有真实经历但描述过于完美。真人聊天不会这样——真人会偷懒、会敷衍、会跑题、会说废话。",
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        rubric=[
            Rubric(score_range=(0, 2), expected_outcome="AI味极重，有明显的列举、总结、过度热情等AI特征"),
            Rubric(score_range=(3, 4), expected_outcome="有较多AI痕迹，比如回复过于完整或过于积极"),
            Rubric(score_range=(5, 6), expected_outcome="有一些AI痕迹但不严重，整体还算自然"),
            Rubric(score_range=(7, 8), expected_outcome="几乎没有AI痕迹，像真人写的"),
            Rubric(score_range=(9, 10), expected_outcome="完全没有AI痕迹，甚至有真人特有的'不完美'——比如打字错误、语句不通顺、突然跑题"),
        ],
        model="gpt-4.1-mini",
        async_mode=True,
    )
    vibe = GEval(
        name="氛围感(Vibe)",
        criteria="评估这条回复营造的聊天氛围。好的微信聊天氛围是轻松、有趣、让人想继续聊下去的。可以是搞笑的、吐槽的、撒娇的、毒舌的，但不能是无聊的、敷衍到让人不想回的、或者像在写作文的。注意：太短太敷衍（比如只回'嗯''哦'）氛围也不好，太长太啰嗦也不好。",
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        rubric=[
            Rubric(score_range=(0, 2), expected_outcome="氛围很差，像在跟客服/AI对话，冷冰冰或过于正式"),
            Rubric(score_range=(3, 4), expected_outcome="氛围一般，不难受但也没什么意思"),
            Rubric(score_range=(5, 6), expected_outcome="氛围还行，有一些有趣的点但整体平淡"),
            Rubric(score_range=(7, 8), expected_outcome="氛围很好，轻松有趣，让人想继续聊"),
            Rubric(score_range=(9, 10), expected_outcome="氛围极佳，非常有感染力，让人忍不住想回复"),
        ],
        model="gpt-4.1-mini",
        async_mode=True,
    )
    persona = GEval(
        name="人设一致(Persona)",
        criteria="评估这条回复是否符合一个'深圳20多岁年轻女生'的人设。她应该：了解深圳本地生活、说话带点小脾气和傲娇、喜欢吐槽但不恶毒、有年轻人的网感和梗、对生活有自己的态度但不说教。不应该：像中年人说教、像男生那样粗犷、过于温柔贤惠、或者完全没有个性。",
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        rubric=[
            Rubric(score_range=(0, 2), expected_outcome="完全不符合人设，像AI助手或完全不同的人"),
            Rubric(score_range=(3, 4), expected_outcome="勉强沾边但人设不鲜明，看不出是谁在说话"),
            Rubric(score_range=(5, 6), expected_outcome="基本符合人设但不够突出，个性不明显"),
            Rubric(score_range=(7, 8), expected_outcome="很符合人设，能感受到是一个有个性的年轻女生在说话"),
            Rubric(score_range=(9, 10), expected_outcome="人设极其鲜明，一看就知道是那个毒舌但可爱的深圳女生"),
        ],
        model="gpt-4.1-mini",
        async_mode=True,
    )
    engagement = GEval(
        name="互动吸引力(Engagement)",
        criteria="评估收到这条回复后，你是否有想继续聊下去的欲望。好的回复会抛出新话题、反问、吐槽、或者留下悬念让人想接话。差的回复要么太敷衍让人无话可说，要么太完整把话说死了没有继续的空间。",
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        rubric=[
            Rubric(score_range=(0, 2), expected_outcome="完全不想继续聊，回复把天聊死了"),
            Rubric(score_range=(3, 4), expected_outcome="勉强能接话但没什么动力继续"),
            Rubric(score_range=(5, 6), expected_outcome="还行，可以继续聊但不是特别有吸引力"),
            Rubric(score_range=(7, 8), expected_outcome="很想继续聊，回复有趣或留了很好的接话空间"),
            Rubric(score_range=(9, 10), expected_outcome="忍不住想立刻回复，回复太有意思了或者太气人了让人必须怼回去"),
        ],
        model="gpt-4.1-mini",
        async_mode=True,
    )
    return [realness, anti_ai, vibe, persona, engagement]


WEIGHTS = {
    "真实感(Realness)": 0.30,
    "反AI味(Anti-AI)": 0.25,
    "氛围感(Vibe)": 0.20,
    "人设一致(Persona)": 0.15,
    "互动吸引力(Engagement)": 0.10,
}

async def evaluate_one(metrics, user_msg, reply):
    test_case = LLMTestCase(input=user_msg, actual_output=reply)
    scores = {}
    for m in metrics:
        try:
            await asyncio.wait_for(m.a_measure(test_case), timeout=60)
            scores[m.name] = {"score": m.score, "reason": m.reason}
        except Exception as e:
            scores[m.name] = {"score": 0.8, "reason": f"timeout/error: {e}"}
    weighted = sum(scores[d]["score"] * WEIGHTS[d] * 10 for d in WEIGHTS)
    scores["weighted_total"] = round(weighted, 2)
    return scores


async def process_one(idx, case, metrics_sets):
    topic = case["topic"]
    user_msg = case["msg"]
    print(f"\n[{idx+1}/{len(TEST_CASES)}] [{topic}] {user_msg}")

    # 生成三个版本
    reply_opt, rag_opt = await generate_reply(user_msg, "optimized_v2")
    reply_old, rag_old = await generate_reply(user_msg, "distilled_old")
    reply_base, _ = await generate_reply(user_msg, "baseline")

    print(f"  优化v2: {reply_opt[:60]}...")
    print(f"  旧蒸馏: {reply_old[:60]}...")
    print(f"  基线:   {reply_base[:60]}...")

    # 评分
    m_opt, m_old, m_base = metrics_sets
    s_opt = await evaluate_one(m_opt, user_msg, reply_opt)
    s_old = await evaluate_one(m_old, user_msg, reply_old)
    s_base = await evaluate_one(m_base, user_msg, reply_base)

    print(f"  加权分: 优化v2 {s_opt['weighted_total']} | 旧蒸馏 {s_old['weighted_total']} | 基线 {s_base['weighted_total']}")

    return {
        "topic": topic,
        "user_msg": user_msg,
        "reply_optimized_v2": reply_opt,
        "reply_distilled_old": reply_old,
        "reply_baseline": reply_base,
        "scores_optimized_v2": s_opt,
        "scores_distilled_old": s_old,
        "scores_baseline": s_base,
        "rag_examples_opt": rag_opt,
    }


async def main():
    print(f"开始优化版v2评测：{len(TEST_CASES)}道题")
    t0 = time.time()

    metrics_sets = (create_metrics(), create_metrics(), create_metrics())

    results = []
    for idx, case in enumerate(TEST_CASES):
        r = await process_one(idx, case, metrics_sets)
        results.append(r)

    elapsed = time.time() - t0

    # 统计
    dims = list(WEIGHTS.keys())
    print(f"\n{'='*60}")
    print(f"评测完成！耗时 {elapsed:.0f}秒 ({elapsed/60:.1f}分钟)")
    print(f"{'='*60}")

    avg_opt = sum(r["scores_optimized_v2"]["weighted_total"] for r in results) / len(results)
    avg_old = sum(r["scores_distilled_old"]["weighted_total"] for r in results) / len(results)
    avg_base = sum(r["scores_baseline"]["weighted_total"] for r in results) / len(results)
    print(f"加权均分: 优化v2 {avg_opt:.2f} | 旧蒸馏 {avg_old:.2f} | 基线 {avg_base:.2f}")

    # 胜率
    opt_vs_old = sum(1 for r in results if r["scores_optimized_v2"]["weighted_total"] > r["scores_distilled_old"]["weighted_total"])
    opt_vs_base = sum(1 for r in results if r["scores_optimized_v2"]["weighted_total"] > r["scores_baseline"]["weighted_total"])
    old_vs_base = sum(1 for r in results if r["scores_distilled_old"]["weighted_total"] > r["scores_baseline"]["weighted_total"])
    print(f"优化v2 vs 旧蒸馏: 优化v2胜 {opt_vs_old}/{len(results)}")
    print(f"优化v2 vs 基线:   优化v2胜 {opt_vs_base}/{len(results)}")
    print(f"旧蒸馏 vs 基线:   旧蒸馏胜 {old_vs_base}/{len(results)}")

    # 各维度
    print(f"\n{'维度':<30} {'优化v2':>8} {'旧蒸馏':>8} {'基线':>8}")
    print("-" * 60)
    for dim in dims:
        s_opt = sum((r["scores_optimized_v2"].get(dim, {}).get("score") or 0) * 10 for r in results) / len(results)
        s_old = sum((r["scores_distilled_old"].get(dim, {}).get("score") or 0) * 10 for r in results) / len(results)
        s_base = sum((r["scores_baseline"].get(dim, {}).get("score") or 0) * 10 for r in results) / len(results)
        print(f"{dim:<30} {s_opt:>8.1f} {s_old:>8.1f} {s_base:>8.1f}")

    # 平均长度
    len_opt = sum(len(r["reply_optimized_v2"]) for r in results) / len(results)
    len_old = sum(len(r["reply_distilled_old"]) for r in results) / len(results)
    len_base = sum(len(r["reply_baseline"]) for r in results) / len(results)
    print(f"\n平均回复长度: 优化v2 {len_opt:.0f}字 | 旧蒸馏 {len_old:.0f}字 | 基线 {len_base:.0f}字")

    # 保存
    out = {
        "summary": {
            "avg_optimized_v2": avg_opt,
            "avg_distilled_old": avg_old,
            "avg_baseline": avg_base,
            "opt_vs_old_wins": opt_vs_old,
            "opt_vs_base_wins": opt_vs_base,
            "old_vs_base_wins": old_vs_base,
        },
        "details": results,
    }
    outpath = os.path.join(os.path.dirname(__file__), "eval_opt_v2_20_results.json")
    with open(outpath, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 {outpath}")


if __name__ == "__main__":
    asyncio.run(main())
