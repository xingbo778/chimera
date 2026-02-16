"""
Style RAG v2: 基于向量检索的动态 few-shot 风格样本选择。
新增功能：支持性别过滤（男/女风格）

核心思路：
- 所有 few-shot 对话样本存入 chromadb（用 multilingual embedding）
- 每次聊天前，用当前对话上下文做语义检索
- 取 top-k 最相关的 few-shot 注入 LLM context
- 支持按性别过滤，返回特定性别风格的样本
- 素材来源：真实微信聊天截图 → 视觉大模型提取
"""

import os
import hashlib
import logging
import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

# 使用 multilingual 模型，中文效果好
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


class StyleRAG:
    """管理 few-shot 风格样本的向量检索，支持性别过滤"""

    def __init__(self, persist_dir, few_shot_path=None):
        """
        persist_dir: chromadb 持久化目录
        few_shot_path: few_shot.md 文件路径（初始化时导入）
        """
        self.persist_dir = persist_dir
        self.few_shot_path = few_shot_path
        os.makedirs(persist_dir, exist_ok=True)

        # 初始化 embedding function
        self._ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )

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
        """解析 few-shot 文件为 (user_msg, assistant_msg, gender) 元组列表"""
        blocks = text.strip().split("\n\n")
        examples = []
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.split("\n")
            user_msg = ""
            assistant_parts = []
            gender = "unknown"
            for line in lines:
                line = line.strip()
                if line.startswith("- user:"):
                    user_msg = line.replace("- user:", "").strip()
                elif line.startswith("- assistant:"):
                    part = line.replace("- assistant:", "").strip()
                    # 检查是否有性别标签
                    if part.endswith("[male]"):
                        gender = "male"
                        part = part[:-6].strip()
                    elif part.endswith("[female]"):
                        gender = "female"
                        part = part[:-8].strip()
                    assistant_parts.append(part)
            if user_msg and assistant_parts:
                examples.append((user_msg, "\n".join(assistant_parts), gender))
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
        # 转换为带gender的格式
        return self._add_examples_with_gender(examples)

    def _make_id(self, user_msg, assistant_msg):
        """生成唯一 ID"""
        content = f"{user_msg}||{assistant_msg}"
        return hashlib.md5(content.encode()).hexdigest()

    def _add_examples_with_gender(self, examples):
        """批量添加带性别标签的样本，自动去重
        examples: [(user_msg, assistant_msg, gender), ...]
        """
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
        seen_ids = set()
        
        for item in examples:
            if len(item) == 3:
                user_msg, assistant_msg, gender = item
            else:
                user_msg, assistant_msg = item
                gender = "unknown"
                
            doc_id = self._make_id(user_msg, assistant_msg)
            if doc_id in existing_ids or doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)
            
            new_docs.append(user_msg)
            new_ids.append(doc_id)
            new_metas.append({
                "user_msg": user_msg,
                "assistant_msg": assistant_msg,
                "gender": gender,
            })

        if new_docs:
            # 分批添加避免超限
            batch_size = 500
            for i in range(0, len(new_docs), batch_size):
                self._collection.add(
                    documents=new_docs[i:i+batch_size],
                    ids=new_ids[i:i+batch_size],
                    metadatas=new_metas[i:i+batch_size],
                )
            logger.info("[StyleRAG] 添加了 %d 组新样本，总计 %d", len(new_docs), self._collection.count())

        return len(new_docs)

    def _add_examples(self, examples):
        """批量添加样本（兼容旧接口），自动去重"""
        # 转换为带gender的格式
        converted = [(u, a, "unknown") for u, a in examples]
        return self._add_examples_with_gender(converted)

    def add_example(self, user_msg, assistant_msg, gender="unknown"):
        """添加单个样本"""
        return self._add_examples_with_gender([(user_msg, assistant_msg, gender)])

    def add_examples_from_text(self, text):
        """从 few-shot 格式的文本中解析并添加样本"""
        examples = self._parse_few_shot_blocks(text)
        return self._add_examples_with_gender(examples)

    def sync_from_file(self, filepath=None):
        """从 few_shot 文件同步（增量导入新增的样本）"""
        filepath = filepath or self.few_shot_path
        if not filepath:
            return 0
        return self._import_from_file(filepath)

    def query(self, user_message, n_results=5, recent_context=None, gender=None):
        """
        根据用户消息检索最相关的 few-shot 样本。

        user_message: 当前用户消息
        n_results: 返回数量
        recent_context: 最近几条对话（可选，用于增强检索）
        gender: 性别过滤 ("male", "female", None=不过滤)

        返回: [{"user": "...", "assistant": "...", "gender": "..."}, ...]
        """
        if self._collection.count() == 0:
            return []

        # 构建查询文本：当前消息 + 最近上下文
        query_text = user_message
        if recent_context:
            recent_user_msgs = [
                m["content"] for m in recent_context[-6:]
                if m.get("role") == "user"
            ][-3:]
            if recent_user_msgs:
                query_text = " ".join(recent_user_msgs) + " " + user_message

        # 如果有性别过滤，多取一些再过滤
        fetch_n = n_results * 3 if gender else n_results
        fetch_n = min(fetch_n, self._collection.count())
        
        # 构建where过滤条件
        where_filter = None
        if gender:
            where_filter = {"gender": gender}
        
        try:
            results = self._collection.query(
                query_texts=[query_text],
                n_results=fetch_n,
                where=where_filter,
            )
        except Exception:
            # 如果where过滤失败（比如没有gender字段），回退到不过滤
            results = self._collection.query(
                query_texts=[query_text],
                n_results=fetch_n,
            )

        examples = []
        if results and results["metadatas"]:
            for meta in results["metadatas"][0]:
                ex = {
                    "user": meta["user_msg"],
                    "assistant": meta["assistant_msg"],
                    "gender": meta.get("gender", "unknown"),
                }
                # 如果有性别过滤但where不生效，手动过滤
                if gender and ex["gender"] != gender:
                    continue
                examples.append(ex)
                if len(examples) >= n_results:
                    break
        
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

    def count_by_gender(self):
        """按性别统计样本数"""
        if self._collection.count() == 0:
            return {"male": 0, "female": 0, "unknown": 0}
        data = self._collection.get()
        counts = {"male": 0, "female": 0, "unknown": 0}
        for meta in data["metadatas"]:
            g = meta.get("gender", "unknown")
            counts[g] = counts.get(g, 0) + 1
        return counts

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
                "gender": meta.get("gender", "unknown"),
            })
        return examples
