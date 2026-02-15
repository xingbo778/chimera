# 技能涌现机制 — 端到端验证报告

## 核心成果

**Agent 从经验中自主发现能力，并真实执行浏览器操作，成功后自动沉淀为可复用的 Skill。**

无任何预设映射。整个过程完全由 LLM 自主推理完成。

---

## 端到端验证路径

```
Agent 浏览豆瓣（scroll_feed）
    ↓ 自动记录
💡 发现新能力：browse_web（"打开网页看内容，能看到文字和图片"）
    ↓ 下次 use_skill 时
🌟 涌现触发：技能「搜索豆瓣小组」score=0.60
    ↓ LLM 从能力记忆中推理
🌟 Recipe 生成：「搜索豆瓣小组」→ [browser_action]
    ↓ Playwright MCP 真实执行
🌐 打开豆瓣小组页面 → 输入"烘焙" → 点击搜索 → 搜索结果显示
    ↓ 执行成功
✅ 涌现成功！source: "real"
    ↓ 自动沉淀
💾 Recipe 持久化到 learned_skills.json
    ↓ 重启后
📦 从技能库加载 Recipe → 直接复用，无需重新规划
```

## 架构设计

### 三层模块

| 模块 | 职责 | 文件 |
|------|------|------|
| **CapabilityMemory** | 记录 agent 从经验中发现的能力 | `capability_memory.py` |
| **SkillConnector** | 涌现引擎：LLM 推理技能→能力映射，生成 Recipe | `skill_connector.py` |
| **BaseRuntime** | 集成涌现到 use_skill 分支，埋点记录能力 | `base_runtime.py` |

### 涌现流程

```
use_skill("搜索豆瓣小组")
    ↓
should_attempt_real() → score > 0.4? → Yes
    ↓
attempt_real_execution()
    ↓
capability_memory.get_capability_count() > 0? → Yes
    ↓
_get_recipe() → LLM 从能力记忆推理 → Recipe
    ↓
_execute_recipe() → 逐步执行原子操作
    ↓
browser_action → Playwright MCP mini agent loop
    ↓
成功 → 缓存 Recipe + 持久化到 learned_skills.json
```

### 能力发现埋点

| 操作 | 发现的能力 | 埋点位置 |
|------|-----------|---------|
| `scroll_feed` 浏览网页 | `browse_web` | base_runtime.py 第 870 行 |
| `take_selfie` 拍照 | `generate_image` | base_runtime.py 第 882 行 |
| 涌现成功执行 | 对应的原子能力 | base_runtime.py 第 943 行 |

### Browser Action — Mini Agent Loop

```
打开 URL → 获取页面快照 → LLM 决策下一步操作 → 执行（click/type/scroll）→ 获取新快照 → ... → 完成
```

- 使用 **Playwright MCP** 驱动真实浏览器
- 每步由 **gpt-4.1-mini** 决策（需要较强的推理能力）
- 最多 15 步，支持 click、type、upload、scroll、wait、navigate
- 完成后截图作为证据

### Recipe 沉淀

```json
{
  "skill_id": "search_douban_group",
  "name": "搜索豆瓣小组",
  "execution": {
    "method": "real",
    "recipe": [
      {
        "step": 1,
        "action": "browser_action",
        "input": {
          "url": "https://www.douban.com/group/",
          "goal": "搜索烘焙相关的小组"
        }
      }
    ]
  }
}
```

重启后自动加载，下次直接复用。

## 与"指导"的区别

| | 旧方式（指导） | 新方式（涌现） |
|---|---|---|
| 谁知道有哪些能力 | 开发者硬编码在 `ATOMIC_CAPABILITIES_DESC` | Agent 从经验中自己发现 |
| 谁决定怎么组合 | 开发者预设映射表 | LLM 自己推理 |
| 触发条件 | 所有技能都尝试 | 只有 agent 有相关经验时才触发 |
| 能力来源 | 静态列表 | 动态积累，越用越多 |

## 验证结果

| 测试场景 | 结果 |
|---------|------|
| 能力记忆为空 → 不涌现 | ✅ 正确返回 None |
| 浏览豆瓣 → 发现 browse_web | ✅ 自动记录 |
| 拍照 → 发现 generate_image | ✅ 自动记录 |
| 画水彩画 → generate_image | ✅ 真实生成图片 |
| 搜索豆瓣小组 → browser_action | ✅ 真实浏览器操作 |
| 做甜点 → 物理操作 → 不可执行 | ✅ 正确拒绝 |
| Recipe 持久化 → 重启加载 | ✅ 成功复用 |

## 待优化

1. **小红书/微博登录**：需要用户扫码或手机验证码登录后，agent 才能浏览这些平台
2. **组合式 Recipe**：目前验证的是单步 Recipe（browser_action），多步组合（generate_image + browser_action 发图文帖）需要更多测试
3. **失败重试**：Recipe 执行失败后应清除缓存，下次重新规划
4. **安全边界**：发帖、评论等操作需要用户授权机制

## 代码提交

- GitHub: `xingbo778/chimera`
- Commit: `3650c0a`
