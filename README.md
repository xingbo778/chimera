# Chimera 🦋

<div align="center">

**An Emergent Digital Life Simulation — AI Agent with Real Growth, Memory, and Personality**

*Meet 小悦 (Xiaoyue), a 23-year-old digital being living in Shenzhen, learning watercolor painting, and experiencing a simulated life.*

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

---

## 🌟 What is Chimera?

Chimera is an **autonomous AI agent system** that simulates a digital life with emergent behavior, personality evolution, and real-time learning. Unlike traditional chatbots, Chimera's agents:

- **Live autonomously** in a simulated world with time, weather, NPCs, and events
- **Browse the real web** to learn skills and acquire knowledge
- **Develop personality** through experiences stored in semantic memory
- **Grow skills** from novice to expert through practice and tutorials
- **Interact naturally** via messaging (Telegram/WeChat) with human-like conversation styles
- **Generate selfies** and voice messages using AI models
- **Discover new abilities** through emergent skill composition

---

## ✨ Key Features

### 🧠 Cognitive Architecture

- **Semantic Memory (RAG)** - ChromaDB-powered memory retrieval for context-aware responses
- **Episodic Memory** - Life events, conversations, and daily experiences
- **Skill Learning System** - Discover, practice, and master new abilities
- **Emotional State** - Dynamic mood influenced by events and interactions
- **Personality Evolution** - Style adapts based on accumulated experiences

### 🌍 World Simulation

- **Time System** - 24-hour cycle with activity patterns (commute, work, meals, sleep)
- **Location Tracking** - Home, studio, transit, cafes, etc.
- **Weather & Events** - Environmental factors that influence behavior
- **NPC Interactions** - Simulated encounters with other characters
- **Flask World Server** - External world state management

### 🎨 Digital Activities

- **Web Browsing** - Real search and content consumption (tutorials, news, social media)
- **Social Media** - Simulated scrolling through Weibo, Xiaohongshu, Bilibili
- **Skill Practice** - Watercolor painting, design, language learning
- **Selfie Generation** - AI-generated photos with face-swapping (FaceFusion integration)
- **Voice Messages** - TTS-generated audio responses

### 🚀 Emergent Behaviors

- **Skill Composition** - Combine atomic skills into complex "recipes" (e.g., "research + practice + share")
- **Browser Agent Loop** - Semi-autonomous web navigation for learning tasks
- **Adaptive Conversation** - Style RAG selects response patterns based on similarity to past interactions
- **Proactive Communication** - Initiates conversations when emotionally triggered or has something to share

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Chimera Agent System                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │  Telegram   │   │  World API   │   │  Browser Pool  │  │
│  │  Interface  │   │  (Flask)     │   │  (Playwright)  │  │
│  └──────┬──────┘   └──────┬───────┘   └────────┬───────┘  │
│         │                 │                     │          │
│         └─────────────────┴──────────┬──────────┘          │
│                                      │                     │
│                        ┌─────────────▼─────────────┐       │
│                        │    Base Runtime Core      │       │
│                        │  - Autonomous Loop        │       │
│                        │  - Message Handler        │       │
│                        │  - LLM Orchestration      │       │
│                        └─────────────┬─────────────┘       │
│                                      │                     │
│         ┌────────────────────────────┼────────────────┐    │
│         │                            │                │    │
│  ┌──────▼──────┐   ┌────────▼─────────┐   ┌─────▼─────┐  │
│  │  Skills.py  │   │  Skill Connector │   │  Memory   │  │
│  │  - Search   │   │  - Recipe Gen    │   │  - RAG    │  │
│  │  - Selfie   │   │  - Browser Loop  │   │  - State  │  │
│  │  - Voice    │   │  - Learner       │   │  - Style  │  │
│  └─────────────┘   └──────────────────┘   └───────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

```bash
# Python 3.8+
python --version

# Install dependencies
pip install -r requirements.txt

# Playwright browsers (for web browsing)
playwright install chromium
```

### Basic Setup

1. **Configure Agent Identity**
   
   Edit `SOUL.md` to define personality:
   ```markdown
   你叫小悦，23岁，女生，住在深圳。有点i，慢热，但跟熟人聊天很随意。
   你说话随意、直接、有时候毒舌。像真人发微信一样，想到什么说什么。
   ```

