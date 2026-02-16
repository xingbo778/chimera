#!/usr/bin/env python3
"""验证新RAG素材库的质量"""
import sys
sys.path.insert(0, '/home/ubuntu/chimera')

from style_rag_v2 import StyleRAG

def main():
    rag = StyleRAG(persist_dir="/home/ubuntu/chimera/chroma_style_db_v2")
    
    print(f"=== 新 Style RAG v2 验证 ===")
    print(f"总样本数: {rag.count()}")
    print(f"性别分布: {rag.count_by_gender()}")
    
    # 测试不同场景的查询
    test_cases = [
        ("你在干嘛", None, "通用查询"),
        ("你在干嘛", "female", "女性风格"),
        ("你在干嘛", "male", "男性风格"),
        ("想你了", None, "通用"),
        ("想你了", "female", "女性撒娇"),
        ("想你了", "male", "男性表达"),
        ("今天好累", None, "通用"),
        ("今天好累", "female", "女性安慰"),
        ("今天好累", "male", "男性安慰"),
        ("哈哈哈哈太好笑了", None, "搞笑"),
        ("我生气了", "female", "女性生气"),
        ("我生气了", "male", "男性生气"),
        ("晚安", "female", "女性晚安"),
        ("晚安", "male", "男性晚安"),
        ("你觉得我胖吗", "female", "女性回应"),
        ("你觉得我胖吗", "male", "男性回应"),
    ]
    
    for query, gender, desc in test_cases:
        results = rag.query(query, n_results=3, gender=gender)
        gender_label = f"[{gender}]" if gender else "[all]"
        print(f"\n--- {desc} {gender_label}: \"{query}\" ---")
        for r in results:
            g = r.get('gender', '?')
            print(f"  [{g}] Q: {r['user'][:40]} -> A: {r['assistant'][:60]}")

if __name__ == "__main__":
    main()
