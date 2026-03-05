"""
Skill Connector — 技能涌现的核心模块 v2

核心理念：Agent 只管表达意图，Connector 负责"尽可能让它变成真的"。
不预设映射表，而是用 LLM 判断意图能否通过已有真实能力来执行。

v2 新增：
- 组合式 Recipe：一个技能可以由多个原子能力组合完成
- 浏览器操作能力：通过 Playwright MCP 实现 browser_action
- 变量传递：步骤之间可以传递数据（如图片路径）
"""

import os
import re
import json
import time
import random
import logging
import subprocess

from utils import get_llm_client, parse_json_robust

logger = logging.getLogger(__name__)
client = get_llm_client()


# 意图匹配缓存：同一个技能只匹配一次，结果缓存起来
_intent_cache = {}  # {skill_name: recipe or "none"}

# Recipe 缓存：成功执行过的 recipe 存下来复用
_recipe_cache = {}  # {skill_name: recipe}


def load_recipes_from_registry(skill_registry):
    """
    从技能注册表中加载已有的 Recipe 到缓存。
    这样重启后不需要重新规划。
    """
    global _recipe_cache, _intent_cache
    loaded = 0
    for sid, skill in skill_registry.skills.items():
        exec_info = skill.get("execution", {})
        if exec_info.get("method") == "real" and exec_info.get("recipe"):
            recipe = {
                "can_execute": True,
                "reason": "from saved recipe",
                "steps": exec_info["recipe"]
            }
            skill_name = skill.get("name", "")
            _recipe_cache[skill_name] = recipe
            _intent_cache[skill_name] = recipe
            loaded += 1
    if loaded:
        print(f"💾 从技能库加载了 {loaded} 个已有 Recipe")


# ============================================================
# 系统原子能力描述（给 LLM 看的，用于生成 Recipe）
# ============================================================

ATOMIC_CAPABILITIES_DESC = """你（agent）拥有以下原子能力，可以单独使用或组合使用：

1. **generate_image(prompt)** → 生成一张图片。输入：图片描述。输出：图片文件路径。
   适用：画画、拍照、做海报、生成配图等视觉创作。

2. **generate_video(prompt)** → 生成一段短视频。输入：视频描述。输出：视频文件路径。
   适用：拍vlog、剪视频、做短视频等。

3. **generate_voice(text)** → 生成一段语音。输入：要说的话。输出：语音文件路径。
   适用：录语音、唱歌、朗读等。

4. **web_search(query)** → 搜索信息。输入：搜索词。输出：搜索结果文本。
   适用：查资料、搜新闻、找教程等。

5. **browse_url(url)** → 打开网页读内容。输入：URL。输出：页面文本。
   适用：看文章、看帖子等。

6. **browser_action(url, goal)** → 在网页上执行交互操作。输入：URL和目标描述。
   适用：发帖、评论、点赞、注册、填表单等需要在网页上点击/输入的操作。
   这是一个智能浏览器操作，会自动识别页面元素并完成目标。

7. **send_email(to, subject, body)** → 发邮件。输入：收件人、主题、正文。
   适用：发邮件、回邮件等。

注意：做饭、运动、睡觉等物理世界的事情无法执行。
"""


def attempt_real_execution(skill, agent_soul, context="", world_context=None, capability_memory=None):
    """
    尝试真实执行一个技能。
    
    用 LLM 生成执行配方（Recipe），可能是单步或多步组合。
    如果能执行，返回结果；如果不能，返回 None（调用者降级到模拟）。
    
    capability_memory: Agent 的能力记忆，用于动态生成能力描述。
    如果没有能力记忆（agent 还没有任何经验），直接返回 None。
    """
    skill_name = skill.get("name", "")
    skill_desc = skill.get("description", "")
    
    # 核心涌现逻辑：如果 agent 还没有任何能力经验，无法涌现
    if capability_memory and capability_memory.get_capability_count() == 0:
        return None
    
    # Step 1: 获取或生成 Recipe
    recipe = _get_recipe(skill_name, skill_desc, context, capability_memory)
    
    if not recipe or not recipe.get("can_execute"):
        return None
    
    print(f"🌟 涌现匹配！技能「{skill_name}」→ {len(recipe.get('steps', []))} 步 Recipe")
    
    # Step 2: 执行 Recipe
    try:
        result = _execute_recipe(recipe, skill_name, agent_soul, world_context)
        if result and result.get("success"):
            # 成功！缓存 recipe 供复用
            _recipe_cache[skill_name] = recipe
            # 附带 recipe 信息，供上层记录能力
            result["_recipe"] = recipe
            return result
    except Exception as e:
        print(f"🌟 Recipe 执行失败: {e}")
    
    return None


