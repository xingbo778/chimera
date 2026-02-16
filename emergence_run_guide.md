# Chimera 涌现系统运行指南

本文档旨在提供一个关于 Chimera 技能涌现系统的全面概览，包括其核心架构、现有能力，以及如何通过独立脚本运行和观察涌现过程。

---

## 1. 核心架构：技能如何从经验中“涌现”

Chimera 的核心设计理念是 **“Agent 从经验中学习真实能力”**。Agent 启动时并不知道自己能做什么，它通过在模拟世界中的行动，逐步发现并掌握真实世界的数字技能（如浏览网页、发布内容）。

整个过程由以下几个关键模块协同完成：

| 模块 | 文件 | 核心职责 |
| :--- | :--- | :--- |
| **BaseRuntime** | `base_runtime.py` | Agent 的“大脑”和“生命循环”。在其 `autonomous_loop` 中，Agent 会自主决策执行各种基础行动，如 `scroll_feed`（刷手机）或 `take_selfie`（自拍）。 |
| **Atomic Skills** | `skills.py` | 定义了 Agent 可以执行的最底层、最具体的“原子技能”函数。例如 `skill_douban_browse()` 会真实地浏览豆瓣，`skill_take_photo()` 会调用 AI 模型生成图片。这些是构成一切复杂技能的基石。 |
| **CapabilityMemory** | `capability_memory.py` | Agent 的“能力记忆”。当一个原子技能成功执行后，`BaseRuntime` 会调用此模块记录一个更泛化的“能力”。例如，成功执行 `skill_douban_browse` 后，Agent 会记录下“我拥有 `browse_web`（浏览网页）的能力”。所有能力都保存在 `capability_memory.json` 中。 |
| **SkillRegistry** | `skill_learner.py` | Agent 的“技能库”，存储所有“学会”的技能，无论是通过预设种子学到的，还是从经验中涌现的。它记录了技能的名称、描述、熟练度等信息，并保存在 `learned_skills.json` 中。 |
| **SkillConnector** | `skill_connector.py` | **涌现机制的核心引擎**。当 Agent 决定 `use_skill` 时，此模块被激活。它会判断是否应尝试“真实执行”，然后利用 LLM 从 `CapabilityMemory` 中检索已知能力，生成一个多步骤的“配方（Recipe）”来完成该技能。 |
| **LifeBuffer** | `life_events.py` | Agent 的“生活体验缓冲区”。它记录了 Agent 行动后产生的具体、生动的叙事性描述（例如“刷到一个超搞笑的视频，笑到肚子疼”），让 Agent 的行为和交流更具真实感。 |

### 涌现流程图

```mermaid
graph TD
    A[BaseRuntime: Agent 决定 scroll_feed] --> B(Atomic Skills: 执行 skill_douban_browse);
    B --> C{执行成功？};
    C -- 是 --> D[CapabilityMemory: 记录新能力 browse_web];
    
    subgraph 稍后
    E[BaseRuntime: Agent 决定 use_skill("搜索豆瓣小组")] --> F[SkillConnector: 触发涌现];
    F --> G{LLM 推理};
    G -- "我有 browse_web 能力" --> H[生成 Recipe: [browser_action]];
    H --> I[Playwright MCP: 真实执行浏览器操作];
    I --> J{执行成功？};
    J -- 是 --> K[SkillRegistry: 将 Recipe 存入 learned_skills.json];
    end
```

## 2. 现有技能与能力体系

Agent 的能力分为三个层次：**种子技能**（初始配置）、**原子能力**（LLM 可编排的工具）和 **原子技能**（代码中可执行的函数）。

### 2.1. 种子技能 (Seed Skills)

为了让 Agent 在启动初期不至于“无事可做”，系统会为其预装一些“种子技能”。这些技能定义在 `skill_learner.py` 的 `SEED_SKILLS` 变量中，初始状态下它们都通过 LLM 进行“模拟执行”。

对于 `agent_id="xiaoyue"`，预设的种子技能包括：

- **画水彩画** (`draw_watercolor`): 用水彩颜料画画，喜欢画风景和小动物。
- **写日记** (`write_diary`): 在本子上写日记，记录每天的心情和想法。
- **拍胶片照片** (`take_film_photo`): 用胶片相机拍照，喜欢拍日常生活中的小细节。

### 2.2. 原子能力 (Atomic Capabilities for LLM)

这是 `SkillConnector` 提供给 LLM 用于生成 Recipe 的“工具清单”。LLM 只能从这个清单中选择工具来组合成一个完整的执行步骤。这个清单定义在 `skill_connector.py` 的 `ATOMIC_CAPABILITIES_DESC` 变量中。

