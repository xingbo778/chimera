# 对话评测框架调研

## 1. CharacterBench (AAAI 2025) — 角色定制评测
**框架结构：6大方面 → 11个评测维度**

### Dense Dimensions (2 Aspects)
- **Believability**: Human-likeness, Engagement
- **Morality**: Morality Robustness, Morality Stability

### Sparse Dimensions (4 Aspects)
- **Memory**: Memory Consistency
- **Persona**: Attribute Consistency, Behavior Consistency
- **Knowledge**: Boundary Consistency, Fact Accuracy
- **Emotion**: Emotion Self-regulation, Empathetic Responsiveness

## 2. CharacterEval (ACL 2024) — 中文角色扮演评测
**4大维度 → 13个指标**
- 角色一致性
- 对话质量
- 人格特征
- 情感表达

## 3. DeepEval — 开源LLM评测框架
- 支持自定义G-Eval指标
- Conversational G-Eval 支持多轮对话评测
- 可以用自然语言定义评测标准

## 4. MT-Bench / Chatbot Arena (LMSYS)
- Pairwise comparison（两两对比）
- ELO rating system
- LLM-as-a-Judge methodology

## 5. Google AnthroBench — 拟人行为评测
- 专门评估LLM的拟人化行为
- 多轮对话中的拟人动态

## 关键发现
- CharacterBench 的 "Human-likeness" 和 "Engagement" 是最相关的维度
- DeepEval 的 G-Eval 框架可以直接复用，支持自定义评分标准
- Chatbot Arena 的 pairwise comparison 是业界标准方法
- CharacterEval 有中文benchmark和专门的reward model
