"""
Style RAG v3: 话题感知 + 质量优先的 few-shot 检索

改进点：
1. 话题分类索引：先按话题匹配，再按语义相似度排序
2. 质量优先：优先返回高质量(4分)和适合few-shot的样本
3. 碎片化优先：优先返回短小、碎片化的回复样本
4. 多样性：避免返回过于相似的样本
"""

import os
import hashlib
import json
import logging
import chromadb
from chromadb.utils import embedding_functions
from collections import defaultdict

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# 话题关键词映射（用于快速话题检测）
TOPIC_KEYWORDS = {
    "工作": ["上班", "加班", "老板", "同事", "工资", "辞职", "跳槽", "开会", "项目", "甲方", "下班", "摸鱼", "打工", "KPI", "绩效", "领导", "公司", "办公", "请假"],
    "穿搭": ["衣服", "裙子", "裤子", "鞋", "穿", "搭配", "好看", "颜色", "外套", "T恤", "卫衣", "牛仔", "风格", "显瘦", "时尚", "款式"],
    "健身": ["健身", "运动", "跑步", "瑜伽", "减肥", "体重", "肌肉", "锻炼", "训练", "卡路里", "蛋白", "增肌", "有氧", "撸铁", "keep", "腹肌"],
    "旅行": ["旅行", "旅游", "出去玩", "景点", "酒店", "机票", "攻略", "打卡", "拍照", "风景", "海边", "山", "度假", "民宿", "自驾"],
    "美食": ["吃", "饭", "火锅", "奶茶", "外卖", "好吃", "餐厅", "做饭", "烧烤", "甜品", "蛋糕", "零食", "夜宵", "饿", "点餐", "菜"],
    "学习": ["学习", "考试", "考研", "考公", "作业", "上课", "老师", "成绩", "分数", "复习", "背书", "图书馆", "论文", "毕业", "学校"],
    "娱乐": ["电影", "电视", "综艺", "游戏", "追剧", "音乐", "歌", "演唱会", "密室", "剧本杀", "KTV", "玩"],
    "宠物": ["猫", "狗", "宠物", "喵", "汪", "铲屎", "猫粮", "狗粮", "养", "毛", "爪", "可爱"],
    "颜值": ["化妆", "护肤", "口红", "眼影", "面膜", "素颜", "丑", "帅", "美", "发型", "头发", "染", "指甲", "防晒", "粉底"],
    "情感": ["喜欢", "爱", "分手", "暧昧", "表白", "男朋友", "女朋友", "老公", "老婆", "想你", "亲", "抱", "心疼", "吃醋"],
}


