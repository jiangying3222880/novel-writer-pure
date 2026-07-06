"""
app/ai/cache.py - M9-A2: LLM 响应二级缓存.

设计:
- L1 内存 LRU (OrderedDict 真 LRU, 容量 256)
- L2 磁盘 SQLite (按 cache_key 索引, JSON 存 LLMResult)
- 命中顺序: 内存 → 磁盘 → 未命中
- 写顺序: 内存 + 磁盘 (同时)
- 统计: hit / miss / 命中率
- TTL: 可选过期 (默认永不过期, 0 = 永不过期)
- 持久化路径: ~/.novel-writer-pure-v3.4/cache/llm_cache.db

为什么不用 pickle/jsonpickle 序列化 LLMResult?
- LLMResult 是 dataclass, json.dumps(asdict) 即可
- raw 字段可能含 provider 私有对象, 跳过不存
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path
from typing import Optional, Dict, Any

from app.core.interfaces import LLMResult

_logger = logging.getLogger("NovelWriter.ai.cache")


# ============================================================
# L1: 真 LRU 内存缓存
# ============================================================

class InMemoryLRUCache:
    """A2 升级: OrderedDict 实现真 LRU (A1 是 FIFO).

    - max_size: 容量, 满了 pop oldest (last=Least Recently Used)
    - 命中即 move_to_end, 这样尾部是最新, 头部是最久未用
    - 线程安全: 加 lock
    """

    def __init__(self, max_size: int = 256) -> None:
        self._max_size = max_size
        self._data: "OrderedDict[str, LLMResult]" = OrderedDict()
        self._lock = threading.Lock()
        # 统计
        self.hit_count = 0
        self.miss_count = 0

    def get(self, key: str) -> Optional[LLMResult]:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)  # mark as recently used
                self.hit_count += 1
                return self._data[key]
            self.miss_count += 1
            return None

    def put(self, key: str, result: LLMResult) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self._data[key] = result
                return
            if len(self._data) >= self._max_size:
                evicted_key, _ = self._data.popitem(last=False)
                _logger.debug("L1 cache evict: %s", evicted_key[:8])
            self._data[key] = result

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hit_count = 0
            self.miss_count = 0

    def stats(self) -> dict:
        with self._lock:
            total = self.hit_count + self.miss_count
            return {
                "size": len(self._data),
                "max_size": self._max_size,
                "hit": self.hit_count,
                "miss": self.miss_count,
                "hit_rate": round(self.hit_count / total, 4) if total else 0.0,
            }


# ============================================================
# L2: 磁盘 SQLite 缓存
# ============================================================

class DiskSqliteCache:
    """A2 新增: 持久化 LLM 响应缓存.

    Schema:
        llm_cache(
            key TEXT PRIMARY KEY,
            content TEXT, model TEXT, provider TEXT,
            input_tokens INT, output_tokens INT, cost REAL, duration_ms INT,
            created_at REAL
        )

    - 写: 同步落盘 (sqlite 默认 WAL)
    - 读: O(1) by key
    - 清: clear() 删全部
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS llm_cache (
        key TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        model TEXT,
        provider TEXT,
        input_tokens INTEGER,
        output_tokens INTEGER,
        cost REAL,
        duration_ms INTEGER,
        created_at REAL
    );
    CREATE INDEX IF NOT EXISTS idx_llm_cache_created ON llm_cache(created_at);
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
        self.hit_count = 0
        self.miss_count = 0

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path), timeout=10)
            try:
                conn.executescript(self.SCHEMA)
                conn.commit()
            finally:
                conn.close()

    def get(self, key: str) -> Optional[LLMResult]:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path), timeout=10)
            try:
                row = conn.execute(
                    "SELECT content, model, provider, input_tokens, output_tokens, "
                    "cost, duration_ms FROM llm_cache WHERE key=?",
                    (key,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            self.miss_count += 1
            return None
        self.hit_count += 1
        return LLMResult(
            content=row[0],
            model=row[1] or "",
            provider=row[2] or "",
            input_tokens=row[3] or 0,
            output_tokens=row[4] or 0,
            cost=row[5] or 0.0,
            duration_ms=row[6] or 0,
        )

    def put(self, key: str, result: LLMResult) -> None:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path), timeout=10)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO llm_cache "
                    "(key, content, model, provider, input_tokens, output_tokens, cost, duration_ms, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        key,
                        result.content,
                        result.model,
                        result.provider,
                        result.input_tokens,
                        result.output_tokens,
                        result.cost,
                        result.duration_ms,
                        time.time(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def clear(self) -> None:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path), timeout=10)
            try:
                conn.execute("DELETE FROM llm_cache")
                conn.commit()
            finally:
                conn.close()
            self.hit_count = 0
            self.miss_count = 0

    def size(self) -> int:
        """查询 cache 条目数. 假设调用者已持有 _lock (被 stats / clear 等内部调用)."""
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        try:
            return conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
        finally:
            conn.close()

    def stats(self) -> dict:
        with self._lock:
            return {
                "size": self.size(),
                "path": str(self._db_path),
                "hit": self.hit_count,
                "miss": self.miss_count,
                "hit_rate": round(
                    self.hit_count / (self.hit_count + self.miss_count), 4
                ) if (self.hit_count + self.miss_count) else 0.0,
            }


# ============================================================
# 二级组合: 内存 L1 + 磁盘 L2
# ============================================================

class TieredCache:
    """A2 主交付: 内存 L1 + 磁盘 L2 二级缓存.

    读路径:
        1. 查 L1 (内存) — 命中即返
        2. miss → 查 L2 (磁盘) — 命中即返 + 回填 L1
        3. 都 miss → 返回 None

    写路径:
        - 同时写 L1 和 L2 (回写策略)
    """

    def __init__(
        self,
        mem_cache: Optional[InMemoryLRUCache] = None,
        disk_cache: Optional[DiskSqliteCache] = None,
    ) -> None:
        self.l1 = mem_cache or InMemoryLRUCache()
        self.l2 = disk_cache

    def get(self, key: str) -> Optional[LLMResult]:
        # 1) L1
        r = self.l1.get(key)
        if r is not None:
            return r
        # 2) L2
        if self.l2 is None:
            return None
        r = self.l2.get(key)
        if r is not None:
            # 回填 L1
            self.l1.put(key, r)
        return r

    def put(self, key: str, result: LLMResult) -> None:
        self.l1.put(key, result)
        if self.l2 is not None:
            self.l2.put(key, result)

    def clear(self) -> None:
        self.l1.clear()
        if self.l2 is not None:
            self.l2.clear()

    def stats(self) -> dict:
        out = {"l1": self.l1.stats()}
        if self.l2 is not None:
            out["l2"] = self.l2.stats()
        return out
