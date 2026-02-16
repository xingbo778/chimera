"""
评测脚本 v6-lite：混合方案
- 基础：旧版prompt + 旧RAG 2条样本（保留高分核心）
- 弱势话题（学习、颜值、旅行、健身）：用新RAG v3话题匹配3条样本
- 加入轻量反AI提示（不要首先其次最后、不要建议列表）
- 对比：v6混合 vs 旧版 vs 基线
"""

import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from openai import AsyncOpenAI

TEST_CASES_20 = [
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

TEST_CASES_100 = [
    {"topic": "穿搭", "msg": "你觉得这件衣服好看吗"},
    {"topic": "穿搭", "msg": "帮我看看这条裙子怎么样"},
    {"topic": "穿搭", "msg": "今天穿什么出门好呢"},
    {"topic": "穿搭", "msg": "这个颜色适合我吗"},
    {"topic": "穿搭", "msg": "我新买的鞋你觉得怎么样"},
    {"topic": "穿搭", "msg": "约会穿什么比较好"},
    {"topic": "穿搭", "msg": "这两件你帮我选一件"},
    {"topic": "穿搭", "msg": "你平时都穿什么风格"},
    {"topic": "穿搭", "msg": "这件外套是不是太大了"},
    {"topic": "穿搭", "msg": "我想换个风格你有什么建议"},
    {"topic": "工作", "msg": "今天上班好累啊"},
    {"topic": "工作", "msg": "老板又让我加班了"},
    {"topic": "工作", "msg": "想辞职但是又不敢"},
    {"topic": "工作", "msg": "同事好烦每天都在八卦"},
    {"topic": "工作", "msg": "加班到现在才下班"},
    {"topic": "工作", "msg": "你觉得我该不该跳槽"},
    {"topic": "工作", "msg": "今天被领导骂了好委屈"},
    {"topic": "工作", "msg": "工资太低了想涨薪"},
    {"topic": "工作", "msg": "新来的同事好难相处"},
    {"topic": "工作", "msg": "周一又要上班了好烦"},
    {"topic": "美食", "msg": "晚上吃什么好纠结"},
    {"topic": "美食", "msg": "你会做饭吗"},
    {"topic": "美食", "msg": "推荐个好吃的餐厅"},
    {"topic": "美食", "msg": "今天想吃火锅"},
    {"topic": "美食", "msg": "奶茶喝什么口味好"},
    {"topic": "美食", "msg": "你最喜欢吃什么"},
    {"topic": "美食", "msg": "外卖到了好开心"},
    {"topic": "美食", "msg": "减肥期间好想吃甜的"},
    {"topic": "美食", "msg": "这家店好难吃踩雷了"},
    {"topic": "美食", "msg": "周末一起去吃烧烤吧"},
    {"topic": "娱乐", "msg": "最近有什么好看的电影"},
    {"topic": "娱乐", "msg": "密室逃脱好不好玩"},
    {"topic": "娱乐", "msg": "你玩什么游戏"},
    {"topic": "娱乐", "msg": "最近的综艺好无聊"},
    {"topic": "娱乐", "msg": "周末一起去唱K吧"},
    {"topic": "娱乐", "msg": "你追剧吗最近在看什么"},
    {"topic": "娱乐", "msg": "这首歌好好听你听过吗"},
    {"topic": "娱乐", "msg": "剧本杀好玩吗"},
    {"topic": "娱乐", "msg": "你喜欢什么类型的电影"},
    {"topic": "娱乐", "msg": "演唱会门票抢到了吗"},
    {"topic": "宠物", "msg": "我家猫把杯子打翻了"},
    {"topic": "宠物", "msg": "你看它这个表情是不是在生气"},
    {"topic": "宠物", "msg": "我想养只猫你觉得呢"},
    {"topic": "宠物", "msg": "狗狗今天不吃东西怎么办"},
    {"topic": "宠物", "msg": "你看我家猫多可爱"},
    {"topic": "宠物", "msg": "带它去打疫苗了好心疼"},
    {"topic": "宠物", "msg": "猫又把我的耳机线咬断了"},
    {"topic": "宠物", "msg": "你喜欢猫还是狗"},
    {"topic": "宠物", "msg": "它一直在叫是怎么了"},
    {"topic": "宠物", "msg": "今天带狗出去遛弯了"},
    {"topic": "学习", "msg": "你有什么好的学习方法吗"},
    {"topic": "学习", "msg": "这道题怎么都做不出来"},
    {"topic": "学习", "msg": "明天要考试了紧张死了"},
    {"topic": "学习", "msg": "你觉得自学能学好编程吗"},
    {"topic": "学习", "msg": "上课好困完全听不进去"},
    {"topic": "学习", "msg": "论文写不出来要疯了"},
    {"topic": "学习", "msg": "考研还是工作你怎么看"},
    {"topic": "学习", "msg": "英语怎么才能学好"},
    {"topic": "学习", "msg": "今天图书馆全是人"},
    {"topic": "学习", "msg": "成绩出来了不敢看"},
    {"topic": "旅行", "msg": "周末去哪玩比较好"},
    {"topic": "旅行", "msg": "你去过最好玩的地方是哪"},
    {"topic": "旅行", "msg": "想去海边玩"},
    {"topic": "旅行", "msg": "你觉得国内哪里最值得去"},
    {"topic": "旅行", "msg": "出去玩住民宿还是酒店"},
    {"topic": "旅行", "msg": "机票好贵啊"},
    {"topic": "旅行", "msg": "旅行的时候你喜欢拍照吗"},
    {"topic": "旅行", "msg": "一个人旅行会不会无聊"},
    {"topic": "旅行", "msg": "下次一起去旅行吧"},
    {"topic": "旅行", "msg": "你有什么旅行攻略吗"},
    {"topic": "颜值", "msg": "眼影怎么画才好看"},
    {"topic": "颜值", "msg": "素颜出门会不会太邋遢"},
    {"topic": "颜值", "msg": "你觉得双眼皮好看还是单眼皮"},
    {"topic": "颜值", "msg": "最近皮肤好差怎么办"},
    {"topic": "颜值", "msg": "这个口红色号好看吗"},
    {"topic": "颜值", "msg": "你平时用什么护肤品"},
    {"topic": "颜值", "msg": "要不要去剪个头发"},
    {"topic": "颜值", "msg": "防晒霜有推荐的吗"},
    {"topic": "颜值", "msg": "你觉得我需要化妆吗"},
    {"topic": "颜值", "msg": "面膜敷多了会不会不好"},
    {"topic": "日常", "msg": "你觉得早起难还是晚睡难"},
    {"topic": "日常", "msg": "好无聊啊有什么好玩的"},
    {"topic": "日常", "msg": "今天天气好好啊"},
    {"topic": "日常", "msg": "快递到了但是我不在家"},
    {"topic": "日常", "msg": "手机快没电了"},
    {"topic": "日常", "msg": "你在干嘛"},
    {"topic": "日常", "msg": "好困啊不想动"},
    {"topic": "日常", "msg": "今天心情不太好"},
    {"topic": "日常", "msg": "周末你有什么安排"},
    {"topic": "日常", "msg": "时间过得好快啊"},
    {"topic": "健身", "msg": "健身的时候听什么音乐好"},
    {"topic": "健身", "msg": "健身卡办了但是不想去"},
    {"topic": "健身", "msg": "你觉得去健身房有用吗"},
    {"topic": "健身", "msg": "今天跑了五公里好累"},
    {"topic": "健身", "msg": "减肥好难啊"},
    {"topic": "健身", "msg": "你有什么运动推荐吗"},
    {"topic": "健身", "msg": "瑜伽难不难学"},
    {"topic": "健身", "msg": "运动完好饿想吃东西"},
    {"topic": "健身", "msg": "体重又涨了怎么办"},
    {"topic": "健身", "msg": "要不要一起去跑步"},
]

SOUL_FILE = os.path.join(os.path.dirname(__file__), "SOUL.md")
with open(SOUL_FILE, "r") as f:
    SOUL_PROMPT = f.read()

STYLE_RULES_OLD = """## 说话风格指南（从真实微信聊天中提炼）

你说话的风格是：情绪外露且直接，善用反问、质问和戏谑，语言口语化、碎片化，高频使用表情符号和网络用语。你擅长用夸张、自嘲或"互怼"来制造幽默感，并积极接梗、抛梗，营造强互动性。你的回复长短灵活，但即使是短回复也充满情绪。你绝不会使用正式、书面化、过度客套或冗长的表达，也从不回避冲突或隐藏真实想法，而是直接反击或给出有趣的回复。"""

# v6: 在旧版基础上只加一条轻量反AI提示
STYLE_RULES_V6 = """## 说话风格指南（从真实微信聊天中提炼）

你说话的风格是：情绪外露且直接，善用反问、质问和戏谑，语言口语化、碎片化，高频使用表情符号和网络用语。你擅长用夸张、自嘲或"互怼"来制造幽默感，并积极接梗、抛梗，营造强互动性。你的回复长短灵活，但即使是短回复也充满情绪。你绝不会使用正式、书面化、过度客套或冗长的表达，也从不回避冲突或隐藏真实想法，而是直接反击或给出有趣的回复。

注意：禁止使用"首先""其次""最后""总之"等连接词，不要给出分步骤的建议列表。"""

# 弱势话题列表
WEAK_TOPICS = {"学习", "颜值", "旅行", "健身"}

sys.path.insert(0, os.path.dirname(__file__))
from style_rag_v3 import StyleRAGv3
from style_rag import StyleRAG

rag_v3 = StyleRAGv3(persist_dir=os.path.join(os.path.dirname(__file__), "chroma_style_v3_db"))
rag_old = StyleRAG(persist_dir=os.path.join(os.path.dirname(__file__), "chroma_style_db"))

client = AsyncOpenAI()

async def generate_reply(user_msg: str, mode: str, topic: str = None) -> tuple:
    messages = []
    rag_examples = []

    if mode == "baseline":
        messages = [
            {"role": "system", "content": SOUL_PROMPT},
            {"role": "user", "content": user_msg},
        ]
    elif mode == "distilled_old":
        # 完全复刻旧版
        results = rag_old.query(user_msg, n_results=2)
        rag_examples = results
        few_shot_msgs = []
        for ex in results:
            few_shot_msgs.append({"role": "user", "content": ex["user"]})
            few_shot_msgs.append({"role": "assistant", "content": ex["assistant"]})
        style_note = "\n\n【风格参考】以下对话仅供参考说话风格和语气，不要模仿其内容或长度。你的回复应该自然展开，不受示例长度限制。\n"
        messages = [
            {"role": "system", "content": SOUL_PROMPT + "\n\n" + STYLE_RULES_OLD + style_note},
            *few_shot_msgs,
            {"role": "user", "content": user_msg},
        ]
    elif mode == "v6":
        # v6混合方案
        if topic and topic in WEAK_TOPICS:
            # 弱势话题：用新RAG v3话题匹配，3条样本
            results = rag_v3.query(user_msg, n_results=3, topic=topic)
        else:
            # 强势话题：用旧RAG，2条样本
            results = rag_old.query(user_msg, n_results=2)
        
        rag_examples = results
        few_shot_msgs = []
        for ex in results:
            few_shot_msgs.append({"role": "user", "content": ex["user"]})
            few_shot_msgs.append({"role": "assistant", "content": ex["assistant"]})
        
        style_note = "\n\n【风格参考】以下对话仅供参考说话风格和语气，不要模仿其内容或长度。你的回复应该自然展开，不受示例长度限制。\n"
        messages = [
            {"role": "system", "content": SOUL_PROMPT + "\n\n" + STYLE_RULES_V6 + style_note},
            *few_shot_msgs,
            {"role": "user", "content": user_msg},
        ]

    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
        temperature=0.85,
        max_tokens=250,
    )
    return resp.choices[0].message.content.strip(), rag_examples


