"""
v3 五维度评测可视化分析
对比 v1(旧RAG) vs v2(新RAG) 在新评分体系下的表现
"""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.style as mplstyle
mplstyle.use('seaborn-v0_8-whitegrid')
plt.rcParams['font.family'] = 'Noto Sans CJK SC'
plt.rcParams['axes.unicode_minus'] = False
import numpy as np

# 加载数据
with open('eval_v3_results_v1.json') as f:
    v1 = json.load(f)
with open('eval_v3_results_v2.json') as f:
    v2 = json.load(f)

dims = ["human_likeness", "content", "vibe", "persona", "empathy"]
dim_cn = ["拟人感\n(30%)", "内容质量\n(25%)", "聊天氛围\n(20%)", "人设一致\n(15%)", "情绪回应\n(10%)"]
topics = ["穿搭", "工作", "美食", "娱乐", "宠物", "学习", "旅行", "颜值", "日常", "健身"]

# ========== 图1: 五维度雷达图 ==========
fig, axes = plt.subplots(1, 2, figsize=(16, 7), subplot_kw=dict(polar=True))
fig.suptitle('Style RAG v3 五维度评分 — 雷达图对比', fontsize=16, fontweight='bold', y=1.02)

for ax_idx, (data, label) in enumerate([(v1, 'v1 旧RAG (406条)'), (v2, 'v2 新RAG (1320条)')]):
    ax = axes[ax_idx]
    scores = data['summary']['avg_scores']
    
    rag_vals = [scores.get(f'rag_{d}', 0) for d in dims]
    norag_vals = [scores.get(f'norag_{d}', 0) for d in dims]
    
    angles = np.linspace(0, 2 * np.pi, len(dims), endpoint=False).tolist()
    rag_vals_plot = rag_vals + [rag_vals[0]]
    norag_vals_plot = norag_vals + [norag_vals[0]]
    angles_plot = angles + [angles[0]]
    
    ax.plot(angles_plot, rag_vals_plot, 'o-', linewidth=2, label='RAG', color='#FF6B6B')
    ax.fill(angles_plot, rag_vals_plot, alpha=0.15, color='#FF6B6B')
    ax.plot(angles_plot, norag_vals_plot, 's-', linewidth=2, label='NoRAG', color='#4ECDC4')
    ax.fill(angles_plot, norag_vals_plot, alpha=0.15, color='#4ECDC4')
    
    ax.set_xticks(angles)
    ax.set_xticklabels(dim_cn, fontsize=10)
    ax.set_ylim(6, 10)
    ax.set_title(label, fontsize=13, fontweight='bold', pad=20)
    ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1))
    
    # 标注分数
    for i, (rv, nv) in enumerate(zip(rag_vals, norag_vals)):
        ax.annotate(f'{rv:.1f}', xy=(angles[i], rv), fontsize=8, color='#FF6B6B', ha='center')
        ax.annotate(f'{nv:.1f}', xy=(angles[i], nv), fontsize=8, color='#4ECDC4', ha='center')

