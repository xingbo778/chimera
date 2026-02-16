"""
Style RAG 200题评测 - asyncio 并发版
====================================
使用 asyncio + httpx 并发调用 API，10 个 worker 同时处理
预计耗时从 3-4 小时降到 20-30 分钟
"""
import sys, os, json, time, re, asyncio
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

RESULTS_FILE = "eval_200_results.json"
NUM_WORKERS = 8  # 并发数
MAX_RETRIES = 3

# 全局统计
completed = 0
total = len(TEST_CASES_200)


async def call_api(client, base_url, api_key, model, messages, max_tokens=2000, temperature=0.8):
    """通用异步 API 调用"""
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=60.0)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                if content and len(content.strip()) > 3:
                    return content.strip()
            elif resp.status_code == 429:
                # Rate limit - wait longer
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


async def evaluate_one(idx, user_msg, topic, rag_hits, few_shot_msgs, soul, client):
    """评测单道题"""
    global completed
    
    result = {"id": idx, "topic": topic, "user_msg": user_msg}
    result["rag_examples"] = [{"u": e["user"][:50], "a": e["assistant"][:50]} for e in rag_hits[:3]]
    
    system_prompt = soul + "\n\n你是一个说话随意、口语化的女生。"
    
    # 1. 有 RAG 的回复
    msgs_rag = [{"role": "system", "content": system_prompt}] + few_shot_msgs + [{"role": "user", "content": user_msg}]
    reply_rag = await call_api(client, COMPASS_BASE_URL, COMPASS_API_KEY, GEN_MODEL, msgs_rag, max_tokens=2000, temperature=0.8)
    result["reply_with_rag"] = reply_rag
    
    # 小延迟避免 rate limit
    await asyncio.sleep(0.5)
    
    # 2. 无 RAG 的回复
    msgs_norag = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_msg}]
    reply_norag = await call_api(client, COMPASS_BASE_URL, COMPASS_API_KEY, GEN_MODEL, msgs_norag, max_tokens=2000, temperature=0.8)
    result["reply_without_rag"] = reply_norag
    
    await asyncio.sleep(0.3)
    
    # 3. 三维度评分
    dims = [
        ("oral", "oral/colloquial naturalness (like real casual chat, NOT like AI)"),
        ("personal", "personality uniqueness (distinctive style, NOT generic)"),
        ("natural", "conversation fluency (smooth natural flow, NOT stiff)"),
    ]
    
    scores = {}
    all_ok = True
    for dim_key, dim_desc in dims:
        a_text = reply_rag[:150] if not reply_rag.startswith("[") else reply_rag
        b_text = reply_norag[:150] if not reply_norag.startswith("[") else reply_norag
        
        prompt = (
            f'User: "{user_msg}"\n'
            f'A: "{a_text}"\n'
            f'B: "{b_text}"\n\n'
            f'Rate {dim_desc} 1-10. JSON only: {{"a":<int>,"b":<int>}}'
        )
        
        raw = await call_api(
            client, MANUS_BASE_URL, MANUS_API_KEY, JUDGE_MODEL,
            [{"role": "system", "content": "Output only JSON"}, {"role": "user", "content": prompt}],
            max_tokens=50, temperature=0.2
        )
        parsed = parse_json_response(raw)
        if parsed and "a" in parsed and "b" in parsed:
            try:
                scores[f"A_{dim_key}"] = int(parsed["a"])
                scores[f"B_{dim_key}"] = int(parsed["b"])
            except:
                all_ok = False
        else:
            all_ok = False
        await asyncio.sleep(0.2)
    
    if all_ok:
        a_total = scores.get("A_oral", 0) + scores.get("A_personal", 0) + scores.get("A_natural", 0)
        b_total = scores.get("B_oral", 0) + scores.get("B_personal", 0) + scores.get("B_natural", 0)
        scores["winner"] = "A" if a_total > b_total else ("B" if b_total > a_total else "tie")
    else:
        scores["winner"] = "error"
    
    result["scores"] = scores
    
    completed += 1
    w = scores.get("winner", "?")
    label = "RAG" if w == "A" else ("NoRAG" if w == "B" else w)
    print(f"  [{completed}/{total}] #{idx} {topic}: {user_msg[:20]}... → {label}  "
          f"A({scores.get('A_oral','?')},{scores.get('A_personal','?')},{scores.get('A_natural','?')}) "
          f"B({scores.get('B_oral','?')},{scores.get('B_personal','?')},{scores.get('B_natural','?')})")
    
    return result


async def worker(queue, rag_data, soul, results_list, lock):
    """Worker 协程，从队列取任务执行"""
    async with httpx.AsyncClient() as client:
        while True:
            try:
                idx, user_msg, topic = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            
            # RAG 检索（同步，但很快）
            rag_hits = rag_data['query'](user_msg, n_results=5)
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
                        "reply_with_rag": f"[ERROR]", "reply_without_rag": f"[ERROR]",
                    })


