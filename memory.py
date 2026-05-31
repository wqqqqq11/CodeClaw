"""
CodeClaw
"""

import json
import logging
import math
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("CodeClaw.memory")

# ──────────────────────────────────────────────────────────────
# 文本 → 向量嵌入（轻量级 TF-IDF 与 numpy）
# ──────────────────────────────────────────────────────────────

# 共享词汇表，随着新文本的摄取逐步构建。
# 将单词映射到向量中的索引。
_vocab: dict[str, int] = {}
_idf: dict[str, float] = {}  # 单词 → 逆文档频率
_doc_count: int = 0


def _tokenize(text: str) -> list[str]:
    """简单的空白符 + 标点符号分词器，小写处理。"""
    return re.findall(r"[a-zA-Z0-9\u00C0-\u024F]+", text.lower())


def _compute_embedding(text: str) -> bytes:
    """为给定文本计算类 TF-IDF 向量并以字节形式返回。"""
    global _doc_count
    tokens = _tokenize(text)
    if not tokens:
        return b""

    # 更新词汇表
    for t in tokens:
        if t not in _vocab:
            _vocab[t] = len(_vocab)

    # 词频（归一化）
    tf = Counter(tokens)
    max_freq = max(tf.values())

    vec = np.zeros(len(_vocab), dtype=np.float32)
    for word, count in tf.items():
        idx = _vocab[word]
        # 简单的 TF 权重
        vec[idx] = count / max_freq

    # 归一化为单位向量以用于余弦相似度
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm

    return vec.tobytes()


def _embedding_from_bytes(data: bytes) -> np.ndarray | None:
    """从存储的字节重构 numpy 向量。"""
    if not data:
        return None
    return np.frombuffer(data, dtype=np.float32)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """两个可能不同长度的向量之间的余弦相似度。"""
    # 填充较短的向量以匹配较长向量
    max_len = max(len(a), len(b))
    if len(a) < max_len:
        a = np.pad(a, (0, max_len - len(a)))
    if len(b) < max_len:
        b = np.pad(b, (0, max_len - len(b)))

    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


# ──────────────────────────────────────────────────────────────
# 记忆存储
# ──────────────────────────────────────────────────────────────


@dataclass
class MemoryRecord:
    id: int
    timestamp: float
    role: str
    content: str
    session_id: str
    similarity: float = 0.0


