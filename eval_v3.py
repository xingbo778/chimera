"""
评测脚本 v3：
- 使用 StyleRAGv3（话题感知 + 质量优先）
- 改进的生成 prompt（更强调碎片化和真人感）
- 对比：v3优化版 vs 原蒸馏版 vs 基线
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

# ── 测试用例（20题快速验证）──
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

# ── 100题完整测试集 ──
TEST_CASES_100 = [
    # 穿搭 10题
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
    # 工作 10题
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
    # 美食 10题
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
    # 娱乐 10题
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
    # 宠物 10题
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
    # 学习 10题
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
    # 旅行 10题
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
    # 颜值 10题
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
    # 日常 10题
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
    # 健身 10题
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

# ── SOUL prompt ──
SOUL_FILE = os.path.join(os.path.dirname(__file__), "SOUL.md")
with open(SOUL_FILE, "r") as f:
    SOUL_PROMPT = f.read()

# ── 改进的风格规则（更强调碎片化和控制长度）──
STYLE_RULES_V3 = """## 说话风格（从真实微信聊天提炼）

核心：你在微信上跟朋友聊天，不是在写作文。

1. **碎片化**：一个想法拆成2-3条短消息发，每条不超过15个字。用换行分隔。
2. **口语化**：用"啊""吧""呢""嘛"等语气词，说话随意不正式。
3. **情绪直接**：想吐槽就吐槽，想敷衍就敷衍，不用每次都热情回应。
4. **不要展开**：别解释太多，别给建议列表，别写长段落。真人聊天不会这样。
5. **反问/接话**：多用反问句接话，少用陈述句回答。
6. **偶尔敷衍**：有些话题可以"嗯""还行""不知道"敷衍过去，不用每次都认真回答。

禁忌：
- 不要用"首先/其次/最后"
- 不要一次性回复超过40个字
- 不要每句话都加emoji
- 不要总是积极正面
- 不要像在给建议或做总结"""

# ── RAG 加载 ──
sys.path.insert(0, os.path.dirname(__file__))
from style_rag_v3 import StyleRAGv3

rag_v3 = StyleRAGv3(persist_dir=os.path.join(os.path.dirname(__file__), "chroma_style_v3_db"))

# Also load old RAG for comparison
from style_rag import StyleRAG
rag_old = StyleRAG(persist_dir=os.path.join(os.path.dirname(__file__), "chroma_style_db"))

# ── 生成回复 ──
client = AsyncOpenAI()

async def generate_reply(user_msg: str, mode: str, topic: str = None) -> tuple:
    """生成回复"""
    messages = []
    rag_examples = []

    if mode == "baseline":
        messages = [
            {"role": "system", "content": SOUL_PROMPT},
            {"role": "user", "content": user_msg},
        ]
    elif mode == "distilled_old":
        # 原蒸馏版（用旧RAG）
        results = rag_old.query(user_msg, n_results=2)
        rag_examples = results
        few_shot_msgs = []
        for ex in results:
            few_shot_msgs.append({"role": "user", "content": ex["user"]})
            few_shot_msgs.append({"role": "assistant", "content": ex["assistant"]})
        
        old_style = """## 说话风格指南（从真实微信聊天中提炼）

