"""
正式评测 v5：100题
对比：旧RAG 3-shot (最优) vs 旧RAG 2-shot (基线)
"""

import asyncio
import json
import os
import sys
import time

from openai import AsyncOpenAI

TEST_CASES = [
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

STYLE_RULES = """## 说话风格指南（从真实微信聊天中提炼）

你说话的风格是：情绪外露且直接，善用反问、质问和戏谑，语言口语化、碎片化，高频使用表情符号和网络用语。你擅长用夸张、自嘲或"互怼"来制造幽默感，并积极接梗、抛梗，营造强互动性。你的回复长短灵活，但即使是短回复也充满情绪。你绝不会使用正式、书面化、过度客套或冗长的表达，也从不回避冲突或隐藏真实想法，而是直接反击或给出有趣的回复。"""

STYLE_NOTE = "\n\n【风格参考】以下对话仅供参考说话风格和语气，不要模仿其内容或长度。你的回复应该自然展开，不受示例长度限制。\n"

sys.path.insert(0, os.path.dirname(__file__))
from style_rag import StyleRAG

rag = StyleRAG(persist_dir=os.path.join(os.path.dirname(__file__), "chroma_style_db"))

client = AsyncOpenAI()

async def generate_reply(user_msg: str, n_shot: int) -> tuple:
    results = rag.query(user_msg, n_results=n_shot)
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


async def run_eval():
    n = len(TEST_CASES)
    print("=" * 60)
    print(f"正式评测：3-shot vs 2-shot x {n}题")
    print("=" * 60)
    
    all_results = []
    start_time = time.time()
    
    for i, tc in enumerate(TEST_CASES):
        topic = tc["topic"]
        user_msg = tc["msg"]
        print(f"\n[{i+1}/{n}] [{topic}] {user_msg}")
        
        # Generate both replies
        reply_3, rag_3 = await generate_reply(user_msg, 3)
        reply_2, rag_2 = await generate_reply(user_msg, 2)
        
        # Evaluate both
        scores_3, scores_2 = await asyncio.gather(
            evaluate_reply(user_msg, reply_3),
            evaluate_reply(user_msg, reply_2),
        )
        
        print(f"  3-shot: {scores_3['weighted_total']:.1f} ({reply_3[:50]})")
        print(f"  2-shot: {scores_2['weighted_total']:.1f} ({reply_2[:50]})")
        
        result = {
            "id": i,
            "topic": topic,
            "user_msg": user_msg,
            "reply_3shot": reply_3,
            "reply_2shot": reply_2,
            "rag_3shot": rag_3,
            "rag_2shot": rag_2,
            "scores_3shot": scores_3,
            "scores_2shot": scores_2,
        }
        all_results.append(result)
        
        # Save intermediate
        if (i + 1) % 20 == 0:
            with open(os.path.join(os.path.dirname(__file__), "eval_v5_100_partial.json"), "w") as f:
                json.dump(all_results, f, ensure_ascii=False, indent=2)
            print(f"\n--- 中间保存: {i+1}/{n} ---")
    
    elapsed = time.time() - start_time
    
    # Summary
    print("\n" + "=" * 60)
    print(f"正式评测完成！耗时 {elapsed:.0f}秒")
    print("=" * 60)
    
    avg_3 = sum(r["scores_3shot"]["weighted_total"] for r in all_results) / n
    avg_2 = sum(r["scores_2shot"]["weighted_total"] for r in all_results) / n
    
    print(f"\n加权均分: 3-shot {avg_3:.2f} | 2-shot {avg_2:.2f}")
    
    win_3 = sum(1 for r in all_results if r["scores_3shot"]["weighted_total"] > r["scores_2shot"]["weighted_total"])
    win_2 = sum(1 for r in all_results if r["scores_2shot"]["weighted_total"] > r["scores_3shot"]["weighted_total"])
    tie = n - win_3 - win_2
    print(f"3-shot vs 2-shot: 3shot胜 {win_3} | 2shot胜 {win_2} | 平 {tie}")
    
    # Dimension breakdown
    dims = ["realness", "anti_ai", "vibe", "persona", "engagement"]
    dim_labels = ["真实感", "反AI味", "氛围感", "人设一致", "互动吸引力"]
    print(f"\n{'维度':<10} {'3-shot':>8} {'2-shot':>8} {'差值':>8}")
    print("-" * 40)
    for dim, label in zip(dims, dim_labels):
        s3 = sum(r["scores_3shot"].get(dim, 5) for r in all_results) / n
        s2 = sum(r["scores_2shot"].get(dim, 5) for r in all_results) / n
        print(f"{label:<10} {s3:>8.2f} {s2:>8.2f} {s3-s2:>+8.2f}")
    
    # Average length
    len_3 = sum(len(r["reply_3shot"]) for r in all_results) / n
    len_2 = sum(len(r["reply_2shot"]) for r in all_results) / n
    print(f"\n平均长度: 3-shot {len_3:.0f} | 2-shot {len_2:.0f}")
    
    # Topic breakdown
    from collections import defaultdict
    topic_scores = defaultdict(lambda: {"3shot": [], "2shot": []})
    for r in all_results:
        t = r["topic"]
        topic_scores[t]["3shot"].append(r["scores_3shot"]["weighted_total"])
        topic_scores[t]["2shot"].append(r["scores_2shot"]["weighted_total"])
    
    print(f"\n{'话题':<8} {'3-shot':>8} {'2-shot':>8} {'差值':>8}")
    print("-" * 40)
    for t in sorted(topic_scores.keys()):
        s3 = sum(topic_scores[t]["3shot"]) / len(topic_scores[t]["3shot"])
        s2 = sum(topic_scores[t]["2shot"]) / len(topic_scores[t]["2shot"])
        print(f"{t:<8} {s3:>8.2f} {s2:>8.2f} {s3-s2:>+8.2f}")
    
    # Save
    output = {
        "experiment": "v5_100_formal",
        "test_count": n,
        "elapsed_seconds": round(elapsed, 1),
        "summary": {
            "avg_3shot": round(avg_3, 2),
            "avg_2shot": round(avg_2, 2),
            "win_3shot": win_3,
            "win_2shot": win_2,
            "tie": tie,
            "avg_len_3shot": round(len_3),
            "avg_len_2shot": round(len_2),
        },
        "details": all_results,
    }
    
    out_path = os.path.join(os.path.dirname(__file__), "eval_v5_100_results.json")
    with open(out_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 {out_path}")


if __name__ == "__main__":
    asyncio.run(run_eval())
