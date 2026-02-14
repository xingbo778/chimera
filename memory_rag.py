"""
Memory RAG: 基于向量检索的语义记忆搜索。

核心思路：
- daily_log 事件和 knowledge 条目存入 chromadb（用 multilingual embedding）
- 每次聊天前，用当前对话上下文做语义检索
- 取 top-k 最相关的记忆注入 LLM context
- 替代原来的关键词匹配搜索
"""

import os
import hashlib
import time
import chromadb
from chromadb.utils import embedding_functions

# 复用 StyleRAG 的 embedding 模型（中文效果好）
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# 全局共享 embedding function（避免重复加载模型）
_shared_ef = None

def get_shared_ef():
    global _shared_ef
    if _shared_ef is None:
        _shared_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
    return _shared_ef


class MemoryRAG:
    """管理 daily_log 和 knowledge 的向量检索"""

    def __init__(self, persist_dir):
        """
        persist_dir: chromadb 持久化目录
        """
        self.persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)

        ef = get_shared_ef()

        self._client = chromadb.PersistentClient(path=persist_dir)

        # 两个 collection：事件日志 + 知识
        self._events = self._client.get_or_create_collection(
            name="events",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        self._knowledge = self._client.get_or_create_collection(
            name="knowledge",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

    # ============================================================
    # 事件日志
    # ============================================================

    def add_event(self, text, importance=5, timestamp=None):
        """添加一条事件到向量库"""
        if not text or len(text.strip()) < 2:
            return
        ts = timestamp or time.time()
        doc_id = hashlib.md5(f"{ts}:{text}".encode()).hexdigest()

        # 检查是否已存在
        try:
            existing = self._events.get(ids=[doc_id])
            if existing and existing["ids"]:
                return
        except:
            pass

        self._events.add(
            documents=[text],
            ids=[doc_id],
            metadatas=[{
                "text": text,
                "importance": importance,
                "timestamp": ts,
            }],
        )

    def search_events(self, query, n_results=5, min_importance=0):
        """语义搜索事件日志"""
        if self._events.count() == 0:
            return []

        n = min(n_results * 2, self._events.count())  # 多取一些，后面过滤
        results = self._events.query(
            query_texts=[query],
            n_results=n,
        )

        events = []
        if results and results["metadatas"]:
            for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
                if meta.get("importance", 0) >= min_importance:
                    events.append({
                        "text": meta["text"],
                        "importance": meta.get("importance", 5),
                        "timestamp": meta.get("timestamp", 0),
                        "relevance": 1 - dist,  # cosine distance → similarity
                    })
                    if len(events) >= n_results:
                        break
        return events

    # ============================================================
    # 知识库
    # ============================================================

    def add_knowledge(self, topic, summary, source="", timestamp=None):
        """添加一条知识到向量库"""
        if not topic or not summary:
            return
        ts = timestamp or time.time()
        content = f"{topic}: {summary}"
        doc_id = hashlib.md5(content.encode()).hexdigest()

        try:
            existing = self._knowledge.get(ids=[doc_id])
            if existing and existing["ids"]:
                return
        except:
            pass

        self._knowledge.add(
            documents=[content],
            ids=[doc_id],
            metadatas=[{
                "topic": topic,
                "summary": summary[:500],
                "source": source,
                "timestamp": ts,
            }],
        )

    def search_knowledge(self, query, n_results=3):
        """语义搜索知识库"""
        if self._knowledge.count() == 0:
            return []

        n = min(n_results, self._knowledge.count())
        results = self._knowledge.query(
            query_texts=[query],
            n_results=n,
        )

        items = []
        if results and results["metadatas"]:
            for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
                items.append({
                    "topic": meta.get("topic", ""),
                    "summary": meta.get("summary", ""),
                    "source": meta.get("source", ""),
                    "relevance": 1 - dist,
                })
        return items

    # ============================================================
    # 综合搜索
    # ============================================================

    def search(self, query, n_events=3, n_knowledge=2, min_importance=3):
        """综合搜索：同时检索事件和知识，返回合并结果"""
        events = self.search_events(query, n_results=n_events, min_importance=min_importance)
        knowledge = self.search_knowledge(query, n_results=n_knowledge)
        return {
            "events": events,
            "knowledge": knowledge,
        }

    def format_for_context(self, search_results, max_chars=500):
        """将搜索结果格式化为可注入 LLM context 的文本"""
        parts = []

        events = search_results.get("events", [])
        if events:
            relevant_events = [e for e in events if e.get("relevance", 0) > 0.3]
            if relevant_events:
                event_texts = [e["text"] for e in relevant_events[:3]]
                parts.append("相关回忆：" + "；".join(event_texts))

        knowledge = search_results.get("knowledge", [])
        if knowledge:
            relevant_k = [k for k in knowledge if k.get("relevance", 0) > 0.3]
            if relevant_k:
                k_texts = [f"{k['topic']}" for k in relevant_k[:2]]
                parts.append("相关知识：" + "；".join(k_texts))

        result = "\n".join(parts)
        return result[:max_chars] if result else ""

    # ============================================================
    # 批量导入（从现有 Memory 数据迁移）
    # ============================================================

    def import_from_daily_log(self, daily_log):
        """从 Memory 的 daily_log 列表导入"""
        count = 0
        for entry in daily_log:
            if isinstance(entry, dict):
                text = entry.get("event", entry.get("text", ""))
                importance = entry.get("importance", 5)
                ts = entry.get("timestamp", time.time())
            else:
                text = str(entry)
                importance = 5
                ts = time.time()
            if text:
                self.add_event(text, importance=importance, timestamp=ts)
                count += 1
        return count

    def import_from_knowledge_dir(self, knowledge_dir):
        """从 knowledge 目录导入"""
        count = 0
        if not os.path.exists(knowledge_dir):
            return 0
        for filename in os.listdir(knowledge_dir):
            if not filename.endswith(".md"):
                continue
            filepath = os.path.join(knowledge_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                topic = filename.replace(".md", "").replace("_", " ")
                if content.strip():
                    self.add_knowledge(topic, content[:500], source="knowledge_file")
                    count += 1
            except:
                pass
        return count

    # ============================================================
    # 统计
    # ============================================================

    def stats(self):
        return {
            "events": self._events.count(),
            "knowledge": self._knowledge.count(),
        }
