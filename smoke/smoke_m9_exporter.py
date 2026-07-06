"""
smoke_m9_exporter.py - M9-B 一键出版 smoke 测试

覆盖范围:
1. 数据结构 / 接口契约
2. Markdown / TXT 导出器
3. EPUB 导出器 (zip + xhtml 校验)
4. DOCX 导出器 (zip + xml 校验)
5. 封面生成器 (5 模板 + PIL 缺失兜底)
6. BookExporter 端到端 (md/txt/epub/docx + cover/no-cover)
7. 错误路径 (不支持的格式 / 空 project)
8. CLI 子命令 (export / export-formats / cover)
9. HTTP 端点 (formats / book / cover)
10. 集成: CLI + HTTP + Service 闭环

通过标准: 全部 OK, 失败时 check() 抛 AssertionError.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import List

# Windows cp936 修复
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 隔离 DB (跟 M8 一致, 父子进程共享)
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
os.environ.setdefault("NOVEL_WRITER_DB_PATH", str(_ROOT / "data" / "smoke_m9_exporter.db"))
os.environ.setdefault("NOVEL_WRITER_PLUGINS_DIR", str(_ROOT / "plugins_test_m9_exporter"))
os.environ.setdefault("NOVEL_WRITER_MARKET_DIR", str(_ROOT / "market_test_m9_exporter"))

# 跑测试前先清掉旧 DB
_db_path = Path(os.environ["NOVEL_WRITER_DB_PATH"])
if _db_path.exists():
    _db_path.unlink()

sys.path.insert(0, str(_ROOT))

_passed = 0
_failed = 0
_errors: List[str] = []


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def check(cond: bool, msg: str) -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ✅ {msg}")
    else:
        _failed += 1
        _errors.append(msg)
        print(f"  ❌ {msg}")


# ============================================================
# Part 1: 数据结构 / 接口
# ============================================================
def part1_data_classes() -> None:
    section("[Part 1] 数据结构 & 接口契约")
    from app.services.exporter import (
        ChapterExport, BookExportData, ExportResult,
        CoverRequest, CoverResult, FormatExporter,
        BookExporter, SUPPORTED_FORMATS,
    )
    c = ChapterExport(chapter_id="c1", chapter_no=1, title="t", content="x")
    check(c.chapter_no == 1, "ChapterExport 创建")
    b = BookExportData(project_id="p1", project_name="pn", book_id="b1", book_title="bt")
    b.chapters.append(c)
    check(len(b.chapters) == 1, "BookExportData 章节列表")
    e = ExportResult(output_path="/x", format="md", chapter_count=1, file_size=10)
    check(e.file_size == 10, "ExportResult 字段")
    cr = CoverRequest(template="default", project_name="t", author_name="a")
    check(cr.template == "default", "CoverRequest 默认")
    cres = CoverResult(path="/x", width=800, height=1200, format="png", template="default")
    check(cres.width == 800, "CoverResult 字段")
    check(FormatExporter is not None, "FormatExporter Protocol 存在")
    check("epub" in SUPPORTED_FORMATS, "SUPPORTED_FORMATS 含 epub")
    check("docx" in SUPPORTED_FORMATS, "SUPPORTED_FORMATS 含 docx")
    check("md" in SUPPORTED_FORMATS, "SUPPORTED_FORMATS 含 md")
    check("txt" in SUPPORTED_FORMATS, "SUPPORTED_FORMATS 含 txt")
    exporter = BookExporter("p1", "b1")
    check(len(exporter._exporters) == 4, "BookExporter 注册 4 个格式")
    check("epub" in exporter._exporters, "BookExporter 注册 epub")
    check("default" not in exporter._exporters, "BookExporter 4 个格式不重复")


# ============================================================
# Part 2: Markdown / TXT 导出器
# ============================================================
def part2_md_txt() -> None:
    section("[Part 2] Markdown / TXT 导出器")
    from app.services.exporter import (
        BookExportData, ChapterExport,
        MarkdownExporter, TxtExporter,
    )
    data = BookExportData(
        project_id="p", project_name="我的项目", book_id="b", book_title="我的书",
        author_name="张三", genre="玄幻", description="一个测试简介",
    )
    data.chapters.extend([
        ChapterExport(chapter_id="c1", chapter_no=1, title="开篇", content="第一段。\n第二段。"),
        ChapterExport(chapter_id="c2", chapter_no=2, title="发展", content="第二章节。"),
    ])

    with tempfile.TemporaryDirectory() as td:
        md_path = Path(td) / "out.md"
        result = MarkdownExporter().export(data, md_path)
        check(md_path.exists(), "MD 文件已生成")
        check(result.format == "md", "MD result.format")
        check(result.chapter_count == 2, "MD chapter_count=2")
        check(result.file_size > 0, "MD file_size > 0")
        content = md_path.read_text(encoding="utf-8")
        check("# 我的书" in content, "MD 包含书名 H1")
        check("**作者**: 张三" in content, "MD 包含作者")
        check("**类型**: 玄幻" in content, "MD 包含类型")
        check("> 一个测试简介" in content, "MD 包含简介")
        check("## 目录" in content, "MD 包含目录")
        check("[第 1 章 开篇]" in content, "MD TOC 含第 1 章")
        check("[第 2 章 发展]" in content, "MD TOC 含第 2 章")
        check("## 第 1 章 开篇" in content, "MD 含第 1 章标题")
        check("第一段。\n第二段。" in content, "MD 保留多段")
        check("---" in content, "MD 章节间分隔线")

    with tempfile.TemporaryDirectory() as td:
        txt_path = Path(td) / "out.txt"
        result = TxtExporter().export(data, txt_path)
        check(txt_path.exists(), "TXT 文件已生成")
        check(result.format == "txt", "TXT result.format")
        check(result.chapter_count == 2, "TXT chapter_count")
        content = txt_path.read_text(encoding="utf-8")
        check("我的书" in content, "TXT 含书名")
        check("作者: 张三" in content, "TXT 含作者")
        check("类型: 玄幻" in content, "TXT 含类型")
        check("简介: 一个测试简介" in content, "TXT 含简介")
        check("第 1 章" in content, "TXT 含第 1 章")
        check("第 2 章" in content, "TXT 含第 2 章")
        check("第一段。\n第二段。" in content, "TXT 保留段落")


# ============================================================
# Part 3: EPUB 导出器
# ============================================================
def part3_epub() -> None:
    section("[Part 3] EPUB 导出器")
    from app.services.exporter import (
        BookExportData, ChapterExport, EpubExporter,
    )
    data = BookExportData(
        project_id="p", project_name="项目", book_id="b1", book_title="书名",
        author_name="作者",
    )
    data.chapters.extend([
        ChapterExport(chapter_id="c1", chapter_no=1, title="一", content="一的内容。"),
        ChapterExport(chapter_id="c2", chapter_no=2, title="二", content="二的内容。"),
    ])
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "book.epub"
        result = EpubExporter().export(data, out)
        check(out.exists(), "EPUB 文件已生成")
        check(result.format == "epub", "EPUB format")
        check(result.file_size > 0, "EPUB file_size > 0")
        check(result.metadata.get("valid_zip") is True, "EPUB 标记 valid_zip")

        # 验证 zip 结构
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
            check("mimetype" in names, "EPUB 包含 mimetype")
            check("META-INF/container.xml" in names, "EPUB 包含 container.xml")
            check("OEBPS/content.opf" in names, "EPUB 包含 content.opf")
            check("OEBPS/nav.xhtml" in names, "EPUB 包含 nav.xhtml")
            check("OEBPS/cover.xhtml" in names, "EPUB 包含 cover.xhtml")
            check("OEBPS/chap_1.xhtml" in names, "EPUB 包含 chap_1")
            check("OEBPS/chap_2.xhtml" in names, "EPUB 包含 chap_2")

            mimetype = zf.read("mimetype").decode("ascii")
            check(mimetype == "application/epub+zip", "EPUB mimetype 内容正确")

            container = zf.read("META-INF/container.xml").decode("utf-8")
            check("OEBPS/content.opf" in container, "container.xml 指向 content.opf")

            opf = zf.read("OEBPS/content.opf").decode("utf-8")
            check("书名" in opf, "OPF 含书名")
            check("作者" in opf, "OPF 含作者")
            check("zh-CN" in opf, "OPF 语言 zh-CN")
            check('href="chap_1.xhtml"' in opf, "OPF manifest 含 chap_1")
            check('idref="chap_2"' in opf, "OPF spine 含 chap_2")

            nav = zf.read("OEBPS/nav.xhtml").decode("utf-8")
            check("目录" in nav, "nav.xhtml 含 '目录'")
            check("chap_1.xhtml" in nav, "nav 链接到 chap_1")
            check("chap_2.xhtml" in nav, "nav 链接到 chap_2")

            ch1 = zf.read("OEBPS/chap_1.xhtml").decode("utf-8")
            check("一的内容。" in ch1, "chap_1 含内容")
            check("第 1 章" in ch1, "chap_1 含章号标题")

    # 测试空章节书 (不崩)
    empty_data = BookExportData(project_id="p", project_name="p", book_id="b", book_title="b")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "empty.epub"
        result = EpubExporter().export(empty_data, out)
        check(out.exists(), "EPUB 空书仍生成")
        check(result.chapter_count == 0, "EPUB 空书 chapter_count=0")

    # 测试特殊字符: < > & 转义
    special_data = BookExportData(
        project_id="p", project_name="p", book_id="b", book_title="b <a>",
    )
    special_data.chapters.append(ChapterExport(
        chapter_id="c1", chapter_no=1, title="t<>&\"", content="x < y & z > w",
    ))
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "special.epub"
        EpubExporter().export(special_data, out)
        with zipfile.ZipFile(out, "r") as zf:
            ch1 = zf.read("OEBPS/chap_1.xhtml").decode("utf-8")
            check("x &lt; y &amp; z &gt; w" in ch1, "EPUB XML 转义 < > & 内容")
            check("t&lt;&gt;&amp;" in ch1, "EPUB XML 转义章节标题 < &")
            # OPF 里的 dc:title 也应该转义
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
            check("b &lt;a&gt;" in opf, "EPUB XML 转义 OPF dc:title")


# ============================================================
# Part 4: DOCX 导出器
# ============================================================
def part4_docx() -> None:
    section("[Part 4] DOCX 导出器")
    from app.services.exporter import BookExportData, ChapterExport, DocxExporter
    data = BookExportData(
        project_id="p", project_name="p", book_id="b", book_title="DOCX 书",
        author_name="作者", genre="科幻",
    )
    data.chapters.append(ChapterExport(
        chapter_id="c1", chapter_no=1, title="一", content="第一段。\n第二段。",
    ))
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "book.docx"
        result = DocxExporter().export(data, out)
        check(out.exists(), "DOCX 文件已生成")
        check(result.format == "docx", "DOCX format")
        check(result.file_size > 0, "DOCX file_size > 0")

        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
            check("[Content_Types].xml" in names, "DOCX 包含 [Content_Types].xml")
            check("_rels/.rels" in names, "DOCX 包含 _rels/.rels")
            check("word/document.xml" in names, "DOCX 包含 document.xml")

            doc = zf.read("word/document.xml").decode("utf-8")
            check("DOCX 书" in doc, "DOCX document.xml 含书名")
            check("作者: 作者" in doc, "DOCX document.xml 含作者")
            check("Heading1" in doc, "DOCX 含 Heading1 样式")
            check("Heading2" in doc, "DOCX 含 Heading2 样式")
            check("第一段。" in doc, "DOCX 段落内容")
            check("第二段。" in doc, "DOCX 多段保留")
            check("第 1 章" in doc, "DOCX 章节标题")

            rels = zf.read("_rels/.rels").decode("utf-8")
            check("word/document.xml" in rels, "DOCX rels 指向 document.xml")


# ============================================================
# Part 5: 封面生成器
# ============================================================
def part5_cover() -> None:
    section("[Part 5] 封面生成器")
    from app.services.exporter import CoverGenerator, CoverRequest
    templates = ("default", "minimal", "wuxia", "romance", "scifi")
    gen = CoverGenerator()
    for tpl in templates:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / f"cover_{tpl}.png"
            req = CoverRequest(template=tpl, project_name=f"书名-{tpl}", author_name="作者")
            res = gen.render(req, out)
            check(out.exists(), f"封面 {tpl} 已生成")
            check(res.template == tpl, f"封面 {tpl} 模板回传")
            check(res.width > 0, f"封面 {tpl} width > 0")
            check(res.height > 0, f"封面 {tpl} height > 0")
            if out.stat().st_size > 0:
                # 验证 PNG 头
                with open(out, "rb") as f:
                    head = f.read(8)
                check(head[:4] == b"\x89PNG", f"封面 {tpl} 是 PNG 格式")


# ============================================================
# Part 6: BookExporter 端到端 (无 DB, _load_book_export_data 走 fallback)
# ============================================================
def part6_book_exporter() -> None:
    section("[Part 6] BookExporter 端到端 (4 格式 × cover/no-cover)")
    from app.services.exporter import BookExporter, SUPPORTED_FORMATS
    # 模拟一个无 DB 的 project: _load_book_export_data 走 fallback 返回空数据
    # 但 BookExporter.export 仍会调 PIL 生成封面 + 写空 chapters 文件
    formats = ("md", "txt", "epub", "docx")
    for fmt in formats:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / f"book.{fmt}"
            exporter = BookExporter("nonexistent-project", None)
            try:
                result = exporter.export(fmt, str(out), with_cover=True, cover_template="default")
            except Exception as e:
                check(False, f"{fmt} export raised: {e}")
                continue
            check(out.exists(), f"{fmt} 文件已生成")
            check(result.format == fmt, f"{fmt} format 回传")
            check(result.chapter_count == 0, f"{fmt} 空项目 chapter_count=0")
            check(result.file_size >= 0, f"{fmt} file_size >= 0")

    # no_cover
    for fmt in ("md", "epub"):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / f"book_nc.{fmt}"
            exporter = BookExporter("nonexistent-project", None)
            result = exporter.export(fmt, str(out), with_cover=False)
            check(result.cover_path is None or result.cover_path == "",
                  f"{fmt} no_cover 不带封面")

    # 不支持的格式
    exporter = BookExporter("nonexistent")
    try:
        exporter.export("pdf", "/tmp/x.pdf")
        check(False, "pdf 应该被拒绝")
    except ValueError as e:
        check("不支持" in str(e) or "pdf" in str(e), "pdf 错误消息正确")


# ============================================================
# Part 7: 错误路径
# ============================================================
def part7_errors() -> None:
    section("[Part 7] 错误路径 & 边界")
    from app.services.exporter import (
        BookExportData, ChapterExport, MarkdownExporter, BookExporter,
    )
    # BookExporter 不存在的 project
    exporter = BookExporter("no-such-project", None)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "x.md"
        # 不抛错, 但返回空数据
        result = exporter.export("md", str(out))
        check(result.chapter_count == 0, "不存在 project 返回 0 章节")
        check(out.exists(), "不存在 project 仍生成空 md")

    # 输出路径父目录不存在 → mkdir parents
    exporter = BookExporter("no-such")
    deep = Path(tempfile.gettempdir()) / "smoke_m9_deep" / "a" / "b" / "x.md"
    if deep.parent.exists():
        import shutil
        shutil.rmtree(deep.parent.parent.parent)
    try:
        result = exporter.export("md", str(deep))
        check(deep.exists(), "深嵌套路径自动创建")
    except Exception as e:
        check(False, f"深嵌套路径失败: {e}")

    # cover_template 不存在 → fallback to default palette (不抛错)
    exporter = BookExporter("no-such")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "x.md"
        result = exporter.export("md", str(out), cover_template="nonsense-template")
        check(out.exists(), "未知 cover_template 不影响导出")


# ============================================================
# Part 8: CLI 子命令
# ============================================================
def _run_cli(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    """封装 subprocess, 强制 utf-8 解码 (避免 Windows gbk 崩)."""
    return subprocess.run(
        [sys.executable] + args,
        capture_output=True, text=True, timeout=timeout, cwd=str(_ROOT),
        env={**os.environ, "PYTHONPATH": str(_ROOT),
             "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        encoding="utf-8", errors="replace",
    )


def part8_cli() -> None:
    section("[Part 8] CLI 子命令 (book export / export-formats / cover)")
    from app.cli import build_parser

    # 解析器可以 build
    p = build_parser()
    check(p is not None, "build_parser() OK")

    # export-formats (无需 DB)
    r = _run_cli(["-m", "app.cli", "book", "export-formats"])
    check(r.returncode == 0, f"CLI export-formats 退出码 0 (rc={r.returncode})")
    stdout = r.stdout or ""
    check("epub" in stdout and "docx" in stdout,
          f"CLI export-formats 输出格式列表: {stdout[:200]!r}")

    # export-formats --json
    r = _run_cli(["-m", "app.cli", "book", "export-formats", "--json"])
    check(r.returncode == 0, f"CLI export-formats --json rc=0 (rc={r.returncode})")
    stdout = r.stdout or ""
    try:
        j = json.loads(stdout) if stdout.strip() else {}
        check("epub" in j.get("formats", []), "CLI --json 含 epub")
        check("default" in j.get("cover_templates", []), "CLI --json 含 default")
    except Exception as e:
        check(False, f"CLI --json 解析失败: {e}, stdout={stdout[:200]!r}")

    # cover 单独生成
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "mycover.png"
        r = _run_cli(["-m", "app.cli", "book", "cover",
                      "--title", "测试书", "--author", "测试作者",
                      "--template", "wuxia", "--output", str(out)])
        check(r.returncode == 0, f"CLI cover rc=0 (rc={r.returncode})")
        check(out.exists(), "CLI cover 生成文件")
        if out.exists() and out.stat().st_size > 0:
            with open(out, "rb") as f:
                head = f.read(8)
            check(head[:4] == b"\x89PNG", "CLI cover 是 PNG")

    # 错误: 不存在的 project
    r = _run_cli(["-m", "app.cli", "book", "export",
                  "--project", "no-such-uuid", "--format", "md"])
    check(r.returncode != 0, f"CLI export 不存在 project 应该非 0 (rc={r.returncode})")

    # 错误: 不支持格式
    r = _run_cli(["-m", "app.cli", "book", "export",
                  "--project", "xxx", "--format", "pdf"])
    check(r.returncode != 0, "CLI export --format pdf 应该非 0")


# ============================================================
# Part 9: HTTP 端点
# ============================================================
def part9_http() -> None:
    section("[Part 9] HTTP 端点 (formats / book / cover)")
    from app.extension_api.http_bridge import start_server, _ROUTES

    # 路由注册
    check(("GET", "/export/formats") in _ROUTES, "/export/formats 已注册")
    check(("POST", "/export/book") in _ROUTES, "/export/book 已注册")
    check(("POST", "/export/cover") in _ROUTES, "/export/cover 已注册")

    # 起 server, 用 urllib 测
    import socket
    import threading
    import time
    import urllib.request
    import urllib.error

    # 找空闲端口
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = start_server("127.0.0.1", port)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)

    base = f"http://127.0.0.1:{port}"

    def _get(path):
        return urllib.request.urlopen(base + path, timeout=5).read().decode("utf-8")

    def _post(path, body):
        req = urllib.request.Request(
            base + path, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        return urllib.request.urlopen(req, timeout=10).read().decode("utf-8")

    try:
        # GET /export/formats
        r = _get("/export/formats")
        j = json.loads(r)
        check(j.get("ok") is True, f"GET /export/formats ok={j.get('ok')}")
        check("epub" in j.get("formats", []), "GET /export/formats 含 epub")
        check("default" in j.get("cover_templates", []), "GET /export/formats 含 default")

        # POST /export/book
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "x.md"
            r = _post("/export/book", {
                "project_id": "no-such-proj",
                "format": "md",
                "output_path": str(out),
                "with_cover": False,
            })
            j = json.loads(r)
            check(j.get("ok") is True, f"POST /export/book ok={j.get('ok')} err={j.get('error')}")
            check(j.get("format") == "md", f"POST /export/book format={j.get('format')}")
            check(Path(j.get("output_path", "")).exists(), "POST /export/book 文件已写")

        # POST /export/book 缺 project_id
        r = _post("/export/book", {"format": "md"})
        j = json.loads(r)
        check(j.get("ok") is False, "POST /export/book 缺 project_id 返回 ok=False")

        # POST /export/book 不支持格式
        r = _post("/export/book", {"project_id": "p", "format": "pdf"})
        j = json.loads(r)
        check(j.get("ok") is False, "POST /export/book pdf 拒绝")

        # POST /export/cover
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "cov.png"
            r = _post("/export/cover", {
                "title": "HTTP 测试", "author": "测试",
                "template": "scifi", "output_path": str(out),
            })
            j = json.loads(r)
            check(j.get("ok") is True, f"POST /export/cover ok={j.get('ok')} err={j.get('error')}")
            check(j.get("template") == "scifi", f"cover template={j.get('template')}")
            check(Path(j.get("path", "")).exists(), "POST /export/cover 文件已写")

        # POST /export/cover 错模板
        r = _post("/export/cover", {"template": "nope"})
        j = json.loads(r)
        check(j.get("ok") is False, "POST /export/cover 错模板拒绝")

        # 回归 /health 还能用 (M4 端点没坏)
        r = _get("/health")
        j = json.loads(r)
        check(j.get("ok") is True, "GET /health 仍 OK")

    finally:
        server.shutdown()
        server.server_close()


# ============================================================
# Part 10: 集成测试 (DB → BookExporter 闭环)
# ============================================================
def part10_integration_db() -> None:
    section("[Part 10] 集成: DB 落库 + Exporter 端到端")
    # 准备 DB
    from app.services.db import init_db
    init_db()
    from app.services import project_service, book_service, chapter_service
    proj = project_service.create(
        name="测试项目-集成", book_title="集成书", genre="玄幻",
        platform="起点", word_target=200000,
    )
    book = book_service.create(project_id=proj["id"], volume_no=1, title="第一卷")
    chapter_service.create(book_id=book["id"], chapter_no=1, title="开篇",
                            scene_context="主角下山")
    chapter_service.create(book_id=book["id"], chapter_no=2, title="遇敌",
                            scene_context="下山遇魔教")
    # 写入 final 内容
    from app.services.db import _connect
    conn = _connect()
    conn.execute(
        "UPDATE chapters SET final=? WHERE book_id=? AND chapter_no=1",
        ("这是第一段内容。\n第二段内容。", book["id"]),
    )
    conn.execute(
        "UPDATE chapters SET final=? WHERE book_id=? AND chapter_no=2",
        ("第二章节。魔教袭来。", book["id"]),
    )
    conn.commit()
    conn.close()

    from app.services.exporter import BookExporter
    with tempfile.TemporaryDirectory() as td:
        for fmt in ("md", "txt", "epub", "docx"):
            out = Path(td) / f"book.{fmt}"
            exp = BookExporter(proj["id"], book["id"])
            res = exp.export(fmt, str(out), with_cover=True, cover_template="wuxia")
            check(out.exists(), f"集成 {fmt} 文件已生成")
            check(res.chapter_count == 2, f"集成 {fmt} chapter_count=2")
            if fmt in ("md", "txt"):
                content = out.read_text(encoding="utf-8")
                check("第一段内容" in content, f"集成 {fmt} 含第 1 章内容")
                check("第二章节" in content, f"集成 {fmt} 含第 2 章内容")
            elif fmt == "epub":
                with zipfile.ZipFile(out, "r") as zf:
                    ch1 = zf.read("OEBPS/chap_1.xhtml").decode("utf-8")
                    check("第一段内容" in ch1, "集成 EPUB chap_1 内容")
            elif fmt == "docx":
                with zipfile.ZipFile(out, "r") as zf:
                    doc = zf.read("word/document.xml").decode("utf-8")
                    check("第一段内容" in doc, "集成 DOCX 含第 1 章内容")

    # book_id=None (全项目合并)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "all.md"
        exp = BookExporter(proj["id"], None)
        res = exp.export("md", str(out), with_cover=False)
        check(out.exists(), "book_id=None 整项目导出")
        check(res.chapter_count == 2, "整项目 chapter_count=2")


# ============================================================
# main
# ============================================================
def main() -> int:
    print("M9-B 一键出版 smoke 测试 (export + cover + http + cli)\n")
    parts = [
        ("Part 1 数据结构", part1_data_classes),
        ("Part 2 MD/TXT", part2_md_txt),
        ("Part 3 EPUB", part3_epub),
        ("Part 4 DOCX", part4_docx),
        ("Part 5 封面", part5_cover),
        ("Part 6 BookExporter", part6_book_exporter),
        ("Part 7 错误路径", part7_errors),
        ("Part 8 CLI", part8_cli),
        ("Part 9 HTTP", part9_http),
        ("Part 10 集成", part10_integration_db),
    ]
    for name, fn in parts:
        try:
            fn()
        except Exception as e:
            check(False, f"{name} 异常: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n========== {_passed} passed / {_failed} failed ==========")
    if _errors:
        print("\n失败项:")
        for e in _errors:
            print(f"  - {e}")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
