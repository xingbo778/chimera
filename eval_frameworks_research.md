# 评测框架调研关键发现

## G-Eval 核心方法论（EMNLP 2023, 2200+ citations）

G-Eval 三步流程：
1. **Evaluation Step Generation**: 把自然语言标准转化为结构化评估步骤（CoT）
2. **Judging**: 用这些步骤让LLM评估输出
3. **Scoring**: 用token log-probabilities加权得到最终分数

关键改进点：
- **CoT**: 先让LLM生成评估步骤，再按步骤打分（比直接打分更准）
- **Token probability weighting**: 用概率加权而非直接取数字（减少偏差）
- **Scoring Rubrics**: 为每个分数档定义具体标准（比"1-10"更精确）

## G-Eval 解决的4个LLM评分器常见问题

1. **Inconsistent Scoring**: CoT让评分更稳定
2. **Lack of Fine-Grained Judgment**: 评估步骤让判断更细致
3. **Verbosity Bias**: LLM倾向给长回复更高分 ← 我们的核心问题
4. **Narcissistic Bias**: LLM倾向给自己风格的回复更高分

## DeepEval GEval 用法

```python
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCaseParams

correctness_metric = GEval(
    name="Correctness",
    criteria="...",
    evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
)
```

支持自定义 evaluation_steps 和 scoring rubric。

## CharacterBench 11维度（AAAI 2025）

Dense: Human-likeness, Engagement, Morality Robustness, Morality Stability
Sparse: Memory Consistency, Attribute Consistency, Behavior Consistency, 
        Boundary Consistency, Fact Accuracy, Emotion Self-regulation, 
        Empathetic Responsiveness

## 对我们项目的启示

1. **用 G-Eval 的 CoT + Rubric 方法**：不只给1-10分，而是定义每档的具体标准
2. **用 Scoring Rubric 对抗 Verbosity Bias**：明确说"短回复如果自然也可以得高分"
3. **可以直接用 DeepEval 框架**：省去自己写评分器的麻烦
4. **CharacterBench 的 Human-likeness 维度**可以直接借鉴
5. **Pairwise comparison**（Chatbot Arena方式）比绝对评分更稳定