class StyleRAGv3:
    """话题感知 + 质量优先的 few-shot 检索"""

    def __init__(self, persist_dir, data_path=None):
        self.persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)

        self._ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )

        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name="style_v3",
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

        # 如果为空且有数据文件，导入
        if self._collection.count() == 0 and data_path:
            self._import_from_json(data_path)

    def _make_id(self, user_msg, assistant_msg):
        content = f"{user_msg}||{assistant_msg}"
        return hashlib.md5(content.encode()).hexdigest()

    def _import_from_json(self, data_path):
        """从JSON文件导入数据"""
        with open(data_path) as f:
            data = json.load(f)

        docs = []
        ids = []
        metas = []
        seen = set()

        for item in data:
            user_msg = item.get("user_msg", "")
            assistant_msg = item.get("assistant_msg", "")
            if not user_msg or not assistant_msg:
                continue

            doc_id = self._make_id(user_msg, assistant_msg)
            if doc_id in seen:
                continue
            seen.add(doc_id)

            # Calculate fragmentation score (碎片化程度)
            asst_clean = assistant_msg.replace("[表情]", "").replace("[图片]", "").strip()
            frag_score = 0
            if "\n" in assistant_msg:
                frag_score += 2
            if len(asst_clean) < 20:
                frag_score += 2
            elif len(asst_clean) < 40:
                frag_score += 1

            docs.append(user_msg)
            ids.append(doc_id)
            metas.append({
                "user_msg": user_msg,
                "assistant_msg": assistant_msg,
                "topic": item.get("topic", "日常"),
                "quality": item.get("quality", 3),
                "good_fewshot": item.get("good_fewshot", False),
                "gender": item.get("assistant_gender", "unknown"),
                "frag_score": frag_score,
                "asst_len": len(asst_clean),
            })

        # Batch add
        batch_size = 500
        for i in range(0, len(docs), batch_size):
            self._collection.add(
                documents=docs[i:i+batch_size],
                ids=ids[i:i+batch_size],
                metadatas=metas[i:i+batch_size],
            )

        logger.info(f"[StyleRAGv3] 导入 {len(docs)} 条样本")
        print(f"[StyleRAGv3] 导入 {len(docs)} 条样本")

    def detect_topic(self, text):
        """检测文本的话题"""
        text_lower = text.lower()
        scores = {}
        for topic, keywords in TOPIC_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[topic] = score
        
        if scores:
            return max(scores, key=scores.get)
        return "日常"

    def query(self, user_message, n_results=3, gender=None, topic=None):
        """
        智能检索 few-shot 样本
        
        策略：
        1. 检测话题
        2. 先尝试话题内检索高质量样本
        3. 如果话题内不够，用语义检索补充
        4. 优先返回碎片化、短小的样本
        """
        if self._collection.count() == 0:
            return []

        # Detect topic
        if not topic:
            topic = self.detect_topic(user_message)

        # Strategy: fetch more, then filter and rank
        fetch_n = min(n_results * 10, self._collection.count())

        # Try topic-filtered search first
        results_topic = None
        try:
            where_filter = {"topic": topic}
            results_topic = self._collection.query(
                query_texts=[user_message],
                n_results=min(fetch_n, self._collection.count()),
                where=where_filter,
            )
        except Exception:
            pass

        # Also do general semantic search
        results_general = self._collection.query(
            query_texts=[user_message],
            n_results=fetch_n,
        )

        # Merge and rank candidates
        candidates = []
        seen_ids = set()

        def add_candidates(results, source):
            if not results or not results["metadatas"]:
                return
            for i, meta in enumerate(results["metadatas"][0]):
                doc_id = results["ids"][0][i] if results["ids"] else None
                if doc_id and doc_id in seen_ids:
                    continue
                if doc_id:
                    seen_ids.add(doc_id)
                
                distance = results["distances"][0][i] if results.get("distances") else 1.0
                candidates.append({
                    "meta": meta,
                    "distance": distance,
                    "source": source,
                })

        if results_topic:
            add_candidates(results_topic, "topic")
        add_candidates(results_general, "general")

        # Score and rank candidates
        ranked = []
        for c in candidates:
            meta = c["meta"]
            score = 0

            # Topic match bonus
            if meta.get("topic") == topic:
                score += 3

            # Quality bonus
            quality = meta.get("quality", 3)
            score += quality * 1.5

            # Few-shot ready bonus
            if meta.get("good_fewshot"):
                score += 2

            # Fragmentation bonus (prefer short, fragmented replies)
            frag = meta.get("frag_score", 0)
            score += frag * 0.5

            # Short reply bonus
            asst_len = meta.get("asst_len", 50)
            if asst_len < 20:
                score += 1.5
            elif asst_len < 40:
                score += 0.8
            elif asst_len > 80:
                score -= 1

            # Semantic similarity bonus (lower distance = more similar)
            score += max(0, (1 - c["distance"]) * 2)

            ranked.append({
                "user": meta["user_msg"],
                "assistant": meta["assistant_msg"],
                "gender": meta.get("gender", "unknown"),
                "topic": meta.get("topic", "日常"),
                "score": score,
            })

        # Sort by score descending
        ranked.sort(key=lambda x: x["score"], reverse=True)

        # Diversity: avoid too similar examples
        selected = []
        selected_texts = set()
        for r in ranked:
            # Check diversity
            asst_short = r["assistant"][:20]
            if asst_short in selected_texts:
                continue
            selected_texts.add(asst_short)
            selected.append(r)
            if len(selected) >= n_results:
                break

        return selected

    def count(self):
        return self._collection.count()

    def stats(self):
        """返回数据库统计信息"""
        if self._collection.count() == 0:
            return {}
        
        data = self._collection.get()
        topics = defaultdict(int)
        qualities = defaultdict(int)
        fewshot_count = 0
        
        for meta in data["metadatas"]:
            topics[meta.get("topic", "unknown")] += 1
            qualities[meta.get("quality", 0)] += 1
            if meta.get("good_fewshot"):
                fewshot_count += 1
        
        return {
            "total": self._collection.count(),
            "topics": dict(topics),
            "qualities": dict(qualities),
            "fewshot_ready": fewshot_count,
        }