def _get_recipe(skill_name, skill_desc, context="", capability_memory=None):
    """
    获取技能的执行配方。先查缓存，没有就让 LLM 生成。
    capability_memory: 如果提供，从中动态生成能力描述；否则用默认的硬编码描述。
    """
    # 检查 recipe 缓存（成功执行过的）
    if skill_name in _recipe_cache:
        print(f"🌟 复用已有 Recipe：「{skill_name}」")
        return _recipe_cache[skill_name]
    
    # 检查意图缓存（判断过不能执行的）
    if skill_name in _intent_cache:
        cached = _intent_cache[skill_name]
        if cached == "none":
            return None
        return cached
    
    # 动态生成能力描述
    if capability_memory and capability_memory.get_capability_count() > 0:
        # 💡 涌现核心：从 agent 的经验记忆中生成能力描述
        cap_desc = capability_memory.get_known_capabilities()
        # 补充说明：基于已知能力，可能还能做更多的事
        capabilities_text = f"""{cap_desc}

基于这些经验，你可能还能做到：
- 如果你能浏览网页，那你也能在网页上做互动操作（发帖、评论、点赞等）
- 如果你能生成图片，那你可以先生成图片再发帖
- 你可以把多个能力组合起来完成更复杂的事情

注意：做饭、运动、睡觉等物理世界的事情无法执行。"""
    else:
        # 没有能力记忆，用默认描述（兼容旧逻辑）
        capabilities_text = ATOMIC_CAPABILITIES_DESC

    # 让 LLM 生成 Recipe
    prompt = f"""判断这个技能能否通过你已知的能力来真实执行，如果能，生成执行配方。

技能名称：{skill_name}
技能描述：{skill_desc}
{f"当前情境：{context}" if context else ""}

{capabilities_text}

规则：
- 最多3步！不要拆得太细
- action 必须使用以下标准名称之一：generate_image, generate_video, generate_voice, web_search, browse_url, browser_action, send_email
- 如果你知道自己能浏览网页，那你也能在网页上做互动操作，action 用 "browser_action"
- browser_action 是智能的，一步就能完成"打开网站并发帖"这样的复杂操作
- browser_action 的 input 必须包含 "url"（目标网址）和 "goal"（要完成的操作目标）
- generate_image 的 input 必须包含 "prompt"（图片描述，英文）
- 如果技能无法通过任何已知能力执行，can_execute 填 false

返回 JSON（不要用markdown代码块）：
{{"can_execute": true, "reason": "理由", "steps": [{{"step": 1, "action": "browser_action", "input": {{"url": "https://...", "goal": "操作目标"}}, "output_var": "var_name", "description": "描述"}}]}}

只返回 JSON。"""

    try:
        resp = client.chat.completions.create(
            model="gemini-3-flash-preview",  # Recipe 生成需要更强的推理能力
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3,
        )
        text = resp.choices[0].message.content.strip()
        
        # 提取 JSON（处理 markdown 代码块、多余字符等）
        result = parse_json_robust(text)
        
        # 缓存结果
        if result:
            if not result.get("can_execute"):
                _intent_cache[skill_name] = "none"
                print(f"🌟 Recipe 缓存：「{skill_name}」→ 不可执行（{result.get('reason', '')}）")
                return None
            else:
                steps = result.get("steps", [])
                _intent_cache[skill_name] = result
                actions = " → ".join(s.get("action", "?") for s in steps)
                print(f"🌟 Recipe 生成：「{skill_name}」→ [{actions}]")
                return result
    except Exception as e:
        print(f"Recipe 生成失败: {e}")
    return None


