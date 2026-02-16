"""
Style RAG 200题评测结果可视化
"""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

# 设置中文字体
plt.style.use('seaborn-v0_8-whitegrid')
plt.rcParams['font.family'] = 'Noto Sans CJK SC'
plt.rcParams['axes.unicode_minus'] = False

# 加载数据
with open('eval_200_results.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

details = data['details']
topic_stats = data['topic_stats']
summary = data['summary']

topics = ["穿搭", "工作", "美食", "娱乐", "宠物", "学习", "旅行", "颜值", "日常", "健身"]

# ============================================================
# 图1: 总体胜负饼图 + 按话题胜率柱状图
# ============================================================
fig, axes = plt.subplots(1, 2, figsize=(16, 7))

# 左: 总体胜负饼图
labels = ['RAG 胜', 'NoRAG 胜', '平局']
sizes = [summary['rag_wins'], summary['norag_wins'], summary['ties']]
colors = ['#4CAF50', '#FF5722', '#9E9E9E']
explode = (0.05, 0.05, 0)
wedges, texts, autotexts = axes[0].pie(sizes, explode=explode, labels=labels, colors=colors,
    autopct='%1.1f%%', startangle=90, textprops={'fontsize': 14})
for t in autotexts:
    t.set_fontsize(13)
    t.set_fontweight('bold')
axes[0].set_title(f'总体胜负分布 (N=200)\nRAG {summary["rag_wins"]} vs NoRAG {summary["norag_wins"]}',
                   fontsize=16, fontweight='bold')

# 右: 按话题RAG胜率柱状图
rag_rates = [topic_stats[t]['rag_win_rate'] for t in topics]
norag_rates = [topic_stats[t]['norag_wins'] / topic_stats[t]['total'] * 100 for t in topics]
tie_rates = [topic_stats[t]['ties'] / topic_stats[t]['total'] * 100 for t in topics]

x = np.arange(len(topics))
width = 0.6

bars_rag = axes[1].bar(x, rag_rates, width, color='#4CAF50', alpha=0.85, label='RAG 胜率')
bars_norag = axes[1].bar(x, [-r for r in norag_rates], width, color='#FF5722', alpha=0.85, label='NoRAG 胜率')

axes[1].axhline(y=0, color='black', linewidth=0.8)
axes[1].axhline(y=50, color='gray', linewidth=0.5, linestyle='--', alpha=0.5)
axes[1].axhline(y=-50, color='gray', linewidth=0.5, linestyle='--', alpha=0.5)

for i, (r, bar) in enumerate(zip(rag_rates, bars_rag)):
    axes[1].text(bar.get_x() + bar.get_width()/2., r + 1, f'{r:.0f}%',
                ha='center', va='bottom', fontsize=10, fontweight='bold', color='#2E7D32')
for i, (r, bar) in enumerate(zip(norag_rates, bars_norag)):
    axes[1].text(bar.get_x() + bar.get_width()/2., -r - 1, f'{r:.0f}%',
                ha='center', va='top', fontsize=10, fontweight='bold', color='#BF360C')

axes[1].set_xticks(x)
axes[1].set_xticklabels(topics, fontsize=12)
axes[1].set_ylabel('胜率 (%)', fontsize=13)
axes[1].set_title('各话题 RAG vs NoRAG 胜率对比', fontsize=16, fontweight='bold')
axes[1].legend(fontsize=12, loc='upper right')
axes[1].set_ylim(-90, 90)

plt.tight_layout()
plt.savefig('eval_chart1_winrate.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 图1: eval_chart1_winrate.png")

# ============================================================
# 图2: 三维度分数对比雷达图 + 柱状图
# ============================================================
fig, axes = plt.subplots(1, 2, figsize=(16, 7))

# 左: 各话题三维度RAG vs NoRAG对比（grouped bar）
dims = ['oral', 'personal', 'natural']
dim_labels = ['口语化', '个性化', '自然度']

# 总体平均分
avg_scores = summary['avg_scores']
x = np.arange(len(dim_labels))
width = 0.35

bars1 = axes[0].bar(x - width/2, [avg_scores[f'rag_{d}'] for d in dims], width,
                     label='有 RAG', color='#4CAF50', alpha=0.85)
bars2 = axes[0].bar(x + width/2, [avg_scores[f'norag_{d}'] for d in dims], width,
                     label='无 RAG', color='#FF5722', alpha=0.85)

for bar in bars1:
    axes[0].text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.02,
                f'{bar.get_height():.2f}', ha='center', va='bottom', fontsize=12, fontweight='bold')
for bar in bars2:
    axes[0].text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.02,
                f'{bar.get_height():.2f}', ha='center', va='bottom', fontsize=12, fontweight='bold')

