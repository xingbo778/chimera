#!/usr/bin/env python3
"""用 style_rag_v2 重建RAG，带性别标签"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, '/home/ubuntu/chimera')

NEW_RAG_DIR = Path("/home/ubuntu/chimera/chroma_style_db_v2")
CLEANED_DATA = Path("/home/ubuntu/chimera/new_rag_data/cleaned_pairs.json")

def main():
    # 清除旧v2数据库
    if NEW_RAG_DIR.exists():
        shutil.rmtree(NEW_RAG_DIR)
    
    # 加载清洗后的数据
    with open(CLEANED_DATA) as f:
        pairs = json.load(f)
    
    print(f"加载 {len(pairs)} 条数据")
    
    # 去重
    seen = set()
    unique = []
    for p in pairs:
        key = f"{p['user_msg']}||{p['assistant_msg']}"
        if key not in seen:
            seen.add(key)
            unique.append(p)
    print(f"去重后: {len(unique)}")
    
    # 用v2版本导入
    from style_rag_v2 import StyleRAG
    rag = StyleRAG(persist_dir=str(NEW_RAG_DIR))
    
    # 转换为 (user_msg, assistant_msg, gender) 格式
    examples = [(p["user_msg"], p["assistant_msg"], p.get("assistant_gender", "unknown")) for p in unique]
    
    added = rag._add_examples_with_gender(examples)
    print(f"添加: {added}")
    print(f"总量: {rag.count()}")
    print(f"性别分布: {rag.count_by_gender()}")
    
    # 测试
    print("\n=== 测试查询 ===")
    tests = [
        ("你在干嘛", None),
        ("你在干嘛", "female"),
        ("你在干嘛", "male"),
        ("想你了", "female"),
        ("想你了", "male"),
        ("晚安", "female"),
        ("晚安", "male"),
        ("我生气了", "female"),
        ("我生气了", "male"),
        ("哈哈哈哈", None),
        ("今天好累啊", "female"),
        ("今天好累啊", "male"),
    ]
    
    for query, gender in tests:
        results = rag.query(query, n_results=3, gender=gender)
        label = f"[{gender or 'all'}]"
        print(f"\n{label} \"{query}\":")
        for r in results:
            print(f"  [{r['gender']}] {r['user'][:30]} -> {r['assistant'][:50]}")

if __name__ == "__main__":
    main()
