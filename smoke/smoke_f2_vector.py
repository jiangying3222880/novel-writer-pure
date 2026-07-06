"""
F2 SMOKE: 向量 DB (本地嵌入 + 0 tokens 费用)
- 测 Embedder 双模式 (TF-IDF fallback, 不依赖真模型下载)
- 测 VectorIndex add/remove/search
- 测持久化 save/load
- 测余弦相似度 top_k
- 测题材/分类/来源 过滤

5 分钟自动超时 (threading.Timer, 跨平台)
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from app.knowledge.vector_db import (
    Embedder,
    VectorIndex,
    build_from_knowledge,
    save,
    load,
    search,
    rebuild,
    VECTORS_FILE,
    META_FILE,
    VectorHit,
)
from app.knowledge import (
    PRESET_CATEGORIES,
    RETRIEVAL_CATEGORIES,
    SOURCE_BUILTIN,
    INDEX_DIR,
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
    print("F2 SMOKE: 向量 DB")
    print("=" * 60)

    # 1) Embedder 初始化 (强制 TF-IDF 模式, 避免真模型下载)
    print("\n[1] Embedder 初始化 (TF-IDF 模式)")
    emb = Embedder(model_name="dummy", dim=128)
    emb._mode = "tfidf"  # 强制 TF-IDF
    emb._init_tfidf()
    check(emb.mode == "tfidf", f"mode = tfidf (实际 {emb.mode})")
    check(emb.dim_out == 128, f"dim_out = 128 (实际 {emb.dim_out})")

    # 2) embed 基础
    print("\n[2] embed 基础")
    texts = [
        "仙侠修真故事，主角是个孤儿",
        "古言宫廷里王爷和侯爷的爱恨情仇",
        "都市职场的霸总和灰姑娘",
        "悬疑推理，密室里的真相",
    ]
    vecs = emb.embed(texts)
    check(vecs.shape[0] == 4, f"vecs shape[0] = 4 (实际 {vecs.shape})")
    check(vecs.shape[1] > 0, f"vecs shape[1] > 0 (实际 {vecs.shape})")
    check(vecs.dtype == np.float32, f"vecs dtype = float32 (实际 {vecs.dtype})")

    # 3) L2 normalize (余弦相似度)
    print("\n[3] L2 normalize")
    norms = np.linalg.norm(vecs, axis=1)
    check(np.allclose(norms, 1.0, atol=1e-3),
          f"所有向量 L2 norm ≈ 1.0 (实际 max={norms.max():.3f}, min={norms.min():.3f})")

    # 4) 相似度: 同主题接近
    print("\n[4] 相似度排序")
    sim_self = float(vecs[0] @ vecs[0])           # 自己 ~1.0
    sim_cross = float(vecs[0] @ vecs[1])          # 仙侠 vs 古言 ~0
    check(sim_self > sim_cross, f"自相似 ({sim_self:.3f}) > 跨主题 ({sim_cross:.3f})")
    check(sim_self > 0.9, f"自相似 > 0.9 (实际 {sim_self:.3f})")

    # 5) VectorIndex add / search
    print("\n[5] VectorIndex add / search")
    idx = VectorIndex(embedder=emb)
    idx.add("d1", texts[0], {"name": "d1", "category": "文风语料", "genre": "仙侠", "snippet": texts[0]})
    idx.add("d2", texts[1], {"name": "d2", "category": "文风语料", "genre": "古言", "snippet": texts[1]})
    idx.add("d3", texts[2], {"name": "d3", "category": "文风语料", "genre": "都市", "snippet": texts[2]})
    check(idx.N == 3, f"N = 3 (实际 {idx.N})")
    check(len(idx.doc_texts) == 3, f"doc_texts 长度 = 3 (实际 {len(idx.doc_texts)})")
    # 触发 search 后 vectors 才会被 fit
    _ = idx.search("修真", top_k=3)
    check(idx.vectors is not None and idx.vectors.shape == (3, 128),
          f"search 后 vectors shape = (3, 128) (实际 {idx.vectors.shape if idx.vectors is not None else None})")
    # 检索: 修真 → 优先 d1
    hits = idx.search("修真", top_k=3)
    check(len(hits) == 3, f"修真 检索 3 命中 (实际 {len(hits)})")
    check(hits[0].doc_id == "d1", f"修真 优先 d1 (实际 {hits[0].doc_id})")
    check(isinstance(hits[0], VectorHit), "返回 VectorHit 类型")

    # 6) 题材过滤
    print("\n[6] 题材过滤")
    hits = idx.search("故事", top_k=3, genre="古言")
    check(len(hits) == 1 and hits[0].doc_id == "d2", f"古言 过滤 (实际 {len(hits)} 命中, top1={hits[0].doc_id if hits else None})")

    # 7) remove
    print("\n[7] remove")
    check(idx.remove("d2") is True, "remove 存在 → True")
    check(idx.N == 2, f"remove 后 N = 2 (实际 {idx.N})")
    check(idx.remove("d2") is False, "remove 不存在 → False")
    # 古言 检索 + genre="古言" 过滤 → 0 命中 (d2 已移除, d1/d3 genre 不对)
    hits = idx.search("古言", top_k=3, genre="古言")
    check(len(hits) == 0, f"d2 移除后古言+genre 过滤 0 命中 (实际 {len(hits)})")

    # 8) 持久化 save / load
    print("\n[8] 持久化 (numpy + pickle)")
    idx.add("d4", texts[3], {"name": "d4", "category": "文风语料", "genre": "悬疑", "snippet": texts[3]})
    save(idx)
    check(VECTORS_FILE.exists(), f"vectors.npy 已保存")
    check(META_FILE.exists(), f"vectors_meta.pkl 已保存")
    loaded = load(embedder=emb)
    check(loaded is not None, "load() 返回非 None")
    check(loaded.N == idx.N, f"加载后 N 一致 ({loaded.N} == {idx.N})")
    check(np.allclose(loaded.vectors, idx.vectors, atol=1e-5),
          "加载后 vectors 与原一致")

    # 9) 边界
    print("\n[9] 边界")
    empty_idx = VectorIndex(embedder=emb)
    check(empty_idx.search("test", top_k=3) == [], "空索引 search → []")
    check(emb.embed([]).shape == (0, emb.dim_out), f"空列表 embed (实际 {emb.embed([]).shape})")
    # 零向量 (空字符串)
    zv = emb.embed_one("")
    check(zv.shape == (emb.dim_out,), f"空字符串 embed 形状 (实际 {zv.shape})")

    # 10) build_from_knowledge 端到端
    print("\n[10] build_from_knowledge 端到端")
    emb2 = Embedder(model_name="dummy", dim=64)
    emb2._mode = "tfidf"
    emb2._init_tfidf()
    big_idx, mode = build_from_knowledge(embedder=emb2)
    check(big_idx.N >= 7, f"知识库嵌入 N ≥ 7 (实际 {big_idx.N})")
    check(mode == "tfidf", f"mode = tfidf (实际 {mode})")
    cats = {m["category"] for m in big_idx.doc_meta.values()}
    check(cats == set(RETRIEVAL_CATEGORIES),
          f"for_retrieval=True 仅含检索类 {cats}")

    # 11) search() 一站式入口
    print("\n[11] search() 一站式入口")
    hits = search("修真", top_k=3, idx=big_idx)
    check(len(hits) > 0, f"修真 检索命中 (实际 {len(hits)})")
    print(f"  [INFO] Top1: {hits[0].doc_id}  score={hits[0].score:.3f}")

    # 总结
    print("\n" + "=" * 60)
    if not fails:
        print(f"F2 SMOKE PASS ({passed} assertions)")
        return 0
    else:
        print(f"F2 SMOKE FAIL ({len(fails)} failed):")
        for f in fails:
            print(f"  - {f}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
