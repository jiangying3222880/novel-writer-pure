"""
app/services/exporter.py - M9-B: 一键出版 (EPUB / Word / Markdown / TXT + 封面).

设计目标 (M9-B1 接口定义):
1. 4 种格式: EPUB (主) / DOCX / Markdown / TXT
2. 封面生成: PIL 拉预设模板 + 项目名/作者名排版
3. 自动目录: 按 book.chapter 顺序生成 TOC + 跳链
4. 三端共享: CLI / HTTP / UI 都能调
5. 不破坏分层: 在 L2 (app/services/) 内部, 走 services.db 拿 project/book/chapter
   业务层 (UI/CLI) 调 BookExporter.export_project()

公开 API:
    BookExporter(project_id, book_id=None) -> BookExporter
    exporter.export(format, output_path, *, with_cover=True) -> ExportResult

数据:
    ExportResult(output_path, format, chapter_count, file_size, cover_path)
    CoverRequest(template, project_name, author_name, style="default")
    CoverResult(path, width, height, format)
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Protocol
from xml.sax.saxutils import escape as xml_escape

_logger = logging.getLogger("NovelWriter.exporter")

# 模块级常量 (CLI/HTTP 端要 import)
SUPPORTED_FORMATS = ("md", "txt", "epub", "docx")
COVER_TEMPLATES = ("default", "minimal", "wuxia", "romance", "scifi")


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ChapterExport:
    """单个章节的导出内容."""
    chapter_id: str
    chapter_no: int
    title: str
    content: str
    word_count: int = 0


@dataclass
class BookExportData:
    """一本书的完整导出数据."""
    project_id: str
    project_name: str
    book_id: str
    book_title: str
    author_name: str = "佚名"
    chapters: List[ChapterExport] = field(default_factory=list)
    cover_path: Optional[str] = None
    description: str = ""
    genre: str = ""


@dataclass
class ExportResult:
    """导出结果."""
    output_path: str
    format: str                    # epub / docx / md / txt
    chapter_count: int
    file_size: int
    cover_path: Optional[str] = None
    duration_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CoverRequest:
    """封面生成请求."""
    template: str = "default"      # default / minimal / wuxia / romance / scifi
    project_name: str = ""
    author_name: str = "佚名"
    style: str = "default"
    width: int = 800
    height: int = 1200


@dataclass
class CoverResult:
    """封面生成结果."""
    path: str
    width: int
    height: int
    format: str                    # png / jpg
    template: str


# ============================================================
# 接口 (Protocol)
# ============================================================

class FormatExporter(Protocol):
    """单个格式的导出器."""
    format: str                    # epub / docx / md / txt

    def export(self, data: BookExportData, output_path: Path) -> ExportResult:
        """导出到 output_path. 返回 ExportResult."""
        ...


# ============================================================
# 默认实现占位 (M9-B2/B3/B4 落实)
# ============================================================

class MarkdownExporter:
    """B2 落实: Markdown 导出器.

    格式:
        # {book_title}
        作者: {author}
        类型: {genre}

        ## 目录
        - [第 1 章 title](#chapter-1)
        - [第 2 章 title](#chapter-2)

        ## 第 1 章 title
        {content}

        ## 第 2 章 title
        {content}
    """
    format = "md"

    def export(self, data: BookExportData, output_path: Path) -> ExportResult:
        t0 = time.time()
        lines: List[str] = []
        lines.append(f"# {data.book_title or data.project_name}")
        lines.append("")
        lines.append(f"**作者**: {data.author_name}")
        if data.genre:
            lines.append(f"**类型**: {data.genre}")
        if data.description:
            lines.append("")
            lines.append(f"> {data.description}")
        lines.append("")

        # 封面
        if data.cover_path:
            lines.append(f"![封面]({Path(data.cover_path).name})")
            lines.append("")

        # 目录
        lines.append("## 目录")
        lines.append("")
        for ch in data.chapters:
            anchor = f"chapter-{ch.chapter_no}"
            lines.append(f"- [第 {ch.chapter_no} 章 {ch.title}](#{anchor})")
        lines.append("")

        # 章节
        for ch in data.chapters:
            lines.append(f"## 第 {ch.chapter_no} 章 {ch.title}")
            lines.append("")
            lines.append(ch.content)
            lines.append("")
            lines.append("---")
            lines.append("")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        size = output_path.stat().st_size
        return ExportResult(
            output_path=str(output_path),
            format="md",
            chapter_count=len(data.chapters),
            file_size=size,
            cover_path=data.cover_path,
            duration_ms=int((time.time() - t0) * 1000),
        )


class TxtExporter:
    """B2 落实: 纯文本导出器."""
    format = "txt"

    def export(self, data: BookExportData, output_path: Path) -> ExportResult:
        t0 = time.time()
        lines: List[str] = []
        lines.append("=" * 60)
        lines.append(f"  {data.book_title or data.project_name}")
        lines.append("=" * 60)
        lines.append(f"作者: {data.author_name}")
        if data.genre:
            lines.append(f"类型: {data.genre}")
        if data.description:
            lines.append(f"简介: {data.description}")
        lines.append("")
        lines.append("")

        for ch in data.chapters:
            lines.append("─" * 60)
            lines.append(f"  第 {ch.chapter_no} 章  {ch.title}")
            lines.append("─" * 60)
            lines.append("")
            lines.append(ch.content)
            lines.append("")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        size = output_path.stat().st_size
        return ExportResult(
            output_path=str(output_path),
            format="txt",
            chapter_count=len(data.chapters),
            file_size=size,
            cover_path=data.cover_path,
            duration_ms=int((time.time() - t0) * 1000),
        )


class EpubExporter:
    """B2 落实: EPUB 导出器 (zip + xhtml, 极简实现).

    EPUB 3.0 最小结构:
        META-INF/container.xml
        mimetype                    (无 BOM, 固定内容 "application/epub+zip")
        OEBPS/content.opf           (包描述)
        OEBPS/toc.ncx               (导航中心, 旧格式但兼容)
        OEBPS/nav.xhtml             (EPUB 3 导航)
        OEBPS/chap_1.xhtml          (章节内容)
        OEBPS/chap_2.xhtml
        OEBPS/cover.xhtml           (封面)
    """
    format = "epub"

    def export(self, data: BookExportData, output_path: Path) -> ExportResult:
        t0 = time.time()
        # 文件名清理: EPUB 内部链接不能用某些字符
        def _sanitize(name: str) -> str:
            return re.sub(r'[^\w\u4e00-\u9fff\-_]', '_', name or "chapter")[:40]

        # 组装章节 xhtml 列表
        chapter_xhtml = []
        nav_lis = []
        for ch in data.chapters:
            fname = f"chap_{ch.chapter_no}.xhtml"
            body = xml_escape(ch.content or "")
            xhtml = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{xml_escape(ch.title or f'第{ch.chapter_no}章')}</title>
</head>
<body>
  <h1>第 {ch.chapter_no} 章 {xml_escape(ch.title or '')}</h1>
  <p>{body.replace(chr(10), '</p><p>')}</p>
</body>
</html>"""
            chapter_xhtml.append((fname, xhtml, ch))
            nav_lis.append(
                f'<li><a href="{fname}">第 {ch.chapter_no} 章 {xml_escape(ch.title or "")}</a></li>'
            )

        # nav.xhtml
        nav_xhtml = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><meta charset="utf-8" /><title>目录</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>目录</h1>
    <ol>
      {"".join(nav_lis)}
    </ol>
  </nav>
</body>
</html>"""

        # cover.xhtml
        cover_xhtml = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><meta charset="utf-8" /><title>封面</title></head>
<body>
  <h1>{xml_escape(data.book_title or data.project_name)}</h1>
  <p>{xml_escape(data.author_name)}</p>
</body>
</html>"""

        # content.opf
        spine_items = "\n    ".join(
            f'<itemref idref="chap_{ch.chapter_no}" />' for _, _, ch in chapter_xhtml
        )
        manifest_items = "\n    ".join(
            f'<item id="chap_{ch.chapter_no}" href="chap_{ch.chapter_no}.xhtml" media-type="application/xhtml+xml" />'
            for _, _, ch in chapter_xhtml
        )
        content_opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookId">urn:uuid:{data.book_id or data.project_id}</dc:identifier>
    <dc:title>{xml_escape(data.book_title or data.project_name)}</dc:title>
    <dc:creator>{xml_escape(data.author_name)}</dc:creator>
    <dc:language>zh-CN</dc:language>
    <dc:description>{xml_escape(data.description or '')}</dc:description>
    <meta property="dcterms:modified">{datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />
    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml" />
    {manifest_items}
  </manifest>
  <spine>
    <itemref idref="cover" />
    <itemref idref="nav" />
    {spine_items}
  </spine>
</package>"""

        # container.xml
        container_xml = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>"""

        # 写 zip (mimetype 必须是无压缩, 第一个 entry)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # mimetype 必须 first, no compress
            zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                        compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", container_xml)
            zf.writestr("OEBPS/content.opf", content_opf)
            zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
            zf.writestr("OEBPS/cover.xhtml", cover_xhtml)
            for fname, xhtml, ch in chapter_xhtml:
                zf.writestr(f"OEBPS/{fname}", xhtml)
            # 封面图
            if data.cover_path and Path(data.cover_path).exists():
                zf.write(data.cover_path, f"OEBPS/cover.png")

        size = output_path.stat().st_size
        return ExportResult(
            output_path=str(output_path),
            format="epub",
            chapter_count=len(data.chapters),
            file_size=size,
            cover_path=data.cover_path,
            duration_ms=int((time.time() - t0) * 1000),
            metadata={"valid_zip": True, "chapter_files": [n[0] for n in chapter_xhtml]},
        )


class DocxExporter:
    """B2 落实: DOCX 导出器 (zip + xml, 极简实现).

    极简 DOCX 结构:
        [Content_Types].xml
        _rels/.rels
        word/document.xml
        word/_rels/document.xml.rels
    字体: 不内嵌, 让系统用默认
    """
    format = "docx"

    def export(self, data: BookExportData, output_path: Path) -> ExportResult:
        t0 = time.time()

        # 段落列表
        paras: List[str] = []
        # 标题
        paras.append(_docx_para(data.book_title or data.project_name, "Heading1"))
        paras.append(_docx_para(f"作者: {data.author_name}", "Heading3"))
        if data.genre:
            paras.append(_docx_para(f"类型: {data.genre}", "Normal"))
        if data.description:
            paras.append(_docx_para(f"简介: {data.description}", "Normal"))
        # 目录
        paras.append(_docx_para("目录", "Heading2"))
        for ch in data.chapters:
            paras.append(_docx_para(f"第 {ch.chapter_no} 章 {ch.title}", "TOC1"))
        # 章节
        for ch in data.chapters:
            paras.append(_docx_para(f"第 {ch.chapter_no} 章 {ch.title}", "Heading2"))
            for line in (ch.content or "").split("\n"):
                paras.append(_docx_para(line, "Normal"))
            paras.append(_docx_para("", "Normal"))

        body = "\n".join(paras)
        document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {body}
    <w:sectPr>
      <w:pgSz w:w="12240" w:h="15840" />
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" />
    </w:sectPr>
  </w:body>
</w:document>"""

        # [Content_Types].xml
        content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />
  <Default Extension="xml" ContentType="application/xml" />
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml" />
</Types>"""

        # _rels/.rels
        rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml" />
</Relationships>"""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", content_types)
            zf.writestr("_rels/.rels", rels)
            zf.writestr("word/document.xml", document_xml)

        size = output_path.stat().st_size
        return ExportResult(
            output_path=str(output_path),
            format="docx",
            chapter_count=len(data.chapters),
            file_size=size,
            cover_path=data.cover_path,
            duration_ms=int((time.time() - t0) * 1000),
            metadata={"valid_zip": True},
        )


def _docx_para(text: str, style: str = "Normal") -> str:
    """生成 docx 段落 XML."""
    escaped = xml_escape(text or "")
    return (
        f'<w:p><w:pPr><w:pStyle w:val="{style}" /></w:pPr>'
        f'<w:r><w:t xml:space="preserve">{escaped}</w:t></w:r></w:p>'
    )


class CoverGenerator:
    """B3 落实: PIL 模板封面 (mock 渲染, 后续可接 AI 生图)."""
    def render(self, req: CoverRequest, output_path: Path) -> CoverResult:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            # PIL 不可用, 写个空 PNG 占位
            output_path.write_bytes(b"")
            return CoverResult(
                path=str(output_path), width=req.width, height=req.height,
                format="png", template=req.template,
            )
        # 配色: 按 template 选
        palettes = {
            "default": ((245, 240, 230), (60, 50, 40), (180, 100, 60)),
            "minimal": ((255, 255, 255), (40, 40, 40), (180, 180, 180)),
            "wuxia":   ((220, 200, 170), (80, 30, 20), (200, 100, 50)),
            "romance": ((250, 230, 235), (130, 60, 80), (220, 150, 170)),
            "scifi":   ((20, 30, 50), (180, 200, 230), (100, 150, 220)),
        }
        bg, fg, accent = palettes.get(req.template, palettes["default"])
        img = Image.new("RGB", (req.width, req.height), bg)
        draw = ImageDraw.Draw(img)
        # 顶部色带
        draw.rectangle([(0, 0), (req.width, 60)], fill=accent)
        # 底部色带
        draw.rectangle([(0, req.height - 60), (req.width, req.height)], fill=accent)

        # 字体
        font_title = None
        font_author = None
        try:
            # Windows 自带
            font_title = ImageFont.truetype("msyh.ttc", 56)
            font_author = ImageFont.truetype("msyh.ttc", 28)
        except Exception:
            try:
                font_title = ImageFont.truetype("arial.ttf", 56)
                font_author = ImageFont.truetype("arial.ttf", 28)
            except Exception:
                font_title = ImageFont.load_default()
                font_author = ImageFont.load_default()

        # 标题 (中间)
        title = req.project_name or "未命名"
        try:
            tbbox = draw.textbbox((0, 0), title, font=font_title)
            tw = tbbox[2] - tbbox[0]
            th = tbbox[3] - tbbox[1]
        except AttributeError:
            tw, th = draw.textsize(title, font=font_title)  # 旧版 PIL
        draw.text(
            ((req.width - tw) // 2, req.height // 2 - th),
            title, fill=fg, font=font_title,
        )
        # 作者 (底部色带上方)
        author = f"作者: {req.author_name}"
        try:
            abbox = draw.textbbox((0, 0), author, font=font_author)
            aw = abbox[2] - abbox[0]
        except AttributeError:
            aw, _ = draw.textsize(author, font=font_author)
        draw.text(
            ((req.width - aw) // 2, req.height - 50),
            author, fill=fg, font=font_author,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, format="PNG")
        return CoverResult(
            path=str(output_path), width=req.width, height=req.height,
            format="png", template=req.template,
        )


# ============================================================
# 数据收集 (M9-B2 落实)
# ============================================================

def _load_book_export_data(
    project_id: str,
    book_id: Optional[str] = None,
) -> BookExportData:
    """
    从 services.db 拿一本书的完整数据.
    - book_id=None → 拿项目下所有书合并导出
    - 章节按 chapter_no 排序
    """
    try:
        from app.db._impl import _connect_raw
        conn = _connect_raw()
    except Exception as e:
        _logger.warning("load_book_export_data: 拿不到 db: %s", e)
        return BookExportData(
            project_id=project_id, project_name="", book_id=book_id or "",
            book_title="",
        )

    # 安全读取: 先查列, 缺列 fallback (不抛错, 不依赖迁移)
    def _cols(table: str) -> set:
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            return {r[1] for r in rows}
        except Exception:
            return set()

    def _safe_value(table: str, row: tuple, col_names: List[str], col: str, default=None):
        if col not in col_names:
            return default
        if col not in row_dict:
            return default
        v = row_dict[col]
        return v if v is not None else default

    proj_cols = _cols("projects")
    chap_cols = _cols("chapters")
    books_cols = _cols("books")

    select_cols = [c for c in ("name", "book_title", "genre", "platform",
                                "author", "description") if c in proj_cols]
    try:
        if select_cols:
            row = conn.execute(
                f"SELECT {','.join(select_cols)} FROM projects WHERE id=?",
                (project_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT name FROM projects WHERE id=?",
                (project_id,),
            ).fetchone()
        if row is None:
            return BookExportData(
                project_id=project_id, project_name="(无项目)", book_id=book_id or "",
                book_title="",
            )
        row_dict = dict(zip(select_cols or ["name"], row))
    except Exception as e:
        _logger.warning("load_book_export_data 读 projects 失败: %s", e)
        return BookExportData(
            project_id=project_id, project_name="", book_id=book_id or "",
            book_title="",
        )

    proj_name = row_dict.get("name") or ""
    author = row_dict.get("author") or "佚名"
    desc = row_dict.get("description") or ""
    genre = row_dict.get("genre") or ""

    # 拿 books
    try:
        if book_id:
            bselect = [c for c in ("id", "title") if c in books_cols]
            if not bselect:
                bselect = ["id"]
            book_row = conn.execute(
                f"SELECT {','.join(bselect)} FROM books WHERE id=? AND project_id=?",
                (book_id, project_id),
            ).fetchone()
            if book_row is None:
                return BookExportData(
                    project_id=project_id, project_name=proj_name,
                    book_id=book_id, book_title="(无此书)",
                )
            books = [book_row]
        else:
            if "volume_no" in books_cols:
                books = conn.execute(
                    "SELECT id, title FROM books WHERE project_id=? ORDER BY volume_no",
                    (project_id,),
                ).fetchall()
            else:
                books = conn.execute(
                    "SELECT id, title FROM books WHERE project_id=?",
                    (project_id,),
                ).fetchall()
    except Exception as e:
        _logger.warning("load_book_export_data 读 books 失败: %s", e)
        books = []

    data = BookExportData(
        project_id=project_id, project_name=proj_name,
        book_id=book_id or "", book_title="", author_name=author,
        description=desc, genre=genre,
    )

    cselect = [c for c in ("id", "chapter_no", "title", "content", "word_count", "final")
               if c in chap_cols]
    if not cselect:
        cselect = ["id"]
    for b_id, *b_rest in books:
        b_title = b_rest[0] if b_rest else ""
        try:
            c_rows = conn.execute(
                f"SELECT {','.join(cselect)} FROM chapters WHERE book_id=? ORDER BY chapter_no",
                (b_id,),
            ).fetchall()
        except Exception as e:
            _logger.warning("load_book_export_data 读 chapters 失败: %s", e)
            c_rows = []
        for c_row in c_rows:
            crow_dict = dict(zip(cselect, c_row))
            content = crow_dict.get("content") or crow_dict.get("final") or ""
            data.chapters.append(ChapterExport(
                chapter_id=crow_dict.get("id", ""),
                chapter_no=crow_dict.get("chapter_no", 0),
                title=crow_dict.get("title", "") or "",
                content=content,
                word_count=crow_dict.get("word_count", 0) or 0,
            ))
    if book_id and books:
        data.book_title = books[0][1] if len(books[0]) > 1 else ""
    return data


# ============================================================
# 入口
# ============================================================

class BookExporter:
    """M9-B 主入口: 一键导出."""

    SUPPORTED_FORMATS = SUPPORTED_FORMATS  # alias for backward compat

    def __init__(
        self,
        project_id: str,
        book_id: Optional[str] = None,
    ) -> None:
        self.project_id = project_id
        self.book_id = book_id
        self._exporters: Dict[str, FormatExporter] = {
            "md": MarkdownExporter(),
            "txt": TxtExporter(),
            "epub": EpubExporter(),
            "docx": DocxExporter(),
        }
        self._cover_gen = CoverGenerator()

    def export(
        self,
        format: str,
        output_path: str,
        *,
        with_cover: bool = True,
        cover_template: str = "default",
    ) -> ExportResult:
        """统一导出入口."""
        if format not in self.SUPPORTED_FORMATS:
            raise ValueError(f"不支持的格式: {format} (支持: {self.SUPPORTED_FORMATS})")
        data = _load_book_export_data(self.project_id, self.book_id)
        if with_cover and self._cover_gen is not None:
            try:
                cover_req = CoverRequest(
                    template=cover_template,
                    project_name=data.book_title or data.project_name,
                    author_name=data.author_name,
                )
                cover_path = Path(output_path).with_suffix(".cover.png")
                cres = self._cover_gen.render(cover_req, cover_path)
                data.cover_path = str(cres.path)
            except Exception as e:
                _logger.warning("封面生成失败 (继续导出): %s", e)

        exporter = self._exporters[format]
        return exporter.export(data, Path(output_path))
