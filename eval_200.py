"""
Style RAG 200 题大规模评测
===========================
- 200 道题覆盖 10 个话题领域
- 断点续传：已完成的题目自动跳过
- 详细日志输出
- 最终生成 eval_200_results.json
"""
import sys, os, json, time, re, traceback
sys.path.insert(0, os.path.dirname(__file__))

from openai import OpenAI
from test_cases_200 import TEST_CASES_200

# Compass API - Gemini 3 Flash Preview (用于回复生成)
compass_client = OpenAI(
    api_key='9a3d58cc61234d927b3d5d0223a1277b106ca171d9a9608a6ff298d1544562a1',
    base_url='https://forum-stan-towers-quest.trycloudflare.com/compass-api/v1'
)
GEN_MODEL = "gemini-3-flash-preview"

# Manus 代理 - gemini-2.5-flash (用于评分)
judge_client = OpenAI()
JUDGE_MODEL = "gemini-2.5-flash"

RESULTS_FILE = "eval_200_results.json"
MAX_RETRIES = 3
RATE_LIMIT_SLEEP = 1.5  # 每次 API 调用间隔


def load_agent_prompts():
    soul_path = os.path.join(os.path.dirname(__file__), "soul.md")
    soul = ""
    if os.path.exists(soul_path):
        with open(soul_path, "r") as f:
            soul = f.read()[:500]
    return soul


def call_gen(messages, max_tokens=2000, temperature=0.8):
    """用 Compass Gemini 3 生成回复，带重试"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = compass_client.chat.completions.create(
                model=GEN_MODEL, messages=messages,
                max_tokens=max_tokens, temperature=temperature,
            )
            content = resp.choices[0].message.content
            if content and len(content.strip()) > 5:
                return content.strip()
            # 回复太短，重试
            time.sleep(RATE_LIMIT_SLEEP)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RATE_LIMIT_SLEEP * (attempt + 1))
            else:
                return f"[GEN ERROR: {e}]"
    return "[GEN ERROR: empty after retries]"


def call_judge(system, user, max_tokens=100, temperature=0.2):
    """用 Manus gemini-2.5-flash 做评分，带重试"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = judge_client.chat.completions.create(
                model=JUDGE_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=max_tokens, temperature=temperature,
            )
            return resp.choices[0].message.content
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RATE_LIMIT_SLEEP * (attempt + 1))
            else:
                return f"[JUDGE ERROR: {e}]"


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


def load_checkpoint():
    """加载已有结果用于断点续传"""
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("details", [])
        except:
            pass
    return []


def save_checkpoint(results, rag_count):
    """保存当前进度"""
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "model": f"{GEN_MODEL} + {JUDGE_MODEL}",
            "rag_count": rag_count,
            "test_count": len(TEST_CASES_200),
            "completed": len(results),
            "details": results,
        }, f, ensure_ascii=False, indent=2)