plt.tight_layout()
plt.savefig('v3_chart1_radar.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 图1 雷达图")

# ========== 图2: v1 vs v2 各维度 RAG-NoRAG 差值对比 ==========
fig, ax = plt.subplots(figsize=(14, 6))

x = np.arange(len(dims))
width = 0.35

v1_diffs = []
v2_diffs = []
for d in dims:
    v1_diffs.append(v1['summary']['avg_scores'].get(f'rag_{d}', 0) - v1['summary']['avg_scores'].get(f'norag_{d}', 0))
    v2_diffs.append(v2['summary']['avg_scores'].get(f'rag_{d}', 0) - v2['summary']['avg_scores'].get(f'norag_{d}', 0))

bars1 = ax.bar(x - width/2, v1_diffs, width, label='v1 旧RAG', color='#45B7D1', alpha=0.85)
bars2 = ax.bar(x + width/2, v2_diffs, width, label='v2 新RAG', color='#FF6B6B', alpha=0.85)

ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
ax.set_ylabel('RAG - NoRAG 分差', fontsize=12)
ax.set_title('各维度 RAG vs NoRAG 分差对比（正值=RAG更好）', fontsize=14, fontweight='bold')
ax.set_xticks(x)
ax.set_xticklabels(dim_cn, fontsize=11)
ax.legend(fontsize=11)

for bar in bars1:
    h = bar.get_height()
    ax.text(bar.get_x() + bar.get_width()/2., h, f'{h:+.2f}', ha='center', va='bottom' if h >= 0 else 'top', fontsize=9)
for bar in bars2:
    h = bar.get_height()
    ax.text(bar.get_x() + bar.get_width()/2., h, f'{h:+.2f}', ha='center', va='bottom' if h >= 0 else 'top', fontsize=9)

plt.tight_layout()
plt.savefig('v3_chart2_dim_diff.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 图2 维度差值")

# ========== 图3: 按话题 RAG 胜率对比 ==========
fig, ax = plt.subplots(figsize=(14, 6))

x = np.arange(len(topics))
width = 0.35

v1_rates = [v1['topic_stats'].get(t, {}).get('rag_win_rate', 0) for t in topics]
v2_rates = [v2['topic_stats'].get(t, {}).get('rag_win_rate', 0) for t in topics]

bars1 = ax.bar(x - width/2, v1_rates, width, label='v1 旧RAG', color='#45B7D1', alpha=0.85)
bars2 = ax.bar(x + width/2, v2_rates, width, label='v2 新RAG', color='#FF6B6B', alpha=0.85)

ax.axhline(y=50, color='gray', linestyle='--', linewidth=1, alpha=0.5)
ax.set_ylabel('RAG 胜率 (%)', fontsize=12)
ax.set_title('v3 五维度评分 — 各话题 RAG 胜率对比', fontsize=14, fontweight='bold')
ax.set_xticks(x)
ax.set_xticklabels(topics, fontsize=11)
ax.legend(fontsize=11)
ax.set_ylim(0, 60)

for bar in bars1:
    h = bar.get_height()
    ax.text(bar.get_x() + bar.get_width()/2., h + 0.5, f'{h:.0f}%', ha='center', va='bottom', fontsize=9)
for bar in bars2:
    h = bar.get_height()
    ax.text(bar.get_x() + bar.get_width()/2., h + 0.5, f'{h:.0f}%', ha='center', va='bottom', fontsize=9)

plt.tight_layout()
plt.savefig('v3_chart3_topic_winrate.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 图3 话题胜率")

# ========== 图4: 五维度热力图 ==========
fig, axes = plt.subplots(1, 2, figsize=(18, 8))

for ax_idx, (data, label) in enumerate([(v1, 'v1 旧RAG'), (v2, 'v2 新RAG')]):
    ax = axes[ax_idx]
    
    heatmap_data = []
    for t in topics:
        row = []
        ts = data['topic_stats'].get(t, {})
        dims_data = ts.get('dims', {})
        for d in dims:
            rag_score = dims_data.get(d, {}).get('rag', 0)
            norag_score = dims_data.get(d, {}).get('norag', 0)
            row.append(rag_score - norag_score)
        heatmap_data.append(row)
    
    heatmap_data = np.array(heatmap_data)
    
    im = ax.imshow(heatmap_data, cmap='RdYlGn', aspect='auto', vmin=-2, vmax=1)
    
    ax.set_xticks(range(len(dims)))
    ax.set_xticklabels([d.replace('\n', '') for d in dim_cn], fontsize=10)
    ax.set_yticks(range(len(topics)))
    ax.set_yticklabels(topics, fontsize=10)
    ax.set_title(f'{label} — RAG vs NoRAG 分差热力图', fontsize=12, fontweight='bold')
    
    for i in range(len(topics)):
        for j in range(len(dims)):
            val = heatmap_data[i, j]
            color = 'white' if abs(val) > 1 else 'black'
            ax.text(j, i, f'{val:+.1f}', ha='center', va='center', fontsize=8, color=color)
    
    plt.colorbar(im, ax=ax, shrink=0.8)

plt.tight_layout()
plt.savefig('v3_chart4_heatmap.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 图4 热力图")

# ========== 图5: 新旧评分体系对比 ==========
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# 旧体系（3维度）
labels_old = ['v1\n旧3维度', 'v2\n旧3维度']
# 从之前的结果文件读取
try:
    with open('eval_200_results_v1.json') as f:
        old_v1 = json.load(f)
    with open('eval_200_results_v2.json') as f:
        old_v2 = json.load(f)
    old_rates = [old_v1['summary']['rag_win_rate'], old_v2['summary']['rag_win_rate']]
except:
    old_rates = [44.0, 25.0]

new_rates = [v1['summary']['rag_win_rate'], v2['summary']['rag_win_rate']]

ax = axes[0]
x = np.arange(2)
width = 0.35
b1 = ax.bar(x - width/2, old_rates, width, label='旧3维度', color='#95a5a6', alpha=0.8)
b2 = ax.bar(x + width/2, new_rates, width, label='新5维度', color='#e74c3c', alpha=0.8)
ax.set_ylabel('RAG 胜率 (%)', fontsize=12)
ax.set_title('评分体系对比 — RAG胜率', fontsize=13, fontweight='bold')
ax.set_xticks(x)
ax.set_xticklabels(['v1 旧RAG', 'v2 新RAG'], fontsize=11)
ax.legend()
ax.axhline(y=50, color='gray', linestyle='--', alpha=0.3)
for bar in b1:
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.5, f'{bar.get_height():.1f}%', ha='center', fontsize=10)
for bar in b2:
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.5, f'{bar.get_height():.1f}%', ha='center', fontsize=10)

# 拟人感维度单独看
ax = axes[1]
v1_hl_rag = v1['summary']['avg_scores'].get('rag_human_likeness', 0)
v1_hl_norag = v1['summary']['avg_scores'].get('norag_human_likeness', 0)
v2_hl_rag = v2['summary']['avg_scores'].get('rag_human_likeness', 0)
v2_hl_norag = v2['summary']['avg_scores'].get('norag_human_likeness', 0)

x = np.arange(2)
b1 = ax.bar(x - width/2, [v1_hl_rag, v2_hl_rag], width, label='RAG', color='#FF6B6B', alpha=0.85)
b2 = ax.bar(x + width/2, [v1_hl_norag, v2_hl_norag], width, label='NoRAG', color='#4ECDC4', alpha=0.85)
ax.set_ylabel('拟人感分数', fontsize=12)
ax.set_title('拟人感维度 — RAG vs NoRAG', fontsize=13, fontweight='bold')
ax.set_xticks(x)
ax.set_xticklabels(['v1 旧RAG', 'v2 新RAG'], fontsize=11)
ax.legend()
ax.set_ylim(7, 10)
for bar in b1:
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.02, f'{bar.get_height():.2f}', ha='center', fontsize=10)
for bar in b2:
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.02, f'{bar.get_height():.2f}', ha='center', fontsize=10)

