"""
C1 SMOKE: 知识导入 (txt + md)
- import_file: .txt / .md (含/不含 frontmatter)
- import_text: 粘贴场景
- ai_classify: mock LLM, 验证 AI 补全 / 失败回退
- batch_import: 进度回调
- delete_local_doc: 防误删 builtin
- list_local: 分类筛选
- 边界: 空内容 / 不支持扩展名 / 文件过大 / 非法分类 / 重名

5 分钟自动超时 (threading.Timer, 跨平台, 防卡死)
"""
from __future__ import annotations

import os
import sys
import shutil
import tempfile
import threading
from pathlib import Path

# 5 分钟全局超时 (smoke 卡死保护, Windows 兼容用 Timer)
_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_c1_importer 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    print(f"[TIMEOUT] 请检查: 1) 终端输出最后一行  2) logs/NovelWriter_*.log  3) 是否被外部 IO 阻塞")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 必须在 import importer 之前先 import app.knowledge (确保 PRESET_CATEGORIES 等就绪)
from app.knowledge import (
    LOCAL_DIR,
    PRESET_CATEGORIES,
    SOURCE_LOCAL,
    bootstrap,
)
from app.knowledge.importer import (
    ImportSuggestion,
    ImportResult,
    import_file,
    import_text,
    ai_classify,
    suggest_only,
    batch_import,
    delete_local_doc,
    list_local,
    MAX_FILE_BYTES,
    DEFAULT_GENRE,
    VALID_CATEGORIES,
    VALID_EXTENSIONS,
    _build_filename,
    _sanitize_name,
    _validate_category,
)


# ────────────────────── Mock LLM ──────────────────────

def _install_mock_llm(canned_json: str = "") -> None:
    """
    替换 app.ai.engine.AIEngine 类为 mock, 无论 get_engine 怎么实现都生效。
    """
    from app.core.interfaces import LLMResult

    class _MockEngine:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, messages, **kwargs):
            return LLMResult(
                content=canned_json,
                model="mock",
                provider="mock",
                input_tokens=10,
                output_tokens=len(canned_json) // 2,
            )

        async def achat(self, messages, **kwargs):
            return self.chat(messages, **kwargs)

    # 直接 patch 类, get_engine() 实例化时调到这个类
    import app.ai.engine as _engine_mod
    _engine_mod.AIEngine = _MockEngine
    # 同时清掉可能的旧单例
    _engine_mod._engine = None


def _install_failing_mock_llm() -> None:
    """mock 一个永远抛异常的引擎. 用于测试 fallback 路径, 不连外网."""
    class _FailingEngine:
        def __init__(self, *a, **kw): pass
        def chat(self, messages, **kwargs):
            raise RuntimeError("mock 失败用于测试 fallback 路径")
        async def achat(self, messages, **kwargs):
            return self.chat(messages, **kwargs)
    import app.ai.engine as _engine_mod
    _engine_mod.AIEngine = _FailingEngine
    _engine_mod._engine = None