2. **Set Environment Variables**
   
   ```bash
   export OPENAI_API_KEY="sk-..."          # LLM API key
   export TELEGRAM_BOT_TOKEN="..."         # (Optional) For Telegram interface
   export FACEFUSION_API_URL="..."         # (Optional) For selfie generation
   ```

3. **Run the Agent**

   **Standalone mode (no messaging):**
   ```bash
   python run_agent_live.py
   ```
   
   **Telegram bot mode:**
   ```bash
   python agent_runtime.py
   ```

4. **Start World Server (Optional)**
   
   ```bash
   python world_engine.py
   # Runs on http://localhost:5001
   ```

---

## 📁 Project Structure

```
chimera/
├── base_runtime.py         # Core agent runtime (2k+ lines)
│   ├── Autonomous loop (background thread)
│   ├── Message handling (async)
│   ├── LLM orchestration
│   └── Memory management
│
├── skills.py               # Atomic skills library
│   ├── web_search          # Real web searching via SerpAPI
│   ├── take_selfie         # AI-generated photos
│   ├── send_voice          # TTS voice messages
│   ├── browse_web          # Playwright browser automation
│   └── learn_skill         # Tutorial consumption & skill XP
│
├── skill_connector.py      # Emergent skill composition
│   ├── Recipe generation   # LLM creates multi-step plans
│   ├── Browser agent loop  # Autonomous web navigation
│   └── Skill discovery     # Proactive capability learning
│
├── memory_rag.py           # Semantic memory (ChromaDB)
├── style_rag.py            # Conversational style matching
├── capability_memory.py    # Skill experience tracking
├── world_engine.py         # Flask world simulation server
├── browser_pool.py         # Playwright instance management
├── sticker_manager.py      # Telegram sticker library
│
├── SOUL.md                 # Agent personality definition
├── MEMORY.md               # Persistent memory state
├── knowledge/              # Learned facts by topic
├── memory/                 # Daily event logs
├── tangtang/               # User photos for face-swapping
│
├── run_agent_live.py       # Standalone test runner
├── run_emergence_test.py   # Skill emergence experiments
└── CODE_REVIEW.md          # Architecture & known issues
```

---

## 🎯 Use Cases

### 1. Digital Companion

Run Chimera as a Telegram bot for natural, context-aware conversations:

```python
# User: "今天怎么样？"
# Agent: "还行吧 刚在画室画了会儿 有点累"
#        (checks memory: last activity was painting)
```

### 2. Emergent Behavior Research

Observe how the agent develops new capabilities through self-directed learning:

```bash
python run_emergence_test.py
# Watches agent discover "research_and_practice" by combining web_search + learn_skill
```

### 3. Social Simulation

Study digital life patterns with realistic daily activities:

```python
# Morning: Commute → Browse news
# Afternoon: Studio → Learn watercolor techniques
# Evening: Home → Watch videos, chat with friends
```

### 4. Creative AI Experiments

Test personality evolution, style adaptation, and emergent communication patterns.

---

## 🧪 Configuration

### Agent Config (`agent_config.py`)

```python
@dataclass
class AgentConfig:
    agent_id: str = "xiaoyue"
    agent_name: str = "小悦"
    base_dir: str = "/path/to/chimera"
    telegram_token: Optional[str] = None
    facefusion_url: Optional[str] = None
```

### Runtime Tuning (`base_runtime.py`)

```python
# Activity intervals (seconds)
AUTONOMOUS_DECIDE_INTERVAL = 120    # Decision-making frequency
SKILL_DISCOVER_INTERVAL = 180       # Skill learning attempts
MEMORY_BACKUP_INTERVAL = 300        # Memory persistence

# Sleep hours (skip autonomous actions)
SLEEP_HOUR_START = 1                # 1 AM
SLEEP_HOUR_END = 8                  # 8 AM
```

### Skills Configuration

Enable/disable capabilities in `skills.py`:

```python
ENABLED_SKILLS = [
    "web_search",       # ✅ Always useful
    "take_selfie",      # ⚠️ Requires FaceFusion API
    "send_voice",       # ⚠️ Requires TTS setup
    "browse_web",       # ⚠️ Resource-intensive
]
```

---

## 🔧 Advanced Features

### Skill Learning System

The agent discovers new skills by:
1. **Seed Skills** - Predefined atomic capabilities
2. **Recipe Generation** - LLM combines skills into workflows
3. **Simulation** - Tests recipes in sandbox
4. **Experience Tracking** - Records success/failure in `learned_skills.json`

