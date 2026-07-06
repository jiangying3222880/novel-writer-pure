"""
H2 SMOKE: Knowledge Plugin (4 维度)
- KnowledgePlugin 启用/停用 (setup/teardown)
- search / search_multi / extract_for_prompt
- import_file (用 fixture 文本, 跳过 AI)
- list_by_dimension / stats / get_dimensions
- 与 PluginManager 集成 (register_builtin)

5 分钟自动超时 (threading.Timer, 跨平台, 防卡死)
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path

# stdout UTF-8 (Windows GBK 兼容)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 5 分钟全局超时 (smoke 卡死保护, Windows 兼容用 Timer)
_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_h2_knowledge_plugin 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    print(f"[TIMEOUT] 请检查: 1) 终端输出最后一行  2) logs/NovelWriter_*.log  3) 是否被外部 IO 阻塞")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ────────────────────── 插件已废弃 (V3.4+ SKIP) ──────────────────────
try:
    from app.plugins.builtin.knowledge_plugin import (
        KnowledgePlugin, KnowledgeHit,
        DIMENSION_STYLE, DIMENSION_PLOT, DIMENSION_CHARACTER, DIMENSION_SCENE,
        DIMENSIONS, DIMENSION_LABELS, DIMENSION_DESCRIPTIONS,
        DIMENSION_TO_CATEGORY, CATEGORY_TO_DIMENSION, RETRIEVAL_DIMENSIONS,
    )
    from app.plugins.manager import PluginManager
    _HAS_PLUGINS = True
except ImportError:
    _HAS_PLUGINS = False
    KnowledgePlugin = None  # type: ignore
    KnowledgeHit = None  # type: ignore
    # 定义空常量 (让类型检查器不报错)
    DIMENSION_STYLE = DIMENSION_PLOT = DIMENSION_CHARACTER = DIMENSION_SCENE = ""
    DIMENSIONS = DIMENSION_LABELS = DIMENSION_DESCRIPTIONS = {}
    DIMENSION_TO_CATEGORY = CATEGORY_TO_DIMENSION = {}
    RETRIEVAL_DIMENSIONS = []
    class _FakePluginManager:
        def __getattr__(self, name):
            return None
    PluginManager = _FakePluginManager

from app.knowledge import (
    BUILTIN_DIR, LOCAL_DIR, INDEX_DIR,
    SOURCE_BUILTIN, SOURCE_LOCAL,
    PRESET_CATEGORIES,
)


# ────────────────────── 计数器 ──────────────────────

_pass = 0
_fail = 0


def check(cond: bool, msg: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  [PASS] {msg}")
    else:
        _fail += 1
        print(f"  [FAIL] {msg}")


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


# ────────────────────── 测试用隔离环境 ──────────────────────

def _isolated_knowledge_env() -> Path:
    """建一个临时 knowledge 根 (避免污染真实 app/knowledge)。"""
    tmpdir = Path(tempfile.mkdtemp(prefix="nw_smoke_h2_"))
    (tmpdir / "builtin").mkdir(parents=True)
    (tmpdir / "local").mkdir(parents=True)
    (tmpdir / "index").mkdir(parents=True)
    # 准备 4 维度各 2 篇 builtin fixture
    fixtures = {
        "文风语料": [
            ("仙侠_文风A", "仙侠", "仙风道骨, 御剑飞行, 一袭青衫立于云端, 剑光如虹, 浩气长存。"),
            ("古言_文风A", "古言", "红烛摇曳, 绣帘低垂, 她回眸, 凤冠霞帔, 端的是雍容华贵, 一笑倾城。"),
        ],
        "桥段": [
            ("仙侠_桥段A", "仙侠", "主角在山洞中意外获得上古剑诀, 闭关三载, 终成大器。"),
            ("悬疑_桥段A", "悬疑", "密室杀人, 唯一的线索是一枚落在地毯上的徽章, 所有人都声称不曾见过。"),
        ],
        "人物人设": [
            ("主角模板", "通用", "姓名: 萧炎。身份: 萧家少年。性格: 坚韧不拔。目标: 复仇与崛起。"),
            ("反派模板", "通用", "姓名: 魂殿殿主。身份: 暗势力首领。性格: 阴险狡诈。目标: 统治大陆。"),
        ],
        "场景描写": [
            ("常见场景_山巅", "通用", "山巅云海翻涌, 残阳如血, 风声如泣, 一剑横空, 万物寂寥。"),
            ("常见场景_城楼", "古言", "城楼之上, 战鼓如雷, 旌旗猎猎, 远方敌军压境, 烽烟四起。"),
        ],
    }
    for cat, docs in fixtures.items():
        cat_dir = tmpdir / "builtin" / cat
        cat_dir.mkdir(parents=True, exist_ok=True)
        for name, genre, content in docs:
            md = (
                f"---\n"
                f"name: {name}\n"
                f"category: {cat}\n"
                f"genre: {genre}\n"
                f"source: builtin\n"
                f"---\n\n"
                f"# {name}\n\n"
                f"{content}\n"
            )
            (cat_dir / f"{name}.md").write_text(md, encoding="utf-8")
    return tmpdir


# ═══════════════════════════════════════════════════════════
#                  H2 TESTS
# ═══════════════════════════════════════════════════════════

def test_dimension_constants() -> None:
    section("[H2 1] 维度常量")

    check(len(DIMENSIONS) == 4, f"4 维度 (实际 {len(DIMENSIONS)})")
    check(DIMENSION_STYLE in DIMENSIONS, "含 DIMENSION_STYLE")
    check(DIMENSION_PLOT in DIMENSIONS, "含 DIMENSION_PLOT")
    check(DIMENSION_CHARACTER in DIMENSIONS, "含 DIMENSION_CHARACTER")
    check(DIMENSION_SCENE in DIMENSIONS, "含 DIMENSION_SCENE")

    check(DIMENSION_TO_CATEGORY[DIMENSION_STYLE] == "文风语料", "style → 文风语料")
    check(DIMENSION_TO_CATEGORY[DIMENSION_PLOT] == "桥段", "plot → 桥段")
    check(DIMENSION_TO_CATEGORY[DIMENSION_CHARACTER] == "人物人设", "character → 人物人设")
    check(DIMENSION_TO_CATEGORY[DIMENSION_SCENE] == "场景描写", "scene → 场景描写")

    check(CATEGORY_TO_DIMENSION["文风语料"] == DIMENSION_STYLE, "反查 文风语料 → style")
    check(CATEGORY_TO_DIMENSION["桥段"] == DIMENSION_PLOT, "反查 桥段 → plot")

    # 可检索维度
    check(DIMENSION_STYLE in RETRIEVAL_DIMENSIONS, "style 可检索")
    check(DIMENSION_PLOT in RETRIEVAL_DIMENSIONS, "plot 可检索")
    check(DIMENSION_CHARACTER not in RETRIEVAL_DIMENSIONS, "character 不可检索")
    check(DIMENSION_SCENE not in RETRIEVAL_DIMENSIONS, "scene 不可检索")

    # 标签
    check(DIMENSION_LABELS[DIMENSION_STYLE] == "文风语料", "label 正确")
    check(DIMENSION_DESCRIPTIONS[DIMENSION_STYLE] != "", "description 非空")


def test_plugin_lifecycle() -> None:
    section("[H2 2] 插件生命周期 (setup/teardown)")

    p = KnowledgePlugin()
    check(p.name == "knowledge", f"name=knowledge (实际 {p.name})")
    check(p.version == "1.0.0", f"version=1.0.0 (实际 {p.version})")
    check(p.enabled is True, "默认 enabled")
    check(p.required_role == "standard", "required_role=standard")

    # setup
    p.setup({})
    check("knowledge_bootstrapped" in p.context, "setup 后 context 含 bootstrapped 标记")

    # teardown
    p.teardown()
    check(p.context == {}, "teardown 后 context 清空")

    # meta
    meta = p.get_meta()
    check(meta["name"] == "knowledge", "meta.name")
    check("dimensions" in meta, "meta 含 dimensions")
    check("stats" in meta, "meta 含 stats")


def test_get_dimensions() -> None:
    section("[H2 3] get_dimensions (UI 渲染)")

    p = KnowledgePlugin()
    p.setup({})
    try:
        dims = p.get_dimensions()
        check(len(dims) == 4, f"4 维度 (实际 {len(dims)})")
        for d in dims:
            check("id" in d and "label" in d, f"维度含 id+label: {d.get('id')}")
            check("description" in d, f"维度含 description")
            check("category" in d, f"维度含 category")
            check("retrieval_enabled" in d, f"维度含 retrieval_enabled")
    finally:
        p.teardown()


def test_stats() -> None:
    section("[H2 4] stats (按维度统计)")

    p = KnowledgePlugin()
    p.setup({})
    try:
        s = p.stats()
        check("total" in s, "stats 含 total")
        check("by_dimension" in s, "stats 含 by_dimension")
        check("by_source" in s, "stats 含 by_source")
        check(len(s["by_dimension"]) == 4, f"4 维度 (实际 {len(s['by_dimension'])})")

        # 验证每个维度有 label / builtin / local / total / retrieval_enabled
        for dim_id, dim_stats in s["by_dimension"].items():
            check("label" in dim_stats, f"{dim_id} 含 label")
            check("builtin" in dim_stats, f"{dim_id} 含 builtin")
            check("local" in dim_stats, f"{dim_id} 含 local")
            check("total" in dim_stats, f"{dim_id} 含 total")
            check("retrieval_enabled" in dim_stats, f"{dim_id} 含 retrieval_enabled")
            # 实际 builtin 至少有 fixture
            check(dim_stats["builtin"] >= 1, f"{dim_id} 至少 1 篇 builtin")

        # 文风 / 桥段 可检索, 人设 / 场景 不可
        check(s["by_dimension"][DIMENSION_STYLE]["retrieval_enabled"] is True, "文风可检索")
        check(s["by_dimension"][DIMENSION_PLOT]["retrieval_enabled"] is True, "桥段可检索")
        check(s["by_dimension"][DIMENSION_CHARACTER]["retrieval_enabled"] is False, "人设不可检索")
        check(s["by_dimension"][DIMENSION_SCENE]["retrieval_enabled"] is False, "场景不可检索")
    finally:
        p.teardown()


def test_list_by_dimension() -> None:
    section("[H2 5] list_by_dimension")

    p = KnowledgePlugin()
    p.setup({})
    try:
        for dim in DIMENSIONS:
            docs = p.list_by_dimension(dim)
            check(len(docs) >= 1, f"{dim} 至少 1 篇 (实际 {len(docs)})")
            for d in docs:
                check(d.category == DIMENSION_TO_CATEGORY[dim],
                      f"category={DIMENSION_TO_CATEGORY[dim]} (实际 {d.category})")

        # 未知维度
        try:
            p.list_by_dimension("unknown")
            check(False, "未知维度应抛错")
        except ValueError:
            check(True, "未知维度抛 ValueError")
    finally:
        p.teardown()


def test_search() -> None:
    section("[H2 6] search (按维度检索)")

    p = KnowledgePlugin()
    p.setup({})
    try:
        # 文风检索 "仙侠"
        hits = p.search("仙侠", DIMENSION_STYLE, top_k=3)
        check(len(hits) >= 1, f"文风 '仙侠' 命中 >= 1 (实际 {len(hits)})")
        if hits:
            h = hits[0]
            check(isinstance(h, KnowledgeHit), "返回 KnowledgeHit")
            check(h.dimension == DIMENSION_STYLE, f"dimension=style")
            check(h.dimension_label == "文风语料", "label=文风语料")
            check(h.score > 0, f"score > 0 (实际 {h.score})")
            d = h.to_dict()
            check("dimension" in d, "to_dict 含 dimension")

        # 桥段检索 "师徒" (仙侠_常见桥段 含此关键词)
        hits = p.search("师徒", DIMENSION_PLOT, top_k=3)
        check(len(hits) >= 1, f"桥段 '师徒' 命中 >= 1 (实际 {len(hits)})")

        # 人设检索 "萧炎"
        hits = p.search("萧炎", DIMENSION_CHARACTER, top_k=3)
        check(len(hits) >= 1, f"人设 '萧炎' 命中 >= 1 (实际 {len(hits)})")

        # 场景检索 "山门" (常见场景模板 含此关键词)
        hits = p.search("山门", DIMENSION_SCENE, top_k=3)
        check(len(hits) >= 1, f"场景 '山门' 命中 >= 1 (实际 {len(hits)})")

        # 未知维度
        try:
            p.search("test", "unknown")
            check(False, "未知维度应抛错")
        except ValueError:
            check(True, "未知维度抛 ValueError")

        # 无关键词
        hits = p.search("", DIMENSION_STYLE)
        check(hits == [], "空 query 返回空")
    finally:
        p.teardown()


def test_search_multi_and_extract() -> None:
    section("[H2 7] search_multi / extract_for_prompt")

    p = KnowledgePlugin()
    p.setup({})
    try:
        # 多维度检索
        results = p.search_multi("仙侠", [DIMENSION_STYLE, DIMENSION_PLOT], top_k_per_dim=2)
        check(DIMENSION_STYLE in results, "含 style 维度")
        check(DIMENSION_PLOT in results, "含 plot 维度")
        check(DIMENSION_CHARACTER not in results, "不含未指定维度")
        check(len(results[DIMENSION_STYLE]) >= 1, f"style 命中 >= 1 (实际 {len(results[DIMENSION_STYLE])})")

        # 默认 (RETRIEVAL_DIMENSIONS)
        results = p.search_multi("仙侠")
        check(DIMENSION_STYLE in results, "默认含 style")
        check(DIMENSION_PLOT in results, "默认含 plot")
        check(DIMENSION_CHARACTER not in results, "默认不含 character")

        # extract_for_prompt
        text = p.extract_for_prompt("仙侠", max_total_chars=500)
        check(text != "", "extract 非空")
        # 应含 【文风语料/...】 或 【桥段/...】 格式
        check("文风语料" in text or "桥段" in text, "含维度标签")
    finally:
        p.teardown()


def test_import_file() -> None:
    section("[H2 8] import_file")

    p = KnowledgePlugin()
    p.setup({})
    tmpdir = None
    try:
        # 准备临时 MD 文件
        tmpdir = Path(tempfile.mkdtemp(prefix="h2_import_"))
        md_path = tmpdir / "test_仙侠_文风.md"
        md_path.write_text(
            "---\n"
            "name: test_imported\n"
            "category: 文风语料\n"
            "genre: 仙侠\n"
            "source: local\n"
            "---\n\n"
            "# test_imported\n\n"
            "测试导入的文风语料内容。剑光如雪, 御风而行, 仙气飘飘。\n",
            encoding="utf-8",
        )

        # 导入到 style 维度 (不用 AI, 因为我们已知 category)
        result = p.import_file(
            md_path, dimension=DIMENSION_STYLE, use_ai=False, overwrite=True,
        )
        check(result.get("ok"), f"导入成功: {result}")
        check(result.get("category") == "文风语料", f"category=文风语料 (实际 {result.get('category')})")
    finally:
        p.teardown()
        if tmpdir:
            import shutil
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass


def test_plugin_manager_integration() -> None:
    section("[H2 9] 与 PluginManager 集成")

    # 临时 plugins 目录
    tmpdir = Path(tempfile.mkdtemp(prefix="h2_mgr_"))
    try:
        mgr = PluginManager(plugins_dir=tmpdir / "plugins")
        p = KnowledgePlugin()
        mgr.register_builtin(p)
        check(any(info.id == p.name for info in mgr.list()), "插件在 manager 中")
        info = mgr.get(p.name)
        check(info is not None, "info 非空")
        check(info.builtin is True, "info.builtin=True")
        check(info.enabled is True, "info.enabled=True")
        check(any(info.id == "knowledge" for info in mgr.list(enabled_only=True)), "在 enabled_only 中")

        # 启停
        mgr.disable(p.name)
        check(mgr.get(p.name).enabled is False, "disable 后 enabled=False")
        mgr.enable(p.name)
        check(mgr.get(p.name).enabled is True, "enable 后 enabled=True")

        # instance
        inst = mgr.get_instance(p.name)
        check(inst is p, "instance 是同一对象")
    finally:
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
#                  MAIN
# ═══════════════════════════════════════════════════════════

def main() -> int:
    if not _HAS_PLUGINS:
        print("⊘ smoke_h2_knowledge_plugin: SKIP (app.plugins 已废弃)")
        return 0
    print("=" * 60)
    print("H2 SMOKE: Knowledge Plugin (4 维度)")
    print("=" * 60)

    test_dimension_constants()
    test_plugin_lifecycle()
    test_get_dimensions()
    test_stats()
    test_list_by_dimension()
    test_search()
    test_search_multi_and_extract()
    test_import_file()
    test_plugin_manager_integration()

    print(f"\n{'=' * 60}")
    print(f"结果: {_pass} passed, {_fail} failed")
    print(f"{'=' * 60}")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
