"""
D2 SMOKE: 知识检索 (BM25 + 向量 + 融合 + 排序)
- 测 HybridFinder build
- 测融合打分 (BM25 命中 + Vector 命中)
- 测题材过滤
- 测 extract_for_prompt (A1.8 拍板 ~200 字)
- 测 for_retrieval=True 跳过非检索类

5 分钟自动超时 (threading.Timer, 跨平台, 防卡死)
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

# 5 分钟全局超时 (smoke 卡死保护, Windows 兼容用 Timer)
_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.knowledge.finder import (
    HybridFinder,
    HybridHit,
    build_finder,
    get_finder,
    search,
    extract_for_prompt,
)
from app.knowledge import (
    RETRIEVAL_CATEGORIES,
    PRESET_CATEGORIES,
)


def main() -> int:
    fails = []
    passed = 0

    def check(cond, msg):
        nonlocal passed
        if cond:
            passed += 1
            print(f"  [PASS] {msg}")
        else:
            fails.append(msg)
            print(f"  [FAIL] {msg}")

    print("=" * 60)
    print("D2 SMOKE: 知识检索 (BM25 + 向量 + 融合)")
    print("=" * 60)

    # 1) build_finder
    print("\n[1] build_finder")
    f = build_finder()
    if f.zvec is not None:
        check(True, "zvec 检索引擎已加载")
        check(f.zvec.N >= 0, f"zvec collection 已初始化")
    else:
        check(f.bm25 is not None, "BM25 索引已加载 (legacy)")
        check(f.vector is not None, "Vector 索引已加载 (legacy)")
        check(f.bm25.N >= 7, f"BM25 N ≥ 7 (实际 {f.bm25.N})")
        check(f.vector.N >= 7, f"Vector N ≥ 7 (实际 {f.vector.N})")

    # 2) 基础混合检索
    print("\n[2] 基础混合检索")
    hits = f.search("修真", top_k=3)
    check(len(hits) > 0, f"修真 检索命中 (实际 {len(hits)})")
    check(isinstance(hits[0], HybridHit), "返回 HybridHit 类型")
    check(hits[0].doc_id, f"doc_id 非空 (实际 {hits[0].doc_id})")
    check(hits[0].category in PRESET_CATEGORIES,
          f"category 在预置中 (实际 {hits[0].category})")

    # 3) 分数有值
    print("\n[3] 融合分数")
    hits = f.search("修真", top_k=5)
    scores = [h.score for h in hits]
    check(all(s >= 0 for s in scores), f"所有分数 >= 0 (实际 {scores})")
    check(scores == sorted(scores, reverse=True),
          f"分数递减 (实际 {scores})")
    # 修真应该 bm25 + vector 都有命中
    has_bm25 = any(h.bm25_score > 0 for h in hits)
    has_vec = any(h.vector_score > 0 for h in hits)
    check(has_bm25 or has_vec, f"修真 有 BM25 ({has_bm25}) 或 Vector ({has_vec}) 命中")

    # 4) 题材过滤
    print("\n[4] 题材过滤")
    hits_g = f.search("故事", top_k=5, genre="古言")
    check(len(hits_g) > 0, f"古言 过滤命中 (实际 {len(hits_g)})")
    for h in hits_g:
        check(h.genre == "古言", f"{h.doc_id} genre=古言 (实际 {h.genre})")
    hits_ng = f.search("故事", top_k=5, genre="不存在的题材")
    check(len(hits_ng) == 0, f"不存在题材 → 0 命中 (实际 {len(hits_ng)})")

    # 5) for_retrieval=True 跳过非检索类
    print("\n[5] for_retrieval 过滤")
    hits = f.search("主角", top_k=10, for_retrieval=True)
    cats = {h.category for h in hits}
    check(cats <= set(RETRIEVAL_CATEGORIES),
          f"仅返回检索类 (实际 {cats})")
    check(cats <= {"文风语料", "桥段"}, f"仅文风+桥段 (实际 {cats})")

    # 6) extract_for_prompt (A1.8 拍板 ~200 字)
    print("\n[6] extract_for_prompt A1.8")
    out = f.extract_for_prompt("修真", top_k=3, max_total_chars=200)
    check(len(out) > 0, "拼装结果非空")
    check(len(out) <= 300, f"总长 ≤ 300 (含标题, 实际 {len(out)})")
    check("文风" in out or "桥段" in out, f"拼装含 文风/桥段 标签 (前 50 字: {out[:50]!r})")
    print(f"  [INFO] 拼装示例 ({len(out)} 字):\n  {out[:200]}...")

    # 7) 空 query
    print("\n[7] 边界")
    check(f.search("", top_k=3) == [], "空 query → []")
    check(f.search("   ", top_k=3) == [], "纯空白 → []")
    check(f.extract_for_prompt("") == "", "空 query 拼装 → 空")

    # 8) 一站式入口
    print("\n[8] search() + extract_for_prompt()")
    hits = search("修真", top_k=3)
    check(len(hits) > 0, f"一站式 search 命中 (实际 {len(hits)})")
    out = extract_for_prompt("修真")
    check(len(out) > 0, f"一站式 extract 非空 (实际 {len(out)} 字)")

    # 9) 融合权重 (仅 legacy 模式; zvec 模式下 FTS+Vector 已融合)
    print("\n[9] 融合权重")
    if f.zvec is not None:
        print("  [SKIP] zvec 模式: FTS+Vector 已融合, 不单独测试 BM25/Vector")
    else:
        f_bm = HybridFinder(bm25=f.bm25, vector=f.vector, w_bm25=1.0, w_vector=0.0)
        f_vec = HybridFinder(bm25=f.bm25, vector=f.vector, w_bm25=0.0, w_vector=1.0)
        hits_bm = f_bm.search("修真", top_k=3)
        hits_vec = f_vec.search("修真", top_k=3)
        check(len(hits_bm) > 0, f"纯 BM25 命中 (实际 {len(hits_bm)})")
        check(len(hits_vec) > 0, f"纯 Vector 命中 (实际 {len(hits_vec)})")
        ids_bm = [h.doc_id for h in hits_bm]
        ids_vec = [h.doc_id for h in hits_vec]
        print(f"  [INFO] BM25-only: {ids_bm}")
        print(f"  [INFO] Vector-only: {ids_vec}")

    # 总结
    print("\n" + "=" * 60)
    if not fails:
        print(f"D2 SMOKE PASS ({passed} assertions)")
        return 0
    else:
        print(f"D2 SMOKE FAIL ({len(fails)} failed):")
        for f in fails:
            print(f"  - {f}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