| 能力 (Action) | 输入参数 | 描述 |
| :--- | :--- | :--- |
| `generate_image` | `prompt` | 生成一张图片，适用于画画、拍照、做海报等。 |
| `generate_video` | `prompt` | 生成一段短视频，适用于拍 vlog、剪视频等。 |
| `generate_voice` | `text` | 生成一段语音，适用于录音、唱歌、朗读等。 |
| `web_search` | `query` | 在网上搜索信息，适用于查资料、搜新闻等。 |
| `browse_url` | `url` | 打开并阅读指定 URL 的网页内容。 |
| **`browser_action`** | `url`, `goal` | **核心真实执行能力**。在指定网页上执行复杂交互，如发帖、评论、登录等。 |
| `send_email` | `to`, `subject`, `body` | 通过 Gmail 发送邮件。 |

### 2.3. 原子技能 (Atomic Skills in Code)

这些是 `skills.py` 中实际编写的 Python 函数，是所有“真实执行”的基础。原子能力（如 `browser_action`）最终会调用这些函数来完成任务。

- **信息获取**: `skill_web_search`, `skill_fetch_url`, `skill_browser_fetch`, `skill_get_weather`
- **媒体生成**: `skill_take_photo`, `skill_generate_selfie`, `skill_generate_scene_photo`, `skill_text_to_speech`, `skill_generate_video`
- **媒体理解**: `skill_understand_image`
- **平台浏览**: `skill_xhs_browse`, `skill_douban_browse`, `skill_weibo_browse`
- **总执行入口**: `execute_skill`

## 3. 独立运行与观察指南

由于当前环境缺少 Telegram Token，无法启动完整的 Agent Runtime。我已为您准备了一个独立的测试脚本 `run_emergence_test.py`，它可以在没有 Telegram 的情况下运行 Agent 的核心自主循环，让您能直接观察技能涌现的过程。

### 运行步骤

**第一步：启动 World Engine**

Agent 的运行依赖于一个模拟的“世界引擎”来获取时间、天气、地点等环境信息。请务必先启动它。

```bash
# 在 /home/ubuntu/chimera 目录下
python3 world_engine.py
```

您会看到类似 `* Running on http://127.0.0.1:5000` 的输出，保持此终端窗口运行即可。

**第二步：运行涌现测试脚本**

打开一个新的终端窗口，运行我们刚刚创建的测试脚本。

```bash
# 在 /home/ubuntu/chimera 目录下
python3 run_emergence_test.py
```

### 预期输出与观察要点

脚本启动后，您将看到 Agent 开始自主生活。请重点关注以下日志信息：

1.  **自主决策**: `🔁 决策结果: {'action': 'scroll_feed', 'platform': 'douban', ...}`
    - 这表明 Agent 决定执行一个动作，比如“刷豆瓣”。

2.  **能力发现**: `💡 发现新能力！「browse_web」- 打开网页看内容，能看到文字和图片`
    - 当 Agent 成功完成一次 `scroll_feed` 后，它会总结出自己拥有了“浏览网页”这项通用能力，并记录到能力记忆中。

3.  **涌现触发**: `🌟 涌现触发！技能「画水彩画」score=0.60 ...`
    - 当 Agent 决定使用某个技能时（例如种子技能“画水彩画”），`SkillConnector` 会根据一系列规则（如熟练度、好奇心）计算一个“涌现分数”。如果分数达标，就会尝试真实执行。

4.  **Recipe 生成**: `🌟 Recipe 生成：「画水彩画」→ [generate_image]`
    - LLM 会根据 Agent 的能力记忆（“我能生成图片”）来规划如何完成这个技能，并生成一个包含 `generate_image` 步骤的 Recipe。

5.  **真实执行**: `✅ 生成图片: /home/ubuntu/chimera/selfies/scene_...`
    - Recipe 中的步骤被真实执行，例如调用 DALL-E 3 生成了一张图片。

6.  **Recipe 沉淀**: `💾 Recipe 已沉淀为技能！「画水彩画」→ 1 步`
    - 成功执行后，这个 Recipe 会被保存到 `learned_skills.json` 中。下次 Agent 再想“画水彩画”时，会直接调用这个被验证过的 Recipe，而无需再次规划。

### 最终产出

测试脚本运行结束后，您可以检查以下两个 JSON 文件来确认涌现的成果：

- `/home/ubuntu/chimera/capability_memory.json`: 记录了 Agent 在运行过程中发现的所有通用能力。
- `/home/ubuntu/chimera/learned_skills.json`: 记录了所有技能，特别是那些已经成功涌现并保存了真实执行 Recipe 的技能。