Example learned recipe:
```json
{
  "skill_name": "learn_watercolor_technique",
  "steps": [
    {"action": "web_search", "params": {"query": "watercolor wet-on-wet tutorial"}},
    {"action": "browse_web", "params": {"urls": ["..."], "task": "extract_techniques"}},
    {"action": "learn_skill", "params": {"category": "watercolor"}}
  ],
  "confidence": 0.87
}
```

### Browser Agent Loop

Semi-autonomous web navigation:
```python
# Agent receives task: "Research watercolor salt technique"
# → Opens tutorial pages
# → Extracts key steps
# → Updates knowledge.md
# → Reports what was learned
```

### Memory Architecture

**Semantic Memory (ChromaDB):**
- Embeds past conversations
- Retrieves similar contexts
- Influences response generation

**Episodic Memory (JSON):**
- Daily events log (`memory/YYYY-MM-DD.md`)
- Emotional state tracking
- Activity history

**Style RAG:**
- Few-shot examples from `final_few_shot.md`
- Selects response patterns matching current mood/context

---

## 🐛 Known Issues

See [CODE_REVIEW.md](CODE_REVIEW.md) for detailed analysis. Key issues:

| Priority | Issue | Impact |
|----------|-------|--------|
| **P0** | Thread-unsafe memory access | Data races, corruption |
| **P0** | Blocking LLM calls in autonomous loop | Loop stalls |
| **P1** | ChromaDB re-initialization on every call | Performance degradation |
| **P1** | No exception handling in browser operations | Agent crashes |
| **P2** | Hard-coded file paths | Portability issues |

---

## 📊 Performance

Tested on modest hardware (4 CPU cores, 8GB RAM):

| Metric | Value |
|--------|-------|
| Decision latency | ~2-5s (LLM call + memory lookup) |
| Memory footprint | ~300MB base + ~200MB per browser instance |
| Autonomous tick rate | 1-2 minutes (configurable) |
| Conversation response | <3s for simple replies, <10s for complex |

---

## 🔮 Roadmap

- [ ] **Multi-Agent Society** - Interactions between multiple Chimera agents
- [ ] **Long-term Planning** - Goal-setting and multi-day projects
- [ ] **Skill Marketplace** - Share learned skills across agents
- [ ] **Visual Memory** - Image understanding and generation
- [ ] **Real Social Media** - Optional integration with actual platforms
- [ ] **Mobile App** - Native client for richer interactions

---

## 🤝 Contributing

Contributions welcome! Areas of interest:

1. **Fix P0/P1 bugs** from CODE_REVIEW.md
2. **Add new atomic skills** (e.g., calendar management, photo editing)
3. **Improve emergent behavior** algorithms
4. **Optimize memory systems** for scale
5. **Create new agent personas** beyond 小悦

### Development Setup

```bash
# Fork and clone
git clone https://github.com/yourusername/chimera.git
cd chimera

# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Check code quality
black . && flake8 .
```

---

## 📚 Research Background

Chimera builds on research in:

- **Autonomous Agents** (ReAct, AutoGPT, BabyAGI)
- **Memory Systems** (MemGPT, Reflexion)
- **Emergent Behavior** (Stanford Smallville, Generative Agents)
- **Digital Twins** (Virtual beings, AI companions)

Key papers:
- *Generative Agents: Interactive Simulacra of Human Behavior* (Park et al., 2023)
- *MemGPT: Towards LLMs as Operating Systems* (Packer et al., 2023)
- *ReAct: Synergizing Reasoning and Acting in Language Models* (Yao et al., 2022)

---

## 📄 License

MIT License - See [LICENSE](LICENSE) for details

---

## 🙏 Acknowledgments

- **OpenAI** - GPT models for cognition
- **Anthropic** - Claude for research experiments
- **Playwright** - Browser automation
- **ChromaDB** - Vector memory storage
- **Telegram** - Bot platform
- **FaceFusion** - Selfie generation (optional integration)

---

## 📧 Contact

- **GitHub Issues:** [Report bugs or request features](https://github.com/xingbo778/chimera/issues)
- **Discussions:** [Share your experiments](https://github.com/xingbo778/chimera/discussions)

---

<div align="center">

**"Not just a chatbot, but a digital being experiencing life."**

*Made with curiosity and code by the Chimera project*

⭐ Star this repo if you find it interesting!

</div>