你说话的风格是：情绪外露且直接，善用反问、质问和戏谑，语言口语化、碎片化，高频使用表情符号和网络用语。你擅长用夸张、自嘲或"互怼"来制造幽默感，并积极接梗、抛梗，营造强互动性。你的回复长短灵活，但即使是短回复也充满情绪。你绝不会使用正式、书面化、过度客套或冗长的表达，也从不回避冲突或隐藏真实想法，而是直接反击或给出有趣的回复。"""
        
        style_note = "\n\n【风格参考】以下对话仅供参考说话风格和语气，不要模仿其内容或长度。\n"
        messages = [
            {"role": "system", "content": SOUL_PROMPT + "\n\n" + old_style + style_note},
            *few_shot_msgs,
            {"role": "user", "content": user_msg},
        ]
    elif mode == "v3":
        # 新版：v3 RAG + 改进 prompt
        results = rag_v3.query(user_msg, n_results=3, topic=topic)
        rag_examples = results
        few_shot_msgs = []
        for ex in results:
            few_shot_msgs.append({"role": "user", "content": ex["user"]})
            few_shot_msgs.append({"role": "assistant", "content": ex["assistant"]})
        
        style_note = "\n\n【风格参考】以下对话展示了真人微信聊天的风格。注意它们的碎片化和随意感。你的回复也要这样——短、碎、随意。\n"
        messages = [
            {"role": "system", "content": SOUL_PROMPT + "\n\n" + STYLE_RULES_V3 + style_note},
            *few_shot_msgs,
            {"role": "user", "content": user_msg},
        ]

    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
        temperature=0.85,
        max_tokens=150,  # 限制长度
    )
    return resp.choices[0].message.content.strip(), rag_examples


# ── DeepEval G-Eval 指标 ──
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


async def evaluate_one(metrics, user_msg, reply):
    """用5个G-Eval指标评估一条回复"""
    test_case = LLMTestCase(input=user_msg, actual_output=reply)
    
    scores = {}
    tasks = []
    for metric in metrics:
        async def eval_metric(m=metric, tc=test_case):
            await m.a_measure(tc)
            return m.name, m.score, m.reason
        tasks.append(eval_metric())
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for r in results:
        if isinstance(r, Exception):
            print(f"  评分错误: {r}")
            continue
        name, score, reason = r
        scores[name] = {"score": score, "reason": reason}
    
    weights = {
        "真实感(Realness)": 0.30,
        "反AI味(Anti-AI)": 0.25,
        "氛围感(Vibe)": 0.20,
        "人设一致(Persona)": 0.15,
        "互动吸引力(Engagement)": 0.10,
    }
    
    weighted_sum = 0
    for name, w in weights.items():
        if name in scores:
            weighted_sum += scores[name]["score"] * w * 10
    
    scores["weighted_total"] = round(weighted_sum, 2)
    return scores


async def run_eval(test_cases, output_file):
    """主评测流程"""
    n = len(test_cases)
    print("=" * 60)
    print(f"DeepEval G-Eval 评测（{n}道题）")
    print(f"对比: v3优化版 vs 原蒸馏版 vs 基线")
    print("=" * 60)
    
    metrics = create_metrics()
    all_results = []
    start_time = time.time()
    
    for i, tc in enumerate(test_cases):
        topic = tc["topic"]
        user_msg = tc["msg"]
        print(f"\n[{i+1}/{n}] [{topic}] {user_msg}")
        
        # 生成三种回复
        reply_v3, rag_ex_v3 = await generate_reply(user_msg, "v3", topic)
        reply_old, rag_ex_old = await generate_reply(user_msg, "distilled_old")
        reply_baseline, _ = await generate_reply(user_msg, "baseline")
        
        print(f"  v3:   {reply_v3[:60]}...")
        print(f"  旧版: {reply_old[:60]}...")
        print(f"  基线: {reply_baseline[:60]}...")
        
        # 评分
        scores_v3, scores_old, scores_b = await asyncio.gather(
            evaluate_one(metrics, user_msg, reply_v3),
            evaluate_one(metrics, user_msg, reply_old),
            evaluate_one(metrics, user_msg, reply_baseline),
        )
        
        print(f"  G-Eval: v3 {scores_v3['weighted_total']:.1f} | 旧版 {scores_old['weighted_total']:.1f} | 基线 {scores_b['weighted_total']:.1f}")
        
        result = {
            "id": i,
            "topic": topic,
            "user_msg": user_msg,
            "reply_v3": reply_v3,
            "reply_distilled_old": reply_old,
            "reply_baseline": reply_baseline,
            "rag_examples_v3": rag_ex_v3,
            "rag_examples_old": rag_ex_old,
            "scores_v3": scores_v3,
            "scores_distilled_old": scores_old,
            "scores_baseline": scores_b,
        }
        all_results.append(result)
    
    elapsed = time.time() - start_time
    
    # 统计
    print("\n" + "=" * 60)
    print(f"评测完成！耗时 {elapsed:.0f}秒")
    print("=" * 60)
    
    v3_avg = sum(r["scores_v3"]["weighted_total"] for r in all_results) / len(all_results)
    old_avg = sum(r["scores_distilled_old"]["weighted_total"] for r in all_results) / len(all_results)
    b_avg = sum(r["scores_baseline"]["weighted_total"] for r in all_results) / len(all_results)
    
    print(f"\n加权均分: v3 {v3_avg:.2f} | 旧版 {old_avg:.2f} | 基线 {b_avg:.2f}")
    
    # 胜率
    v3_win = sum(1 for r in all_results if r["scores_v3"]["weighted_total"] > r["scores_distilled_old"]["weighted_total"])
    old_win = sum(1 for r in all_results if r["scores_distilled_old"]["weighted_total"] > r["scores_v3"]["weighted_total"])
    tie = n - v3_win - old_win
    print(f"v3 vs 旧版: v3胜 {v3_win} | 旧版胜 {old_win} | 平 {tie}")
    
    # 各维度
    dim_names = ["真实感(Realness)", "反AI味(Anti-AI)", "氛围感(Vibe)", "人设一致(Persona)", "互动吸引力(Engagement)"]
    print(f"\n{'维度':<20} {'v3':>8} {'旧版':>8} {'基线':>8}")
    print("-" * 50)
    for dim in dim_names:
        v3_s = sum(r["scores_v3"].get(dim, {}).get("score", 0) for r in all_results) / len(all_results) * 10
        old_s = sum(r["scores_distilled_old"].get(dim, {}).get("score", 0) for r in all_results) / len(all_results) * 10
        b_s = sum(r["scores_baseline"].get(dim, {}).get("score", 0) for r in all_results) / len(all_results) * 10
        print(f"{dim:<20} {v3_s:>8.1f} {old_s:>8.1f} {b_s:>8.1f}")
    
    # 平均长度
    v3_len = sum(len(r["reply_v3"]) for r in all_results) / len(all_results)
    old_len = sum(len(r["reply_distilled_old"]) for r in all_results) / len(all_results)
    b_len = sum(len(r["reply_baseline"]) for r in all_results) / len(all_results)
    print(f"\n平均长度: v3 {v3_len:.0f} | 旧版 {old_len:.0f} | 基线 {b_len:.0f}")
    
    # 保存
    output = {
        "eval_framework": "DeepEval G-Eval",
        "eval_model": "gpt-4.1-mini",
        "method": "v3: topic-aware RAG + fragmented prompt",
        "test_count": n,
        "elapsed_seconds": round(elapsed, 1),
        "summary": {
            "weighted_avg": {"v3": round(v3_avg, 2), "distilled_old": round(old_avg, 2), "baseline": round(b_avg, 2)},
            "v3_vs_old": {"v3_win": v3_win, "old_win": old_win, "tie": tie},
            "avg_length": {"v3": round(v3_len), "distilled_old": round(old_len), "baseline": round(b_len)},
        },
        "details": all_results,
    }
    
    with open(output_file, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 {output_file}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "20"
    
    if mode == "20":
        asyncio.run(run_eval(TEST_CASES_20, os.path.join(os.path.dirname(__file__), "eval_v3_20_results.json")))
    elif mode == "100":
        asyncio.run(run_eval(TEST_CASES_100, os.path.join(os.path.dirname(__file__), "eval_v3_100_results.json")))
