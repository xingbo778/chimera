# SOUL + Memory 重设计笔记

## 现有问题诊断

从Telegram截图看，小悦的回复有以下"AI味"问题：
1. 每句话都带波浪号（～）和感叹号（！）——过度热情
2. 每次都在追问用户——像客服不像朋友
3. 回复太长、太完整——真人聊天经常是碎片化的
4. 没有"自己的事"在做——总是100%关注用户
5. 情绪太平——永远开心积极，没有真实的情绪波动
6. 语言太书面——"颜色特别丰富"、"千变万化"不像口语

## OpenClaw的设计启发

### Memory架构（两层）
- `memory/YYYY-MM-DD.md`：每日日志（append-only），每次session启动读今天+昨天
- `MEMORY.md`：长期记忆（curated），决策/偏好/持久事实
- 核心理念："把LLM上下文当缓存，把磁盘记忆当真相源"
- compaction前自动flush：防止遗忘

### System Prompt架构
- Bootstrap注入：SOUL.md, IDENTITY.md, USER.md, MEMORY.md 每次对话都注入
- 但daily memory文件不自动注入，按需通过memory_search检索
- 保持compact，用固定section

### SOUL.md设计（来自soul.md项目）
- 核心理念：具体>笼统，矛盾>一致，真实观点>安全立场
- 结构：Who I Am / Worldview / Opinions / Interests / Tensions & Contradictions / Pet Peeves / Vocabulary
- 好的例子："我觉得大部分AI安全讨论都是自欺欺人" vs 坏的例子："我对AI有nuanced的看法"
- 关键：读完SOUL.md应该能预测这个人对新话题的反应

## 重设计方案

### 静态部分（SOUL.md）——不随时间变化
- 核心人格：内向但跟熟人能聊、对美敏感、有点焦虑
- 世界观和价值观：具体的、有争议性的观点
- 说话习惯：具体的语言模式（不是"自然口语化"这种空话）
- 矛盾和缺陷：让她不完美
- 讨厌的事情：具体的pet peeves

### 动态部分——随世界引擎变化
- 当前情绪（从世界事件计算）
- 当前活动和位置
- 最近的生活事件（从episodic memory）
- 跟用户的关系状态
- 今天的日记/总结

### Memory重设计
- 短期：当前session的聊天记录（context window内）
- 中期：每日日志（memory/YYYY-MM-DD.md），记录今天发生的事
- 长期：MEMORY.md，用户偏好、重要事件、关系里程碑
- 检索：对话时根据话题从daily logs中检索相关记忆
