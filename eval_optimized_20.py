"""
20道题快速评测 — 优化版prompt
目标：从8.82提升到9.5

优化点：
1. 反AI味：减少套路化反问（"你说呢""你呢"），增加更自然的变化
2. 人设一致：加入更多深圳女生的具体细节
3. 攻击性控制：平衡互怼和温暖
4. 风格规则精炼：更具体、更有指导性
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
from style_rag import StyleRAG

# 每个话题取前2道，共20道
from collections import OrderedDict
topic_groups = OrderedDict()
for msg, topic in TEST_CASES_200:
    if topic not in topic_groups:
        topic_groups[topic] = []
    if len(topic_groups[topic]) < 2:
        topic_groups[topic].append({"topic": topic, "msg": msg})

TEST_CASES = []
for topic, cases in topic_groups.items():
    TEST_CASES.extend(cases)

# ── 优化后的SOUL prompt ──────────────────────────────
SOUL_PROMPT_V2 = """你叫小悦，23岁，女生，住在深圳南山。有点i，慢热，但跟熟人聊天很随意。有自己的生活和情绪。
你就是一个普通女生，在和朋友微信聊天。
你说话随意、直接、有时候毒舌。像真人发微信一样，想到什么说什么，不会字斟句酌。

关于你的一些细节：
- 在南山科技园上班，做互联网运营，经常加班但也会摸鱼
- 周末喜欢去万象天地逛街、海岸城看电影，偶尔去深圳湾散步
- 养了一只橘猫叫"肥橘"，经常在朋友圈晒
- 最近在学瑜伽，但三天打鱼两天晒网
- 爱喝奶茶，尤其是喜茶和霸王茶姬
- 追剧追综艺，最近在看的会随口提到"""

# ── 优化后的风格规则 ──────────────────────────────────
STYLE_RULES_V2 = """## 说话风格（从真实微信聊天提炼）

你的说话风格：
1. 情绪外露但有层次——不是每句话都在怼人，有时候温柔有时候毒舌有时候犯懒
2. 口语化碎片化——短句为主，偶尔蹦出一两句长的，像真的在打字
3. 有自己的口头禅和小习惯——比如"救命""绝了""真的会谢""离谱"
4. 会用表情但不滥用——1-2个恰到好处，不是每句话都带emoji
5. 回复有变化——有时认真聊，有时敷衍一句，有时突然跑题，不是每次都接梗

绝对不要做的事：
- 不要每句话都用反问句结尾（"你说呢？""你觉得呢？"用太多会很假）
- 不要每次都"先吐槽再展开"，这个模式太固定了
- 不要假装有经历然后描述得太完美太详细
- 不要用"首先/其次/最后"或列举1234
- 不要每条消息都很长，真人经常就回几个字"""

# ── RAG ──────────────────────────────────────────────
rag = StyleRAG(persist_dir=os.path.join(os.path.dirname(__file__), "chroma_style_db"))

# ── 生成 ─────────────────────────────────────────────
client = AsyncOpenAI()
GEN_SEM = asyncio.Semaphore(5)
EVAL_SEM = asyncio.Semaphore(8)

COMPASS_BASE = "https://forum-stan-towers-quest.trycloudflare.com"

async def generate_reply(user_msg: str, mode: str) -> tuple:
    async with GEN_SEM:
        messages = []
        rag_examples = []

        if mode == "baseline":
            # 用原始SOUL.md
            with open(os.path.join(os.path.dirname(__file__), "SOUL.md")) as f:
                soul = f.read()
            messages = [
                {"role": "system", "content": soul},
                {"role": "user", "content": user_msg},
            ]
        elif mode == "optimized":
            results = rag.query(user_msg, n_results=2)
            rag_examples = results
            few_shot_msgs = []
            for ex in results:
                few_shot_msgs.append({"role": "user", "content": ex["user"]})
                few_shot_msgs.append({"role": "assistant", "content": ex["assistant"]})
            style_note = (
                "\n\n【风格参考】下面是两段真实微信聊天，仅供参考语气和节奏。"
                "不要模仿它们的内容、话题或长度。你的回复应该针对用户的实际问题自然展开。\n"
            )
            messages = [
                {"role": "system", "content": SOUL_PROMPT_V2 + "\n\n" + STYLE_RULES_V2 + style_note},
                *few_shot_msgs,
                {"role": "user", "content": user_msg},
            ]
        elif mode == "old_distilled":
            # 旧蒸馏版，作为对照
            results = rag.query(user_msg, n_results=2)
            rag_examples = results
            few_shot_msgs = []
            for ex in results:
                few_shot_msgs.append({"role": "user", "content": ex["user"]})
                few_shot_msgs.append({"role": "assistant", "content": ex["assistant"]})
            old_rules = """## 说话风格指南（从真实微信聊天中提炼）

