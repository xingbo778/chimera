"""
新评分器评测：
- 评分器以"真人微信聊天对象"视角打分
- 碎片化、随意、自然得高分
- AI味重、太完整、太像写作文的扣分
- 同时跑三个方案：蒸馏版 / 5个few-shot版 / 纯基线
"""
import sys, os, json, time, re, asyncio, random
sys.path.insert(0, os.path.dirname(__file__))

import httpx
from test_cases_200 import TEST_CASES_200

# API 配置
COMPASS_API_KEY = '9a3d58cc61234d927b3d5d0223a1277b106ca171d9a9608a6ff298d1544562a1'
COMPASS_BASE_URL = 'https://edmonton-yesterday-instead-ballot.trycloudflare.com/compass-api/v1'
GEN_MODEL = "gemini-3-flash-preview"

MANUS_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MANUS_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
JUDGE_MODEL = "gemini-2.5-flash"

NUM_WORKERS = 5
MAX_RETRIES = 3

# ========== 新评分体系 ==========
# 维度和权重
WEIGHTS = {
    "realness": 0.35,      # 真实感（最高权重）
    "anti_ai": 0.25,       # 去AI味
    "vibe": 0.20,          # 聊天氛围
    "persona": 0.10,       # 人设
    "engagement": 0.10,    # 互动性
}
DIM_NAMES = {
    "realness": "真实感",
    "anti_ai": "去AI味",
    "vibe": "聊天氛围",
    "persona": "人设一致",
    "engagement": "互动性",
}

# 蒸馏风格规则
STYLE_RULES = """你说话的风格是：情绪外露且直接，善用反问、质问和戏谑，语言口语化、碎片化，高频使用表情符号和网络用语。你擅长用夸张、自嘲或"互怼"来制造幽默感，并积极接梗、抛梗，营造强互动性。你的回复长短灵活，但即使是短回复也充满情绪。你绝不会使用正式、书面化、过度客套或冗长的表达，也从不回避冲突或隐藏真实想法，而是直接反击或给出有趣的回复。"""

FEW_SHOT_INTRO = "【以下是一些说话风格的参考示例，学习它们的语气和风格，不要照搬内容。你的回复应该根据实际话题自由展开，不受示例长度限制。】"

# ========== 新评分器 ==========
JUDGE_SYSTEM = """你是一个23岁的普通女生，正在微信上和朋友聊天。你要评价两条回复，哪条更像是你真实的微信好友发来的。

你的判断标准很简单：看完这条消息，你的第一反应是"这是真人发的"还是"这是AI写的"。

重要提醒：
- 真人微信聊天经常很短、很碎、很随意，有时候就一两个字、一个表情，这是正常的
- 真人不会每条消息都"有观点有展开有互动"，有时候就是敷衍一下、随口一说
- 如果一条回复读起来像小红书文案、公众号文章、或者ChatGPT的输出，那就是AI味重
- 长≠好，短≠差。关键是"自然不自然"
- 真人会有情绪波动，有时候热情有时候冷淡，不会每条都保持同样的"热情有趣"
- 列数字（1. 2. 3.）、用加粗、分段太工整、每段都有总结，这些都是AI的特征"""

JUDGE_TEMPLATE = """你朋友发了一条微信："{user_msg}"

下面是两个人的回复，你觉得哪个更像真人发的微信消息？

回复A："{reply_a}"
回复B："{reply_b}"

从5个角度打分（1-10分）：

1. **真实感** (realness)：这条消息像不像真人随手打的微信？碎片化、有错别字、有语气词、想到哪说到哪的得高分。结构完整、逻辑清晰、像写文章的扣分。一个"哈哈哈"如果用在对的地方，比一大段精心组织的回复更真实。

2. **去AI味** (anti_ai)：有没有AI的痕迹？以下特征要重扣分：每段都有观点+展开+总结、使用"说真的""不过话说回来"等过渡词太频繁、排比句式、每条消息都面面俱到不遗漏任何角度、永远保持"有趣+毒舌+关心"的完美人设不崩。真人会偶尔敷衍、偶尔跑题、偶尔答非所问。

3. **聊天氛围** (vibe)：和这个人聊天舒不舒服？注意：太热情太有趣也会让人不舒服（像销售），真人朋友之间有时候就是平淡地聊，不需要每句话都抖机灵。自然的节奏感比刻意的有趣更重要。

4. **人设一致** (persona)：像不像一个23岁深圳女生？注意：不是每句话都要提深圳、都要说"i人"、都要毒舌。真人的人设是自然流露的，不是刻意表演的。

5. **互动性** (engagement)：看完这条消息你想不想回？注意：让你想回的不一定是"有趣的"消息，有时候一句简短的关心、一个恰到好处的吐槽、甚至一个"？"都能让你想回。长篇大论反而可能让人不知道该回什么。

只输出JSON：
{{"a":{{"realness":<int>,"anti_ai":<int>,"vibe":<int>,"persona":<int>,"engagement":<int>}},"b":{{"realness":<int>,"anti_ai":<int>,"vibe":<int>,"persona":<int>,"engagement":<int>}}}}"""