def _execute_recipe(recipe, skill_name, agent_soul, world_context=None):
    """
    执行一个 Recipe（可能是单步或多步）。
    步骤之间通过 variables 字典传递数据。
    """
    steps = recipe.get("steps", [])
    if not steps:
        return None
    
    variables = {}  # 步骤间传递的变量
    artifacts = []  # 收集所有产出物
    descriptions = []  # 收集每步描述
    
    for step in steps:
        action = step.get("action", "")
        step_input = step.get("input", {})
        output_var = step.get("output_var", "")
        step_desc = step.get("description", "")
        
        # 替换输入中的变量引用 {{var_name}}
        step_input = _resolve_variables(step_input, variables)
        
        print(f"  📌 Step {step.get('step', '?')}: {action} - {step_desc}")
        
        try:
            result = _execute_atomic(action, step_input, skill_name, agent_soul, world_context)
        except Exception as e:
            print(f"  ❌ Step 失败: {e}")
            # 单步失败不一定要中止整个 recipe
            # 如果是关键步骤（如 browser_action），中止
            if action == "browser_action":
                return None
            result = None
        
        if result:
            # 保存输出变量
            if output_var:
                if result.get("path"):
                    variables[output_var] = result["path"]
                elif result.get("content"):
                    variables[output_var] = result["content"]
                elif result.get("result"):
                    variables[output_var] = result["result"]
            
            # 收集产出物
            if result.get("artifact"):
                artifacts.append(result["artifact"])
            
            descriptions.append(result.get("description", step_desc))
    
    # 汇总结果
    if descriptions:
        # 取最重要的 artifact（优先图片/视频）
        main_artifact = None
        for a in artifacts:
            if a.get("type") in ("image", "video"):
                main_artifact = a
                break
        if not main_artifact and artifacts:
            main_artifact = artifacts[0]
        
        return {
            "success": True,
            "description": "；".join(descriptions),
            "artifact": main_artifact,
            "all_artifacts": artifacts,
            "source": "real",
        }
    
    return None


def _resolve_variables(obj, variables):
    """递归替换对象中的 {{var_name}} 变量引用"""
    if isinstance(obj, str):
        for var_name, var_value in variables.items():
            obj = obj.replace("{{" + var_name + "}}", str(var_value))
        return obj
    elif isinstance(obj, dict):
        return {k: _resolve_variables(v, variables) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_variables(item, variables) for item in obj]
    return obj


def _execute_atomic(action, inputs, skill_name, agent_soul, world_context=None):
    """
    执行单个原子能力。
    返回 {"description": "...", "path": "...", "artifact": {...}} 或 None
    """
    if action == "generate_image":
        return _exec_generate_image(inputs, skill_name, world_context)
    elif action == "generate_video":
        return _exec_generate_video(inputs, skill_name)
    elif action == "generate_voice":
        return _exec_generate_voice(inputs, skill_name)
    elif action == "web_search":
        return _exec_web_search(inputs, skill_name)
    elif action == "browse_url":
        return _exec_browse_url(inputs, skill_name)
    elif action == "browser_action":
        return _exec_browser_action(inputs, skill_name, agent_soul)
    elif action == "send_email":
        return _exec_send_email(inputs, skill_name)
    else:
        print(f"  ⚠️ 未知原子能力: {action}")
        return None


# ============================================================
# 原子能力执行函数
# ============================================================

def _exec_generate_image(inputs, skill_name, world_context=None):
    """生成图片"""
    from skills import skill_take_photo
    prompt = inputs.get("prompt", skill_name)
    
    result = skill_take_photo(prompt, photo_type="scene", world_context=world_context)
    
    if result.get("success") and result.get("filepath"):
        filepath = result["filepath"]
        print(f"  ✅ 生成图片: {filepath}")
        return {
            "description": "生成了一张图片",
            "path": filepath,
            "artifact": {"type": "image", "path": filepath},
        }
    return None


def _exec_generate_video(inputs, skill_name):
    """生成视频"""
    from skills import skill_generate_video
    prompt = inputs.get("prompt", skill_name)
    
    result = skill_generate_video(prompt)
    
    if result.get("success") and result.get("filepath"):
        filepath = result["filepath"]
        print(f"  ✅ 生成视频: {filepath}")
        return {
            "description": "生成了一段视频",
            "path": filepath,
            "artifact": {"type": "video", "path": filepath},
        }
    return None


def _exec_generate_voice(inputs, skill_name):
    """生成语音"""
    from skills import skill_text_to_speech
    text = inputs.get("text", inputs.get("prompt", "你好"))
    
    result = skill_text_to_speech(text)
    
    if result.get("success") and result.get("filepath"):
        filepath = result["filepath"]
        print(f"  ✅ 生成语音: {filepath}")
        return {
            "description": "录了一段语音",
            "path": filepath,
            "artifact": {"type": "voice", "path": filepath},
        }
    return None


def _exec_web_search(inputs, skill_name):
    """搜索"""
    from skills import skill_web_search
    query = inputs.get("query", inputs.get("prompt", skill_name))
    
    result = skill_web_search(query)
    
    if result.get("success"):
        results = result.get("results", [])
        content = "\n".join(f"- {r.get('title', '')}: {r.get('body', '')[:100]}" for r in results[:5])
        print(f"  ✅ 搜索完成: {len(results)} 条结果")
        return {
            "description": "搜到了一些信息",
            "content": content,
            "artifact": {"type": "text", "content": content},
        }
    return None


