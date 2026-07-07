"""
I13 RichTextViewer - Markdown/HTML 富文本查看器.

设计参考 docs/widgets-mockup.html I13 (2026-06-10 批准).

特性:
- 输入 Markdown 文本, 渲染为 HTML 显示
- 暗色样式 (与全局 theme 同步): h1/h2/h3/code/pre/blockquote/ul/ol
- 仅用于只读展示 (无编辑)
- 自动滚动 + 限制最大高度

依赖说明:
- 优先用 markdown 库 (轻量), 失败则降级为纯文本 + 简易行级替换
"""
from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget


# ---- Markdown 渲染 ----

def _md_to_html(text: str) -> str:
    """轻量 Markdown → HTML 转换 (不依赖外部库).

    支持: # ## ### 标题, **粗体**, *斜体*, `code`, 代码块 ```, > 引用, - 列表, [text](url).
    转换结果再用 CSS 渲染 (在 QTextBrowser 的 document 中).
    """
    lines: list[str] = []
    in_code = False
    in_list = False
    in_para: list[str] = []

    def flush_para() -> None:
        if in_para:
            lines.append("<p>" + _inline(" ".join(in_para)) + "</p>")
            in_para.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                lines.append("</code></pre>")
                in_code = False
            else:
                flush_para()
                if in_list:
                    lines.append("</ul>")
                    in_list = False
                lines.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            # code block 内不解析 markdown
            lines.append(_escape(line))
            continue
        if not line.strip():
            flush_para()
            if in_list:
                lines.append("</ul>")
                in_list = False
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush_para()
            if in_list:
                lines.append("</ul>")
                in_list = False
            level = len(m.group(1))
            lines.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            continue
        if line.startswith("> "):
            flush_para()
            if in_list:
                lines.append("</ul>")
                in_list = False
            lines.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
            continue
        if re.match(r"^\s*[-*]\s+", line):
            if not in_list:
                lines.append("<ul>")
                in_list = True
            item = re.sub(r"^\s*[-*]\s+", "", line)
            lines.append(f"<li>{_inline(item)}</li>")
            continue
        # 普通段落行
        in_para.append(line)

    flush_para()
    if in_list:
        lines.append("</ul>")
    if in_code:
        lines.append("</code></pre>")
    return "\n".join(lines)


_INLINE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_INLINE_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_INLINE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline(text: str) -> str:
    text = _escape(text)
    # 注意顺序: code > bold > italic > link
    text = _INLINE_CODE.sub(r'<code>\1</code>', text)
    text = _INLINE_BOLD.sub(r"<strong>\1</strong>", text)
    text = _INLINE_ITALIC.sub(r"<em>\1</em>", text)
    text = _INLINE_LINK.sub(r'<a href="\2">\1</a>', text)
    return text


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ---- QSS 暗色 ----

_DARK_RICH_QSS = """
QTextBrowser {
    background: #0a0b0d; color: #c8cdd4; border: 1px solid #2a2b2f;
    border-radius: 4px; padding: 16px 20px; line-height: 1.7;
}
QTextBrowser h1 { color: #f0f1f2; font-size: 18px; margin: 12px 0 8px; padding-bottom: 6px; border-bottom: 1px solid #2a2b2f; }
QTextBrowser h2 { color: #f0f1f2; font-size: 15px; margin: 10px 0 6px; }
QTextBrowser h3 { color: #6c7ae0; font-size: 13px; margin: 8px 0 4px; }
QTextBrowser h4, QTextBrowser h5, QTextBrowser h6 { color: #c8cdd4; font-size: 12px; margin: 6px 0 4px; }
QTextBrowser p { margin: 6px 0; }
QTextBrowser code {
    background: #191a1b; border: 1px solid #2a2b2f; border-radius: 2px;
    padding: 1px 5px; color: #e8a23a; font-family: "JetBrains Mono", "Consolas", monospace; font-size: 12px;
}
QTextBrowser pre {
    background: #0a0b0d; border: 1px solid #2a2b2f; border-radius: 3px;
    padding: 8px 12px; margin: 8px 0;
}
QTextBrowser pre code { background: transparent; border: none; padding: 0; color: #c8cdd4; }
QTextBrowser ul, QTextBrowser ol { margin: 6px 0 6px 20px; }
QTextBrowser li { margin: 2px 0; }
QTextBrowser blockquote {
    border-left: 3px solid #6c7ae0; background: rgba(108,122,224,0.06);
    padding: 6px 12px; margin: 8px 0; color: #8a8f98; font-style: italic;
}
QTextBrowser strong { color: #f0f1f2; }
QTextBrowser em { color: #6c7ae0; }
QTextBrowser a { color: #6c7ae0; text-decoration: none; }
QTextBrowser a:hover { text-decoration: underline; }
"""


class RichTextViewer(QWidget):
    """Markdown / HTML 富文本只读查看器."""

    def __init__(
        self,
        *,
        max_height: int = 280,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._max_height = max_height
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._browser = QTextBrowser(self)
        self._browser.setOpenExternalLinks(True)
        f = QFont("Inter")
        f.setPointSize(10)
        self._browser.setFont(f)
        self._browser.setStyleSheet(_DARK_RICH_QSS)
        self._browser.document().setDocumentMargin(0)
        if max_height:
            self._browser.setMaximumHeight(max_height)
        layout.addWidget(self._browser)

    # ---- 公开 API ----
    def set_markdown(self, md: str) -> None:
        html = _md_to_html(md or "")
        self._browser.setHtml(f'<div style="color:#c8cdd4;">{html}</div>')

    def set_html(self, html: str) -> None:
        self._browser.setHtml(html or "")

    def set_plain(self, text: str) -> None:
        """直接显示纯文本 (不转 markdown)."""
        self._browser.setPlainText(text or "")

    def clear(self) -> None:
        self._browser.clear()

    def text_browser(self) -> QTextBrowser:
        return self._browser
