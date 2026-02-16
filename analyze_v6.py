import json
from collections import defaultdict

with open('eval_v6_lite_100.json') as f:
    d = json.load(f)

topic_scores = defaultdict(lambda: {'v6': [], 'old': [], 'base': []})
dim_scores = defaultdict(lambda: {'v6': [], 'old': []})

for item in d['details']:
    t = item['topic']
    topic_scores[t]['v6'].append(item['scores_v6']['weighted_total'])
    topic_scores[t]['old'].append(item['scores_distilled_old']['weighted_total'])
    topic_scores[t]['base'].append(item['scores_baseline']['weighted_total'])
    
    for dim in ['realness', 'anti_ai', 'vibe', 'persona', 'engagement']:
        pass  # handled below
    
    for dim in ['realness', 'anti_ai', 'vibe', 'persona', 'engagement']:
        dim_scores[dim]['v6'].append(item['scores_v6'][dim])
        dim_scores[dim]['old'].append(item['scores_distilled_old'][dim])

print('=== 话题对比 ===')
header = f"{'话题':8s} {'v6':>8s} {'旧版':>8s} {'基线':>8s} {'v6-旧':>8s}"
print(header)
print('-' * 50)
weak_topics = {'学习', '颜值', '旅行', '健身'}
for t in sorted(topic_scores.keys()):
    v6 = sum(topic_scores[t]['v6'])/len(topic_scores[t]['v6'])
    old = sum(topic_scores[t]['old'])/len(topic_scores[t]['old'])
    base = sum(topic_scores[t]['base'])/len(topic_scores[t]['base'])
    diff = v6 - old
    marker = ' *弱势' if t in weak_topics else ''
    print(f"{t:8s} {v6:8.2f} {old:8.2f} {base:8.2f} {diff:+8.2f}{marker}")

print()
print('=== 维度对比 ===')
dim_names = {'realness': '真实感', 'anti_ai': '反AI味', 'vibe': '氛围感', 'persona': '人设一致', 'engagement': '互动吸引力'}
for dim, name in dim_names.items():
    v6 = sum(dim_scores[dim]['v6'])/len(dim_scores[dim]['v6'])
    old = sum(dim_scores[dim]['old'])/len(dim_scores[dim]['old'])
    diff = v6 - old
    print(f"{name:8s} v6={v6:.2f} old={old:.2f} diff={diff:+.2f}")

# 弱势话题汇总
weak_v6 = []
weak_old = []
strong_v6 = []
strong_old = []
for item in d['details']:
    if item['topic'] in weak_topics:
        weak_v6.append(item['scores_v6']['weighted_total'])
        weak_old.append(item['scores_distilled_old']['weighted_total'])
    else:
        strong_v6.append(item['scores_v6']['weighted_total'])
        strong_old.append(item['scores_distilled_old']['weighted_total'])

print(f"\n弱势话题(学习/颜值/旅行/健身): v6={sum(weak_v6)/len(weak_v6):.2f} old={sum(weak_old)/len(weak_old):.2f}")
print(f"强势话题(其他): v6={sum(strong_v6)/len(strong_v6):.2f} old={sum(strong_old)/len(strong_old):.2f}")