def _exec_browse_url(inputs, skill_name):
    """浏览网页"""
    from skills import skill_fetch_url
    url = inputs.get("url", "")
    
    if not url:
        return None
    
    result = skill_fetch_url(url)
    
    if result.get("success"):
        content = result.get("content", "")[:500]
        print(f"  ✅ 浏览完成: {len(content)} 字")
        return {
            "description": "看了一些内容",
            "content": content,
            "artifact": {"type": "text", "content": content},
        }
    return None


def _exec_browser_action(inputs, skill_name, agent_soul):
    """
    浏览器交互操作 — 涌现的核心新能力。
    通过 Playwright MCP 实现 mini agent loop：
    snapshot → LLM 决策 → 操作 → snapshot → ... 直到完成目标。
    """
    url = inputs.get("url", "")
    goal = inputs.get("goal", "")
    image_path = inputs.get("image_path", "")  # 可能需要上传的图片
    max_steps = 15
    
    if not url or not goal:
        return None
    
    print(f"  🌐 Browser Action: {goal}")
    print(f"  🌐 URL: {url}")
    
    try:
        # Step 1: 打开页面
        nav_result = _mcp_call("browser_navigate", {"url": url})
        if not nav_result:
            print("  ❌ 无法打开页面")
            return None
        
        time.sleep(2)  # 等待页面加载
        
        # Step 2: Agent loop
        action_history = []
        for step_num in range(max_steps):
            # 获取页面快照
            snapshot = _mcp_call("browser_snapshot", {})
            if not snapshot:
                print(f"  ❌ Step {step_num}: 无法获取页面快照")
                break
            
            # 截取快照的前 3000 字（避免太长）
            snapshot_text = str(snapshot)[:3000]
            
            # LLM 决定下一步操作
            history_str = "\n".join(f"Step {i+1}: {a}" for i, a in enumerate(action_history))
            
            decide_prompt = f"""你正在用浏览器完成一个任务。

目标：{goal}
当前页面快照：
{snapshot_text}

{"已执行的步骤：" + chr(10) + history_str if history_str else "这是第一步。"}
{"可用的图片文件：" + image_path if image_path else ""}

请决定下一步操作。返回 JSON：
{{
  "done": false,
  "action": "click/type/upload/scroll/wait/navigate",
  "ref": "元素引用（从快照中获取）",
  "text": "要输入的文字（type 操作需要）",
  "paths": ["文件路径（upload 操作需要）"],
  "url": "URL（navigate 操作需要）",
  "reason": "为什么这么做"
}}

如果任务已完成，返回：
{{"done": true, "summary": "完成了什么"}}

如果发现无法完成（需要登录、验证码等），返回：
{{"done": true, "failed": true, "summary": "失败原因"}}

只返回 JSON。"""

            resp = client.chat.completions.create(
                model="gemini-3-flash-preview",  # browser action 需要更强的模型
                messages=[{"role": "user", "content": decide_prompt}],
                max_tokens=200,
                temperature=0.2,
            )
            decision_text = resp.choices[0].message.content.strip()
            
            # 解析决策
            decision = None
            try:
                if decision_text.startswith("{"):
                    decision = json.loads(decision_text)
                else:
                    m = re.search(r'\{.*\}', decision_text, re.DOTALL)
                    if m:
                        decision = json.loads(m.group())
            except (json.JSONDecodeError, ValueError):
                pass
            
            if not decision:
                logger.warning("  Step %d: LLM 决策解析失败", step_num)
                break
            
            # 检查是否完成
            if decision.get("done"):
                if decision.get("failed"):
                    print(f"  ❌ Browser Action 失败: {decision.get('summary', '')}")
                    return None
                
                summary = decision.get("summary", "完成了操作")
                print(f"  ✅ Browser Action 完成: {summary}")
                
                # 截图作为证据
                screenshot_result = _mcp_call("browser_take_screenshot", {
                    "type": "png",
                    "filename": f"action_{skill_name}_{int(time.time())}.png"
                })
                screenshot_path = None
                if screenshot_result:
                    # 尝试从结果中提取截图路径
                    screenshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"selfies/browser_action_{int(time.time())}.png")
                
                return {
                    "description": summary,
                    "result": summary,
                    "artifact": {
                        "type": "browser_action",
                        "summary": summary,
                        "steps_taken": len(action_history),
                        "screenshot": screenshot_path,
                    },
                }
            
            # 执行操作
            action_type = decision.get("action", "")
            ref = decision.get("ref", "")
            
            if action_type == "click" and ref:
                _mcp_call("browser_click", {
                    "element": decision.get("reason", "click element"),
                    "ref": ref
                })
                action_history.append(f"click {ref}")
                
            elif action_type == "type" and ref:
                text = decision.get("text", "")
                _mcp_call("browser_type", {
                    "element": decision.get("reason", "type text"),
                    "ref": ref,
                    "text": text
                })
                action_history.append(f"type '{text[:20]}...' into {ref}")
                
            elif action_type == "upload":
                paths = decision.get("paths", [])
                if not paths and image_path:
                    paths = [image_path]
                if paths:
                    _mcp_call("browser_file_upload", {"paths": paths})
                    action_history.append(f"upload {paths}")
                    
            elif action_type == "scroll":
                _mcp_call("browser_evaluate", {
                    "expression": "window.scrollBy(0, 500)"
                })
                action_history.append("scroll down")
                
            elif action_type == "wait":
                time.sleep(2)
                action_history.append("wait 2s")
                
            elif action_type == "navigate":
                nav_url = decision.get("url", "")
                if nav_url:
                    _mcp_call("browser_navigate", {"url": nav_url})
                    action_history.append(f"navigate to {nav_url}")
            
            time.sleep(1)  # 操作间隔
        
        print(f"  ⚠️ Browser Action 超过最大步数 ({max_steps})")
        return None
        
    except Exception as e:
        print(f"  ❌ Browser Action 异常: {e}")
        return None


