"""
Style RAG 200题评测 v3 — 五维度评分体系
======================================
维度：拟人感(30%) + 内容质量(25%) + 聊天氛围(20%) + 人设一致性(15%) + 情绪回应(10%)
支持同时对比 v1 和 v2 RAG
"""
import sys, os, json, time, re, asyncio
sys.path.insert(0, os.path.dirname(__file__))

import httpx
from test_cases_200 import TEST_CASES_200

# API 配置
COMPASS_API_KEY = '9a3d58cc61234d927b3d5d0223a1277b106ca171d9a9608a6ff298d1544562a1'
COMPASS_BASE_URL = 'https://forum-stan-towers-quest.trycloudflare.com/compass-api/v1'
GEN_MODEL = "gemini-3-flash-preview"

MANUS_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MANUS_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
JUDGE_MODEL = "gemini-2.5-flash"

NUM_WORKERS = 8
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

# 评分 prompt
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
    """计算加权总分"""
    total = 0
    for dim, weight in WEIGHTS.items():
        total += dim_scores.get(dim, 0) * weight
    return round(total, 2)


async def evaluate_one(idx, user_msg, topic, rag_hits, few_shot_msgs, soul, client):
    global completed
    
    result = {"id": idx, "topic": topic, "user_msg": user_msg}
    result["rag_examples"] = [{"u": e["user"][:50], "a": e["assistant"][:50]} for e in rag_hits[:3]]
    
    system_prompt = soul + "\n\n你是一个说话随意、口语化的女生。"
    
    # 1. 有 RAG 的回复
    msgs_rag = [{"role": "system", "content": system_prompt}] + few_shot_msgs + [{"role": "user", "content": user_msg}]
    reply_rag = await call_api(client, COMPASS_BASE_URL, COMPASS_API_KEY, GEN_MODEL, msgs_rag, max_tokens=2000, temperature=0.8)
    result["reply_with_rag"] = reply_rag
    
    await asyncio.sleep(0.5)
    
    # 2. 无 RAG 的回复
    msgs_norag = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_msg}]
    reply_norag = await call_api(client, COMPASS_BASE_URL, COMPASS_API_KEY, GEN_MODEL, msgs_norag, max_tokens=2000, temperature=0.8)
    result["reply_without_rag"] = reply_norag
    
    await asyncio.sleep(0.3)
    
    # 3. 五维度一次性评分
    judge_prompt = JUDGE_TEMPLATE.format(
        user_msg=user_msg,
        reply_a=reply_rag[:300] if not reply_rag.startswith("[") else reply_rag,
        reply_b=reply_norag[:300] if not reply_norag.startswith("[") else reply_norag,
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
    label = "RAG" if w == "A" else ("NoRAG" if w == "B" else w)
    a_w = scores.get("A_weighted", "?")
    b_w = scores.get("B_weighted", "?")
    print(f"  [{completed}/{total}] #{idx} {topic}: {user_msg[:20]}... → {label}  "
          f"A={a_w} B={b_w}  "
          f"[人{scores.get('A_human_likeness','?')}/内{scores.get('A_content','?')}/氛{scores.get('A_vibe','?')}/设{scores.get('A_persona','?')}/情{scores.get('A_empathy','?')}] "
          f"vs [{scores.get('B_human_likeness','?')}/{scores.get('B_content','?')}/{scores.get('B_vibe','?')}/{scores.get('B_persona','?')}/{scores.get('B_empathy','?')}]")
    
    return result


async def worker(queue, rag_query_fn, soul, results_list, lock):
    async with httpx.AsyncClient() as client:
        while True:
            try:
                idx, user_msg, topic = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            
            rag_hits = rag_query_fn(user_msg, n_results=5)
            few_shot_msgs = []
            for ex in rag_hits:
                few_shot_msgs.append({"role": "user", "content": ex["user"]})
                few_shot_msgs.append({"role": "assistant", "content": ex["assistant"]})
            
            try:
                result = await evaluate_one(idx, user_msg, topic, rag_hits, few_shot_msgs, soul, client)
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


def summarize(results_list, elapsed, rag_count, label, results_file):
    results_list.sort(key=lambda r: r["id"])
    
    print(f"\n{'='*60}")
    print(f"=== {label} 最终汇总 ({len(results_list)} 道题, 耗时 {elapsed/60:.1f} 分钟) ===\n")
    
    valid = [r for r in results_list if r["scores"].get("winner") not in ("error", None)]
    a_wins = sum(1 for r in valid if r["scores"]["winner"] == "A")
    b_wins = sum(1 for r in valid if r["scores"]["winner"] == "B")
    ties = sum(1 for r in valid if r["scores"]["winner"] == "tie")
    errors = len(results_list) - len(valid)
    
    print(f"有效评分: {len(valid)}/{len(results_list)}")
    print(f"总体胜负: RAG赢 {a_wins} | NoRAG赢 {b_wins} | 平局 {ties} | 错误 {errors}")
    
    if valid:
        print(f"\n加权平均分:")
        a_w_avg = sum(r["scores"].get("A_weighted", 0) for r in valid) / len(valid)
        b_w_avg = sum(r["scores"].get("B_weighted", 0) for r in valid) / len(valid)
        print(f"  RAG: {a_w_avg:.2f} vs NoRAG: {b_w_avg:.2f} (差值: {a_w_avg-b_w_avg:+.2f})")
        
        print(f"\n各维度平均分 (权重):")
        for dim in WEIGHTS:
            a_avg = sum(r["scores"].get(f"A_{dim}", 0) for r in valid) / len(valid)
            b_avg = sum(r["scores"].get(f"B_{dim}", 0) for r in valid) / len(valid)
            print(f"  {DIM_NAMES[dim]}({WEIGHTS[dim]*100:.0f}%): RAG {a_avg:.2f} vs NoRAG {b_avg:.2f} (差值: {a_avg-b_avg:+.2f})")
    
    # 按话题统计
    print(f"\n--- 按话题统计 ---")
    topics = ["穿搭", "工作", "美食", "娱乐", "宠物", "学习", "旅行", "颜值", "日常", "健身"]
    topic_stats = {}
    for topic in topics:
        tr = [r for r in valid if r["topic"] == topic]
        if not tr:
            continue
        ta = sum(1 for r in tr if r["scores"]["winner"] == "A")
        tb = sum(1 for r in tr if r["scores"]["winner"] == "B")
        tt = sum(1 for r in tr if r["scores"]["winner"] == "tie")
        
        dims_avg = {}
        for dim in WEIGHTS:
            a_avg = sum(r["scores"].get(f"A_{dim}", 0) for r in tr) / len(tr)
            b_avg = sum(r["scores"].get(f"B_{dim}", 0) for r in tr) / len(tr)
            dims_avg[dim] = {"rag": round(a_avg, 2), "norag": round(b_avg, 2)}
        
        topic_stats[topic] = {
            "total": len(tr), "rag_wins": ta, "norag_wins": tb, "ties": tt,
            "rag_win_rate": round(ta / len(tr) * 100, 1),
            "dims": dims_avg,
        }
        print(f"  {topic}: RAG赢{ta} NoRAG赢{tb} 平{tt} (共{len(tr)}) → RAG胜率 {ta/len(tr)*100:.0f}%")
    
    # 回复长度
    rag_lens = [len(r["reply_with_rag"]) for r in valid if not r["reply_with_rag"].startswith("[")]
    norag_lens = [len(r["reply_without_rag"]) for r in valid if not r["reply_without_rag"].startswith("[")]
    
    print(f"\n--- 回复长度 ---")
    if rag_lens:
        print(f"  RAG: {sum(rag_lens)/len(rag_lens):.0f} 字")
    if norag_lens:
        print(f"  NoRAG: {sum(norag_lens)/len(norag_lens):.0f} 字")
    
    # 保存
    avg_scores = {}
    if valid:
        for dim in WEIGHTS:
            avg_scores[f"rag_{dim}"] = round(sum(r["scores"].get(f"A_{dim}", 0) for r in valid) / len(valid), 2)
            avg_scores[f"norag_{dim}"] = round(sum(r["scores"].get(f"B_{dim}", 0) for r in valid) / len(valid), 2)
        avg_scores["rag_weighted"] = round(sum(r["scores"].get("A_weighted", 0) for r in valid) / len(valid), 2)
        avg_scores["norag_weighted"] = round(sum(r["scores"].get("B_weighted", 0) for r in valid) / len(valid), 2)
    
    final_data = {
        "eval_version": "v3_5dim",
        "label": label,
        "model": f"{GEN_MODEL} + {JUDGE_MODEL}",
        "rag_count": rag_count,
        "weights": WEIGHTS,
        "test_count": len(TEST_CASES_200),
        "completed": len(results_list),
        "elapsed_minutes": round(elapsed / 60, 1),
        "summary": {
            "rag_wins": a_wins, "norag_wins": b_wins, "ties": ties, "errors": errors,
            "rag_win_rate": round(a_wins / max(len(valid), 1) * 100, 1),
            "avg_scores": avg_scores,
        },
        "topic_stats": topic_stats,
        "avg_reply_len": {
            "rag": round(sum(rag_lens) / max(len(rag_lens), 1)),
            "norag": round(sum(norag_lens) / max(len(norag_lens), 1)),
        },
        "details": results_list,
    }
    
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 结果已保存到 {results_file}")
    return final_data


async def run_eval(rag_persist_dir, label, results_file):
    global completed, total
    completed = 0
    total = len(TEST_CASES_200)
    
    print(f"\n{'#'*60}")
    print(f"### {label} ###")
    print(f"{'#'*60}")
    
    from style_rag import StyleRAG
    rag = StyleRAG(persist_dir=rag_persist_dir)
    
    with open('SOUL.md', 'r') as f:
        soul = f.read()[:500]
    
    print(f"RAG 库: {rag.count()} 条")
    print(f"评分体系: 五维度加权 (拟人30%+内容25%+氛围20%+人设15%+情绪10%)")
    print(f"并发数: {NUM_WORKERS}\n")
    
    queue = asyncio.Queue()
    for idx, (user_msg, topic) in enumerate(TEST_CASES_200):
        queue.put_nowait((idx, user_msg, topic))
    
    results_list = []
    lock = asyncio.Lock()
    start_time = time.time()
    
    workers = [asyncio.create_task(worker(queue, rag.query, soul, results_list, lock)) for _ in range(NUM_WORKERS)]
    await asyncio.gather(*workers)
    
    elapsed = time.time() - start_time
    return summarize(results_list, elapsed, rag.count(), label, results_file)


async def main():
    # 先跑 v1
    v1_data = await run_eval('style_rag_db', 'v1_旧RAG_406条', 'eval_v3_results_v1.json')
    
    # 再跑 v2
    v2_data = await run_eval('chroma_style_db', 'v2_新RAG_1320条', 'eval_v3_results_v2.json')
    
    # 对比汇总
    print(f"\n{'='*60}")
    print(f"=== v1 vs v2 对比（五维度评分体系 v3）===")
    print(f"{'='*60}")
    print(f"  v1 RAG胜率: {v1_data['summary']['rag_win_rate']}%")
    print(f"  v2 RAG胜率: {v2_data['summary']['rag_win_rate']}%")
    print(f"\n  v1 加权分: RAG {v1_data['summary']['avg_scores'].get('rag_weighted','?')} vs NoRAG {v1_data['summary']['avg_scores'].get('norag_weighted','?')}")
    print(f"  v2 加权分: RAG {v2_data['summary']['avg_scores'].get('rag_weighted','?')} vs NoRAG {v2_data['summary']['avg_scores'].get('norag_weighted','?')}")


if __name__ == "__main__":
    asyncio.run(main())
