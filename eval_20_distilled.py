"""
风格蒸馏版评测：
- system prompt 中加入蒸馏出的风格规则
- few-shot 从5个减到1-2个
- prompt 明确说"参考说话风格，不是内容"
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

# 五维度权重
WEIGHTS = {
    "human_likeness": 0.30,
    "content": 0.25,
    "vibe": 0.20,
    "persona": 0.15,
    "empathy": 0.10,
}
DIM_NAMES = {
    "human_likeness": "拟人感",
    "content": "内容质量",
    "vibe": "聊天氛围",
    "persona": "人设一致",
    "empathy": "情绪回应",
}

# ========== 核心改动：蒸馏风格规则 ==========
STYLE_RULES = """你说话的风格是：情绪外露且直接，善用反问、质问和戏谑，语言口语化、碎片化，高频使用表情符号和网络用语。你擅长用夸张、自嘲或"互怼"来制造幽默感，并积极接梗、抛梗，营造强互动性。你的回复长短灵活，但即使是短回复也充满情绪。你绝不会使用正式、书面化、过度客套或冗长的表达，也从不回避冲突或隐藏真实想法，而是直接反击或给出有趣的回复。"""

# few-shot 前的引导语
FEW_SHOT_INTRO = "【以下是一些说话风格的参考示例，学习它们的语气和风格，不要照搬内容。你的回复应该根据实际话题自由展开，不受示例长度限制。】"

JUDGE_SYSTEM = """你是一个评估聊天机器人回复质量的专家。背景：这是一个模拟23岁深圳女生"小悦"的微信聊天机器人。她有点i，慢热，但跟熟人聊天很随意，说话直接，有时候毒舌。"""

JUDGE_TEMPLATE = """用户消息："{user_msg}"

回复A："{reply_a}"
回复B："{reply_b}"

请从以下5个维度分别给A和B打分（1-10分）：

1. **拟人感** (human_likeness)：像不像真人在微信上发的消息？短句碎片化、有语气词、口语化的得高分。太工整太完美太像AI的扣分。注意：短≠差，真人微信本来就是短的。长但像AI写的应该扣分。
2. **内容质量** (content)：回复有没有实质内容？一句精准的吐槽比一大段废话更好。不以长度论好坏。
3. **聊天氛围** (vibe)：营造的聊天氛围好不好？让人想继续聊吗？有互动感、有趣味、有来有回的感觉得高分。
4. **人设一致性** (persona)：像不像一个23岁深圳女生，有点i但跟熟人很随意、说话直接有时毒舌？
5. **情绪回应** (empathy)：对用户情绪的回应是否恰当自然？真人式的回应（调侃、共鸣、吐槽）得高分，AI式的"我理解你的感受"扣分。