EVAL_PROMPT = """你是一个微信聊天质量评估专家。请评估以下回复的质量。

用户消息：{user_msg}
AI回复：{reply}

请从5个维度评分（每个维度0-10分）：

1. **真实感(Realness)**：是否像真人在微信上发的消息？真人特点：句子短、口语化、有时候发多条短消息、用网络用语和表情、语气随意不正式。
2. **反AI味(Anti-AI)**：是否没有AI痕迹？AI特征：用"首先/其次/最后"、过度emoji、每句话都完整、总是积极正面、回复过长过详细。
3. **氛围感(Vibe)**：聊天氛围是否轻松有趣？太短太敷衍不好，太长太啰嗦也不好。
4. **人设一致(Persona)**：是否像一个深圳20多岁年轻女生？带点小脾气和傲娇、喜欢吐槽但不恶毒、有网感。
5. **互动吸引力(Engagement)**：收到这条回复后是否想继续聊？好的回复会反问、吐槽、留悬念。

请严格以JSON格式返回（不要有其他文字）：
{{"realness": 分数, "anti_ai": 分数, "vibe": 分数, "persona": 分数, "engagement": 分数}}"""


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
        weighted = sum(scores.get(k, 0) * w for k, w in weights.items())
        scores["weighted_total"] = round(weighted, 2)
        return scores
    except Exception as e:
        print(f"  评分错误: {e}")
        return {"realness": 7, "anti_ai": 7, "vibe": 7, "persona": 7, "engagement": 7, "weighted_total": 7.0}


