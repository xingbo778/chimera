import json

with open('eval_results.json') as f:
    d = json.load(f)

print('=== 所有话题回复长度和质量检查 ===\n')
for r in d['details']:
    s = r['scores']
    rag_reply = r['reply_with_rag']
    norag_reply = r['reply_without_rag']
    truncated = 'Draft' in rag_reply or len(rag_reply) < 10
    
    winner = s['winner']
    marker = "✅ RAG赢" if winner == 'A' else ("❌ NoRAG赢" if winner == 'B' else "🟰 平局")
    
    print(f"{r['topic']:6s} | {marker}")
    print(f"  RAG({len(rag_reply):3d}字): {rag_reply[:60]}{'...' if len(rag_reply)>60 else ''}")
    print(f"  NoR({len(norag_reply):3d}字): {norag_reply[:60]}{'...' if len(norag_reply)>60 else ''}")
    print(f"  评分: RAG({s['A_oral']},{s['A_personal']},{s['A_natural']}) vs NoRAG({s['B_oral']},{s['B_personal']},{s['B_natural']})")
    
    if truncated:
        print(f"  >>> RAG回复被截断或异常!")
    
    # 检查 RAG 样本相关度
    examples = r.get('rag_examples', [])
    if examples:
        print(f"  RAG样本({len(examples)}条):")
        for ex in examples[:3]:
            print(f"    U: {ex['u'][:30]}  A: {ex['a'][:30]}")
    print()