class MemoryStore:
    """
    具有语义召回的持久化记忆。

    使用 SQLite 进行存储，使用 TF-IDF 向量进行相似度搜索。
    每次交互都被存储，并可基于与查询的语义相似度被召回——
    实现跨会话的"无限记忆"。
    """

    def __init__(self, db_path: str = "CodeClaw.db"):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self._init_db()
        self._rebuild_vocab()

    def _init_db(self):
        """如果表不存在则创建表。"""
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                session_id TEXT NOT NULL,
                embedding BLOB
            );
            CREATE INDEX IF NOT EXISTS idx_interactions_session
                ON interactions(session_id);
            CREATE INDEX IF NOT EXISTS idx_interactions_timestamp
                ON interactions(timestamp);

            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                summary TEXT DEFAULT '',
                updated REAL
            );
        """)
        self.db.commit()

    def _rebuild_vocab(self):
        """在启动时从所有存储的交互重建词汇表。"""
        global _vocab, _doc_count
        cursor = self.db.execute("SELECT content FROM interactions")
        _doc_count = 0
        for (content,) in cursor:
            _doc_count += 1
            for token in _tokenize(content):
                if token not in _vocab:
                    _vocab[token] = len(_vocab)
        if _vocab:
            log.info(f"重建词汇表：{_doc_count} 次交互中的 {len(_vocab)} 个词项")

    # ── 摄取 ────────────────────────────────────────────────

    def ingest(self, role: str, content: str, session_id: str):
        """将交互及其嵌入保存到数据库。"""
        global _doc_count
        if not content.strip():
            return

        embedding = _compute_embedding(content)
        _doc_count += 1

        self.db.execute(
            "INSERT INTO interactions (timestamp, role, content, session_id, embedding) VALUES (?, ?, ?, ?, ?)",
            (time.time(), role, content, session_id, embedding),
        )
        self.db.commit()

    # ── 召回 (RAG) ──────────────────────────────────────────

    def recall(self, query: str, top_k: int = 5, exclude_session: str | None = None) -> list[MemoryRecord]:
        """
        查找语义上最相似的 top_k 个过往交互。
        这是 RAG 检索步骤——在每次 LLM 提示之前调用。
        """
        query_embedding = _compute_embedding(query)
        if not query_embedding:
            return []
        query_vec = _embedding_from_bytes(query_embedding)
        if query_vec is None:
            return []

        # 获取所有嵌入（对于中小型数据集这没问题；
        # 对于非常大的数据库，切换到 FAISS 或类似方案）
        sql = "SELECT id, timestamp, role, content, session_id, embedding FROM interactions"
        params: list = []
        if exclude_session:
            sql += " WHERE session_id != ?"
            params.append(exclude_session)

        cursor = self.db.execute(sql, params)
        scored: list[tuple[float, MemoryRecord]] = []

        for row in cursor:
            rec_id, ts, role, content, sid, emb_bytes = row
            if not emb_bytes:
                continue
            stored_vec = _embedding_from_bytes(emb_bytes)
            if stored_vec is None:
                continue

            sim = _cosine_similarity(query_vec, stored_vec)
            if sim > 0.05:  # 阈值
                record = MemoryRecord(
                    id=rec_id, timestamp=ts, role=role,
                    content=content, session_id=sid, similarity=sim,
                )
                scored.append((sim, record))

        # 按相似度降序排序，返回 top_k
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]

    # ── 近期历史 ────────────────────────────────────────

    def get_recent(self, session_id: str, limit: int = 20) -> list[dict]:
        """获取会话的近期消息（用于即时上下文）。"""
        cursor = self.db.execute(
            "SELECT role, content FROM interactions WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
            (session_id, limit),
        )
        rows = cursor.fetchall()
        rows.reverse()  # 按时间顺序
        return [{"role": role, "content": content} for role, content in rows]

    # ── 会话摘要 ───────────────────────────────────────

    def get_summary(self, session_id: str) -> str:
        """获取会话的存储摘要。"""
        cursor = self.db.execute(
            "SELECT summary FROM sessions WHERE session_id = ?", (session_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else ""

    def set_summary(self, session_id: str, summary: str):
        """存储或更新会话摘要。"""
        self.db.execute(
            "INSERT INTO sessions (session_id, summary, updated) VALUES (?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET summary = ?, updated = ?",
            (session_id, summary, time.time(), summary, time.time()),
        )
        self.db.commit()

    # ── 统计 ─────────────────────────────────────────────────

    def stats(self) -> dict:
        """返回记忆统计信息。"""
        total = self.db.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
        sessions = self.db.execute("SELECT COUNT(DISTINCT session_id) FROM interactions").fetchone()[0]
        vocab_size = len(_vocab)
        return {
            "total_interactions": total,
            "unique_sessions": sessions,
            "vocabulary_size": vocab_size,
        }

    # ── 清除 ─────────────────────────────────────────────────

    def clear_session(self, session_id: str):
        """删除特定会话的所有交互。"""
        self.db.execute("DELETE FROM interactions WHERE session_id = ?", (session_id,))
        self.db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        self.db.commit()

    def delete_delegation_transcripts(self, session_id: str) -> int:
        """删除作为本地代理委派记录的助手消息。"""
        cursor = self.db.execute(
            "DELETE FROM interactions "
            "WHERE session_id = ? AND role = 'assistant' AND content LIKE ?",
            (session_id, "🤖 Delegated to %"),
        )
        self.db.commit()
        return int(cursor.rowcount or 0)

    def clear_all(self):
        """删除所有会话的所有记忆数据。"""
        global _vocab, _idf, _doc_count
        self.db.execute("DELETE FROM interactions")
        self.db.execute("DELETE FROM sessions")
        self.db.commit()
        _vocab.clear()
        _idf.clear()
        _doc_count = 0

    def format_memories_for_prompt(self, memories: list[MemoryRecord]) -> str:
        """格式化召回的记忆以注入系统提示。"""
        if not memories:
            return ""

        lines = ["## Recalled Memories", ""]
        for m in memories:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(m.timestamp))
            lines.append(f"- [{ts}] {m.role}: {m.content[:200]}")
        return "\n".join(lines)