async def main():
    # 加载 RAG
    print("Loading RAG database...")
    from style_rag import StyleRAG
    rag = StyleRAG(persist_dir='style_rag_db', few_shot_path='final_few_shot.md')
    
    # 加载 soul
    with open('SOUL.md', 'r') as f:
        soul = f.read()[:500]
    
    print(f"=== Style RAG 200题并发评测 ===")
    print(f"生成模型: {GEN_MODEL}")
    print(f"评分模型: {JUDGE_MODEL}")
    print(f"RAG 库: {rag.count()} 条")
    print(f"并发数: {NUM_WORKERS}")
    print(f"测试用例: {len(TEST_CASES_200)} 个\n")
    
    # 构建任务队列
    queue = asyncio.Queue()
    for idx, (user_msg, topic) in enumerate(TEST_CASES_200):
        queue.put_nowait((idx, user_msg, topic))
    
    # RAG 查询封装（同步调用）
    rag_data = {'query': rag.query}
    
    results_list = []
    lock = asyncio.Lock()
    
    start_time = time.time()
    
    # 启动 workers
    workers = [asyncio.create_task(worker(queue, rag_data, soul, results_list, lock)) for _ in range(NUM_WORKERS)]
    await asyncio.gather(*workers)
    
    elapsed = time.time() - start_time
    
    # 按 id 排序
    results_list.sort(key=lambda r: r["id"])
    
    # ============================================================
    # 汇总统计
    # ============================================================
    print(f"\n{'='*60}")
    print(f"=== 最终汇总 ({len(results_list)} 道题, 耗时 {elapsed/60:.1f} 分钟) ===\n")
    
    valid = [r for r in results_list if r["scores"].get("winner") not in ("error", None)]
    a_wins = sum(1 for r in valid if r["scores"]["winner"] == "A")
    b_wins = sum(1 for r in valid if r["scores"]["winner"] == "B")
    ties = sum(1 for r in valid if r["scores"]["winner"] == "tie")
    errors = len(results_list) - len(valid)
    
    print(f"有效评分: {len(valid)}/{len(results_list)}")
    print(f"总体胜负: RAG赢 {a_wins} | NoRAG赢 {b_wins} | 平局 {ties} | 错误 {errors}")
    
    if valid:
        print(f"\n平均分对比:")
        for dim in ["oral", "personal", "natural"]:
            a_avg = sum(r["scores"].get(f"A_{dim}", 0) for r in valid) / len(valid)
            b_avg = sum(r["scores"].get(f"B_{dim}", 0) for r in valid) / len(valid)
            print(f"  {dim}: RAG {a_avg:.2f} vs NoRAG {b_avg:.2f} (差值: {a_avg-b_avg:+.2f})")
    
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
        for dim in ["oral", "personal", "natural"]:
            a_avg = sum(r["scores"].get(f"A_{dim}", 0) for r in tr) / len(tr)
            b_avg = sum(r["scores"].get(f"B_{dim}", 0) for r in tr) / len(tr)
            dims_avg[dim] = {"rag": round(a_avg, 2), "norag": round(b_avg, 2)}
        
        topic_stats[topic] = {
            "total": len(tr), "rag_wins": ta, "norag_wins": tb, "ties": tt,
            "rag_win_rate": round(ta / len(tr) * 100, 1),
            "dims": dims_avg,
        }
        print(f"  {topic}: RAG赢{ta} NoRAG赢{tb} 平{tt} (共{len(tr)}) → RAG胜率 {ta/len(tr)*100:.0f}%")
    
    # 回复长度统计
    rag_lens = [len(r["reply_with_rag"]) for r in valid if not r["reply_with_rag"].startswith("[")]
    norag_lens = [len(r["reply_without_rag"]) for r in valid if not r["reply_without_rag"].startswith("[")]
    
    print(f"\n--- 回复长度统计 ---")
    if rag_lens:
        print(f"  RAG 平均长度: {sum(rag_lens)/len(rag_lens):.0f} 字")
    if norag_lens:
        print(f"  NoRAG 平均长度: {sum(norag_lens)/len(norag_lens):.0f} 字")
    
    # 保存完整结果
    final_data = {
        "model": f"{GEN_MODEL} + {JUDGE_MODEL}",
        "rag_count": rag.count(),
        "test_count": len(TEST_CASES_200),
        "completed": len(results_list),
        "elapsed_minutes": round(elapsed / 60, 1),
        "summary": {
            "rag_wins": a_wins,
            "norag_wins": b_wins,
            "ties": ties,
            "errors": errors,
            "rag_win_rate": round(a_wins / max(len(valid), 1) * 100, 1),
        },
        "topic_stats": topic_stats,
        "avg_reply_len": {
            "rag": round(sum(rag_lens) / max(len(rag_lens), 1)),
            "norag": round(sum(norag_lens) / max(len(norag_lens), 1)),
        },
        "details": results_list,
    }
    
    if valid:
        final_data["summary"]["avg_scores"] = {}
        for dim in ["oral", "personal", "natural"]:
            final_data["summary"]["avg_scores"][f"rag_{dim}"] = round(
                sum(r["scores"].get(f"A_{dim}", 0) for r in valid) / len(valid), 2)
            final_data["summary"]["avg_scores"][f"norag_{dim}"] = round(
                sum(r["scores"].get(f"B_{dim}", 0) for r in valid) / len(valid), 2)
    
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 完整结果已保存到 {RESULTS_FILE}")
    print(f"总耗时: {elapsed/60:.1f} 分钟")


if __name__ == "__main__":
    asyncio.run(main())