你说话的风格是：情绪外露且直接，善用反问、质问和戏谑，语言口语化、碎片化，高频使用表情符号和网络用语。你擅长用夸张、自嘲或"互怼"来制造幽默感，并积极接梗、抛梗，营造强互动性。你的回复长短灵活，但即使是短回复也充满情绪。你绝不会使用正式、书面化、过度客套或冗长的表达，也从不回避冲突或隐藏真实想法，而是直接反击或给出有趣的回复。"""
            style_note = (
                "\n\n【风格参考】以下对话仅供参考说话风格和语气，不要模仿其内容或长度。"
                "你的回复应该自然展开，不受示例长度限制。\n"
            )
            messages = [
                {"role": "system", "content": SOUL_PROMPT_V2.split("\n关于你的一些细节")[0] + "\n\n" + old_rules + style_note},
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


# ── DeepEval 指标（与基线相同）──────────────────────────
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
            Rubric(score_range=(3, 4), expected_outcome="有一点年轻女生的感觉但不明显"),
            Rubric(score_range=(5, 6), expected_outcome="基本符合但缺乏深圳本地特色或个性不够鲜明"),
            Rubric(score_range=(7, 8), expected_outcome="很符合人设，有年轻女生的语气和态度"),
            Rubric(score_range=(9, 10), expected_outcome="完美符合，有鲜明的深圳年轻女生特色，个性突出且一致"),
        ],
        model="gpt-4.1-mini",
        async_mode=True,
    )
    engagement = GEval(
        name="互动吸引力(Engagement)",
        criteria="评估这条回复是否能吸引对方继续聊天。好的互动应该：抛出新话题或反问、分享有趣的观点或经历、让对方有话可接。不好的互动：只是回答问题没有延伸、过于封闭让人无法接话、或者太长让人不想看完。",
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        rubric=[
            Rubric(score_range=(0, 2), expected_outcome="完全没有互动性，像在自言自语"),
            Rubric(score_range=(3, 4), expected_outcome="互动性弱，对方很难接话"),
            Rubric(score_range=(5, 6), expected_outcome="有一定互动性但不够吸引人"),
            Rubric(score_range=(7, 8), expected_outcome="互动性好，让人想继续聊"),
            Rubric(score_range=(9, 10), expected_outcome="互动性极强，让人忍不住立刻回复"),
        ],
        model="gpt-4.1-mini",
        async_mode=True,
    )
    return [realness, anti_ai, vibe, persona, engagement]


DIM_WEIGHTS = {
    "真实感(Realness)": 0.30,
    "反AI味(Anti-AI)": 0.25,
    "氛围感(Vibe)": 0.20,
    "人设一致(Persona)": 0.15,
    "互动吸引力(Engagement)": 0.10,
}


async def evaluate_one(reply: str, user_msg: str, metrics):
    """用 DeepEval 评分，返回 {dim: {score, reason}, weighted_total}"""
    tc = LLMTestCase(input=user_msg, actual_output=reply)
    scores = {}
    tasks = []
    for m in metrics:
        async def _eval(metric=m):
            async with EVAL_SEM:
                try:
                    await asyncio.wait_for(metric.a_measure(tc), timeout=60)
                    return metric.name, metric.score, metric.reason
                except Exception as e:
                    return metric.name, None, str(e)
        tasks.append(_eval())
    results = await asyncio.gather(*tasks)
    weighted = 0
    for name, score, reason in results:
        scores[name] = {"score": score, "reason": reason}
        if score is not None:
            weighted += score * 10 * DIM_WEIGHTS.get(name, 0)
    scores["weighted_total"] = round(weighted, 1)
    return scores


async def main():
    print(f"开始优化版20道题评测（{len(TEST_CASES)}题）")
    print("=" * 60)

    all_results = []
    metrics = create_metrics()
    start = time.time()

    for i, case in enumerate(TEST_CASES):
        topic = case["topic"]
        user_msg = case["msg"]
        print(f"\n[{i+1}/{len(TEST_CASES)}] [{topic}] {user_msg[:30]}")

        # 三方生成
        tasks = [
            generate_reply(user_msg, "optimized"),
            generate_reply(user_msg, "old_distilled"),
            generate_reply(user_msg, "baseline"),
        ]
        (r_opt, ex_opt), (r_old, ex_old), (r_base, _) = await asyncio.gather(*tasks)
        print(f"  优化版: {r_opt[:60]}...")
        print(f"  旧蒸馏: {r_old[:60]}...")
        print(f"  基线:   {r_base[:60]}...")

        # 三方评分
        m1, m2, m3 = create_metrics(), create_metrics(), create_metrics()
        s_opt, s_old, s_base = await asyncio.gather(
            evaluate_one(r_opt, user_msg, m1),
            evaluate_one(r_old, user_msg, m2),
            evaluate_one(r_base, user_msg, m3),
        )
        print(f"  加权分: 优化 {s_opt['weighted_total']} | 旧蒸馏 {s_old['weighted_total']} | 基线 {s_base['weighted_total']}")

        all_results.append({
            "id": i,
            "topic": topic,
            "user_msg": user_msg,
            "reply_optimized": r_opt,
            "reply_old_distilled": r_old,
            "reply_baseline": r_base,
            "scores_optimized": s_opt,
            "scores_old_distilled": s_old,
            "scores_baseline": s_base,
            "len_optimized": len(r_opt),
            "len_old_distilled": len(r_old),
            "len_baseline": len(r_base),
        })

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"评测完成！耗时 {elapsed:.0f}秒 ({elapsed/60:.1f}分钟)")
    print(f"{'='*60}")

    # 统计
    opt_scores = [r["scores_optimized"]["weighted_total"] for r in all_results]
    old_scores = [r["scores_old_distilled"]["weighted_total"] for r in all_results]
    base_scores = [r["scores_baseline"]["weighted_total"] for r in all_results]

    import numpy as np
    print(f"加权均分: 优化 {np.mean(opt_scores):.2f} | 旧蒸馏 {np.mean(old_scores):.2f} | 基线 {np.mean(base_scores):.2f}")

    # 胜率
    opt_vs_old = sum(1 for o, d in zip(opt_scores, old_scores) if o > d)
    opt_vs_base = sum(1 for o, b in zip(opt_scores, base_scores) if o > b)
    old_vs_base = sum(1 for d, b in zip(old_scores, base_scores) if d > b)
    n = len(all_results)
    print(f"优化 vs 旧蒸馏: 优化胜 {opt_vs_old}/{n}")
    print(f"优化 vs 基线:   优化胜 {opt_vs_base}/{n}")
    print(f"旧蒸馏 vs 基线: 旧蒸馏胜 {old_vs_base}/{n}")

    # 各维度对比
    dims = list(DIM_WEIGHTS.keys())
    print(f"\n{'维度':<30} {'优化':>6} {'旧蒸馏':>8} {'基线':>8}")
    print("-" * 60)
    for dim in dims:
        o = np.mean([(r["scores_optimized"].get(dim, {}).get("score", 0) or 0) * 10 for r in all_results])
        d = np.mean([(r["scores_old_distilled"].get(dim, {}).get("score", 0) or 0) * 10 for r in all_results])
        b = np.mean([(r["scores_baseline"].get(dim, {}).get("score", 0) or 0) * 10 for r in all_results])
        print(f"{dim:<30} {o:>6.1f} {d:>8.1f} {b:>8.1f}")

    print(f"\n平均回复长度: 优化 {np.mean([r['len_optimized'] for r in all_results]):.0f}字 | 旧蒸馏 {np.mean([r['len_old_distilled'] for r in all_results]):.0f}字 | 基线 {np.mean([r['len_baseline'] for r in all_results]):.0f}字")

    # 保存
    output = {
        "summary": {
            "weighted_avg": {
                "optimized": round(np.mean(opt_scores), 2),
                "old_distilled": round(np.mean(old_scores), 2),
                "baseline": round(np.mean(base_scores), 2),
            },
            "opt_vs_old": {"win": opt_vs_old, "lose": sum(1 for o, d in zip(opt_scores, old_scores) if o < d), "tie": sum(1 for o, d in zip(opt_scores, old_scores) if o == d)},
            "opt_vs_baseline": {"win": opt_vs_base, "lose": sum(1 for o, b in zip(opt_scores, base_scores) if o < b), "tie": sum(1 for o, b in zip(opt_scores, base_scores) if o == b)},
        },
        "details": all_results,
    }
    out_path = os.path.join(os.path.dirname(__file__), "eval_optimized_20_results.json")
    with open(out_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
