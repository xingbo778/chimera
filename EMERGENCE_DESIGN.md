# 浏览器原子操作涌现机制 — 设计文档

## 核心理念

Agent 不预先知道自己"能做什么"。它只有一组**浏览器原子操作**（截图、获取URL、提取文字等），当用户提出请求时，Agent 通过**规则 + LLM 双层意图识别**判断是否可以用这些原子操作组合完成，成功后将操作序列缓存为**已学会的技能**。

这就是"涌现"：技能不是硬编码的，而是从用户交互中自然产生的。

## 架构概览

```
用户消息 "截个图给我看看"
    │
    ▼
┌─────────────────────────────┐
│  route_skill() → "none"     │  现有技能路由无法处理
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│  attempt_instant_execution() │  即时涌现入口
│  ┌─────────────────────┐    │
│  │ 1. 意图分类          │    │  规则层（零延迟）+ LLM 层（兜底）
│  │ 2. 查缓存            │    │  已学会的技能直接复用
│  │ 3. 规划操作序列       │    │  screenshot_share → [screenshot]
│  │ 4. 执行原子操作       │    │  BrowserAtomicOps.execute()
│  │ 5. 缓存为已学技能     │    │  持久化到 .chimera_instant_skills.json
│  └─────────────────────┘    │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│  _generate_emergence_reply() │  口语化回复（不是机械报告）
│  → "给你截了个图~"           │
└─────────────────────────────┘
    │
    ▼
  发送截图 + 文字回复给用户
```

## 修改的文件

### 1. `browser_pool.py` — 新增 `BrowserAtomicOps` 类

**8 个原子操作：**

| 操作 | 类别 | 说明 |
|------|------|------|
| `screenshot` | capture | 截取当前页面截图 |
| `get_current_url` | info | 获取当前页面 URL |
| `get_page_title` | info | 获取页面标题 |
| `extract_text` | capture | 提取页面文字内容 |
| `navigate` | action | 导航到指定 URL |
| `click` | action | 点击页面元素 |
| `type_text` | action | 输入文字 |
| `scroll` | action | 滚动页面 |

每个操作返回统一格式：`{"success": bool, "result": any, "error": str|None}`

### 2. `skill_connector.py` — 即时涌现系统

**新增函数：**

- `attempt_instant_execution(user_request, capability_memory)` — 涌现入口
- `_classify_user_intent(user_request)` — 规则+LLM 双层意图分类
- `_llm_classify_intent(user_request)` — LLM 意图分类（兜底）
- `_plan_instant_operations(intent)` — 规划原子操作序列
- `_execute_instant_operations(operations, extra_params)` — 执行操作序列
- `_exec_browser_atomic(inputs, skill_name)` — Recipe 系统的 browser_atomic 执行器

**意图分类策略：**

1. **规则层**（零延迟）：关键词匹配截图、URL分享、内容提取、标题获取
2. **排除层**：过滤普通聊天（你好、天气、无聊等）
3. **LLM 层**（有延迟）：处理复杂意图

**缓存机制：**

- 成功的操作序列缓存到 `~/.chimera_instant_skills.json`
- 下次相同意图直接复用，无需重新规划

### 3. `base_runtime.py` — 涌现拦截层

在 `_delayed_reply` 方法中，`route_skill` 返回 "none" 后插入涌现拦截：

```python
if skill_name == "none":
    instant_result = attempt_instant_execution(combined_text, capability_memory)
    if instant_result and instant_result["success"]:
        # 根据结果类型（screenshot/url/text/title）发送对应内容
        # 用 _generate_emergence_reply() 生成口语化回复
        return
```

**新增方法：**

- `_generate_emergence_reply(user_input, action_type, action_result)` — 为涌现操作生成拟人化回复

### 4. `capability_memory.py` — 能力记忆扩展

**新增方法：**

- `record_browser_atomic(operation, context_desc)` — 记录原子操作使用
- `record_emerged_skill(skill_key, operations, user_request)` — 记录涌现技能
- `get_browser_capabilities()` — 获取浏览器相关能力
- `get_emerged_skills_summary()` — 获取涌现技能摘要

## 涌现流程示例

### 用户说"截个图"

```
1. route_skill("截个图") → "none"（现有技能无法处理）
2. attempt_instant_execution("截个图")
   → _classify_user_intent → {"type": "screenshot_share"}（规则层命中）
   → _plan_instant_operations → [{"operation": "screenshot"}]
   → BrowserAtomicOps.execute("screenshot") → 截图文件路径
   → 缓存 "screenshot_share" 技能
3. _generate_emergence_reply → "给你截了个图~"
4. 发送截图 + 文字回复
```

### 用户说"把链接发给我"

```
1. route_skill → "none"
2. attempt_instant_execution
   → 意图: "share_url"
   → 操作: [get_current_url, get_page_title]
   → 执行两个原子操作
   → 缓存 "share_url" 技能
3. 回复: "给你~ https://xxx.com"
```

### 第二次说"截个图"

```
1. route_skill → "none"
2. attempt_instant_execution
   → 意图: "screenshot_share"
   → 缓存命中！直接复用已学会的操作序列
   → 执行截图
3. 回复 + 截图
```

## 测试覆盖

17 个测试全部通过：

- BrowserAtomicOps：操作描述生成、注册表完整性、未知操作处理
- 意图分类：截图/URL/内容提取意图识别、普通聊天不触发
- 操作规划：截图/URL/内容提取操作序列
- CapabilityMemory：原子操作记录、涌现技能记录、技能摘要
- 即时技能缓存：持久化保存和加载
- 端到端：截图涌现、URL分享涌现、缓存复用