axes[0].set_xticks(x)
axes[0].set_xticklabels(dim_labels, fontsize=13)
axes[0].set_ylabel('平均分 (1-10)', fontsize=13)
axes[0].set_title('总体三维度平均分对比', fontsize=16, fontweight='bold')
axes[0].legend(fontsize=12)
axes[0].set_ylim(6, 10)

# 右: 各话题个性化分数对比（这是RAG最有优势的维度）
rag_personal = [topic_stats[t]['dims']['personal']['rag'] for t in topics]
norag_personal = [topic_stats[t]['dims']['personal']['norag'] for t in topics]
diff = [r - n for r, n in zip(rag_personal, norag_personal)]

x = np.arange(len(topics))
colors_diff = ['#4CAF50' if d > 0 else '#FF5722' for d in diff]
bars = axes[1].bar(x, diff, 0.6, color=colors_diff, alpha=0.85)

for i, (d, bar) in enumerate(zip(diff, bars)):
    axes[1].text(bar.get_x() + bar.get_width()/2.,
                d + (0.02 if d >= 0 else -0.02),
                f'{d:+.2f}', ha='center',
                va='bottom' if d >= 0 else 'top',
                fontsize=10, fontweight='bold')

axes[1].axhline(y=0, color='black', linewidth=0.8)
axes[1].set_xticks(x)
axes[1].set_xticklabels(topics, fontsize=11)
axes[1].set_ylabel('RAG - NoRAG 分差', fontsize=13)
axes[1].set_title('各话题「个性化」维度分差\n(正值=RAG更好)', fontsize=16, fontweight='bold')

