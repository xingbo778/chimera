"""
导出200道题完整回复对比文档
"""
import json

with open('eval_200_results.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

details = sorted(data['details'], key=lambda r: r['id'])
summary = data['summary']

lines = []
lines.append("# Style RAG vs NoRAG — 200 道题完整回复对比\n")
lines.append(f"**总体结果**：RAG 胜 {summary['rag_wins']} | NoRAG 胜 {summary['norag_wins']} | 平局 {summary['ties']}\n")
lines.append("---\n")

# 按话题分组
topics_order = ["穿搭", "工作", "美食", "娱乐", "宠物", "学习", "旅行", "颜值", "日常", "健身"]
topic_groups = {}
for r in details:
    t = r['topic']
    topic_groups.setdefault(t, []).append(r)

for topic in topics_order:
    items = topic_groups.get(topic, [])
    if not items:
        continue
    
    # 统计该话题
    rag_w = sum(1 for r in items if r['scores'].get('winner') == 'A')
    norag_w = sum(1 for r in items if r['scores'].get('winner') == 'B')
    ties = sum(1 for r in items if r['scores'].get('winner') == 'tie')
    
    lines.append(f"\n## {topic}（RAG 胜 {rag_w} | NoRAG 胜 {norag_w} | 平局 {ties}）\n")
    
    for r in items:
        idx = r['id']
        user_msg = r['user_msg']
        reply_rag = r.get('reply_with_rag', '[无]')
        reply_norag = r.get('reply_without_rag', '[无]')
        scores = r.get('scores', {})
        
        winner = scores.get('winner', '?')
        if winner == 'A':
            winner_label = '**RAG 胜**'
        elif winner == 'B':
            winner_label = '**NoRAG 胜**'
        elif winner == 'tie':
            winner_label = '**平局**'
        else:
            winner_label = '**错误**'
        
        a_oral = scores.get('A_oral', '?')
        a_personal = scores.get('A_personal', '?')
        a_natural = scores.get('A_natural', '?')
        b_oral = scores.get('B_oral', '?')
        b_personal = scores.get('B_personal', '?')
        b_natural = scores.get('B_natural', '?')
        
        lines.append(f"### #{idx+1}. {user_msg}\n")
        lines.append(f"**结果**：{winner_label} — RAG({a_oral},{a_personal},{a_natural}) vs NoRAG({b_oral},{b_personal},{b_natural})\n")
        lines.append(f"**有 RAG 的回复**：\n")
        lines.append(f"> {reply_rag}\n")
        lines.append(f"**无 RAG 的回复**：\n")
        lines.append(f"> {reply_norag}\n")
        lines.append("---\n")

output = '\n'.join(lines)

with open('200题完整回复对比.md', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"✅ 已导出 {len(details)} 道题完整回复到 200题完整回复对比.md")
print(f"文件大小: {len(output)} 字符")