只输出JSON，不要任何解释：
{{"a":{{"human_likeness":<int>,"content":<int>,"vibe":<int>,"persona":<int>,"empathy":<int>}},"b":{{"human_likeness":<int>,"content":<int>,"vibe":<int>,"persona":<int>,"empathy":<int>}}}}"""

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


async def evaluate_one(idx, user_msg, topic, rag_hits, soul, client, mode):
    """
    mode = "distilled" | "baseline"
    distilled: SOUL + 风格规则 + 1-2个few-shot（带引导语）
    baseline: SOUL + 无RAG（纯system prompt）
    """
    global completed
    
    result = {"id": idx, "topic": topic, "user_msg": user_msg, "mode": mode}
    
    if mode == "distilled":
        # 构建 system prompt = SOUL + 蒸馏风格规则
        system_prompt = soul + "\n\n" + STYLE_RULES
        
        # 只取前2个 few-shot，加引导语
        msgs = [{"role": "system", "content": system_prompt}]
        
        # 加引导语作为一条system消息
        msgs.append({"role": "system", "content": FEW_SHOT_INTRO})
        
        # 只取1-2个最相关的示例
        n_examples = min(2, len(rag_hits))
        for ex in rag_hits[:n_examples]:
            msgs.append({"role": "user", "content": ex["user"]})
            msgs.append({"role": "assistant", "content": ex["assistant"]})
        
        msgs.append({"role": "user", "content": user_msg})
        
        result["rag_examples"] = [{"u": e["user"][:60], "a": e["assistant"][:60]} for e in rag_hits[:n_examples]]
        
    else:  # baseline
        system_prompt = soul + "\n\n你是一个说话随意、口语化的女生。"
        msgs = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_msg}]
    
    reply = await call_api(client, COMPASS_BASE_URL, COMPASS_API_KEY, GEN_MODEL, msgs, max_tokens=2000, temperature=0.8)
    result["reply"] = reply
    
    return result


async def evaluate_pair(idx, user_msg, topic, rag_hits, soul, client):
    """同时生成 distilled 和 baseline 回复，然后评分"""
    global completed
    
    result = {"id": idx, "topic": topic, "user_msg": user_msg}
    
    # 1. Distilled RAG 回复
    distilled = await evaluate_one(idx, user_msg, topic, rag_hits, soul, client, "distilled")
    result["reply_with_rag"] = distilled["reply"]
    result["rag_examples"] = distilled.get("rag_examples", [])
    
    await asyncio.sleep(0.3)
    
    # 2. Baseline 无RAG 回复
    baseline = await evaluate_one(idx, user_msg, topic, rag_hits, soul, client, "baseline")
    result["reply_without_rag"] = baseline["reply"]
    
    await asyncio.sleep(0.3)
    
    # 3. 五维度评分
    judge_prompt = JUDGE_TEMPLATE.format(
        user_msg=user_msg,
        reply_a=result["reply_with_rag"][:300] if not result["reply_with_rag"].startswith("[") else result["reply_with_rag"],
        reply_b=result["reply_without_rag"][:300] if not result["reply_without_rag"].startswith("[") else result["reply_without_rag"],
    )
    
    raw = await call_api(
        client, MANUS_BASE_URL, MANUS_API_KEY, JUDGE_MODEL,
        [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": judge_prompt}],
        max_tokens=200, temperature=0.2
    )
    
    parsed = parse_json_response(raw)
    scores = {}
    all_ok = False
    
    if parsed and "a" in parsed and "b" in parsed:
        try:
            a_dims = parsed["a"]
            b_dims = parsed["b"]
            all_dims_ok = True
            for dim in WEIGHTS:
                if dim in a_dims and dim in b_dims:
                    scores[f"A_{dim}"] = int(a_dims[dim])
                    scores[f"B_{dim}"] = int(b_dims[dim])
                else:
                    all_dims_ok = False
            
            if all_dims_ok:
                a_weighted = calc_weighted_score({d: scores[f"A_{d}"] for d in WEIGHTS})
                b_weighted = calc_weighted_score({d: scores[f"B_{d}"] for d in WEIGHTS})
                scores["A_weighted"] = a_weighted
                scores["B_weighted"] = b_weighted
                scores["winner"] = "A" if a_weighted > b_weighted else ("B" if b_weighted > a_weighted else "tie")
                all_ok = True
        except:
            pass
    
    if not all_ok:
        scores["winner"] = "error"
        scores["raw_response"] = raw[:200] if raw else "None"
    
    result["scores"] = scores
    
    completed += 1
    w = scores.get("winner", "?")
    label = "蒸馏✓" if w == "A" else ("基线✓" if w == "B" else w)
    a_w = scores.get("A_weighted", "?")
    b_w = scores.get("B_weighted", "?")
    print(f"  [{completed}/{total}] {topic}: {user_msg[:25]}... → {label}  蒸馏={a_w} 基线={b_w}")
    
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
                result = await evaluate_pair(idx, user_msg, topic, rag_hits, soul, client)
                async with lock:
                    results_list.append(result)
            except Exception as e:
                print(f"  ❌ #{idx} Error: {e}")
                async with lock:
                    results_list.append({
                        "id": idx, "topic": topic, "user_msg": user_msg,
                        "scores": {"winner": "error", "error": str(e)},
                        "reply_with_rag": "[ERROR]", "reply_without_rag": "[ERROR]",
                    })


async def main():
    global completed, total, soul
    
    # 从200道题中每个话题抽2道 = 20道（同样的seed保证和之前一致）
    random.seed(42)
    topics = ["穿搭", "工作", "美食", "娱乐", "宠物", "学习", "旅行", "颜值", "日常", "健身"]
    selected = []
    for topic in topics:
        topic_cases = [(msg, t) for msg, t in TEST_CASES_200 if t == topic]
        chosen = random.sample(topic_cases, min(2, len(topic_cases)))
        selected.extend(chosen)
    
    total = len(selected)
    completed = 0
    
    print(f"{'='*60}")
    print(f"=== 风格蒸馏版评测 ({total} 道题) ===")
    print(f"{'='*60}")
    print(f"\n方案A（蒸馏）: SOUL + 风格规则 + 1-2个few-shot（带引导语）")
    print(f"方案B（基线）: SOUL + 无RAG")
    print()
    
    from style_rag import StyleRAG
    rag = StyleRAG(persist_dir='chroma_style_db')
    
    with open('SOUL.md', 'r') as f:
        soul = f.read().strip()
    
    print(f"RAG 库: {rag.count()} 条")
    print(f"风格规则: {len(STYLE_RULES)} 字")
    print(f"Few-shot: 最多2个示例 + 引导语")
    print(f"引导语: \"{FEW_SHOT_INTRO}\"")
    print(f"评分体系: 五维度加权\n")
    
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
    
    # 汇总
    valid = [r for r in results_list if r["scores"].get("winner") not in ("error", None)]
    a_wins = sum(1 for r in valid if r["scores"]["winner"] == "A")
    b_wins = sum(1 for r in valid if r["scores"]["winner"] == "B")
    ties = sum(1 for r in valid if r["scores"]["winner"] == "tie")
    errors = len(results_list) - len(valid)
    
    print(f"\n{'='*60}")
    print(f"=== 评测结果 ({len(valid)} 道有效题, {elapsed:.0f}秒) ===\n")
    print(f"蒸馏赢: {a_wins} ({a_wins/max(len(valid),1)*100:.0f}%) | 基线赢: {b_wins} ({b_wins/max(len(valid),1)*100:.0f}%) | 平局: {ties} | 错误: {errors}")
    
    if valid:
        a_w_avg = sum(r["scores"].get("A_weighted", 0) for r in valid) / len(valid)
        b_w_avg = sum(r["scores"].get("B_weighted", 0) for r in valid) / len(valid)
        print(f"\n加权平均: 蒸馏 {a_w_avg:.2f} vs 基线 {b_w_avg:.2f} (差值: {a_w_avg-b_w_avg:+.2f})")
        
        print(f"\n各维度:")
        for dim in WEIGHTS:
            a_avg = sum(r["scores"].get(f"A_{dim}", 0) for r in valid) / len(valid)
            b_avg = sum(r["scores"].get(f"B_{dim}", 0) for r in valid) / len(valid)
            diff = a_avg - b_avg
            marker = "✓" if diff > 0 else ("✗" if diff < 0 else "=")
            print(f"  {DIM_NAMES[dim]}({WEIGHTS[dim]*100:.0f}%): 蒸馏 {a_avg:.1f} vs 基线 {b_avg:.1f} ({diff:+.1f}) {marker}")
    
    # 按话题
    print(f"\n按话题:")
    for topic in topics:
        tr = [r for r in valid if r["topic"] == topic]
        if not tr:
            continue
        ta = sum(1 for r in tr if r["scores"]["winner"] == "A")
        tb = sum(1 for r in tr if r["scores"]["winner"] == "B")
        tt = sum(1 for r in tr if r["scores"]["winner"] == "tie")
        print(f"  {topic}: 蒸馏 {ta} - 基线 {tb} (平{tt})")
    
    # 逐题展示
    print(f"\n{'='*60}")
    print(f"=== 逐题详情 ===\n")
    for r in results_list:
        w = r["scores"].get("winner", "?")
        label = "蒸馏✓" if w == "A" else ("基线✓" if w == "B" else w)
        print(f"--- [{r['topic']}] {r['user_msg']} → {label} ---")
        print(f"  蒸馏回复: {r['reply_with_rag'][:200]}")
        print(f"  基线回复: {r['reply_without_rag'][:200]}")
        if r.get("rag_examples"):
            for i, ex in enumerate(r["rag_examples"][:2]):
                print(f"  示例{i+1}: {ex['u'][:40]} → {ex['a'][:50]}")
        a_w = r["scores"].get("A_weighted", "?")
        b_w = r["scores"].get("B_weighted", "?")
        print(f"  评分: 蒸馏={a_w} 基线={b_w}")
        print()
    
    # 回复长度对比
    rag_lens = [len(r["reply_with_rag"]) for r in valid if not r["reply_with_rag"].startswith("[")]
    norag_lens = [len(r["reply_without_rag"]) for r in valid if not r["reply_without_rag"].startswith("[")]
    if rag_lens:
        print(f"\n回复长度: 蒸馏 {sum(rag_lens)//len(rag_lens)} 字 vs 基线 {sum(norag_lens)//len(norag_lens)} 字")
    
    # 保存
    summary = {
        "eval_version": "distilled_v1",
        "approach": "风格蒸馏 + 1-2个few-shot + 引导语",
        "style_rules": STYLE_RULES,
        "few_shot_intro": FEW_SHOT_INTRO,
        "rag_count": rag.count(),
        "test_count": total,
        "elapsed_seconds": round(elapsed),
        "summary": {
            "distilled_wins": a_wins, "baseline_wins": b_wins, "ties": ties, "errors": errors,
            "distilled_win_rate": round(a_wins / max(len(valid), 1) * 100, 1),
        },
        "details": results_list,
    }
    
    with open('eval_20_distilled_results.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 结果已保存到 eval_20_distilled_results.json")


if __name__ == "__main__":
    asyncio.run(main())
