"""
Capability Memory — Agent 的能力记忆

核心理念：Agent 不知道自己"能做什么"，直到它做过一次。
每次成功执行真实操作后，记录一条能力经验。
下次想做新事情时，从能力记忆中回忆可用的能力。

这是涌现的基础：没有预设的能力清单，一切来自经验。
"""

import os
import json
import time

CAPABILITY_FILE = "capability_memory.json"


class CapabilityMemory:
    """
    Agent 的能力记忆。
    
    每条记忆记录：
    - capability_id: 能力标识（如 "browse_web", "generate_image"）
    - description: 这个能力能做什么（从经验中总结）
    - first_discovered: 第一次发现的时间
    - use_count: 成功使用次数
    - last_used: 最后使用时间
    - examples: 使用过的场景示例（最多5个）
    - source_action: 是通过什么动作发现的（如 "scroll_feed", "take_selfie"）
    """
    
    def __init__(self, agent_dir):
        self.filepath = os.path.join(agent_dir, CAPABILITY_FILE)
        self.capabilities = {}  # {capability_id: {...}}
        self._load()
    
    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    self.capabilities = json.load(f)
            except:
                self.capabilities = {}
    
    def _save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump(self.capabilities, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存能力记忆失败: {e}")
    
    def record_capability(self, capability_id, description, example="", source_action=""):
        """
        记录一次成功的能力使用。
        如果是新能力，创建记录；如果已有，更新计数和示例。
        """
        now = time.time()
        
        if capability_id in self.capabilities:
            cap = self.capabilities[capability_id]
            cap["use_count"] += 1
            cap["last_used"] = now
            # 添加新示例（最多保留5个）
            if example and example not in cap["examples"]:
                cap["examples"].append(example)
                if len(cap["examples"]) > 5:
                    cap["examples"] = cap["examples"][-5:]
            # 更新描述（可能越来越准确）
            if description and len(description) > len(cap.get("description", "")):
                cap["description"] = description
        else:
            self.capabilities[capability_id] = {
                "capability_id": capability_id,
                "description": description,
                "first_discovered": now,
                "use_count": 1,
                "last_used": now,
                "examples": [example] if example else [],
                "source_action": source_action,
            }
            print(f"💡 发现新能力！「{capability_id}」- {description}")
        
        self._save()
    
    def get_known_capabilities(self):
        """获取所有已知能力的描述，供 LLM 回忆用"""
        if not self.capabilities:
            return ""
        
        lines = []
        for cap_id, cap in self.capabilities.items():
            desc = cap["description"]
            count = cap["use_count"]
            examples_str = ""
            if cap["examples"]:
                examples_str = f"（用过：{'、'.join(cap['examples'][:3])}）"
            lines.append(f"- {desc} [用过{count}次]{examples_str}")
        
        return "你记得自己能做这些事情：\n" + "\n".join(lines)
    
    def get_capability_ids(self):
        """获取所有已知能力的 ID 列表"""
        return list(self.capabilities.keys())
    
    def has_capability(self, capability_id):
        """检查是否知道某个能力"""
        return capability_id in self.capabilities
    
    def get_capability_count(self):
        """获取已知能力数量"""
        return len(self.capabilities)