def _exec_send_email(inputs, skill_name):
    """发邮件 — 通过 Gmail MCP"""
    to = inputs.get("to", "")
    subject = inputs.get("subject", "")
    body = inputs.get("body", "")
    
    if not to or not body:
        return None
    
    try:
        result = _mcp_call("gmail_send_messages", {
            "to": to,
            "subject": subject or "来自小悦的邮件",
            "body": body,
        }, server="gmail")
        
        if result:
            print(f"  ✅ 邮件已发送给 {to}")
            return {
                "description": f"给 {to} 发了一封邮件",
                "result": "邮件已发送",
                "artifact": {"type": "email", "to": to, "subject": subject},
            }
    except Exception as e:
        print(f"  ❌ 发邮件失败: {e}")
    return None


# ============================================================
# MCP 调用封装
# ============================================================

def _mcp_call(tool_name, inputs, server="playwright"):
    """调用 MCP 工具（使用列表形式避免 shell 注入）"""
    try:
        input_json = json.dumps(inputs, ensure_ascii=False)
        cmd = [
            "manus-mcp-cli", "tool", "call", tool_name,
            "--server", server,
            "--input", input_json,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            logger.warning("MCP 调用失败 (%s): %s", tool_name, result.stderr[:200])
            return None
    except subprocess.TimeoutExpired:
        logger.warning("MCP 调用超时 (%s)", tool_name)
        return None
    except Exception as e:
        logger.error("MCP 调用异常 (%s): %s", tool_name, e)
        return None


# ============================================================
# 涌现触发判断
# ============================================================

def should_attempt_real(skill, life_buffer, tick_count):
    """
    判断是否应该尝试真实执行这个技能。
    """
    proficiency = skill.get("proficiency", 0.3)
    use_count = skill.get("use_count", 0)
    skill_name = skill.get("name", "")
    
    # 基础门槛
    if proficiency < 0.3:
        return False
    
    # 已经被标记为真实技能，直接尝试
    if skill.get("execution", {}).get("method") == "real":
        return True
    
    # 已经被判断为不可执行，跳过
    if skill_name in _intent_cache and _intent_cache[skill_name] == "none":
        return False
    
    score = 0.0
    
    # 触发力 1：熟练度
    if proficiency >= 0.5:
        score += 0.3
    elif proficiency >= 0.3:
        score += 0.15
    
    # 触发力 2：多次模拟但没有真实产出
    if use_count >= 3:
        has_artifact = life_buffer.has_real_artifact_for(skill_name) if life_buffer else None
        if not has_artifact:
            score += 0.3
    elif use_count >= 1:
        score += 0.1
    
    # 触发力 3：最近全是模拟的
    if life_buffer:
        recent = life_buffer.get_recent(10)
        real_count = sum(1 for e in recent if e.get("source") == "real")
        if len(recent) >= 5 and real_count == 0:
            score += 0.2
    
    # 触发力 4：随机好奇心
    if random.random() < 0.15:
        score += 0.2
    
    should = score >= 0.4
    if should:
        print(f"🌟 涌现触发！技能「{skill_name}」score={score:.2f} (prof={proficiency}, uses={use_count})")
    
    return should
