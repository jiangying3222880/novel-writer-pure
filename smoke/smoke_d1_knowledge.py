"""
D1 smoke: 知识包目录初始化 + 扫描 + 读取 + 检索
- 启动时 init / bootstrap 正常
- 5 个分类 × 2 个来源 = 10 个目录齐全
- 内置知识 ≥ 10 篇 (4 文风 + 3 桥段 + 2 人物 + 1 场景 + 2 框架)
- 本地知识空 (用户自填)
- 扫描 + 读 + 检索 + 提取 prompt 全部工作

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

# 项目根加进 path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.knowledge import (
    bootstrap,
    init_knowledge_dirs,
    count_all,
    list_all,
    scan_category,
    read_doc,
    search_text,
    extract_for_prompt,
    KNOWLEDGE_ROOT,
    BUILTIN_DIR,
    LOCAL_DIR,
    INDEX_DIR,
    PRESET_CATEGORIES,
    RETRIEVAL_CATEGORIES,
    SOURCE_BUILTIN,
    SOURCE_LOCAL,
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
    print("D1 SMOKE: 知识包目录")
    print("=" * 60)

    # 1) bootstrap
    print("\n[1] bootstrap + 目录初始化")
    counts = bootstrap()
    check(counts["total"] >= 10, f"内置知识 ≥ 10 篇 (实际 {counts['total']})")
    check(counts["by_source"][SOURCE_BUILTIN] >= 10, f"builtin 知识 ≥ 10 (实际 {counts['by_source'][SOURCE_BUILTIN]})")
    check(counts["by_source"][SOURCE_LOCAL] >= 0, f"local 知识 ≥ 0 (实际 {counts['by_source'][SOURCE_LOCAL]})")
    check(BUILTIN_DIR.exists(), "builtin/ 目录存在")
    check(LOCAL_DIR.exists(), "local/ 目录存在")
    check(INDEX_DIR.exists(), "index/ 目录存在")

    # 2) 5 个分类
    print("\n[2] 5 个分类齐全")
    for cat in PRESET_CATEGORIES:
        d_bu = BUILTIN_DIR / cat
        d_lo = LOCAL_DIR / cat
        check(d_bu.exists(), f"builtin/{cat}/ 存在")
        check(d_lo.exists(), f"local/{cat}/ 存在")

    # 3) 文风 + 桥段 覆盖
    print("\n[3] 文风 + 桥段 内容覆盖")
    style_docs = scan_category("文风语料", SOURCE_BUILTIN)
    plot_docs = scan_category("桥段", SOURCE_BUILTIN)
    check(len(style_docs) >= 3, f"文风语料 ≥ 3 篇 (实际 {len(style_docs)})")
    check(len(plot_docs) >= 3, f"桥段 ≥ 3 篇 (实际 {len(plot_docs)})")
    style_genres = {d.genre for d in style_docs}
    plot_genres = {d.genre for d in plot_docs}
    check(len(style_genres) >= 3, f"文风覆盖 ≥ 3 题材 (实际 {style_genres})")
    check(len(plot_genres) >= 3, f"桥段覆盖 ≥ 3 题材 (实际 {plot_genres})")

    # 4) read_doc
    print("\n[4] read_doc 解析 frontmatter")
    doc = read_doc(BUILTIN_DIR / "文风语料" / "仙侠_文风参考.md")
    check(doc.genre == "仙侠", f"genre 解析 = 仙侠 (实际 {doc.genre})")
    check("文风" in doc.tags or len(doc.tags) > 0, f"tags 解析 (实际 {doc.tags})")
    check("仙侠" in doc.content, "内容含 '仙侠' 关键词")
    check(len(doc.content) > 200, f"内容长度 > 200 (实际 {len(doc.content)})")

    # 5) for_retrieval 过滤
    print("\n[5] for_retrieval 只取 文风+桥段")
    for cat in PRESET_CATEGORIES:
        is_retrieval = cat in RETRIEVAL_CATEGORIES
        d = scan_category(cat, SOURCE_BUILTIN, for_retrieval=True)
        if is_retrieval:
            check(len(d) > 0, f"for_retrieval=True 应能取 {cat} (实际 {len(d)})")
        else:
            check(len(d) == 0, f"for_retrieval=True 应跳过 {cat} (实际 {len(d)})")

    # 6) search_text 关键词
    print("\n[6] search_text 关键词检索")
    res = search_text("修真", "文风语料", SOURCE_BUILTIN, top_k=2)
    check(len(res) > 0, f"搜 '修真' 命中 (实际 {len(res)} 篇)")
    if res:
        check("修真" in res[0].content, f"Top1 含 '修真' 关键词 (实际 {res[0].name})")

    # 7) extract_for_prompt
    print("\n[7] extract_for_prompt 拼装给 AI")
    docs = scan_category("文风语料", SOURCE_BUILTIN, for_retrieval=True)
    out = extract_for_prompt(docs, max_total_chars=200)
    check(len(out) > 0, "拼装结果非空")
    check(len(out) <= 250, f"总长 ≤ 250 (实际 {len(out)})")  # 含标题
    print(f"  [INFO] 拼装示例 ({len(out)} 字):\n  {out[:150]}...")

    # 8) list_all
    print("\n[8] list_all 全量结构")
    all_knowledge = list_all()
    check(SOURCE_BUILTIN in all_knowledge and SOURCE_LOCAL in all_knowledge, "含 builtin + local 两组")
    for cat in PRESET_CATEGORIES:
        check(cat in all_knowledge[SOURCE_BUILTIN], f"builtin 含 {cat}")
        check(cat in all_knowledge[SOURCE_LOCAL], f"local 含 {cat}")

    # 9) 容错: 错误分类 / 来源
    print("\n[9] 容错处理")
    try:
        scan_category("不存在的分类")
        check(False, "错误分类应抛异常")
    except ValueError:
        check(True, "错误分类抛 ValueError")
    try:
        get_cat = __import__("app.knowledge", fromlist=["get_category_dir"]).get_category_dir
        get_cat("文风语料", "unknown_source")
        check(False, "错误来源应抛异常")
    except ValueError:
        check(True, "错误来源抛 ValueError")

    # 总结
    print("\n" + "=" * 60)
    total = 9  # 大组数
    if not fails:
        print(f"D1 SMOKE PASS ({passed} assertions)")
        return 0
    else:
        print(f"D1 SMOKE FAIL ({len(fails)} failed):")
        for f in fails:
            print(f"  - {f}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
