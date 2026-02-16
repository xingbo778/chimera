"""
并发评测子任务脚本
用法: python3 eval_batch.py <input_json> <output_json>
input_json 包含: cases (测试用例列表), rag_examples (RAG样本), soul (系统提示词),
                  compass_api_key, compass_base_url, gen_model
"""
import sys, os, json, time, re

def main():
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    
    with open(input_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    cases = config['cases']
    rag_examples = config['rag_examples']
    soul = config['soul']
    compass_api_key = config['compass_api_key']
    compass_base_url = config['compass_base_url']
    gen_model = config['gen_model']
    
    from openai import OpenAI
    
    # Compass API for generation
    compass_client = OpenAI(api_key=compass_api_key, base_url=compass_base_url)
    # Manus API for judging
    judge_client = OpenAI()
    judge_model = "gemini-2.5-flash"
    
    # Simple vector similarity using sentence-transformers
    from sentence_transformers import SentenceTransformer
    import numpy as np
    
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    
    # Pre-compute embeddings for all RAG examples
    rag_user_texts = [ex['user'] for ex in rag_examples]
    rag_embeddings = model.encode(rag_user_texts, normalize_embeddings=True)
    
    def query_rag(user_msg, n_results=5):
        """Simple cosine similarity search"""
        q_emb = model.encode([user_msg], normalize_embeddings=True)
        scores = np.dot(rag_embeddings, q_emb.T).flatten()
        top_indices = np.argsort(scores)[-n_results:][::-1]
        return [rag_examples[i] for i in top_indices]
    
    def call_gen(messages, max_tokens=2000, temperature=0.8):
        for attempt in range(3):
            try:
                resp = compass_client.chat.completions.create(
                    model=gen_model, messages=messages,
                    max_tokens=max_tokens, temperature=temperature,
                )
                content = resp.choices[0].message.content
                if content and len(content.strip()) > 3:
                    return content.strip()
                time.sleep(1)
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                else:
                    return f"[GEN ERROR: {e}]"
        return "[GEN ERROR: empty]"
    
    def call_judge(system, user, max_tokens=80, temperature=0.2):
        for attempt in range(3):
            try:
                resp = judge_client.chat.completions.create(
                    model=judge_model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    max_tokens=max_tokens, temperature=temperature,
                )
                return resp.choices[0].message.content
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
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
                if text[i] == '{': depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try: return json.loads(text[brace_start:i+1])
                        except: break
        return None
    
    results = []
    system_prompt = soul + "\n\n你是一个说话随意、口语化的女生。"
    
    for case in cases:
        user_msg = case['user_msg']
        topic = case['topic']
        case_id = case['id']
        
        result = {"id": case_id, "topic": topic, "user_msg": user_msg}
        
        try:
            # RAG retrieval
            rag_hits = query_rag(user_msg, n_results=5)
            few_shot_msgs = []
            for ex in rag_hits:
                few_shot_msgs.append({"role": "user", "content": ex["user"]})
                few_shot_msgs.append({"role": "assistant", "content": ex["assistant"]})
            
            result["rag_examples"] = [{"u": e["user"][:50], "a": e["assistant"][:50]} for e in rag_hits[:3]]
            
            # With RAG
            msgs_rag = [{"role": "system", "content": system_prompt}] + few_shot_msgs + [{"role": "user", "content": user_msg}]
            reply_rag = call_gen(msgs_rag)
            result["reply_with_rag"] = reply_rag
            time.sleep(0.8)
            
            # Without RAG
            msgs_norag = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_msg}]
            reply_norag = call_gen(msgs_norag)
            result["reply_without_rag"] = reply_norag
            time.sleep(0.8)
            
            # Scoring - 3 dimensions
            dims = [
                ("oral", "oral/colloquial naturalness (like real casual chat, NOT like AI assistant)"),
                ("personal", "personality uniqueness (distinctive style, NOT generic)"),
                ("natural", "conversation fluency (smooth natural flow, NOT stiff or over-structured)"),
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
                raw = call_judge("Output only JSON", prompt, max_tokens=50)
                parsed = parse_json_response(raw)
                if parsed and "a" in parsed and "b" in parsed:
                    try:
                        scores[f"A_{dim_key}"] = int(parsed["a"])
                        scores[f"B_{dim_key}"] = int(parsed["b"])
                    except:
                        all_ok = False
                else:
                    all_ok = False
                time.sleep(0.3)
            
            if all_ok:
                a_total = scores.get("A_oral",0) + scores.get("A_personal",0) + scores.get("A_natural",0)
                b_total = scores.get("B_oral",0) + scores.get("B_personal",0) + scores.get("B_natural",0)
                scores["winner"] = "A" if a_total > b_total else ("B" if b_total > a_total else "tie")
            else:
                scores["winner"] = "error"
            
            result["scores"] = scores
            
        except Exception as e:
            result["scores"] = {"winner": "error", "error": str(e)}
            result["reply_with_rag"] = f"[ERROR: {e}]"
            result["reply_without_rag"] = f"[ERROR: {e}]"
        
        results.append(result)
        print(f"  [{case_id}] {topic}: {user_msg[:20]}... → {result['scores'].get('winner','?')}")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"Done: {len(results)} results saved to {output_path}")

if __name__ == "__main__":
    main()