# ────────────────────── 测试 ──────────────────────

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
    print("C1 SMOKE: 知识导入 (txt + md)")
    print("=" * 60)

    # 0) 准备: bootstrap 目录 + 清空 local (除 README)
    print("\n[0] 准备: bootstrap + 清空 local")
    bootstrap()
    for cat in PRESET_CATEGORIES:
        d = LOCAL_DIR / cat
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.md"):
            if f.name.lower() != "readme.md":
                f.unlink()
    check(True, "local/ 已清空 (除 README)")

    # 1) 工具函数
    print("\n[1] 工具函数 _sanitize_name / _build_filename / _validate_category")
    check(_sanitize_name("仙侠_文风参考") == "仙侠_文风参考", f"中文名保留 (实际 {_sanitize_name('仙侠_文风参考')!r})")
    check(_sanitize_name("hello world!!") == "hello_world", f"特殊字符 → 下划线 (实际 {_sanitize_name('hello world!!')!r})")
    check(_sanitize_name("") != "", "空名 → 自动生成")
    check(_build_filename("仙侠", "文风") == "仙侠_文风.md", f"filename 拼接 (实际 {_build_filename('仙侠', '文风')!r})")
    try:
        _validate_category("不存在的分类")
        check(False, "非法分类应抛异常")
    except ValueError:
        check(True, "非法分类抛 ValueError")
    check(_validate_category("文风语料") == "文风语料", "合法分类通过")

    # 2) import_file - 纯 txt
    print("\n[2] import_file (.txt)")
    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = Path(tmpdir) / "test1.txt"
        txt_path.write_text(
            "这是一段仙侠风格的示例文字。剑光如霜, 主角立于山巅, "
            "寒风吹动衣袂, 故事从这一夜的雷雨开始。",
            encoding="utf-8",
        )
        r = import_file(txt_path, use_ai=False)
        check(r.success, f"import_file 成功 (error={r.error!r})")
        check(r.path is not None and r.path.exists(), f"文件已写入: {r.path}")
        check(r.path.parent.name in PRESET_CATEGORIES, f"落在合法分类目录 (实际 {r.path.parent.name})")
        check(r.suggestion.category == "文风语料", f"未传 category → 默认文风语料 (实际 {r.suggestion.category})")
        check(r.suggestion.genre == DEFAULT_GENRE, f"未传 genre → 默认通用 (实际 {r.suggestion.genre})")
        check(r.content_chars > 0, f"内容字数 > 0 (实际 {r.content_chars})")
        check(r.ai_used is False, "use_ai=False → ai_used=False")
        # frontmatter 校验
        text = r.path.read_text(encoding="utf-8")
        check(text.startswith("---\n"), "写入文件以 --- 开头")
        check("genre: 通用" in text, "frontmatter 含 genre: 通用")
        check("source: import" in text, "frontmatter 含 source: import")
        check("imported_at:" in text, "frontmatter 含 imported_at")
        # 校验能 read_doc 读回
        from app.knowledge import read_doc
        doc = read_doc(r.path)
        check(doc.genre == DEFAULT_GENRE, f"read_doc 读回 genre (实际 {doc.genre})")
        check(doc.content.strip() != "", "read_doc 读回 content 非空")

    # 3) import_file - 强传参数
    print("\n[3] import_file (强传 category/genre/tags)")
    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = Path(tmpdir) / "test2.txt"
        txt_path.write_text("古言宫廷文, 王爷与侯爷的爱恨情仇, 权谋与情义交织。", encoding="utf-8")
        r = import_file(
            txt_path,
            category="桥段",
            genre="古言",
            tags=["古言", "宫廷", "权谋"],
            summary="古言宫廷权谋",
            use_ai=False,
        )
        check(r.success, "强传参数成功")
        check(r.path.parent.name == "桥段", f"category=桥段 (实际 {r.path.parent.name})")
        check(r.suggestion.genre == "古言", f"genre=古言 (实际 {r.suggestion.genre})")
        check(r.suggestion.tags == ["古言", "宫廷", "权谋"], f"tags 一致 (实际 {r.suggestion.tags})")
        check(r.ai_used is False, "强传 → 无需 AI")

    # 4) import_file - .md 含 frontmatter (沿用原值)
    print("\n[4] import_file (.md 含 frontmatter)")
    with tempfile.TemporaryDirectory() as tmpdir:
        md_path = Path(tmpdir) / "test3.md"
        md_path.write_text(
            "---\ngeneric_text: 都市\ntags: [都市, 职场]\n---\n\n"
            "# 都市文参考\n\n"
            "霸总和灰姑娘, 写字楼里的爱恨情仇。",
            encoding="utf-8",
        )
        # 注意: 原文件用 'generic_text' 而非 'genre', 应 fallback 到 AI / 默认
        r = import_file(md_path, use_ai=False)
        check(r.success, ".md 导入成功")
        check(r.suggestion.genre == DEFAULT_GENRE, f"无 genre 字段 → 默认通用 (实际 {r.suggestion.genre})")

        # 现在传 genre, tags 缺失, 沿用 md 的 tags
        r2 = import_file(
            md_path.with_name("test3b.md"),
            genre="都市",
            use_ai=False,
        )
        # 写到 tmpdir 不行, 重写一个新文件
        md_path2 = Path(tmpdir) / "test3b.md"
        md_path2.write_text(
            "---\ngenre: 都市\ntags: [都市, 职场, 霸总]\n---\n\n"
            "写字楼里的霸总故事。",
            encoding="utf-8",
        )
        r2 = import_file(md_path2, use_ai=False)
        check(r2.success, ".md 带 genre 导入成功")
        check(r2.suggestion.genre == "都市", f"沿用 frontmatter genre (实际 {r2.suggestion.genre})")
        check(r2.suggestion.tags == ["都市", "职场", "霸总"], f"沿用 frontmatter tags (实际 {r2.suggestion.tags})")

    # 5) 重名 → 自动加后缀
    print("\n[5] 重名处理")
    with tempfile.TemporaryDirectory() as tmpdir:
        p1 = Path(tmpdir) / "dup.txt"
        p2 = Path(tmpdir) / "dup.txt"  # 同名
        p1.write_text("第一份内容, 仙侠风格。", encoding="utf-8")
        r1 = import_file(p1, genre="仙侠", use_ai=False)
        check(r1.success and not r1.renamed, "第一份: 不重命名")

        # 模拟第二份 (同名, 改 p2 内容)
        p2.write_text("第二份内容, 仍是仙侠。", encoding="utf-8")
        r2 = import_file(p2, genre="仙侠", use_ai=False)
        check(r2.success and r2.renamed, f"第二份: 自动重命名 (renamed={r2.renamed})")
        check(r1.path != r2.path, f"两个不同文件 (r1={r1.path.name}, r2={r2.path.name})")
        check("_2" in r2.path.name, f"重命名含 _2 (实际 {r2.path.name})")

    # 6) import_text
    print("\n[6] import_text (粘贴场景)")
    r = import_text(
        "悬疑推理: 密室里的真相, 每个人都有嫌疑。",
        name="密室推理",
        category="桥段",
        genre="悬疑",
        use_ai=False,
    )
    check(r.success, f"import_text 成功 (error={r.error!r})")
    check(r.path is not None and r.path.exists(), "文件已写入")
    check(r.path.parent.name == "桥段", f"分类=桥段 (实际 {r.path.parent.name})")
    check("密室" in r.path.read_text(encoding="utf-8"), "内容含 '密室'")

    # 7) ai_classify - 失败回退
    print("\n[7] ai_classify (mock 失败, 应回退默认 - 避免真连外网 138s)")
    _install_failing_mock_llm()  # mock 直接抛异常 → 走 fallback, 耗时 < 1s
    r = ai_classify("任意内容, 至少三十个字符的长度才能触发 AI 调用检查机制。")
    check(isinstance(r, ImportSuggestion), "返回 ImportSuggestion")
    check(r.category in VALID_CATEGORIES, f"category 合法 (实际 {r.category})")
    check(r.genre in (DEFAULT_GENRE,) + ("仙侠", "古言"), f"genre 在白名单 (实际 {r.genre})")
    # 注: 装失败 mock 后, ImportSuggestion 走兜底默认 (耗时 < 1s)

    # 8) ai_classify - mock LLM 正常返回
    print("\n[8] ai_classify (mock LLM)")
    canned = '{"category": "桥段", "genre": "仙侠", "tags": ["仙侠", "桥段"], "summary": "测试", "confidence": 0.9}'
    _install_mock_llm(canned)
    r = ai_classify("这是一段仙侠风格的桥段素材, 至少三十个字符能通过阈值检查。")
    check(r.category == "桥段", f"category=桥段 (实际 {r.category})")
    check(r.genre == "仙侠", f"genre=仙侠 (实际 {r.genre})")
    check(r.tags == ["仙侠", "桥段"], f"tags 一致 (实际 {r.tags})")
    check(r.confidence == 0.9, f"confidence=0.9 (实际 {r.confidence})")

    # 9) ai_classify - mock 烂 JSON
    print("\n[9] ai_classify (mock 烂 JSON)")
    _install_mock_llm("这不是 JSON, 一堆废话。AI 抽风了。")
    r = ai_classify("任意内容, 至少三十个字符的长度才能触发 AI 调用检查机制。")
    check(r.category == "文风语料", f"烂 JSON → 默认文风语料 (实际 {r.category})")
    check(r.genre == DEFAULT_GENRE, f"烂 JSON → 默认通用 (实际 {r.genre})")

    # 10) ai_classify - 短内容跳过
    print("\n[10] ai_classify (内容过短)")
    r = ai_classify("太短")
    check(r.category == "文风语料" and r.genre == DEFAULT_GENRE, "短内容 → 默认 suggestion")

    # 11) import_file + use_ai=True (mock)
    print("\n[11] import_file + use_ai=True (mock)")
    _install_mock_llm(canned)
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "ai_test.txt"
        # 内容必须 >= 30 字符 (MIN_CONTENT_FOR_AI), 否则 ai_classify 短路
        p.write_text(
            "一段仙侠风格的桥段素材, 描述主角在山巅与宿敌对峙的关键场景, "
            "含动作描写与环境烘托, 可作为玄幻文风参考。",
            encoding="utf-8",
        )
        r = import_file(p)  # use_ai=True 默认
        check(r.success, f"AI 导入成功 (error={r.error!r})")
        check(r.ai_used, f"ai_used=True (实际 {r.ai_used})")
        check(r.suggestion.category == "桥段", f"AI 建议 category=桥段 (实际 {r.suggestion.category})")
        check(r.suggestion.genre == "仙侠", f"AI 建议 genre=仙侠 (实际 {r.suggestion.genre})")

    # 12) 边界: 不支持的扩展名
    print("\n[12] 边界: 不支持的扩展名")
    with tempfile.TemporaryDirectory() as tmpdir:
        bad = Path(tmpdir) / "test.exe"
        bad.write_text("binary", encoding="utf-8")
        r = import_file(bad)
        check(not r.success, "不支持的扩展名应失败")
        check("不支持" in r.error, f"错误信息含 '不支持' (实际 {r.error!r})")

    # 13) 边界: 空内容
    print("\n[13] 边界: 空内容")
    with tempfile.TemporaryDirectory() as tmpdir:
        empty = Path(tmpdir) / "empty.txt"
        empty.write_text("   \n  \n", encoding="utf-8")
        r = import_file(empty, use_ai=False)
        check(not r.success, "空内容应失败")
        check("空" in r.error, f"错误信息含 '空' (实际 {r.error!r})")

    # 14) 边界: 文件过大
    print("\n[14] 边界: 文件过大")
    with tempfile.TemporaryDirectory() as tmpdir:
        big = Path(tmpdir) / "big.txt"
        big.write_text("a" * (MAX_FILE_BYTES + 100), encoding="utf-8")
        r = import_file(big, use_ai=False)
        check(not r.success, "文件过大应失败")
        check("过大" in r.error or "size" in r.error.lower(), f"错误信息含 '过大' (实际 {r.error!r})")

    # 15) 边界: 非法分类
    print("\n[15] 边界: 非法分类 (传给 import_text)")
    r = import_text(
        "内容至少三十个字符, 这样才能通过长度阈值的检查机制测试。",
        name="bad_cat",
        category="不存在的分类",
        use_ai=False,
    )
    check(not r.success, "非法分类应失败")
    check("未知分类" in r.error, f"错误信息含 '未知分类' (实际 {r.error!r})")

    # 16) batch_import + 进度回调
    print("\n[16] batch_import + 进度回调")
    with tempfile.TemporaryDirectory() as tmpdir:
        files = []
        for i in range(3):
            p = Path(tmpdir) / f"batch_{i}.txt"
            p.write_text(f"批量导入测试内容 {i}, 至少三十字符。 " * 2, encoding="utf-8")
            files.append(p)
        progress = []
        results = batch_import(files, use_ai=False, on_progress=lambda i, n, r: progress.append((i, n, r.success)))
        check(len(results) == 3, f"批量返回 3 个结果 (实际 {len(results)})")
        check(len(progress) == 3, f"回调触发 3 次 (实际 {len(progress)})")
        check(all(r.success for r in results), "全部成功")
        check(progress[-1][0] == 3, f"最后一次回调 i=3 (实际 {progress[-1][0]})")

    # 17) delete_local_doc
    print("\n[17] delete_local_doc")
    # 找一个 local 下的真实文件 (上面已经导入了一些)
    local_files = list_local("文风语料")
    check(len(local_files) > 0, f"local/文风语料 有文件 (实际 {len(local_files)})")
    if local_files:
        target = local_files[0]
        ok = delete_local_doc(target)
        check(ok, f"删除成功: {target.name}")
        check(not target.exists(), "文件已不存在")
        # 再删一次 → False
        check(delete_local_doc(target) is False, "重复删 → False")

    # 18) delete_local_doc - 拒绝删 builtin
    print("\n[18] delete_local_doc (拒绝删 builtin)")
    from app.knowledge import BUILTIN_DIR
    builtin_file = BUILTIN_DIR / "文风语料" / "仙侠_文风参考.md"
    if builtin_file.exists():
        try:
            delete_local_doc(builtin_file)
            check(False, "删 builtin 应抛异常")
        except ValueError:
            check(True, "删 builtin 抛 ValueError")
        check(builtin_file.exists(), "builtin 文件未受影响")

    # 19) list_local
    print("\n[19] list_local")
    all_local = list_local()
    check(isinstance(all_local, list), "list_local 返回 list")
    # 上面导入了不少, 应 ≥ 5 个
    check(len(all_local) >= 5, f"local 至少 5 个 (实际 {len(all_local)})")
    # 按分类
    style = list_local("文风语料")
    check(isinstance(style, list) and len(style) > 0, f"文风语料有内容 (实际 {len(style)})")

    # 20) suggest_only (UI 预览用)
    print("\n[20] suggest_only (UI 预览)")
    _install_mock_llm(canned)
    r = suggest_only(
        "一段仙侠风格的桥段素材, 描述主角在山巅对峙的关键场景, 含动作与环境烘托。"
    )
    check(isinstance(r, ImportSuggestion), "返回 ImportSuggestion")
    check(r.category == "桥段", f"suggest category=桥段 (实际 {r.category})")
    # suggest_only 是 ImportSuggestion (无 path 字段), 验证没意外写文件
    check(not hasattr(r, "path"), "suggest_only 是 ImportSuggestion (无 path)")

    # 总结
    print("\n" + "=" * 60)
    if not fails:
        print(f"C1 SMOKE PASS ({passed} assertions)")
        return 0
    else:
        print(f"C1 SMOKE FAIL ({len(fails)} failed):")
        for f in fails:
            print(f"  - {f}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