completed = 0
total = 0


async def call_api(client, base_url, api_key, model, messages, max_tokens=2000, temperature=0.8):
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=60.0)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                if content and len(content.strip()) > 3:
                    return content.strip()
            elif resp.status_code == 429:
                await asyncio.sleep(5 * (attempt + 1))
                continue
            else:
                await asyncio.sleep(2 * (attempt + 1))
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 * (attempt + 1))
            else:
                return f"[API ERROR: {e}]"
    return "[API ERROR: empty after retries]"


def parse_json_response(text):
    if not text:
        return None
    md_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if md_match:
        text = md_match.group(1).strip()
    try:
        return json.loads(text)
    except:
        pass
    brace_start = text.find('{')
    if brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start:i+1])
                    except:
                        break
    return None


def calc_weighted_score(dim_scores):
    total = 0
    for dim, weight in WEIGHTS.items():
        total += dim_scores.get(dim, 0) * weight
    return round(total, 2)


async def generate_reply(client, soul, user_msg, rag_hits, mode):
    """
    mode:
    - "distilled": SOUL + 风格规则 + 2个few-shot + 引导语
    - "fewshot5": SOUL + 5个few-shot（旧方案）
    - "baseline": SOUL only
    """
    if mode == "distilled":
        system_prompt = soul + "\n\n" + STYLE_RULES
        msgs = [{"role": "system", "content": system_prompt}]
        msgs.append({"role": "system", "content": FEW_SHOT_INTRO})
        n_examples = min(2, len(rag_hits))
        for ex in rag_hits[:n_examples]:
            msgs.append({"role": "user", "content": ex["user"]})
            msgs.append({"role": "assistant", "content": ex["assistant"]})
        msgs.append({"role": "user", "content": user_msg})
    
    elif mode == "fewshot5":
        system_prompt = soul + "\n\n你是一个说话随意、口语化的女生。"
        msgs = [{"role": "system", "content": system_prompt}]
        for ex in rag_hits[:5]:
            msgs.append({"role": "user", "content": ex["user"]})
            msgs.append({"role": "assistant", "content": ex["assistant"]})
        msgs.append({"role": "user", "content": user_msg})
    
    else:  # baseline
        system_prompt = soul + "\n\n你是一个说话随意、口语化的女生。"
        msgs = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_msg}]
    
    return await call_api(client, COMPASS_BASE_URL, COMPASS_API_KEY, GEN_MODEL, msgs, max_tokens=2000, temperature=0.8)


