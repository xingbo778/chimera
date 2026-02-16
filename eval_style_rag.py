"""
Style RAG 评测脚本
=================
评测维度：
1. 检索质量：给定用户消息，RAG 返回的 few-shot 是否语义相关
2. 回复风格对比：同一个用户消息，有 RAG vs 无 RAG 的回复差异
3. 口语化程度评分：用 LLM 打分评估回复的自然度
"""
import sys, os, json, time, re
sys.path.insert(0, os.path.dirname(__file__))

from openai import OpenAI

# Compass API - Gemini 3 Flash Preview (用于回复生成)
compass_client = OpenAI(
    api_key='9a3d58cc61234d927b3d5d0223a1277b106ca171d9a9608a6ff298d1544562a1',
    base_url='https://forum-stan-towers-quest.trycloudflare.com/compass-api/v1'
)
GEN_MODEL = "gemini-3-flash-preview"

# Manus 代理 - gemini-2.5-flash (用于评分，稳定不截断)
judge_client = OpenAI()  # 自动读取环境变量
JUDGE_MODEL = "gemini-2.5-flash"

# ============================================================
# 测试用例：覆盖不同话题
# ============================================================
TEST_CASES = [
    # (用户消息, 话题标签)
    ("你觉得这件衣服好看吗", "穿搭"),
    ("今天上班好累啊不想动", "工作"),
    ("推荐个好吃的呗", "美食"),
    ("最近有什么好看的电影吗", "娱乐"),
    ("我想养只猫你觉得呢", "宠物"),
    ("明天要考试了紧张死了", "学习"),
    ("周末去哪玩比较好", "旅行"),
    ("这个发型适合我吗", "颜值"),
    ("好无聊啊有什么好玩的", "日常"),
    ("减肥太难了根本坚持不下去", "健身"),
]

# ============================================================
# SOUL 和 STYLE（从配置中读取）
# ============================================================
def load_agent_prompts():
    """加载 agent 的 SOUL 和 STYLE"""
    soul_path = os.path.join(os.path.dirname(__file__), "soul.md")
    style_path = os.path.join(os.path.dirname(__file__), "final_few_shot.md")
    
    soul = ""
    if os.path.exists(soul_path):
        with open(soul_path, "r") as f:
            soul = f.read()[:500]
    
    # 只取 STYLE 的前 2000 字作为基础 prompt
    style_header = ""
    if os.path.exists(style_path):
        with open(style_path, "r") as f:
            style_header = f.read()[:2000]
    
    return soul, style_header


def call_gen(system, user, messages=None, max_tokens=300, temperature=0.8):
    """用 Compass Gemini 3 生成回复"""
    try:
        if messages:
            return compass_client.chat.completions.create(
                model=GEN_MODEL, messages=messages,
                max_tokens=max_tokens, temperature=temperature,
            ).choices[0].message.content
        return compass_client.chat.completions.create(
            model=GEN_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens, temperature=temperature,
        ).choices[0].message.content
    except Exception as e:
        return f"[LLM ERROR: {e}]"


def call_judge(system, user, max_tokens=300, temperature=0.3):
    """用 Manus gemini-2.5-flash 做评分"""
    try:
        return judge_client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens, temperature=temperature,
        ).choices[0].message.content
    except Exception as e:
        return f"[LLM ERROR: {e}]"


def parse_json_response(text):
    """从 LLM 回复中提取 JSON，兼容 markdown 代码块"""
    if not text:
        return None
    
    # 1. 先尝试去掉 markdown 代码块
    md_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if md_match:
        text = md_match.group(1).strip()
    
    # 2. 尝试直接解析
    try:
        return json.loads(text)
    except:
        pass
    
    # 3. 尝试提取 {...} 部分（允许嵌套）
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


