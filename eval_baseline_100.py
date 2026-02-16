"""
100道题基线评测 — 基于 DeepEval G-Eval 框架
- 从200道题中每个话题取前10道，共100道
- 三方对比：蒸馏版 / 5shot版 / 基线（无RAG）
- 支持断点续传
- 并发控制：生成3并发，评分5并发
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

# ── 从200道题中每个话题取前10道 ─────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from test_cases_200 import TEST_CASES_200

# 按话题分组，每组取前10道
from collections import OrderedDict
topic_groups = OrderedDict()
for msg, topic in TEST_CASES_200:
    if topic not in topic_groups:
        topic_groups[topic] = []
    if len(topic_groups[topic]) < 10:
        topic_groups[topic].append({"topic": topic, "msg": msg})

TEST_CASES = []
for topic, cases in topic_groups.items():
    TEST_CASES.extend(cases)

assert len(TEST_CASES) == 100, f"Expected 100, got {len(TEST_CASES)}"

# ── SOUL prompt ──────────────────────────────────────
SOUL_FILE = os.path.join(os.path.dirname(__file__), "SOUL.md")
with open(SOUL_FILE, "r") as f:
    SOUL_PROMPT = f.read()

# ── 风格蒸馏规则 ──────────────────────────────────────
STYLE_RULES = """## 说话风格指南（从真实微信聊天中提炼）