def evaluate_one(idx, user_msg, topic, rag, soul):
    """评测单道题"""
    result = {
        "id": idx,
        "topic": topic,
        "user_msg": user_msg,
    }

    # 1. RAG 检索
    rag_examples = rag.query(user_msg, n_results=5)
    few_shot_messages = rag.to_few_shot_messages(rag_examples)
    result["rag_count"] = len(rag_examples)
    result["rag_examples"] = [
        {"u": e.get("user", "")[:50], "a": e.get("assistant", "")[:50]}
        for e in rag_examples[:3]
    ]

    # 2. 有 RAG 的回复
    system_prompt = soul + "\n\n你是一个说话随意、口语化的女生。"
    messages_with_rag = [{"role": "system", "content": system_prompt}]
    messages_with_rag.extend(few_shot_messages)
    messages_with_rag.append({"role": "user", "content": user_msg})

    reply_with_rag = call_gen(messages_with_rag)
    result["reply_with_rag"] = reply_with_rag
    time.sleep(RATE_LIMIT_SLEEP)

    # 3. 无 RAG 的回复
    messages_without_rag = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]
    reply_without_rag = call_gen(messages_without_rag)
    result["reply_without_rag"] = reply_without_rag
    time.sleep(RATE_LIMIT_SLEEP)

    # 4. 三维度评分
    dims = [
        ("oral", "oral/colloquial naturalness (like real casual chat between friends, NOT like AI assistant)"),
        ("personal", "personality uniqueness (has distinctive speaking style, NOT generic or template-like)"),
        ("natural", "conversation fluency (smooth and natural flow, NOT stiff or over-structured)"),
    ]

    scores = {}
    all_ok = True
    for dim_key, dim_desc in dims:
        # 截取回复用于评分（避免过长）
        a_text = reply_with_rag[:150] if not reply_with_rag.startswith("[") else reply_with_rag
        b_text = reply_without_rag[:150] if not reply_without_rag.startswith("[") else reply_without_rag

        prompt = (
            f'User message: "{user_msg}"\n'
            f'Response A: "{a_text}"\n'
            f'Response B: "{b_text}"\n\n'
            f'Rate both responses on {dim_desc}, scale 1-10.\n'
            f'Output ONLY valid JSON: {{"a":<int>,"b":<int>}}'
        )
        raw = call_judge("You are a fair judge. Output only JSON, no explanation.", prompt, max_tokens=50)
        parsed = parse_json_response(raw)
        if parsed and "a" in parsed and "b" in parsed:
            try:
                scores[f"A_{dim_key}"] = int(parsed["a"])
                scores[f"B_{dim_key}"] = int(parsed["b"])
            except:
                all_ok = False
                scores[f"raw_{dim_key}"] = str(raw)[:100]
        else:
            all_ok = False
            scores[f"raw_{dim_key}"] = str(raw)[:100]
        time.sleep(0.5)

    if all_ok:
        a_total = scores.get("A_oral", 0) + scores.get("A_personal", 0) + scores.get("A_natural", 0)
        b_total = scores.get("B_oral", 0) + scores.get("B_personal", 0) + scores.get("B_natural", 0)
        scores["winner"] = "A" if a_total > b_total else ("B" if b_total > a_total else "tie")
    else:
        scores["winner"] = "error"

    result["scores"] = scores
    return result


