"""
Style RAG: 基于向量检索的动态 few-shot 风格样本选择。

核心思路：
- 所有 few-shot 对话样本存入 chromadb（用 multilingual embedding）
- 每次聊天前，用当前对话上下文做语义检索
- 取 top-k 最相关的 few-shot 注入 LLM context
- 随着浏览学习到更多样本，风格库越来越丰富
"""

import os
import hashlib
import logging
import chromadb

from memory_rag import get_shared_ef

logger = logging.getLogger(__name__)


class StyleRAG:
    """管理 few-shot 风格样本的向量检索"""

    def __init__(self, persist_dir, few_shot_path=None):
        """
        persist_dir: chromadb 持久化目录
        few_shot_path: few_shot.md 文件路径（初始化时导入）
        """
        self.persist_dir = persist_dir
        self.few_shot_path = few_shot_path
        os.makedirs(persist_dir, exist_ok=True)

        # 复用 MemoryRAG 的共享 embedding function（避免模型加载两次）
        self._ef = get_shared_ef()

        # 初始化 chromadb（持久化模式）
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name="style_examples",
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

        # 如果 collection 是空的，从 few_shot 文件导入
        if self._collection.count() == 0 and few_shot_path:
            self._import_from_file(few_shot_path)

    def _parse_few_shot_blocks(self, text):
        """解析 few-shot 文件为 (user_msg, assistant_msg) 对列表"""
        blocks = text.strip().split("\n\n")
        examples = []
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.split("\n")
            user_msg = ""
            assistant_parts = []
            for line in lines:
                line = line.strip()
                if line.startswith("- user:"):
                    user_msg = line.replace("- user:", "").strip()
                elif line.startswith("- assistant:"):
                    assistant_parts.append(line.replace("- assistant:", "").strip())
            if user_msg and assistant_parts:
                examples.append((user_msg, "\n".join(assistant_parts)))
        return examples

    def _import_from_file(self, filepath):
        """从 few_shot.md 文件导入样本"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            logger.warning("[StyleRAG] 文件不存在: %s", filepath)
            return 0

        examples = self._parse_few_shot_blocks(text)
        return self._add_examples(examples)

    def _make_id(self, user_msg, assistant_msg):
        """生成唯一 ID"""
        content = f"{user_msg}||{assistant_msg}"
        return hashlib.md5(content.encode()).hexdigest()

    def _add_examples(self, examples):
        """批量添加样本，自动去重"""
        if not examples:
            return 0

        # 获取已有 ID 集合
        existing_ids = set()
        if self._collection.count() > 0:
            all_data = self._collection.get()
            existing_ids = set(all_data["ids"])

        new_docs = []
        new_ids = []
        new_metas = []
        for user_msg, assistant_msg in examples:
            doc_id = self._make_id(user_msg, assistant_msg)
            if doc_id in existing_ids:
                continue
            # document 用 user_msg 做检索（因为我们要根据用户说的话找相似的样本）
            new_docs.append(user_msg)
            new_ids.append(doc_id)
            new_metas.append({
                "user_msg": user_msg,
                "assistant_msg": assistant_msg,
            })

        if new_docs:
            self._collection.add(
                documents=new_docs,
                ids=new_ids,
                metadatas=new_metas,
            )
            logger.info("[StyleRAG] 添加了 %d 组新样本，总计 %d", len(new_docs), self._collection.count())

        return len(new_docs)

    def add_example(self, user_msg, assistant_msg):
        """添加单个样本"""
        return self._add_examples([(user_msg, assistant_msg)])

    def add_examples_from_text(self, text):
        """从 few-shot 格式的文本中解析并添加样本"""
        examples = self._parse_few_shot_blocks(text)
        return self._add_examples(examples)

    def sync_from_file(self, filepath=None):
        """从 few_shot 文件同步（增量导入新增的样本）"""
        filepath = filepath or self.few_shot_path
        if not filepath:
            return 0
        return self._import_from_file(filepath)

    def query(self, user_message, n_results=5, recent_context=None):
        """
        根据用户消息检索最相关的 few-shot 样本。

        user_message: 当前用户消息
        n_results: 返回数量
        recent_context: 最近几条对话（可选，用于增强检索）

        返回: [{"user": "...", "assistant": "..."}, ...]
        """
        if self._collection.count() == 0:
            return []

        # 构建查询文本：当前消息 + 最近上下文
        query_text = user_message
        if recent_context:
            # 取最近 3 条用户消息拼接
            recent_user_msgs = [
                m["content"] for m in recent_context[-6:]
                if m.get("role") == "user"
            ][-3:]
            if recent_user_msgs:
                query_text = " ".join(recent_user_msgs) + " " + user_message

        n = min(n_results, self._collection.count())
        results = self._collection.query(
            query_texts=[query_text],
            n_results=n,
        )

        examples = []
        if results and results["metadatas"]:
            for meta in results["metadatas"][0]:
                examples.append({
                    "user": meta["user_msg"],
                    "assistant": meta["assistant_msg"],
                })
        return examples

    def to_few_shot_messages(self, examples):
        """将检索结果转换为 LLM messages 格式"""
        messages = []
        for ex in examples:
            messages.append({"role": "user", "content": ex["user"]})
            messages.append({"role": "assistant", "content": ex["assistant"]})
        return messages

    def count(self):
        """返回样本总数"""
        return self._collection.count()

    def get_all(self):
        """返回所有样本"""
        if self._collection.count() == 0:
            return []
        data = self._collection.get()
        examples = []
        for meta in data["metadatas"]:
            examples.append({
                "user": meta["user_msg"],
                "assistant": meta["assistant_msg"],
            })
        return examples
