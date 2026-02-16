"""100道题基线评测可视化分析"""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# 字体设置
plt.style.use('seaborn-v0_8-whitegrid')
plt.rcParams['font.family'] = 'Noto Sans CJK SC'
plt.rcParams['axes.unicode_minus'] = False

with open('/home/ubuntu/chimera/eval_baseline_100_results.json') as f:
    data = json.load(f)

results = data['details']
summary = data['summary']

# ── 图1: 雷达图 ──
dims = ['真实感', '反AI味', '氛围感', '人设一致', '互动吸引力']
dim_keys = ['真实感(Realness)', '反AI味(Anti-AI)', '氛围感(Vibe)', '人设一致(Persona)', '互动吸引力(Engagement)']

def avg_dim(results, score_key, dim_key):
    vals = [r[score_key].get(dim_key, {}).get('score', 0) or 0 for r in results]
    return np.mean(vals) * 10

d_vals = [avg_dim(results, 'scores_distilled', k) for k in dim_keys]
f_vals = [avg_dim(results, 'scores_fewshot5', k) for k in dim_keys]
b_vals = [avg_dim(results, 'scores_baseline', k) for k in dim_keys]

angles = np.linspace(0, 2*np.pi, len(dims), endpoint=False).tolist()
angles += angles[:1]

fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
for vals, label, color in [(d_vals, '蒸馏版', '#FF6B6B'), (f_vals, '5shot版', '#4ECDC4'), (b_vals, '基线', '#95A5A6')]:
    v = vals + vals[:1]
    ax.plot(angles, v, 'o-', linewidth=2, label=label, color=color)
    ax.fill(angles, v, alpha=0.1, color=color)

ax.set_xticks(angles[:-1])
ax.set_xticklabels(dims, fontsize=12)
ax.set_ylim(0, 10)
ax.set_title('100道题基线评测 — 五维度雷达图', fontsize=16, fontweight='bold', pad=20)
ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1), fontsize=12)
plt.tight_layout()
plt.savefig('/home/ubuntu/chimera/baseline100_radar.png', dpi=150, bbox_inches='tight')
plt.close()

# ── 图2: 按话题胜率 ──
topics = ['穿搭', '工作', '美食', '娱乐', '宠物', '学习', '旅行', '颜值', '日常', '健身']
d_wins = []
f_wins = []
for topic in topics:
    t_res = [r for r in results if r['topic'] == topic]
    d_w = sum(1 for r in t_res if r['scores_distilled']['weighted_total'] > r['scores_baseline']['weighted_total'])
    f_w = sum(1 for r in t_res if r['scores_fewshot5']['weighted_total'] > r['scores_baseline']['weighted_total'])
    d_wins.append(d_w / len(t_res) * 100 if t_res else 0)
    f_wins.append(f_w / len(t_res) * 100 if t_res else 0)

fig, ax = plt.subplots(figsize=(12, 6))
x = np.arange(len(topics))
w = 0.35
bars1 = ax.bar(x - w/2, d_wins, w, label='蒸馏 vs 基线 胜率', color='#FF6B6B', alpha=0.85)
bars2 = ax.bar(x + w/2, f_wins, w, label='5shot vs 基线 胜率', color='#4ECDC4', alpha=0.85)
ax.axhline(y=50, color='gray', linestyle='--', alpha=0.5, label='50%基准线')
ax.set_xticks(x)
ax.set_xticklabels(topics, fontsize=12)
ax.set_ylabel('胜率 (%)', fontsize=12)
ax.set_title('100道题基线评测 — 按话题胜率对比', fontsize=16, fontweight='bold')
ax.legend(fontsize=11)
ax.set_ylim(0, 110)
for bar in bars1:
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1, f'{bar.get_height():.0f}%', ha='center', va='bottom', fontsize=9)
for bar in bars2:
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1, f'{bar.get_height():.0f}%', ha='center', va='bottom', fontsize=9)
plt.tight_layout()
plt.savefig('/home/ubuntu/chimera/baseline100_topic_winrate.png', dpi=150, bbox_inches='tight')
plt.close()

# ── 图3: 加权分分布 ──
fig, axes = plt.subplots(1, 3, figsize=(15, 5))
for ax, key, label, color in [
    (axes[0], 'scores_distilled', '蒸馏版', '#FF6B6B'),
    (axes[1], 'scores_fewshot5', '5shot版', '#4ECDC4'),
    (axes[2], 'scores_baseline', '基线', '#95A5A6'),
]:
    scores = [r[key]['weighted_total'] for r in results]
    ax.hist(scores, bins=15, color=color, alpha=0.7, edgecolor='white')
    ax.axvline(np.mean(scores), color='red', linestyle='--', label=f'均值 {np.mean(scores):.1f}')
    ax.set_title(f'{label} 加权分分布', fontsize=13, fontweight='bold')
    ax.set_xlabel('加权分', fontsize=11)
    ax.set_ylabel('题数', fontsize=11)
    ax.legend(fontsize=10)
    ax.set_xlim(3, 10)
plt.suptitle('100道题基线评测 — 加权分分布', fontsize=16, fontweight='bold', y=1.02)
plt.tight_layout()
plt.savefig('/home/ubuntu/chimera/baseline100_score_dist.png', dpi=150, bbox_inches='tight')
plt.close()

# ── 图4: 维度差值热力图 ──
fig, ax = plt.subplots(figsize=(10, 8))
heatmap_data = []
for topic in topics:
    t_res = [r for r in results if r['topic'] == topic]
    row = []
    for dk in dim_keys:
        d_s = np.mean([r['scores_distilled'].get(dk, {}).get('score', 0) or 0 for r in t_res]) * 10
        b_s = np.mean([r['scores_baseline'].get(dk, {}).get('score', 0) or 0 for r in t_res]) * 10
        row.append(d_s - b_s)
    heatmap_data.append(row)

heatmap_data = np.array(heatmap_data)
im = ax.imshow(heatmap_data, cmap='RdYlGn', aspect='auto', vmin=-3, vmax=3)
ax.set_xticks(range(len(dims)))
ax.set_xticklabels(dims, fontsize=11, rotation=30, ha='right')
ax.set_yticks(range(len(topics)))
ax.set_yticklabels(topics, fontsize=11)
for i in range(len(topics)):
    for j in range(len(dims)):
        ax.text(j, i, f'{heatmap_data[i,j]:+.1f}', ha='center', va='center', fontsize=10, fontweight='bold')
plt.colorbar(im, label='蒸馏 - 基线 分差')
ax.set_title('100道题基线评测 — 蒸馏vs基线 各话题×维度分差', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig('/home/ubuntu/chimera/baseline100_heatmap.png', dpi=150, bbox_inches='tight')
plt.close()

print("4张图表生成完成")
print(f"总体: 蒸馏 {summary['weighted_avg']['distilled']} | 5shot {summary['weighted_avg']['fewshot5']} | 基线 {summary['weighted_avg']['baseline']}")
print(f"蒸馏vs基线: {summary['distilled_vs_baseline']}")
print(f"5shot vs基线: {summary['fewshot5_vs_baseline']}")
print(f"蒸馏vs5shot: {summary['distilled_vs_fewshot5']}")
