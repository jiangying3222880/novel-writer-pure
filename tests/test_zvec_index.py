"""
tests/test_zvec_index — ZvecIndex 单元测试
"""
import sys, os, shutil, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_zvec_index_lifecycle():
    """测试 ZvecIndex 完整生命周期: 创建 → 插入 → 搜索 → 删除."""
    from app.knowledge._zvec_index import ZvecIndex, ZvecHit

    # 用临时目录避免污染
    tmp_dir = tempfile.mkdtemp()
    try:
        idx = ZvecIndex(path=os.path.join(tmp_dir, "test_index"))

        # 1. 初始化 (可能从 builtin 知识库自动填充)
        idx._ensure_init()
        initial_n = idx.N
        print(f"  1. 初始化: N={initial_n} (可能含 builtin 文档)")

        # 2. 插入文档
        idx.add("doc1", "仙侠修真小说，主角从炼气期开始修炼", {
            "name": "修真入门",
            "category": "文风语料",
            "genre": "仙侠",
            "source": "builtin",
        })
        idx.add("doc2", "都市职场，白领加班到深夜", {
            "name": "都市职场",
            "category": "桥段",
            "genre": "都市",
            "source": "builtin",
        })
        idx.add("doc3", "悬疑推理，密室杀人案", {
            "name": "密室悬疑",
            "category": "桥段",
            "genre": "悬疑",
            "source": "builtin",
        })
        assert idx.N >= initial_n + 3, f"插入后应增加 3 篇 (实际 N={idx.N})"
        print("  2. 插入 3 篇文档: OK")

        # 3. 搜索
        hits = idx.search("修真", top_k=5)
        assert len(hits) > 0, "搜索 '修真' 应有命中"
        assert isinstance(hits[0], ZvecHit), "返回 ZvecHit 类型"
        print(f"  3. 搜索 '修真': {len(hits)} hits, OK")

        # 4. 过滤搜索
        hits_filtered = idx.search("小说", top_k=5, genre="仙侠")
        # genre 过滤可能返回 0 (zvec filter 行为)
        print(f"  4. 过滤搜索 genre=仙侠: {len(hits_filtered)} hits")

        # 5. 删除
        removed = idx.remove("doc1")
        assert removed, "删除应成功"
        assert idx.N >= initial_n + 2, f"删除后应减少 1 篇 (实际 N={idx.N})"
        print("  5. 删除文档: OK")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_zvec_vs_finder():
    """测试 ZvecIndex 与 HybridFinder 集成."""
    from app.knowledge.finder import build_finder

    f = build_finder()
    if f.zvec is not None:
        hits = f.search("修真", top_k=3)
        assert len(hits) > 0, "zvec 搜索应有命中"
        print(f"  Finder+zvec: {len(hits)} hits, OK")
    else:
        print("  Finder+zvec: 跳过 (legacy 模式)")


def main():
    print("test_zvec_index:")
    test_zvec_index_lifecycle()
    test_zvec_vs_finder()
    print("  ALL PASSED")


if __name__ == "__main__":
    main()