def main():
    from style_rag import StyleRAG
    
    rag = StyleRAG(persist_dir='style_rag_db', few_shot_path='final_few_shot.md')
    soul, style_header = load_agent_prompts()
    
    print(f"=== Style RAG 评测 (生成: {GEN_MODEL}, 评分: {JUDGE_MODEL}) ===")
    print(f"RAG 库: {rag.count()} 条")
    print(f"测试用例: {len(TEST_CASES)} 个\n")
    
    results = []
    
    for i, (user_msg, topic) in enumerate(TEST_CASES):
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(TEST_CASES)}] 话题: {topic}")
        print(f"  用户: {user_msg}")
        
        # --- 1. 检索质量 ---
        rag_examples = rag.query(user_msg, n_results=5)
        few_shot_messages = rag.to_few_shot_messages(rag_examples)
        
        print(f"\n  📚 RAG 检索到 {len(rag_examples)} 条:")
        for j, ex in enumerate(rag_examples):
            u = ex.get('user', '?')[:40]
            a = ex.get('assistant', '?')[:40]
            print(f"    {j+1}. U:{u} → A:{a}")
        
        # --- 2. 有 RAG 的回复 ---
        system_with_rag = soul + "\n\n你是一个说话随意、口语化的女生。"
        messages_with_rag = [{"role": "system", "content": system_with_rag}]
        messages_with_rag.extend(few_shot_messages)
        messages_with_rag.append({"role": "user", "content": user_msg})
        
        try:
            reply_with_rag = call_gen(None, None, messages=messages_with_rag, max_tokens=2000, temperature=0.8)
        except Exception as e:
            reply_with_rag = f"[ERROR: {e}]"
        
        print(f"\n  ✅ 有RAG回复: {reply_with_rag[:200]}")
        
        # --- 3. 无 RAG 的回复 ---
        system_without_rag = soul + "\n\n你是一个说话随意、口语化的女生。"
        messages_without_rag = [
            {"role": "system", "content": system_without_rag},
            {"role": "user", "content": user_msg},
        ]
        
        try:
            reply_without_rag = call_gen(None, None, messages=messages_without_rag, max_tokens=2000, temperature=0.8)
        except Exception as e:
            reply_without_rag = f"[ERROR: {e}]"
        
        print(f"  ❌ 无RAG回复: {reply_without_rag[:200]}")
        
        # --- 4. LLM 评分（分 3 次单独打分，避免输出截断）---
        def score_one_dimension(dim_name, dim_desc, reply_a, reply_b, user):
            """单维度打分，返回 (a_score, b_score)"""
            prompt = f'User:"{user}" A:"{reply_a[:80]}" B:"{reply_b[:80]}" Rate {dim_desc} 1-10. Output ONLY: {{"a":<int>,"b":<int>}}'
            raw = call_judge("Output only JSON, no markdown", prompt, max_tokens=50)
            parsed = parse_json_response(raw)
            if parsed and "a" in parsed and "b" in parsed:
                return int(parsed["a"]), int(parsed["b"]), raw
            return None, None, raw
        
        dims = [
            ("oral", "oral/colloquial naturalness (like real friend chat, not AI)"),
            ("personal", "personality uniqueness (distinctive style, not generic)"),
            ("natural", "fluency and naturalness (smooth tone, not stiff)"),
        ]
        
        scores = {}
        all_ok = True
        for dim_key, dim_desc in dims:
            a_s, b_s, raw = score_one_dimension(dim_key, dim_desc, reply_with_rag, reply_without_rag, user_msg)
            if a_s is not None:
                scores[f"A_{dim_key}"] = a_s
                scores[f"B_{dim_key}"] = b_s
            else:
                all_ok = False
                scores[f"raw_{dim_key}"] = raw[:100]
            time.sleep(0.5)
        
        if all_ok:
            a_total = scores.get("A_oral",0) + scores.get("A_personal",0) + scores.get("A_natural",0)
            b_total = scores.get("B_oral",0) + scores.get("B_personal",0) + scores.get("B_natural",0)
            scores["winner"] = "A" if a_total > b_total else ("B" if b_total > a_total else "tie")
        else:
            scores["error"] = "partial_parse_failed"
        
        print(f"\n  📊 评分: {json.dumps(scores, ensure_ascii=False)}")
        
        results.append({
            "topic": topic,
            "user_msg": user_msg,
            "rag_count": len(rag_examples),
            "reply_with_rag": reply_with_rag,
            "reply_without_rag": reply_without_rag,
            "scores": scores,
            "rag_examples": [{"u": e.get("user","")[:30], "a": e.get("assistant","")[:30]} for e in rag_examples[:3]],
        })
        
        time.sleep(1)  # 避免 rate limit
    
    # ============================================================
    # 汇总统计
    # ============================================================
    print(f"\n\n{'='*60}")
    print(f"=== 汇总统计 ===")
    
    a_wins = 0
    b_wins = 0
    ties = 0
    a_oral_total = 0
    b_oral_total = 0
    a_personal_total = 0
    b_personal_total = 0
    a_natural_total = 0
    b_natural_total = 0
    valid_count = 0
    
    for r in results:
        s = r["scores"]
        if "error" in s:
            continue
        valid_count += 1
        a_oral_total += s.get("A_oral", 0)
        b_oral_total += s.get("B_oral", 0)
        a_personal_total += s.get("A_personal", 0)
        b_personal_total += s.get("B_personal", 0)
        a_natural_total += s.get("A_natural", 0)
        b_natural_total += s.get("B_natural", 0)
        w = s.get("winner", "tie")
        if w == "A":
            a_wins += 1
        elif w == "B":
            b_wins += 1
        else:
            ties += 1
    
    if valid_count > 0:
        print(f"\n有效评分: {valid_count}/{len(results)}")
        print(f"\n胜负: 有RAG赢 {a_wins} | 无RAG赢 {b_wins} | 平局 {ties}")
        print(f"\n平均分对比:")
        print(f"  口语化: 有RAG {a_oral_total/valid_count:.1f} vs 无RAG {b_oral_total/valid_count:.1f}")
        print(f"  个性化: 有RAG {a_personal_total/valid_count:.1f} vs 无RAG {b_personal_total/valid_count:.1f}")
        print(f"  自然度: 有RAG {a_natural_total/valid_count:.1f} vs 无RAG {b_natural_total/valid_count:.1f}")
    else:
        print(f"\n⚠️ 没有有效评分！")
    
    # 保存完整结果
    with open("eval_results.json", "w", encoding="utf-8") as f:
        json.dump({
            "model": f"{GEN_MODEL} + {JUDGE_MODEL}",
            "rag_count": rag.count(),
            "test_count": len(TEST_CASES),
            "valid_scores": valid_count,
            "summary": {
                "a_wins": a_wins, "b_wins": b_wins, "ties": ties,
                "avg_a_oral": round(a_oral_total/max(valid_count,1), 1),
                "avg_b_oral": round(b_oral_total/max(valid_count,1), 1),
                "avg_a_personal": round(a_personal_total/max(valid_count,1), 1),
                "avg_b_personal": round(b_personal_total/max(valid_count,1), 1),
                "avg_a_natural": round(a_natural_total/max(valid_count,1), 1),
                "avg_b_natural": round(b_natural_total/max(valid_count,1), 1),
            },
            "details": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n完整结果已保存到 eval_results.json")


if __name__ == "__main__":
    main()