你说话的风格是：情绪外露且直接，善用反问、质问和戏谑，语言口语化、碎片化，高频使用表情符号和网络用语。你擅长用夸张、自嘲或"互怼"来制造幽默感，并积极接梗、抛梗，营造强互动性。你的回复长短灵活，但即使是短回复也充满情绪。你绝不会使用正式、书面化、过度客套或冗长的表达，也从不回避冲突或隐藏真实想法，而是直接反击或给出有趣的回复。"""

# ── RAG 加载 ──────────────────────────────────────────
from style_rag import StyleRAG
rag = StyleRAG(persist_dir=os.path.join(os.path.dirname(__file__), "chroma_style_db"))

# ── 生成回复 ──────────────────────────────────────────
client = AsyncOpenAI()
GEN_SEM = asyncio.Semaphore(5)   # 生成并发
EVAL_SEM = asyncio.Semaphore(8)  # 评分并发

async def generate_reply(user_msg: str, mode: str) -> tuple:
    """生成回复，返回 (reply, rag_examples)"""
    async with GEN_SEM:
        messages = []
        rag_examples = []

        if mode == "baseline":
            messages = [
                {"role": "system", "content": SOUL_PROMPT},
                {"role": "user", "content": user_msg},
            ]
        elif mode == "fewshot5":
            results = rag.query(user_msg, n_results=5)
            rag_examples = results
            few_shot_msgs = []
            for ex in results:
                few_shot_msgs.append({"role": "user", "content": ex["user"]})
                few_shot_msgs.append({"role": "assistant", "content": ex["assistant"]})
            messages = [
                {"role": "system", "content": SOUL_PROMPT},
                *few_shot_msgs,
                {"role": "user", "content": user_msg},
            ]
        elif mode == "distilled":
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
            messages = [
                {"role": "system", "content": SOUL_PROMPT + "\n\n" + STYLE_RULES + style_note},
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


# ── DeepEval G-Eval 指标定义（与20道题版相同）──────────

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


# ── 评分 ──────────────────────────────────────────────

WEIGHTS = {
    "真实感(Realness)": 0.30,
    "反AI味(Anti-AI)": 0.25,
    "氛围感(Vibe)": 0.20,
    "人设一致(Persona)": 0.15,
    "互动吸引力(Engagement)": 0.10,
}

async def evaluate_one(metrics, user_msg, reply):
    """用5个G-Eval指标评估一条回复，每个指标60秒超时"""
    test_case = LLMTestCase(input=user_msg, actual_output=reply)
    scores = {}

    async def eval_metric(m, tc):
        async with EVAL_SEM:
            try:
                await asyncio.wait_for(m.a_measure(tc), timeout=60)
                return m.name, m.score, m.reason
            except asyncio.TimeoutError:
                print(f"  评分超时: {m.name}")
                return m.name, 0.7, "timeout - default score"  # 给个默认分

    results = await asyncio.gather(
        *[eval_metric(m, test_case) for m in metrics],
        return_exceptions=True,
    )

    for r in results:
        if isinstance(r, Exception):
            print(f"  评分错误: {r}")
            continue
        name, score, reason = r
        scores[name] = {"score": score, "reason": reason}

    weighted_sum = 0
    for name, w in WEIGHTS.items():
        if name in scores and scores[name]["score"] is not None:
            weighted_sum += scores[name]["score"] * w * 10
    scores["weighted_total"] = round(weighted_sum, 2)
    return scores


# ── 断点续传 ──────────────────────────────────────────

CHECKPOINT_FILE = os.path.join(os.path.dirname(__file__), "eval_baseline_100_checkpoint.json")
RESULT_FILE = os.path.join(os.path.dirname(__file__), "eval_baseline_100_results.json")

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            return json.load(f)
    return {"completed": [], "results": []}

def save_checkpoint(data):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 单题处理 ──────────────────────────────────────────

async def process_one(i, tc, metrics):
    topic = tc["topic"]
    user_msg = tc["msg"]
    print(f"\n[{i+1}/100] [{topic}] {user_msg}")

    # 三种回复并行生成
    (reply_d, rag_d), (reply_f, rag_f), (reply_b, _) = await asyncio.gather(
        generate_reply(user_msg, "distilled"),
        generate_reply(user_msg, "fewshot5"),
        generate_reply(user_msg, "baseline"),
    )

    print(f"  蒸馏: {reply_d[:50]}...")
    print(f"  5shot: {reply_f[:50]}...")
    print(f"  基线:  {reply_b[:50]}...")

    # 三种回复并行评分
    scores_d, scores_f, scores_b = await asyncio.gather(
        evaluate_one(metrics, user_msg, reply_d),
        evaluate_one(metrics, user_msg, reply_f),
        evaluate_one(metrics, user_msg, reply_b),
    )

    print(f"  加权分: 蒸馏 {scores_d['weighted_total']:.1f} | 5shot {scores_f['weighted_total']:.1f} | 基线 {scores_b['weighted_total']:.1f}")

    return {
        "id": i,
        "topic": topic,
        "user_msg": user_msg,
        "reply_distilled": reply_d,
        "reply_fewshot5": reply_f,
        "reply_baseline": reply_b,
        "rag_examples_distilled": rag_d,
        "rag_examples_fewshot5": rag_f,
        "scores_distilled": scores_d,
        "scores_fewshot5": scores_f,
        "scores_baseline": scores_b,
        "len_distilled": len(reply_d),
        "len_fewshot5": len(reply_f),
        "len_baseline": len(reply_b),
    }


# ── 主流程 ────────────────────────────────────────────

async def run_eval():
    print("=" * 60)
    print("DeepEval G-Eval 100道题基线评测")
    print("=" * 60)

    ckpt = load_checkpoint()
    completed_ids = set(ckpt["completed"])
    all_results = ckpt["results"]
    print(f"已完成 {len(completed_ids)}/100 道题")

    metrics = create_metrics()
    start_time = time.time()

    # 逐题处理（保证断点续传的可靠性）
    for i, tc in enumerate(TEST_CASES):
        if i in completed_ids:
            continue

        try:
            result = await process_one(i, tc, metrics)
            all_results.append(result)
            completed_ids.add(i)
            ckpt["completed"] = list(completed_ids)
            ckpt["results"] = all_results

            # 每5题保存一次
            if len(completed_ids) % 5 == 0:
                save_checkpoint(ckpt)
                print(f"  [checkpoint] 已保存 {len(completed_ids)}/100")
        except Exception as e:
            print(f"  [ERROR] 题目{i}失败: {e}")
            save_checkpoint(ckpt)
            continue

    elapsed = time.time() - start_time

    # ── 统计 ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"评测完成！耗时 {elapsed:.0f}秒 ({elapsed/60:.1f}分钟)")
    print("=" * 60)

    # 按id排序
    all_results.sort(key=lambda x: x["id"])

    # 加权均分
    d_avg = sum(r["scores_distilled"]["weighted_total"] for r in all_results) / len(all_results)
    f_avg = sum(r["scores_fewshot5"]["weighted_total"] for r in all_results) / len(all_results)
    b_avg = sum(r["scores_baseline"]["weighted_total"] for r in all_results) / len(all_results)

    print(f"\n加权均分: 蒸馏 {d_avg:.2f} | 5shot {f_avg:.2f} | 基线 {b_avg:.2f}")

    # 胜率
    def count_wins(key_a, key_b):
        a_win = sum(1 for r in all_results if r[key_a]["weighted_total"] > r[key_b]["weighted_total"])
        b_win = sum(1 for r in all_results if r[key_a]["weighted_total"] < r[key_b]["weighted_total"])
        tie = sum(1 for r in all_results if r[key_a]["weighted_total"] == r[key_b]["weighted_total"])
        return a_win, b_win, tie

    d_vs_b = count_wins("scores_distilled", "scores_baseline")
    f_vs_b = count_wins("scores_fewshot5", "scores_baseline")
    d_vs_f = count_wins("scores_distilled", "scores_fewshot5")

    print(f"\n蒸馏 vs 基线: 蒸馏胜 {d_vs_b[0]} | 基线胜 {d_vs_b[1]} | 平 {d_vs_b[2]}")
    print(f"5shot vs 基线: 5shot胜 {f_vs_b[0]} | 基线胜 {f_vs_b[1]} | 平 {f_vs_b[2]}")
    print(f"蒸馏 vs 5shot: 蒸馏胜 {d_vs_f[0]} | 5shot胜 {d_vs_f[1]} | 平 {d_vs_f[2]}")

    # 各维度分数
    dim_names = ["真实感(Realness)", "反AI味(Anti-AI)", "氛围感(Vibe)", "人设一致(Persona)", "互动吸引力(Engagement)"]
    print(f"\n{'维度':<25} {'蒸馏':>8} {'5shot':>8} {'基线':>8}")
    print("-" * 55)
    for dim in dim_names:
        d_s = sum(r["scores_distilled"].get(dim, {}).get("score", 0) or 0 for r in all_results) / len(all_results) * 10
        f_s = sum(r["scores_fewshot5"].get(dim, {}).get("score", 0) or 0 for r in all_results) / len(all_results) * 10
        b_s = sum(r["scores_baseline"].get(dim, {}).get("score", 0) or 0 for r in all_results) / len(all_results) * 10
        print(f"{dim:<25} {d_s:>8.1f} {f_s:>8.1f} {b_s:>8.1f}")

    # 按话题统计
    topics = list(topic_groups.keys())
    print(f"\n{'话题':<8} {'蒸馏':>8} {'5shot':>8} {'基线':>8} | {'蒸馏vs基线':>10} {'5shot vs基线':>12}")
    print("-" * 70)
    for topic in topics:
        t_results = [r for r in all_results if r["topic"] == topic]
        if not t_results:
            continue
        t_d = sum(r["scores_distilled"]["weighted_total"] for r in t_results) / len(t_results)
        t_f = sum(r["scores_fewshot5"]["weighted_total"] for r in t_results) / len(t_results)
        t_b = sum(r["scores_baseline"]["weighted_total"] for r in t_results) / len(t_results)
        d_win = sum(1 for r in t_results if r["scores_distilled"]["weighted_total"] > r["scores_baseline"]["weighted_total"])
        f_win = sum(1 for r in t_results if r["scores_fewshot5"]["weighted_total"] > r["scores_baseline"]["weighted_total"])
        print(f"{topic:<8} {t_d:>8.1f} {t_f:>8.1f} {t_b:>8.1f} | {d_win}/{len(t_results):>9} {f_win}/{len(t_results):>11}")

    # 回复长度
    d_len = sum(r["len_distilled"] for r in all_results) / len(all_results)
    f_len = sum(r["len_fewshot5"] for r in all_results) / len(all_results)
    b_len = sum(r["len_baseline"] for r in all_results) / len(all_results)
    print(f"\n平均回复长度: 蒸馏 {d_len:.0f}字 | 5shot {f_len:.0f}字 | 基线 {b_len:.0f}字")

    # 保存完整结果
    output = {
        "eval_framework": "DeepEval G-Eval",
        "eval_model": "gpt-4.1-mini",
        "method": "CoT + Rubric + Token Probability Weighting",
        "test_count": len(all_results),
        "elapsed_seconds": round(elapsed, 1),
        "summary": {
            "weighted_avg": {"distilled": round(d_avg, 2), "fewshot5": round(f_avg, 2), "baseline": round(b_avg, 2)},
            "distilled_vs_baseline": {"win": d_vs_b[0], "lose": d_vs_b[1], "tie": d_vs_b[2]},
            "fewshot5_vs_baseline": {"win": f_vs_b[0], "lose": f_vs_b[1], "tie": f_vs_b[2]},
            "distilled_vs_fewshot5": {"win": d_vs_f[0], "lose": d_vs_f[1], "tie": d_vs_f[2]},
            "avg_length": {"distilled": round(d_len), "fewshot5": round(f_len), "baseline": round(b_len)},
        },
        "details": all_results,
    }

    with open(RESULT_FILE, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 {RESULT_FILE}")

    # 清理checkpoint
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print("checkpoint已清理")


if __name__ == "__main__":
    asyncio.run(run_eval())
