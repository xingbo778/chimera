#!/usr/bin/env python3
"""对比 v1 和 v2 RAG 的评测结果"""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# 设置中文字体
plt.style.use('seaborn-v0_8-whitegrid')
plt.rcParams['font.family'] = 'Noto Sans CJK SC'
plt.rcParams['axes.unicode_minus'] = False

with open('/home/ubuntu/chimera/eval_200_results_v1.json') as f:
    v1 = json.load(f)
with open('/home/ubuntu/chimera/eval_200_results_v2.json') as f:
    v2 = json.load(f)

print("=" * 60)
print("=== Style RAG v1 vs v2 对比分析 ===")
print("=" * 60)

# 总体对比
print(f"\n--- 总体胜负 ---")
print(f"{'指标':<15} {'v1(旧RAG 406条)':<20} {'v2(新RAG 1320条)':<20}")
print(f"{'RAG胜':<15} {v1['summary']['rag_wins']:<20} {v2['summary']['rag_wins']:<20}")
print(f"{'NoRAG胜':<15} {v1['summary']['norag_wins']:<20} {v2['summary']['norag_wins']:<20}")
print(f"{'平局':<15} {v1['summary']['ties']:<20} {v2['summary']['ties']:<20}")
print(f"{'RAG胜率':<15} {v1['summary']['rag_win_rate']}%{'':<17} {v2['summary']['rag_win_rate']}%")

# 平均分对比
print(f"\n--- 平均分对比 ---")
for dim in ['oral', 'personal', 'natural']:
    v1_rag = v1['summary']['avg_scores'][f'rag_{dim}']
    v1_norag = v1['summary']['avg_scores'][f'norag_{dim}']
    v2_rag = v2['summary']['avg_scores'][f'rag_{dim}']
    v2_norag = v2['summary']['avg_scores'][f'norag_{dim}']
    print(f"  {dim}:")
    print(f"    v1: RAG {v1_rag:.2f} vs NoRAG {v1_norag:.2f} (差值 {v1_rag-v1_norag:+.2f})")
    print(f"    v2: RAG {v2_rag:.2f} vs NoRAG {v2_norag:.2f} (差值 {v2_rag-v2_norag:+.2f})")

# 回复长度对比
print(f"\n--- 回复长度 ---")
print(f"  v1: RAG {v1['avg_reply_len']['rag']}字 vs NoRAG {v1['avg_reply_len']['norag']}字")
print(f"  v2: RAG {v2['avg_reply_len']['rag']}字 vs NoRAG {v2['avg_reply_len']['norag']}字")

# 按话题对比
print(f"\n--- 按话题RAG胜率对比 ---")
topics = ["穿搭", "工作", "美食", "娱乐", "宠物", "学习", "旅行", "颜值", "日常", "健身"]
print(f"{'话题':<8} {'v1 RAG胜率':<15} {'v2 RAG胜率':<15} {'变化':<10}")
for topic in topics:
    v1_rate = v1['topic_stats'].get(topic, {}).get('rag_win_rate', 0)
    v2_rate = v2['topic_stats'].get(topic, {}).get('rag_win_rate', 0)
    change = v2_rate - v1_rate
    arrow = "↑" if change > 0 else ("↓" if change < 0 else "→")
    print(f"  {topic:<6} {v1_rate:>5.0f}%{'':<9} {v2_rate:>5.0f}%{'':<9} {change:+.0f}% {arrow}")

# 分析具体回复差异
print(f"\n--- 回复内容分析 ---")
v1_details = {r['id']: r for r in v1['details']}
v2_details = {r['id']: r for r in v2['details']}

# 找出v1赢但v2输的题
v1_win_v2_lose = []
v2_win_v1_lose = []
for idx in v1_details:
    if idx in v2_details:
        v1_w = v1_details[idx]['scores'].get('winner', '')
        v2_w = v2_details[idx]['scores'].get('winner', '')
        if v1_w == 'A' and v2_w == 'B':
            v1_win_v2_lose.append(idx)
        elif v1_w == 'B' and v2_w == 'A':
            v2_win_v1_lose.append(idx)

print(f"  v1赢→v2输: {len(v1_win_v2_lose)} 道")
print(f"  v1输→v2赢: {len(v2_win_v1_lose)} 道")

# 展示几个典型案例
print(f"\n--- v1赢→v2输 的典型案例 ---")
for idx in v1_win_v2_lose[:5]:
    r1 = v1_details[idx]
    r2 = v2_details[idx]
    print(f"\n  #{idx} [{r1['topic']}] {r1['user_msg'][:40]}")
    print(f"    v1 RAG回复: {r1['reply_with_rag'][:80]}")
    print(f"    v2 RAG回复: {r2['reply_with_rag'][:80]}")
    print(f"    v1 NoRAG:   {r1['reply_without_rag'][:80]}")