plt.tight_layout()
plt.savefig('eval_chart2_scores.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 图2: eval_chart2_scores.png")

# ============================================================
# 图3: 回复长度分布 + 长度与胜负关系
# ============================================================
fig, axes = plt.subplots(1, 2, figsize=(16, 7))

# 左: 回复长度分布
rag_lens = [len(r['reply_with_rag']) for r in details if not r['reply_with_rag'].startswith('[')]
norag_lens = [len(r['reply_without_rag']) for r in details if not r['reply_without_rag'].startswith('[')]

axes[0].hist(rag_lens, bins=30, alpha=0.7, color='#4CAF50', label=f'RAG (均值{np.mean(rag_lens):.0f}字)')
axes[0].hist(norag_lens, bins=30, alpha=0.7, color='#FF5722', label=f'NoRAG (均值{np.mean(norag_lens):.0f}字)')
axes[0].axvline(np.mean(rag_lens), color='#2E7D32', linestyle='--', linewidth=2)
axes[0].axvline(np.mean(norag_lens), color='#BF360C', linestyle='--', linewidth=2)
axes[0].set_xlabel('回复长度 (字符数)', fontsize=13)
axes[0].set_ylabel('频次', fontsize=13)
axes[0].set_title('回复长度分布对比', fontsize=16, fontweight='bold')
axes[0].legend(fontsize=12)

# 右: 各话题平均回复长度
rag_topic_lens = {}
norag_topic_lens = {}
for r in details:
    t = r['topic']
    if not r['reply_with_rag'].startswith('['):
        rag_topic_lens.setdefault(t, []).append(len(r['reply_with_rag']))
    if not r['reply_without_rag'].startswith('['):
        norag_topic_lens.setdefault(t, []).append(len(r['reply_without_rag']))

x = np.arange(len(topics))
width = 0.35
rag_avg_lens = [np.mean(rag_topic_lens.get(t, [0])) for t in topics]
norag_avg_lens = [np.mean(norag_topic_lens.get(t, [0])) for t in topics]

axes[1].bar(x - width/2, rag_avg_lens, width, color='#4CAF50', alpha=0.85, label='RAG')
axes[1].bar(x + width/2, norag_avg_lens, width, color='#FF5722', alpha=0.85, label='NoRAG')
axes[1].set_xticks(x)
axes[1].set_xticklabels(topics, fontsize=11)
axes[1].set_ylabel('平均回复长度 (字符)', fontsize=13)
axes[1].set_title('各话题平均回复长度对比', fontsize=16, fontweight='bold')
axes[1].legend(fontsize=12)

plt.tight_layout()
plt.savefig('eval_chart3_length.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 图3: eval_chart3_length.png")

# ============================================================
# 图4: 热力图 - 各话题 x 各维度的 RAG 优势
# ============================================================
fig, ax = plt.subplots(figsize=(10, 8))

heatmap_data = np.zeros((len(topics), 3))
for i, t in enumerate(topics):
    for j, dim in enumerate(dims):
        rag_val = topic_stats[t]['dims'][dim]['rag']
        norag_val = topic_stats[t]['dims'][dim]['norag']
        heatmap_data[i, j] = rag_val - norag_val

im = ax.imshow(heatmap_data, cmap='RdYlGn', aspect='auto', vmin=-1.5, vmax=1.5)

ax.set_xticks(np.arange(3))
ax.set_xticklabels(dim_labels, fontsize=13)
ax.set_yticks(np.arange(len(topics)))
ax.set_yticklabels(topics, fontsize=13)

# 添加数值标注
for i in range(len(topics)):
    for j in range(3):
        val = heatmap_data[i, j]
        color = 'white' if abs(val) > 0.8 else 'black'
        ax.text(j, i, f'{val:+.2f}', ha='center', va='center', fontsize=11, fontweight='bold', color=color)

ax.set_title('RAG 优势热力图\n(正值=RAG更好, 负值=NoRAG更好)', fontsize=16, fontweight='bold')
cbar = plt.colorbar(im, ax=ax, shrink=0.8)
cbar.set_label('RAG - NoRAG 分差', fontsize=12)

plt.tight_layout()
plt.savefig('eval_chart4_heatmap.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 图4: eval_chart4_heatmap.png")

# ============================================================
# 输出一些典型案例用于报告
# ============================================================
print("\n=== RAG 赢得最明显的案例 ===")
rag_best = sorted([r for r in details if r['scores'].get('winner') == 'A'],
                   key=lambda r: sum(r['scores'].get(f'A_{d}', 0) for d in dims) - sum(r['scores'].get(f'B_{d}', 0) for d in dims),
                   reverse=True)[:5]
for r in rag_best:
    a_total = sum(r['scores'].get(f'A_{d}', 0) for d in dims)
    b_total = sum(r['scores'].get(f'B_{d}', 0) for d in dims)
    print(f"\n[{r['topic']}] {r['user_msg']}")
    print(f"  RAG({a_total}) vs NoRAG({b_total}), 差值: +{a_total-b_total}")
    print(f"  RAG: {r['reply_with_rag'][:100]}...")
    print(f"  NoR: {r['reply_without_rag'][:100]}...")

print("\n=== NoRAG 赢得最明显的案例 ===")
norag_best = sorted([r for r in details if r['scores'].get('winner') == 'B'],
                     key=lambda r: sum(r['scores'].get(f'B_{d}', 0) for d in dims) - sum(r['scores'].get(f'A_{d}', 0) for d in dims),
                     reverse=True)[:5]
for r in norag_best:
    a_total = sum(r['scores'].get(f'A_{d}', 0) for d in dims)
    b_total = sum(r['scores'].get(f'B_{d}', 0) for d in dims)
    print(f"\n[{r['topic']}] {r['user_msg']}")
    print(f"  RAG({a_total}) vs NoRAG({b_total}), 差值: {a_total-b_total}")
    print(f"  RAG: {r['reply_with_rag'][:100]}...")
    print(f"  NoR: {r['reply_without_rag'][:100]}...")

print("\n✅ 所有图表已生成")