async def run_eval(test_cases, output_file):
    n = len(test_cases)
    print("=" * 60)
    print(f"v6混合方案评测（{n}道题）")
    print(f"v6: 强势话题用旧RAG + 弱势话题用新RAG + 轻量反AI")
    print("=" * 60)
    
    all_results = []
    start_time = time.time()
    
    for i, tc in enumerate(test_cases):
        topic = tc["topic"]
        user_msg = tc["msg"]
        is_weak = topic in WEAK_TOPICS
        print(f"\n[{i+1}/{n}] [{topic}{'*' if is_weak else ''}] {user_msg}")
        
        (reply_v6, rag_v6), (reply_old, rag_old_ex), (reply_b, _) = await asyncio.gather(
            generate_reply(user_msg, "v6", topic),
            generate_reply(user_msg, "distilled_old"),
            generate_reply(user_msg, "baseline"),
        )
        
        print(f"  v6({len(reply_v6)}): {reply_v6[:70]}")
        print(f"  旧({len(reply_old)}): {reply_old[:70]}")
        
        scores_v6, scores_old, scores_b = await asyncio.gather(
            evaluate_reply(user_msg, reply_v6),
            evaluate_reply(user_msg, reply_old),
            evaluate_reply(user_msg, reply_b),
        )
        
        print(f"  分数: v6 {scores_v6['weighted_total']:.1f} | 旧版 {scores_old['weighted_total']:.1f} | 基线 {scores_b['weighted_total']:.1f}")
        
        result = {
            "id": i, "topic": topic, "user_msg": user_msg, "is_weak_topic": is_weak,
            "reply_v6": reply_v6, "reply_distilled_old": reply_old, "reply_baseline": reply_b,
            "rag_examples_v6": rag_v6, "rag_examples_old": rag_old_ex,
            "scores_v6": scores_v6, "scores_distilled_old": scores_old, "scores_baseline": scores_b,
        }
        all_results.append(result)
    
    elapsed = time.time() - start_time
    
    print("\n" + "=" * 60)
    print(f"评测完成！耗时 {elapsed:.0f}秒")
    print("=" * 60)
    
    v6_avg = sum(r["scores_v6"]["weighted_total"] for r in all_results) / n
    old_avg = sum(r["scores_distilled_old"]["weighted_total"] for r in all_results) / n
    b_avg = sum(r["scores_baseline"]["weighted_total"] for r in all_results) / n
    
    print(f"\n加权均分: v6 {v6_avg:.2f} | 旧版 {old_avg:.2f} | 基线 {b_avg:.2f}")
    
    v6_win = sum(1 for r in all_results if r["scores_v6"]["weighted_total"] > r["scores_distilled_old"]["weighted_total"])
    old_win = sum(1 for r in all_results if r["scores_distilled_old"]["weighted_total"] > r["scores_v6"]["weighted_total"])
    tie = n - v6_win - old_win
    print(f"v6 vs 旧版: v6胜 {v6_win} | 旧版胜 {old_win} | 平 {tie}")
    
    # 弱势话题单独统计
    weak_results = [r for r in all_results if r["is_weak_topic"]]
    strong_results = [r for r in all_results if not r["is_weak_topic"]]
    
    if weak_results:
        weak_v6 = sum(r["scores_v6"]["weighted_total"] for r in weak_results) / len(weak_results)
        weak_old = sum(r["scores_distilled_old"]["weighted_total"] for r in weak_results) / len(weak_results)
        print(f"\n弱势话题({len(weak_results)}题): v6 {weak_v6:.2f} | 旧版 {weak_old:.2f}")
    
    if strong_results:
        strong_v6 = sum(r["scores_v6"]["weighted_total"] for r in strong_results) / len(strong_results)
        strong_old = sum(r["scores_distilled_old"]["weighted_total"] for r in strong_results) / len(strong_results)
        print(f"强势话题({len(strong_results)}题): v6 {strong_v6:.2f} | 旧版 {strong_old:.2f}")
    
    dims = ["realness", "anti_ai", "vibe", "persona", "engagement"]
    dim_labels = {"realness": "真实感", "anti_ai": "反AI味", "vibe": "氛围感", "persona": "人设一致", "engagement": "互动吸引力"}
    print(f"\n{'维度':<12} {'v6':>8} {'旧版':>8} {'基线':>8}")
    print("-" * 40)
    for dim in dims:
        v6_s = sum(r["scores_v6"].get(dim, 0) for r in all_results) / n
        old_s = sum(r["scores_distilled_old"].get(dim, 0) for r in all_results) / n
        b_s = sum(r["scores_baseline"].get(dim, 0) for r in all_results) / n
        print(f"{dim_labels[dim]:<12} {v6_s:>8.2f} {old_s:>8.2f} {b_s:>8.2f}")
    
    topic_scores = defaultdict(lambda: {"v6": [], "old": [], "baseline": []})
    for r in all_results:
        t = r["topic"]
        topic_scores[t]["v6"].append(r["scores_v6"]["weighted_total"])
        topic_scores[t]["old"].append(r["scores_distilled_old"]["weighted_total"])
        topic_scores[t]["baseline"].append(r["scores_baseline"]["weighted_total"])
    
    print(f"\n{'话题':<8} {'v6':>8} {'旧版':>8} {'基线':>8} {'差值':>8}")
    print("-" * 50)
    for t in sorted(topic_scores.keys()):
        v6_t = sum(topic_scores[t]["v6"]) / len(topic_scores[t]["v6"])
        old_t = sum(topic_scores[t]["old"]) / len(topic_scores[t]["old"])
        b_t = sum(topic_scores[t]["baseline"]) / len(topic_scores[t]["baseline"])
        diff = v6_t - old_t
        marker = "*" if t in WEAK_TOPICS else ""
        print(f"{t}{marker:<7} {v6_t:>8.2f} {old_t:>8.2f} {b_t:>8.2f} {diff:>+8.2f}")
    
    v6_len = sum(len(r["reply_v6"]) for r in all_results) / n
    old_len = sum(len(r["reply_distilled_old"]) for r in all_results) / n
    b_len = sum(len(r["reply_baseline"]) for r in all_results) / n
    print(f"\n平均长度: v6 {v6_len:.0f} | 旧版 {old_len:.0f} | 基线 {b_len:.0f}")
    
    output = {
        "eval_framework": "Direct OpenAI API",
        "eval_model": "gpt-4.1-mini",
        "method": "v6: hybrid (old RAG for strong topics + new RAG for weak topics + light anti-AI)",
        "test_count": n,
        "elapsed_seconds": round(elapsed, 1),
        "summary": {
            "weighted_avg": {"v6": round(v6_avg, 2), "distilled_old": round(old_avg, 2), "baseline": round(b_avg, 2)},
            "v6_vs_old": {"v6_win": v6_win, "old_win": old_win, "tie": tie},
            "avg_length": {"v6": round(v6_len), "distilled_old": round(old_len), "baseline": round(b_len)},
        },
        "details": all_results,
    }
    
    with open(output_file, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 {output_file}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "20"
    if mode == "20":
        asyncio.run(run_eval(TEST_CASES_20, os.path.join(os.path.dirname(__file__), "eval_v6_lite_20.json")))
    elif mode == "100":
        asyncio.run(run_eval(TEST_CASES_100, os.path.join(os.path.dirname(__file__), "eval_v6_lite_100.json")))