def main():
    from style_rag import StyleRAG

    rag = StyleRAG(persist_dir='style_rag_db', few_shot_path='final_few_shot.md')
    soul = load_agent_prompts()

    print(f"=== Style RAG 200题评测 ===")
    print(f"生成模型: {GEN_MODEL}")
    print(f"评分模型: {JUDGE_MODEL}")
    print(f"RAG 库: {rag.count()} 条")
    print(f"测试用例: {len(TEST_CASES_200)} 个\n")

    # 断点续传
    existing = load_checkpoint()
    completed_ids = {r["id"] for r in existing if r.get("scores", {}).get("winner", "error") != "error"}
    results = [r for r in existing if r["id"] in completed_ids]
    print(f"已完成: {len(completed_ids)} / {len(TEST_CASES_200)}")

    start_time = time.time()
    errors = 0

    for idx, (user_msg, topic) in enumerate(TEST_CASES_200):
        if idx in completed_ids:
            continue

        elapsed = time.time() - start_time
        remaining = len(TEST_CASES_200) - len(completed_ids) - (idx - len(completed_ids))
        if len(completed_ids) > 0 or idx > 0:
            rate = elapsed / max(idx - len(completed_ids) + 1, 1)
            eta = rate * remaining
            eta_str = f"ETA: {eta/60:.0f}min"
        else:
            eta_str = "ETA: calculating..."

        print(f"\n[{idx+1}/{len(TEST_CASES_200)}] {topic}: {user_msg[:30]}... ({eta_str})")

        try:
            result = evaluate_one(idx, user_msg, topic, rag, soul)
            results.append(result)
            completed_ids.add(idx)

            w = result["scores"].get("winner", "?")
            a_scores = f"A({result['scores'].get('A_oral',0)},{result['scores'].get('A_personal',0)},{result['scores'].get('A_natural',0)})"
            b_scores = f"B({result['scores'].get('B_oral',0)},{result['scores'].get('B_personal',0)},{result['scores'].get('B_natural',0)})"
            print(f"  → {a_scores} vs {b_scores} → Winner: {'RAG' if w=='A' else 'NoRAG' if w=='B' else w}")
            print(f"  RAG: {result['reply_with_rag'][:80]}...")
            print(f"  NoR: {result['reply_without_rag'][:80]}...")

            # 每 10 题保存一次
            if len(results) % 10 == 0:
                save_checkpoint(results, rag.count())
                print(f"  💾 Checkpoint saved ({len(results)} results)")

        except Exception as e:
            errors += 1
            print(f"  ❌ Error: {e}")
            traceback.print_exc()
            if errors > 10:
                print("Too many errors, stopping.")
                break
            time.sleep(3)

    # 最终保存
    save_checkpoint(results, rag.count())

    # ============================================================
    # 汇总统计
    # ============================================================
    print(f"\n\n{'='*60}")
    print(f"=== 最终汇总 ({len(results)} 道有效题) ===\n")

    # 总体统计
    a_wins = sum(1 for r in results if r["scores"].get("winner") == "A")
    b_wins = sum(1 for r in results if r["scores"].get("winner") == "B")
    ties = sum(1 for r in results if r["scores"].get("winner") == "tie")
    errors_count = sum(1 for r in results if r["scores"].get("winner") == "error")

    print(f"总体胜负: RAG赢 {a_wins} | NoRAG赢 {b_wins} | 平局 {ties} | 错误 {errors_count}")

    # 各维度平均分
    valid = [r for r in results if r["scores"].get("winner") not in ("error", None)]
    if valid:
        metrics = {}
        for dim in ["oral", "personal", "natural"]:
            a_avg = sum(r["scores"].get(f"A_{dim}", 0) for r in valid) / len(valid)
            b_avg = sum(r["scores"].get(f"B_{dim}", 0) for r in valid) / len(valid)
            metrics[dim] = (a_avg, b_avg)
            print(f"  {dim}: RAG {a_avg:.2f} vs NoRAG {b_avg:.2f} (差值: {a_avg-b_avg:+.2f})")

    # 按话题统计
    print(f"\n--- 按话题统计 ---")
    topics = ["穿搭", "工作", "美食", "娱乐", "宠物", "学习", "旅行", "颜值", "日常", "健身"]
    topic_stats = {}
    for topic in topics:
        topic_results = [r for r in valid if r["topic"] == topic]
        if not topic_results:
            continue
        ta = sum(1 for r in topic_results if r["scores"].get("winner") == "A")
        tb = sum(1 for r in topic_results if r["scores"].get("winner") == "B")
        tt = sum(1 for r in topic_results if r["scores"].get("winner") == "tie")
        total = len(topic_results)
        
        # 各维度平均
        dims_avg = {}
        for dim in ["oral", "personal", "natural"]:
            a_avg = sum(r["scores"].get(f"A_{dim}", 0) for r in topic_results) / total
            b_avg = sum(r["scores"].get(f"B_{dim}", 0) for r in topic_results) / total
            dims_avg[dim] = (a_avg, b_avg)
        
        topic_stats[topic] = {
            "total": total, "rag_wins": ta, "norag_wins": tb, "ties": tt,
            "rag_win_rate": ta / total * 100,
            "dims": dims_avg,
        }
        print(f"  {topic}: RAG赢{ta} NoRAG赢{tb} 平{tt} (共{total}) → RAG胜率 {ta/total*100:.0f}%")

    # 回复长度统计
    rag_lens = [len(r["reply_with_rag"]) for r in valid if not r["reply_with_rag"].startswith("[")]
    norag_lens = [len(r["reply_without_rag"]) for r in valid if not r["reply_without_rag"].startswith("[")]
    if rag_lens and norag_lens:
        print(f"\n--- 回复长度统计 ---")
        print(f"  RAG 平均长度: {sum(rag_lens)/len(rag_lens):.0f} 字")
        print(f"  NoRAG 平均长度: {sum(norag_lens)/len(norag_lens):.0f} 字")

    # 保存最终结果（含统计）
    final_data = {
        "model": f"{GEN_MODEL} + {JUDGE_MODEL}",
        "rag_count": rag.count(),
        "test_count": len(TEST_CASES_200),
        "completed": len(results),
        "summary": {
            "rag_wins": a_wins,
            "norag_wins": b_wins,
            "ties": ties,
            "errors": errors_count,
            "rag_win_rate": round(a_wins / max(len(valid), 1) * 100, 1),
        },
        "topic_stats": topic_stats,
        "avg_reply_len": {
            "rag": round(sum(rag_lens) / max(len(rag_lens), 1)),
            "norag": round(sum(norag_lens) / max(len(norag_lens), 1)),
        },
        "details": results,
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
    total_time = time.time() - start_time
    print(f"总耗时: {total_time/60:.1f} 分钟")


if __name__ == "__main__":
    main()