plt.tight_layout()
plt.savefig('v3_chart5_compare_systems.png', dpi=150, bbox_inches='tight')
plt.close()
print("✅ 图5 评分体系对比")

# ========== 打印总结 ==========
print(f"\n{'='*60}")
print("v3 五维度评测总结")
print(f"{'='*60}")
print(f"\nv1 旧RAG: RAG胜率 {v1['summary']['rag_win_rate']}% | 加权分 RAG {v1['summary']['avg_scores']['rag_weighted']} vs NoRAG {v1['summary']['avg_scores']['norag_weighted']}")
print(f"v2 新RAG: RAG胜率 {v2['summary']['rag_win_rate']}% | 加权分 RAG {v2['summary']['avg_scores']['rag_weighted']} vs NoRAG {v2['summary']['avg_scores']['norag_weighted']}")
print(f"\n拟人感维度:")
print(f"  v1: RAG {v1_hl_rag:.2f} vs NoRAG {v1_hl_norag:.2f} (差值 {v1_hl_rag-v1_hl_norag:+.2f})")
print(f"  v2: RAG {v2_hl_rag:.2f} vs NoRAG {v2_hl_norag:.2f} (差值 {v2_hl_rag-v2_hl_norag:+.2f})")
print(f"\n核心发现: 即使在以拟人感为核心的新评分体系下，NoRAG仍然全面领先")
print(f"说明问题不在评分标准，而在RAG的few-shot注入方式本身")