print(f"\n--- v1输→v2赢 的典型案例 ---")
for idx in v2_win_v1_lose[:5]:
    r1 = v1_details[idx]
    r2 = v2_details[idx]
    print(f"\n  #{idx} [{r1['topic']}] {r1['user_msg'][:40]}")
    print(f"    v1 RAG回复: {r1['reply_with_rag'][:80]}")
    print(f"    v2 RAG回复: {r2['reply_with_rag'][:80]}")

# ============================================================
# 生成对比图表
# ============================================================

# 图1: v1 vs v2 RAG胜率对比（按话题）
fig, ax = plt.subplots(figsize=(12, 6))
x = np.arange(len(topics))
width = 0.35
v1_rates = [v1['topic_stats'].get(t, {}).get('rag_win_rate', 0) for t in topics]
v2_rates = [v2['topic_stats'].get(t, {}).get('rag_win_rate', 0) for t in topics]

bars1 = ax.bar(x - width/2, v1_rates, width, label='v1 (旧RAG 406条)', color='#4ECDC4', alpha=0.8)
bars2 = ax.bar(x + width/2, v2_rates, width, label='v2 (新RAG 1320条)', color='#FF6B6B', alpha=0.8)

ax.set_ylabel('RAG 胜率 (%)')
ax.set_title('Style RAG v1 vs v2 各话题 RAG 胜率对比')
ax.set_xticks(x)
ax.set_xticklabels(topics)
ax.legend()
ax.axhline(y=50, color='gray', linestyle='--', alpha=0.5)

for bar in bars1:
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1,
            f'{bar.get_height():.0f}%', ha='center', va='bottom', fontsize=8)
for bar in bars2:
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1,
            f'{bar.get_height():.0f}%', ha='center', va='bottom', fontsize=8)

plt.tight_layout()
plt.savefig('/home/ubuntu/chimera/compare_v1v2_winrate.png', dpi=150)
plt.close()

# 图2: 三维度分数对比
fig, axes = plt.subplots(1, 3, figsize=(15, 5))
dims = ['oral', 'personal', 'natural']
dim_names = ['口语自然度', '个性独特性', '对话流畅度']

for i, (dim, name) in enumerate(zip(dims, dim_names)):
    ax = axes[i]
    categories = ['v1 RAG', 'v1 NoRAG', 'v2 RAG', 'v2 NoRAG']
    values = [
        v1['summary']['avg_scores'][f'rag_{dim}'],
        v1['summary']['avg_scores'][f'norag_{dim}'],
        v2['summary']['avg_scores'][f'rag_{dim}'],
        v2['summary']['avg_scores'][f'norag_{dim}'],
    ]
    colors = ['#4ECDC4', '#95E1D3', '#FF6B6B', '#FFA07A']
    bars = ax.bar(categories, values, color=colors, alpha=0.8)
    ax.set_title(name)
    ax.set_ylim(6, 10)
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.05,
                f'{val:.2f}', ha='center', va='bottom', fontsize=9)

plt.suptitle('Style RAG v1 vs v2 三维度分数对比', fontsize=14, y=1.02)
plt.tight_layout()
plt.savefig('/home/ubuntu/chimera/compare_v1v2_scores.png', dpi=150)
plt.close()

# 图3: 回复长度分布对比
fig, ax = plt.subplots(figsize=(10, 6))

v1_rag_lens = [len(r['reply_with_rag']) for r in v1['details'] if not r['reply_with_rag'].startswith('[')]
v1_norag_lens = [len(r['reply_without_rag']) for r in v1['details'] if not r['reply_without_rag'].startswith('[')]
v2_rag_lens = [len(r['reply_with_rag']) for r in v2['details'] if not r['reply_with_rag'].startswith('[')]
v2_norag_lens = [len(r['reply_without_rag']) for r in v2['details'] if not r['reply_without_rag'].startswith('[')]

data = [v1_rag_lens, v2_rag_lens, v1_norag_lens, v2_norag_lens]
labels = ['v1 RAG', 'v2 RAG', 'v1 NoRAG', 'v2 NoRAG']
colors = ['#4ECDC4', '#FF6B6B', '#95E1D3', '#FFA07A']

bp = ax.boxplot(data, labels=labels, patch_artist=True)
for patch, color in zip(bp['boxes'], colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.7)

ax.set_ylabel('回复长度 (字)')
ax.set_title('v1 vs v2 回复长度分布对比')
plt.tight_layout()
plt.savefig('/home/ubuntu/chimera/compare_v1v2_length.png', dpi=150)
plt.close()

print("\n图表已保存:")
print("  compare_v1v2_winrate.png")
print("  compare_v1v2_scores.png")
print("  compare_v1v2_length.png")