async def judge_pair(client, user_msg, reply_a, reply_b):
    """用新评分器评分"""
    judge_prompt = JUDGE_TEMPLATE.format(
        user_msg=user_msg,
        reply_a=reply_a[:400] if not reply_a.startswith("[") else reply_a,
        reply_b=reply_b[:400] if not reply_b.startswith("[") else reply_b,
    )
    
    raw = await call_api(
        client, MANUS_BASE_URL, MANUS_API_KEY, JUDGE_MODEL,
        [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": judge_prompt}],
        max_tokens=200, temperature=0.2
    )
    
    parsed = parse_json_response(raw)
    scores = {}
    
    if parsed and "a" in parsed and "b" in parsed:
        try:
            a_dims = parsed["a"]
            b_dims = parsed["b"]
            all_ok = True
            for dim in WEIGHTS:
                if dim in a_dims and dim in b_dims:
                    scores[f"A_{dim}"] = int(a_dims[dim])
                    scores[f"B_{dim}"] = int(b_dims[dim])
                else:
                    all_ok = False
            
            if all_ok:
                a_w = calc_weighted_score({d: scores[f"A_{d}"] for d in WEIGHTS})
                b_w = calc_weighted_score({d: scores[f"B_{d}"] for d in WEIGHTS})
                scores["A_weighted"] = a_w
                scores["B_weighted"] = b_w
                scores["winner"] = "A" if a_w > b_w else ("B" if b_w > a_w else "tie")
                return scores
        except:
            pass
    
    return {"winner": "error", "raw": raw[:200] if raw else "None"}


async def evaluate_one_question(idx, user_msg, topic, rag_hits, soul, client):
    """对一道题生成三个方案的回复，然后两两比较"""
    global completed
    
    result = {"id": idx, "topic": topic, "user_msg": user_msg}
    
    # 生成三个方案的回复
    reply_distilled = await generate_reply(client, soul, user_msg, rag_hits, "distilled")
    await asyncio.sleep(0.3)
    reply_fewshot5 = await generate_reply(client, soul, user_msg, rag_hits, "fewshot5")
    await asyncio.sleep(0.3)
    reply_baseline = await generate_reply(client, soul, user_msg, rag_hits, "baseline")
    await asyncio.sleep(0.3)
    
    result["reply_distilled"] = reply_distilled
    result["reply_fewshot5"] = reply_fewshot5
    result["reply_baseline"] = reply_baseline
    result["rag_examples"] = [{"u": e["user"][:60], "a": e["assistant"][:60]} for e in rag_hits[:2]]
    
    # 三组对比评分
    # 1. 蒸馏 vs 基线
    scores_db = await judge_pair(client, user_msg, reply_distilled, reply_baseline)
    await asyncio.sleep(0.3)
    
    # 2. 5-shot vs 基线
    scores_fb = await judge_pair(client, user_msg, reply_fewshot5, reply_baseline)
    await asyncio.sleep(0.3)
    
    # 3. 蒸馏 vs 5-shot
    scores_df = await judge_pair(client, user_msg, reply_distilled, reply_fewshot5)
    
    result["scores_distilled_vs_baseline"] = scores_db
    result["scores_fewshot5_vs_baseline"] = scores_fb
    result["scores_distilled_vs_fewshot5"] = scores_df
    
    completed += 1
    
    # 简洁输出
    db_w = scores_db.get("winner", "?")
    fb_w = scores_fb.get("winner", "?")
    df_w = scores_df.get("winner", "?")
    
    db_label = "蒸馏" if db_w == "A" else ("基线" if db_w == "B" else "平")
    fb_label = "5shot" if fb_w == "A" else ("基线" if fb_w == "B" else "平")
    df_label = "蒸馏" if df_w == "A" else ("5shot" if df_w == "B" else "平")
    
    print(f"  [{completed}/{total}] {topic}: {user_msg[:20]}... | 蒸vs基:{db_label} | 5svs基:{fb_label} | 蒸vs5s:{df_label}")
    
    return result


async def worker(queue, rag_query_fn, soul, results_list, lock):
    async with httpx.AsyncClient() as client:
        while True:
            try:
                idx, user_msg, topic = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            
            rag_hits = rag_query_fn(user_msg, n_results=5)
            
            try:
                result = await evaluate_one_question(idx, user_msg, topic, rag_hits, soul, client)
                async with lock:
                    results_list.append(result)
            except Exception as e:
                print(f"  ❌ #{idx} Error: {e}")
                async with lock:
                    results_list.append({
                        "id": idx, "topic": topic, "user_msg": user_msg,
                        "scores_distilled_vs_baseline": {"winner": "error"},
                        "scores_fewshot5_vs_baseline": {"winner": "error"},
                        "scores_distilled_vs_fewshot5": {"winner": "error"},
                        "reply_distilled": "[ERROR]", "reply_fewshot5": "[ERROR]", "reply_baseline": "[ERROR]",
                    })


async def main():
    global completed, total
    
    random.seed(42)
    topics = ["穿搭", "工作", "美食", "娱乐", "宠物", "学习", "旅行", "颜值", "日常", "健身"]
    selected = []
    for topic in topics:
        topic_cases = [(msg, t) for msg, t in TEST_CASES_200 if t == topic]
        chosen = random.sample(topic_cases, min(2, len(topic_cases)))
        selected.extend(chosen)
    
    total = len(selected)
    completed = 0
    
    print(f"{'='*70}")
    print(f"=== 新评分器三方对比评测 ({total} 道题) ===")
    print(f"{'='*70}")
    print(f"\n方案A: 蒸馏版（风格规则 + 2个few-shot + 引导语）")
    print(f"方案B: 5-shot版（5个few-shot，旧方案）")
    print(f"方案C: 基线（纯SOUL，无RAG）")
    print(f"\n评分器: 真人微信视角（真实感35% + 去AI味25% + 氛围20% + 人设10% + 互动10%）")
    print()
    
    from style_rag import StyleRAG
    rag = StyleRAG(persist_dir='chroma_style_db')
    
    with open('SOUL.md', 'r') as f:
        soul = f.read().strip()
    
    print(f"RAG 库: {rag.count()} 条\n")
    
    queue = asyncio.Queue()
    for idx, (user_msg, topic) in enumerate(selected):
        queue.put_nowait((idx, user_msg, topic))
    
    results_list = []
    lock = asyncio.Lock()
    start_time = time.time()
    
    workers_list = [asyncio.create_task(worker(queue, rag.query, soul, results_list, lock)) for _ in range(NUM_WORKERS)]
    await asyncio.gather(*workers_list)
    
    elapsed = time.time() - start_time
    results_list.sort(key=lambda r: r["id"])
    
    # ========== 汇总 ==========
    print(f"\n{'='*70}")
    print(f"=== 评测结果 ({elapsed:.0f}秒) ===\n")
    
    comparisons = [
        ("蒸馏 vs 基线", "scores_distilled_vs_baseline", "蒸馏", "基线"),
        ("5-shot vs 基线", "scores_fewshot5_vs_baseline", "5-shot", "基线"),
        ("蒸馏 vs 5-shot", "scores_distilled_vs_fewshot5", "蒸馏", "5-shot"),
    ]
    
    for title, key, a_name, b_name in comparisons:
        valid = [r for r in results_list if r[key].get("winner") not in ("error", None)]
        a_wins = sum(1 for r in valid if r[key]["winner"] == "A")
        b_wins = sum(1 for r in valid if r[key]["winner"] == "B")
        ties = sum(1 for r in valid if r[key]["winner"] == "tie")
        
        print(f"【{title}】")
        print(f"  {a_name}: {a_wins} ({a_wins/max(len(valid),1)*100:.0f}%) | {b_name}: {b_wins} ({b_wins/max(len(valid),1)*100:.0f}%) | 平局: {ties}")
        
        if valid:
            a_avg = sum(r[key].get("A_weighted", 0) for r in valid) / len(valid)
            b_avg = sum(r[key].get("B_weighted", 0) for r in valid) / len(valid)
            print(f"  加权分: {a_name} {a_avg:.2f} vs {b_name} {b_avg:.2f} ({a_avg-b_avg:+.2f})")
            
            for dim in WEIGHTS:
                a_d = sum(r[key].get(f"A_{dim}", 0) for r in valid) / len(valid)
                b_d = sum(r[key].get(f"B_{dim}", 0) for r in valid) / len(valid)
                marker = "✓" if a_d > b_d else ("✗" if a_d < b_d else "=")
                print(f"    {DIM_NAMES[dim]}: {a_d:.1f} vs {b_d:.1f} ({a_d-b_d:+.1f}) {marker}")
        print()
    
    # 回复长度
    d_lens = [len(r["reply_distilled"]) for r in results_list if not r["reply_distilled"].startswith("[")]
    f_lens = [len(r["reply_fewshot5"]) for r in results_list if not r["reply_fewshot5"].startswith("[")]
    b_lens = [len(r["reply_baseline"]) for r in results_list if not r["reply_baseline"].startswith("[")]
    print(f"回复长度: 蒸馏 {sum(d_lens)//max(len(d_lens),1)}字 | 5-shot {sum(f_lens)//max(len(f_lens),1)}字 | 基线 {sum(b_lens)//max(len(b_lens),1)}字")
    
    # 逐题详情
    print(f"\n{'='*70}")
    print(f"=== 逐题详情 ===\n")
    for r in results_list:
        db = r["scores_distilled_vs_baseline"].get("winner", "?")
        fb = r["scores_fewshot5_vs_baseline"].get("winner", "?")
        df = r["scores_distilled_vs_fewshot5"].get("winner", "?")
        print(f"--- [{r['topic']}] {r['user_msg']} ---")
        print(f"  蒸馏: {r['reply_distilled'][:150]}")
        print(f"  5shot: {r['reply_fewshot5'][:150]}")
        print(f"  基线:  {r['reply_baseline'][:150]}")
        
        db_s = f"蒸馏{r['scores_distilled_vs_baseline'].get('A_weighted','?')} vs 基线{r['scores_distilled_vs_baseline'].get('B_weighted','?')}"
        fb_s = f"5shot{r['scores_fewshot5_vs_baseline'].get('A_weighted','?')} vs 基线{r['scores_fewshot5_vs_baseline'].get('B_weighted','?')}"
        df_s = f"蒸馏{r['scores_distilled_vs_fewshot5'].get('A_weighted','?')} vs 5shot{r['scores_distilled_vs_fewshot5'].get('B_weighted','?')}"
        print(f"  评分: {db_s} | {fb_s} | {df_s}")
        print()
    
    # 保存
    summary = {
        "eval_version": "newjudge_v1",
        "judge_description": "真人微信视角评分器（真实感35%+去AI味25%+氛围20%+人设10%+互动10%）",
        "test_count": total,
        "elapsed_seconds": round(elapsed),
        "details": results_list,
    }
    
    with open('eval_20_newjudge_results.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 结果已保存到 eval_20_newjudge_results.json")


if __name__ == "__main__":
    asyncio.run(main())
