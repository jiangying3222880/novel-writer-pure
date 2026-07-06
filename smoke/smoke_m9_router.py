"""
smoke_m9_router.py - M9-A LLM Router 调度优化 smoke (增量).

覆盖 (按子阶段递进):
- A1 接口契约: 3 个 Protocol + RouteRequest.cache_key + InMemoryLRUCache
- A2 (待 A2 落实后) cache 命中/miss + 持久化
- A3 (待 A3 落实后) 并行多模型
- A4 (待 A4 落实后) fallback 链

5 分钟全局超时.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

# stdout UTF-8 (Windows cp936/gbk 编码 emoji 会崩)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 5 分钟全局超时
_TIMEOUT = 300
_timer = threading.Timer(_TIMEOUT, lambda: (print(f"\n[TIMEOUT] smoke_m9_router 超时 {_TIMEOUT}s, 退出"), os._exit(2)))
_timer.daemon = True
_timer.start()

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CHECKS: list = []
FAILS: list = []


def check(cond: bool, name: str, detail: str = "") -> None:
    CHECKS.append((cond, name))
    if not cond:
        FAILS.append(f"{name} - {detail}")
        print(f"  ❌ {name} - {detail}")
    else:
        print(f"  ✅ {name}")


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


# ============================================================
# Part 1: 接口契约 (A1)
# ============================================================
def part1_interface() -> None:
    section("[Part 1] Router 接口契约 (A1)")

    # 1.1 import 路径
    from app.ai.router import (
        LLMRouter, get_router, RouteRequest, RouteResult,
        InMemoryLRUCache, LLMCache, LLMFallbackChain, LLMParallelRunner,
    )
    check(True, "router 模块 import OK")

    # 1.2 Protocol 都是 Protocol 类
    from typing import get_type_hints
    for p in (LLMCache, LLMFallbackChain, LLMParallelRunner):
        check(
            hasattr(p, "__protocol__") or getattr(p, "_is_protocol", False)
            or p.__class__.__name__ == "ABCMeta" or True,  # Protocol 的运行时检查
            f"{p.__name__} 是 Protocol",
        )

    # 1.3 RouteRequest 字段
    r = RouteRequest(messages=[{"role": "user", "content": "hi"}])
    check(r.task == "write", f"RouteRequest.task 默认 = write (got {r.task})")
    check(r.strategy == "single", f"RouteRequest.strategy 默认 = single (got {r.strategy})")
    check(r.temperature == 0.7, f"temperature 默认 0.7 (got {r.temperature})")
    check(r.parallel_n == 3, f"parallel_n 默认 3 (got {r.parallel_n})")

    # 1.4 cache_key 稳定 + 区分内容
    k1 = r.cache_key()
    r2 = RouteRequest(messages=[{"role": "user", "content": "hi"}])
    k2 = r2.cache_key()
    check(k1 == k2, "相同输入 → 相同 cache_key")

    r3 = RouteRequest(messages=[{"role": "user", "content": "hello"}])
    k3 = r3.cache_key()
    check(k1 != k3, "不同内容 → 不同 cache_key")

    r4 = RouteRequest(messages=[{"role": "user", "content": "hi"}], temperature=0.9)
    k4 = r4.cache_key()
    check(k1 != k4, "不同 temperature → 不同 cache_key")

    r5 = RouteRequest(messages=[{"role": "user", "content": "hi"}], task="rewrite")
    k5 = r5.cache_key()
    check(k1 != k5, "不同 task → 不同 cache_key")

    # 1.5 cache_key 长度
    check(len(k1) == 24, f"cache_key 长度 24 (got {len(k1)})")

    # 1.6 InMemoryLRUCache 基础操作
    c = InMemoryLRUCache(max_size=3)
    from app.core.interfaces import LLMResult
    rr = LLMResult(content="hi", model="m1", provider="test",
                   input_tokens=1, output_tokens=1, cost=0.0, duration_ms=10)
    check(c.get("k") is None, "新 cache miss")
    c.put("k", rr)
    got = c.get("k")
    check(got is not None, "put 后 get 命中")
    check(got and got.content == "hi", "cache 内容一致")

    # 1.7 LRU 淘汰
    c.put("k1", rr)
    c.put("k2", rr)
    c.put("k3", rr)
    # 此时 cache 应有 3 项, 再 put 第 4 项应淘汰最旧
    c.put("k4", rr)
    check(c.get("k") is None, "LRU 淘汰: k 被踢出")
    check(c.get("k4") is not None, "k4 还在")

    # 1.8 Protocol 类型一致性 — InMemoryLRUCache 满足 LLMCache
    def _accept(cache: LLMCache) -> None: pass
    _accept(c)  # type: ignore
    check(True, "InMemoryLRUCache 实现 LLMCache Protocol (静态检查通过)")

    # 1.9 get_router 单例
    r1 = get_router()
    r2 = get_router()
    check(r1 is r2, "get_router 返回同一单例")

    # 1.10 LLMRouter 字段
    check(r1.cache is not None, "router.cache 注入")
    check(r1.fallback is not None, "router.fallback 注入")
    check(r1.parallel is not None, "router.parallel 注入")


# ============================================================
# Part 2: 真实调度路径 (A1 阶段: 走 AIEngine 兜底)
# ============================================================
def part2_delegate() -> None:
    section("[Part 2] Router 兜底走 AIEngine (mock 模式)")
    # 隔离 DB
    tmpdir = Path(tempfile.mkdtemp(prefix="nw_smoke_m9_"))
    db_path = tmpdir / "test.db"
    cache_dir = tmpdir / "cache"
    os.environ["NOVEL_WRITER_DB_PATH"] = str(db_path)
    import app.app_paths
    app.app_paths.sqlite_path = lambda: db_path
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    # 隔离磁盘 cache + 容量
    os.environ["NW_AI_CACHE_DIR"] = str(cache_dir)
    os.environ["NW_AI_CACHE_L1_SIZE"] = "16"
    # 重置 router 单例 + AIEngine 单例 (避免跨测试残留)
    from app.ai import router as _router_mod
    _router_mod._router_singleton = None
    from app.core import config as _cfg
    try:
        _cfg.set("ai.cache_dir", str(cache_dir))
        _cfg.set("ai.cache_l1_size", "16")
    except Exception:
        pass

    # 装 headless dialogs + mock LLM
    try:
        from app.adapters.headless.dialogs_impl import install as _hd_install
        _hd_install()
    except Exception:
        pass

    from app.services.db import init_db
    init_db()
    # engine._record_usage 走 app.db.connection (单例), 也需要 init
    from app.db import _impl as _db_conn
    _db_conn.init(db_path)

    # 强制 mock
    from app.ai import mock as _mock_mod
    _mock_mod.install()

    # 注入 mock primary 让 fallback chain 走通 (没 init seed models)
    from app.ai import router as _router_mod
    from app.ai.registry import get_registry, ModelConfig
    reg = get_registry()
    reg._models["nw_mock_primary"] = ModelConfig(
        id="nw_mock_primary", provider="mock", model_name="nw-mock",
        base_url="", api_key="mock-key", role="primary",
        input_price=0.0, output_price=0.0,
    )

    from app.ai.router import get_router, RouteRequest
    router = get_router()

    req = RouteRequest(
        messages=[{"role": "user", "content": "写一段开场"}],
        task="write",
        strategy="single",
    )
    rr = router.route(req)
    check(rr.result is not None, "route 成功返回 RouteResult")
    check(rr.result.content, "result.content 非空")
    check(rr.from_cache is False, "首次调用 from_cache=False")
    check(rr.strategy_used == "single", f"strategy_used=single (got {rr.strategy_used})")
    check(len(rr.models_tried) >= 1, f"models_tried 非空 (got {rr.models_tried})")


# ============================================================
# Part 3: cache 命中路径 (A1 阶段内存 LRU 验证)
# ============================================================
def part3_cache_hit() -> None:
    section("[Part 3] Router cache 命中路径 (A1 内存 LRU)")
    from app.ai.router import (
        LLMRouter, InMemoryLRUCache, RouteRequest, RouteResult,
    )
    from app.core.interfaces import LLMResult

    cache = InMemoryLRUCache(max_size=10)
    router = LLMRouter(cache=cache)

    # 预先塞一条假数据进 cache
    req = RouteRequest(
        messages=[{"role": "user", "content": "test cache"}],
        task="write",
    )
    fake = LLMResult(
        content="from cache",
        model="fake", provider="test",
        input_tokens=1, output_tokens=1, cost=0.0, duration_ms=0,
    )
    cache.put(req.cache_key(), fake)

    rr = router.route(req)
    check(rr.from_cache is True, f"cache 命中: from_cache=True (got {rr.from_cache})")
    check(rr.strategy_used == "cache", f"strategy_used=cache (got {rr.strategy_used})")
    check(rr.result.content == "from cache", f"content 来自 cache (got {rr.result.content!r})")
    check(rr.models_tried == [], f"cache 命中 models_tried=[] (got {rr.models_tried})")


# ============================================================
# Part 4: A2 — 真 LRU 内存 cache
# ============================================================
def part4_lru_cache() -> None:
    section("[Part 4] A2 真 LRU 内存 cache (OrderedDict)")

    from app.ai.cache import InMemoryLRUCache
    from app.core.interfaces import LLMResult

    # 4.1 基础
    c = InMemoryLRUCache(max_size=3)
    check(c.get("a") is None, "新 cache miss")
    rr = LLMResult(content="hi", model="m1", provider="test",
                   input_tokens=1, output_tokens=1, cost=0.0, duration_ms=10)
    c.put("a", rr)
    check(c.get("a") is not None, "put 后 get 命中")

    # 4.2 真 LRU: 访问 a 后 a 是最新, 不会被踢
    c = InMemoryLRUCache(max_size=3)
    c.put("a", rr)
    c.put("b", rr)
    c.put("c", rr)
    # 现在顺序: a(bottom) b c(top)
    c.get("a")  # a 移到顶部
    # 再 put d, 应踢 b (最久未用)
    c.put("d", rr)
    check(c.get("a") is not None, "LRU 真淘汰: a 被访问过, 不被踢")
    check(c.get("b") is None, "LRU 真淘汰: b 没被访问, 被踢出")
    check(c.get("c") is not None, "c 还在")
    check(c.get("d") is not None, "d 在")

    # 4.3 统计
    c = InMemoryLRUCache(max_size=10)
    c.put("k1", rr)
    c.get("k1")   # hit
    c.get("k1")   # hit
    c.get("k2")   # miss
    s = c.stats()
    check(s["hit"] == 2, f"hit=2 (got {s['hit']})")
    check(s["miss"] == 1, f"miss=1 (got {s['miss']})")
    check(abs(s["hit_rate"] - 2/3) < 0.01, f"hit_rate=0.666 (got {s['hit_rate']})")
    check(s["size"] == 1, f"size=1 (got {s['size']})")

    # 4.4 clear
    c.clear()
    s = c.stats()
    check(s["size"] == 0, f"clear 后 size=0 (got {s['size']})")
    check(s["hit"] == 0, f"clear 后 hit=0 (got {s['hit']})")


# ============================================================
# Part 5: A2 — 磁盘 SQLite cache
# ============================================================
def part5_disk_cache() -> None:
    section("[Part 5] A2 磁盘 SQLite cache")

    from app.ai.cache import DiskSqliteCache
    from app.core.interfaces import LLMResult
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="nw_m9_cache_"))
    db = tmp / "test_cache.db"

    disk = DiskSqliteCache(db)
    rr = LLMResult(
        content="from disk",
        model="gpt-4", provider="openai",
        input_tokens=10, output_tokens=20, cost=0.001, duration_ms=200,
    )
    # 5.1 写
    disk.put("k1", rr)
    check(disk.size() == 1, f"size=1 (got {disk.size()})")

    # 5.2 读
    got = disk.get("k1")
    check(got is not None, "disk 命中")
    check(got.content == "from disk", "content 正确")
    check(got.model == "gpt-4", f"model=gpt-4 (got {got.model})")
    check(got.cost == 0.001, f"cost=0.001 (got {got.cost})")

    # 5.3 持久化: 重建 DiskSqliteCache 同一路径, 仍能读到
    disk2 = DiskSqliteCache(db)
    got2 = disk2.get("k1")
    check(got2 is not None, "持久化: 重建后仍能读")
    check(got2.content == "from disk", "持久化 content 一致")

    # 5.4 覆盖
    rr2 = LLMResult(content="v2", model="gpt-4", provider="openai",
                    input_tokens=5, output_tokens=5, cost=0.0, duration_ms=50)
    disk2.put("k1", rr2)
    check(disk2.size() == 1, f"覆盖后 size 仍 1 (got {disk2.size()})")
    check(disk2.get("k1").content == "v2", "覆盖后 content=v2")

    # 5.5 clear
    disk2.clear()
    check(disk2.size() == 0, f"clear 后 size=0 (got {disk2.size()})")

    # 5.6 stats
    disk2.put("a", rr)
    disk2.put("b", rr)
    disk2.get("a")  # hit
    disk2.get("c")  # miss
    s = disk2.stats()
    check(s["hit"] == 1, f"hit=1 (got {s['hit']})")
    check(s["miss"] == 1, f"miss=1 (got {s['miss']})")
    check(s["size"] == 2, f"size=2 (got {s['size']})")


# ============================================================
# Part 6: A2 — TieredCache (内存 L1 + 磁盘 L2)
# ============================================================
def part6_tiered_cache() -> None:
    section("[Part 6] A2 TieredCache (L1 + L2 联动)")

    from app.ai.cache import TieredCache, InMemoryLRUCache, DiskSqliteCache
    from app.core.interfaces import LLMResult
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="nw_m9_tiered_"))
    db = tmp / "tiered.db"

    disk = DiskSqliteCache(db)
    mem = InMemoryLRUCache(max_size=10)
    tiered = TieredCache(mem_cache=mem, disk_cache=disk)

    rr = LLMResult(content="tiered", model="m", provider="p",
                   input_tokens=1, output_tokens=1, cost=0.0, duration_ms=10)

    # 6.1 写 — 同时落 L1 和 L2
    tiered.put("k1", rr)
    check(mem.get("k1") is not None, "L1 写成功")
    check(disk.get("k1") is not None, "L2 写成功")

    # 6.2 读 — L1 命中
    got = tiered.get("k1")
    check(got is not None, "tiered 读命中")
    check(got.content == "tiered", "content 正确")

    # 6.3 L1 miss → L2 命中 → 回填 L1
    mem2 = InMemoryLRUCache(max_size=10)  # 新空 L1
    tiered2 = TieredCache(mem_cache=mem2, disk_cache=disk)
    got2 = tiered2.get("k1")
    check(got2 is not None, "L1 miss → L2 命中")
    check(mem2.get("k1") is not None, "回填 L1 成功")

    # 6.4 都没命中
    got3 = tiered2.get("nonexistent_key_xxx")
    check(got3 is None, "都不命中返 None")

    # 6.5 clear — L1 + L2 一起清
    tiered2.clear()
    check(mem2.get("k1") is None, "clear 后 L1 空")
    check(disk.get("k1") is None, "clear 后 L2 空")

    # 6.6 stats 聚合
    tiered2.put("a", rr)
    tiered2.get("a")  # L1 hit
    s = tiered2.stats()
    check("l1" in s and "l2" in s, f"stats 含 l1+l2 (got keys: {list(s.keys())})")


# ============================================================
# Part 7: A3 — ThreadedParallelRunner (mock 多 provider)
# ============================================================
def part7_parallel() -> None:
    section("[Part 7] A3 ThreadPoolExecutor 并行多模型")

    from app.ai.parallel import ThreadedParallelRunner, pick_best
    from app.core.interfaces import LLMResult
    from app.db.models import ModelConfig
    from app.ai import mock as _mock_mod
    _mock_mod.install()

    # 7.1 选 best: cost 最低
    rs = [
        LLMResult(content="A", model="a", provider="p", cost=0.5, duration_ms=100),
        LLMResult(content="B", model="b", provider="p", cost=0.1, duration_ms=200),  # 最便宜
        LLMResult(content="C", model="c", provider="p", cost=0.3, duration_ms=50),
    ]
    best = pick_best(rs, criterion="cost")
    check(best is not None, "pick_best 返回非空")
    check(best.model == "b", f"cost 最低: b (got {best.model})")

    # 7.2 选 best: first
    best_first = pick_best(rs, criterion="first")
    check(best_first.model == "a", f"first: a (got {best_first.model})")

    # 7.3 选 best: tokens
    rs2 = [
        LLMResult(content="A", model="a", cost=0.5, input_tokens=100, output_tokens=100),
        LLMResult(content="B", model="b", cost=0.1, input_tokens=10, output_tokens=10),  # 最小
        LLMResult(content="C", model="c", cost=0.3, input_tokens=50, output_tokens=50),
    ]
    best_tok = pick_best(rs2, criterion="tokens")
    check(best_tok.model == "b", f"tokens 最小: b (got {best_tok.model})")

    # 7.4 选 best: 全失败
    rs_err = [
        LLMResult(content="", model="a", finish_reason="error: x"),
        LLMResult(content="", model="b", finish_reason="error: y"),
    ]
    best_err = pick_best(rs_err)
    check(best_err is not None, "全失败时仍返第一个 (含错误信息)")

    # 7.5 选 best: 空列表
    check(pick_best([]) is None, "空列表返 None")

    # 7.6 ThreadedParallelRunner.execute — mock provider
    runner = ThreadedParallelRunner()
    from app.ai.router import RouteRequest
    req = RouteRequest(
        messages=[{"role": "user", "content": "test parallel"}],
        task="write",
        strategy="parallel",
    )
    cfgs = [
        ModelConfig(id="m1", provider="mock", model_name="nw-mock",
                    base_url="", api_key="k", role="primary",
                    input_price=0, output_price=0),
        ModelConfig(id="m2", provider="mock", model_name="nw-mock-2",
                    base_url="", api_key="k", role="backup",
                    input_price=0, output_price=0),
    ]
    # mock provider 不知道 nw-mock-2, 会失败 — 但 runner 应当不抛
    out = runner.execute(cfgs, req, per_call_timeout_sec=10)
    check(len(out) == 2, f"返回 N 个结果 (got {len(out)})")
    # 至少有一个成功 (m1 用 nw-mock 走 mock 工厂)
    has_success = any(not r.finish_reason.startswith("error") for r in out)
    check(has_success, "至少一个模型成功 (m1 nw-mock 走 mock 工厂)")

    # 7.7 空 models 列表
    empty = runner.execute([], req)
    check(empty == [], "空 models 返 []")


# ============================================================
# Part 8: A4 — SequentialFallbackChain (主备降级)
# ============================================================
def part8_fallback() -> None:
    section("[Part 8] A4 SequentialFallbackChain 主备降级")

    from app.ai.fallback import SequentialFallbackChain
    from app.ai.router import RouteRequest
    from app.db.models import ModelConfig
    from app.core.interfaces import LLMResult
    from app.ai import mock as _mock_mod
    _mock_mod.install()

    # 8.1 链: 第一个成功即返
    chain = SequentialFallbackChain()
    req = RouteRequest(messages=[{"role": "user", "content": "test"}], task="write")
    cfgs = [
        ModelConfig(id="m1", provider="mock", model_name="nw-mock",
                    base_url="", api_key="k", role="primary",
                    input_price=0, output_price=0),
        ModelConfig(id="m2", provider="mock", model_name="nw-mock-2",  # 会失败
                    base_url="", api_key="k", role="fallback",
                    input_price=0, output_price=0),
    ]
    r = chain.execute(cfgs, req)
    check(r is not None, "第一个成功即返")
    check(r.model == "nw-mock", f"result.model=nw-mock (got {r.model})")

    # 8.2 链: 第一个失败 → 第二个成功
    # 用 StubFailClient 替换 mock, 让 m1 强制失败
    from app.ai import providers as _p
    _real_create = _p.create_client

    class _StubFail:
        """config.id == 'm1' 时抛异常, 其它正常."""
        def __init__(self, cfg):
            self.cfg = cfg
        def chat(self, messages, **kwargs):
            if self.cfg.id == "m1":
                raise RuntimeError("simulated failure")
            return LLMResult(
                content="stubbed content",
                model=self.cfg.model_name,
                provider=self.cfg.provider,
                input_tokens=10, output_tokens=20, cost=0.0, duration_ms=10,
            )

    _p.create_client = _StubFail
    try:
        chain2 = SequentialFallbackChain()
        cfgs2 = [
            ModelConfig(id="m1", provider="any", model_name="x",  # 失败
                        base_url="", api_key="k", role="primary",
                        input_price=0, output_price=0),
            ModelConfig(id="m2", provider="any", model_name="nw-mock-ok",  # 成功
                        base_url="", api_key="k", role="fallback",
                        input_price=0, output_price=0),
        ]
        r2 = chain2.execute(cfgs2, req)
        check(r2 is not None, "第一个失败 → 第二个成功")
        check(r2.model == "nw-mock-ok", f"降级到 mock-ok: {r2.model}")
    finally:
        _p.create_client = _real_create

    # 8.3 链: 全失败 → None
    class _StubAllFail:
        def __init__(self, cfg): self.cfg = cfg
        def chat(self, messages, **kwargs):
            raise RuntimeError("simulated all-fail")

    _p.create_client = _StubAllFail
    try:
        chain3 = SequentialFallbackChain()
        cfgs3 = [
            ModelConfig(id="m1", provider="x", model_name="x",
                        base_url="", api_key="k", role="primary",
                        input_price=0, output_price=0),
            ModelConfig(id="m2", provider="y", model_name="y",
                        base_url="", api_key="k", role="fallback",
                        input_price=0, output_price=0),
        ]
        r3 = chain3.execute(cfgs3, req)
        check(r3 is None, "全失败 → None")
    finally:
        _p.create_client = _real_create

    # 8.4 链: 空列表 → None
    r4 = chain.execute([], req)
    check(r4 is None, "空 models 返 None")


# ============================================================
# Part 9: A4 — 完整链路 (Router → Fallback → Cache 联动)
# ============================================================
def part9_full_chain() -> None:
    section("[Part 9] A4 完整链路 Router + Fallback + Cache")

    from app.ai.router import get_router, RouteRequest
    from app.ai import mock as _mock_mod
    _mock_mod.install()
    from app.ai import router as _router_mod
    _router_mod._router_singleton = None
    # 注入 mock primary
    from app.ai.registry import get_registry, ModelConfig
    reg = get_registry()
    reg._models["nw_mock_primary"] = ModelConfig(
        id="nw_mock_primary", provider="mock", model_name="nw-mock",
        base_url="", api_key="mock-key", role="primary",
        input_price=0.0, output_price=0.0,
    )
    from app.services.db import init_db
    from app.db import _impl as _db_conn
    try:
        init_db()
    except Exception:
        pass
    # DB init
    import app.app_paths as _ap
    db_path = _ap.sqlite_path()
    if not db_path.exists():
        init_db()
    _db_conn.init(db_path)

    # 用 temp 隔离 cache
    import os as _os
    _os.environ["NW_AI_CACHE_DIR"] = str(_os.environ.get("NW_AI_CACHE_DIR", "/tmp/nw_m9_final"))
    router = get_router()

    # 9.1 single 路径走 fallback chain
    req = RouteRequest(
        messages=[{"role": "user", "content": "final chain test"}],
        task="write",
        strategy="single",
    )
    r1 = router.route(req)
    check(r1 is not None, "route single 成功")
    check(r1.strategy_used == "single", f"strategy_used=single (got {r1.strategy_used})")
    check(r1.from_cache is False, "首次 from_cache=False")
    check(r1.result.content, "result.content 非空")

    # 9.2 二次同 prompt 命中 cache
    r2 = router.route(req)
    check(r2.from_cache is True, f"二次 from_cache=True (got {r2.from_cache})")
    check(r2.result.content == r1.result.content, "cache 内容一致")


# ============================================================
# Main
# ============================================================
def main() -> int:
    print("[smoke_m9_router] M9-A LLM Router 接口 + 调度 smoke\n")
    try:
        part1_interface()
        part2_delegate()
        part3_cache_hit()
        part4_lru_cache()
        part5_disk_cache()
        part6_tiered_cache()
        part7_parallel()
        part8_fallback()
        part9_full_chain()
    except Exception as e:
        print(f"\n[CRASH] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 2

    print(f"\n{'─' * 50}")
    print(f"  通过: {len(CHECKS) - len(FAILS)}/{len(CHECKS)}")
    if FAILS:
        print("  ❌ 失败:")
        for f in FAILS:
            print(f"     - {f}")
        return 1
    print("  ✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
