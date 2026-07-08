"""
F1 SMOKE: BM25 检索 (含中文分词)
- 测分词 (中英文 + 停用词过滤)
- 测 BM25 索引构建
- 测打分 / top_k
- 测题材 / 分类 / 来源 过滤
- 测持久化 (save + load)
- 测边界 (空 query / 空索引)

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

from app.knowledge._bm25 import (
    BM25Index,
    build_from_knowledge,
    save,
    load,
    search,
    rebuild,
    tokenize,
    INDEX_FILE,
    BM25Hit,
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
    print("F1 SMOKE: BM25 检索")
    print("=" * 60)

    # 1) 分词
    print("\n[1] tokenize 中文分词")
    toks = tokenize("仙侠修真")
    check("仙侠" in toks, f"中文切出 '仙侠' (实际 {toks})")
    check("修真" in toks, f"中文切出 '修真' (实际 {toks})")
    # 关键短语: "修真的" 必须保留 "修真"
    toks2 = tokenize("仙侠修真的故事，主角是个孤儿")
    check("修真" in toks2, f"'修真的' 保留 '修真' (实际 {toks2})")
    check("的" not in toks2, "停用词 '的' 已过滤")
    check("是" not in toks2, "停用词 '是' 已过滤")
    # 英文
    toks_en = tokenize("Harry Potter is a wizard")
    check("harry" in toks_en, f"英文切出 'harry' (实际 {toks_en})")
    check("potter" in toks_en, f"英文切出 'potter' (实际 {toks_en})")
    check("is" not in toks_en, "英文停用词 'is' 已过滤")
    # 边界
    check(tokenize("") == [], "空字符串返回空")
    check(tokenize("，。！？") == [], "纯标点返回空")

    # 2) 索引构建
    print("\n[2] build_from_knowledge 索引")
    idx = build_from_knowledge(for_retrieval=True)
    check(idx.N >= 7, f"索引 N ≥ 7 篇 (实际 {idx.N})")
    check(len(idx.df) > 20, f"词汇表 > 20 (实际 {len(idx.df)})")
    check(idx.avgdl > 0, f"avgdl > 0 (实际 {idx.avgdl:.1f})")
    check("修真" in idx.df, "'修真' 在词汇表")
    check("仙侠" in idx.df, "'仙侠' 在词汇表")
    check("反派" in idx.df, "'反派' 在词汇表")

    # 3) 题材过滤（for_retrieval=True 应只含文风+桥段）
    print("\n[3] for_retrieval 题材过滤")
    cats_in_idx = {m["category"] for m in idx.doc_meta.values()}
    check(cats_in_idx == set(RETRIEVAL_CATEGORIES),
          f"索引仅含检索类 {cats_in_idx}")

    # 4) 打分 / top_k
    print("\n[4] top_k 检索")
    hits = idx.top_k(tokenize("修真 仙侠"), k=3)
    check(len(hits) > 0, f"搜 '修真 仙侠' 命中 (实际 {len(hits)} 篇)")
    if hits:
        check(hits[0].score > 0, f"Top1 分数 > 0 (实际 {hits[0].score:.3f})")
        check(isinstance(hits[0], BM25Hit), "返回 BM25Hit 类型")
        print(f"  [INFO] Top1: {hits[0].doc_id}  score={hits[0].score:.3f}")

    # 5) 题材过滤
    print("\n[5] 题材 / 来源 过滤")
    hits_g = idx.top_k(tokenize("修真"), k=5, genre="仙侠")
    for h in hits_g:
        meta = idx.doc_meta[h.doc_id]
        check(meta.get("genre") == "仙侠", f"{h.doc_id} genre=仙侠")
    hits_g_only = idx.top_k(tokenize("修真"), k=5, genre="不存在的题材")
    check(len(hits_g_only) == 0, f"过滤不存在题材 → 0 命中 (实际 {len(hits_g_only)})")

    hits_c = idx.top_k(tokenize("修真"), k=5, category="文风语料")
    for h in hits_c:
        meta = idx.doc_meta[h.doc_id]
        check(meta.get("category") == "文风语料", f"{h.doc_id} category=文风语料")

    # 6) 排序
    print("\n[6] 排序分数递减")
    hits = idx.top_k(tokenize("反派"), k=5)
    if len(hits) >= 2:
        scores = [h.score for h in hits]
        check(scores == sorted(scores, reverse=True),
              f"分数递减 (实际 {scores})")

    # 7) 持久化
    print("\n[7] 持久化 (save + load)")
    saved_path = save(idx)
    check(saved_path.exists(), f"索引文件已保存: {saved_path}")
    loaded = load()
    check(loaded is not None, "load() 返回非 None")
    check(loaded.N == idx.N, f"加载后 N 一致 ({loaded.N} == {idx.N})")
    check(len(loaded.df) == len(idx.df), "加载后词汇表一致")

    # 8) search 入口 (含 load)
    print("\n[8] search() 一站式入口")
    # 清掉内存 idx, 让 search 走 load 路径
    hits = search("修真", top_k=3)
    check(len(hits) > 0, f"search() 走 load 路径命中 (实际 {len(hits)} 篇)")

    # 9) 边界
    print("\n[9] 边界")
    check(search("") == [], "空 query 返回空")
    check(search("   ") == [], "纯空白 query 返回空")
    empty_idx = BM25Index()
    check(empty_idx.top_k(tokenize("test"), k=3) == [], "空索引 top_k 返回空")

    # 10) 增量操作
    print("\n[10] 增量 add / remove")
    test_idx = BM25Index()
    test_idx.add("d1", ["仙侠", "修真"], {"name": "d1"})
    test_idx.add("d2", ["都市", "职场"], {"name": "d2"})
    test_idx.add("d3", ["仙侠", "秘境"], {"name": "d3"})
    check(test_idx.N == 3, f"add 后 N=3 (实际 {test_idx.N})")
    check("仙侠" in test_idx.df and test_idx.df["仙侠"] == 2,
          f"'仙侠' 出现在 2 篇 (实际 {test_idx.df.get('仙侠', 0)})")
    test_idx.remove("d2")
    check(test_idx.N == 2, f"remove 后 N=2 (实际 {test_idx.N})")
    check("都市" not in test_idx.df, "'都市' 词汇已消失")
    # 检索修真应优先 d1 (有 修真)
    hits = test_idx.top_k(tokenize("修真"), k=2)
    check(len(hits) > 0 and hits[0].doc_id == "d1", f"修真 优先 d1 (实际 {hits[0].doc_id if hits else None})")

    # 总结
    print("\n" + "=" * 60)
    if not fails:
        print(f"F1 SMOKE PASS ({passed} assertions)")
        return 0
    else:
        print(f"F1 SMOKE FAIL ({len(fails)} failed):")
        for f in fails:
            print(f"  - {f}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
