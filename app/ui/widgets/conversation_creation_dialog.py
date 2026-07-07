"""
ConversationCreationDialog — 自由对话式项目创建（流式输出版）.

不再是僵硬的 3 步向导，而是一个真正的聊天界面：
  1. LLM 作为写作助手，像朋友一样聊天，逐步了解故事
  2. 思考过程 (thinking) 和正式回复 (content) 流式分开展示
  3. 聊到双方满意后，用户点「生成设定」→ LLM 输出完整设定
  4. 设定可编辑，确认后创建项目（世界观/角色/大纲全同步）
  5. 项目创建后具备开始写作的全部条件，用户手动去写

主题适配: 不硬编码颜色, 通过 theme 工具函数取值, 暗/亮主题自适应.
"""
from __future__ import annotations
import logging
import os
import re
import time
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QTextBrowser, QFrame, QWidget, QSplitter,
    QTextEdit, QSizePolicy,
)

from app.ui.widgets import Dialogs

log = logging.getLogger(__name__)


# ================================================================
# 主题取色 (全部从 app.ui.theme 统一管理)
# ================================================================
from app.ui.theme import (
    text_primary, text_muted, text_secondary, text_accent, text_warn,
    surface_bg, deep_bg, border_color, input_bg,
    is_dark, text_accent_violet,
)


# ================================================================
# 流式聊天 Worker
# ================================================================
class _StreamChatWorker(QThread):
    """在后台线程调 LLM 流式 API，通过 Signal 推回主线程。

    Signal:
      thinking(str) — 思考过程 chunk（实时）
      chunk(str) — 正文 chunk（实时）
      done(str, str) — 完整内容 + 完整思考
      fail(str) — 错误信息
      finished() — 必发，清 thread
    """
    thinking = Signal(str)
    chunk = Signal(str)
    done = Signal(str, str)  # (content, thinking)
    fail = Signal(str)
    finished = Signal()

    def __init__(self, messages: list[dict], max_tokens: int = 2000,
                 *, use_mock: bool = False, mock_fn=None) -> None:
        super().__init__()
        self._messages = messages
        self._max_tokens = max_tokens
        self._use_mock = use_mock
        self._mock_fn = mock_fn

    def run(self) -> None:
        try:
            if self._use_mock:
                self._run_mock()
            else:
                self._run_stream()
        except Exception as e:
            log.warning("StreamChatWorker failed: %s", e)
            self.fail.emit(str(e))
        finally:
            self.finished.emit()

    def _run_stream(self) -> None:
        """真正的流式 LLM 调用."""
        from app.services.router.real_client import create_real_client
        client = create_real_client()
        content_acc = ""
        thinking_acc = ""
        try:
            for typ, text in client.chat_stream(
                self._messages,
                temperature=0.7,
                max_tokens=self._max_tokens,
            ):
                if typ == "thinking":
                    thinking_acc += text
                    self.thinking.emit(text)
                else:
                    content_acc += text
                    self.chunk.emit(text)
        except Exception:
            # 流式失败 → 降级到非流式
            log.warning("Stream failed, falling back to non-streaming chat")
            result = client.chat(
                self._messages,
                temperature=0.7,
                max_tokens=self._max_tokens,
            )
            content_acc = result.content if hasattr(result, 'content') else str(result)
            thinking_acc = getattr(result, 'thinking', '') or ''
            if thinking_acc:
                self.thinking.emit(thinking_acc)
            # 一次发完整内容
            self.chunk.emit(content_acc)
        self.done.emit(content_acc.strip() if content_acc else "", thinking_acc)

    def _run_mock(self) -> None:
        """Mock 模式：分段模拟流式输出."""
        if self._mock_fn is None:
            self.done.emit("", "")
            return
        full_text = self._mock_fn()
        # 模拟思考
        if "追问" in str(self._messages) or "了解" in str(self._messages):
            # 模拟一小段思考
            self._emit_delayed(
                "正在回顾对话内容，分析作者的创作意图和故事框架...\n",
                "thinking",
            )
        # 按句子分段模拟流式
        parts = self._split_sentences(full_text)
        for part in parts:
            time.sleep(0.08)
            self.chunk.emit(part)
        self.done.emit(full_text.strip(), "")

    def _emit_delayed(self, text: str, typ: str) -> None:
        """逐字模拟延迟发送."""
        for i in range(0, len(text), 3):
            chunk = text[i:i+3]
            time.sleep(0.04)
            if typ == "thinking":
                self.thinking.emit(chunk)
            else:
                self.chunk.emit(chunk)

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """按句子边界分段，保证每段不太短."""
        import re as _re
        parts = _re.split(r'(?<=[。！？\n])', text)
        result = []
        buf = ""
        for p in parts:
            buf += p
            if len(buf) >= 4:
                result.append(buf)
                buf = ""
        if buf:
            result.append(buf)
        return result


# ================================================================
# System Prompts
# ================================================================
CHAT_SYSTEM_PROMPT = """你是一位资深的小说策划编辑（不是代笔作家）。你的唯一任务是通过自然对话，帮作者把小说的「核心设定」聊清楚。

## 你的身份
你是策划编辑，负责前期规划。你不是来替作者写正文的，绝对不要写任何小说正文、片段或描写。

## 你需要收集的信息（按顺序推进）
请像朋友聊天一样，逐步了解以下 6 个方面。每轮只问 1-2 个问题，不要一口气全问：

1. **基础信息** — 题材类型？什么时代/世界背景？大概多少字？
2. **主角** — 姓名、性格、目标、最大的困境是什么？
3. **世界观** — 这个世界有什么特殊规则？（修炼体系/科技水平/社会结构等）
4. **核心冲突** — 主角要面对的主要矛盾是什么？谁在阻碍他/她？
5. **剧情走向** — 开篇怎么切入？大致的故事弧线？
6. **风格定位** — 基调（热血/轻松/严肃）？节奏快慢？目标读者？

## 对话规则
- 自然友好，适当幽默，让对方有表达欲
- 根据回答深入追问关键细节，不要浮于表面
- 对用户的创意给予积极反馈和共鸣
- 回应简洁有力，不要长篇大论

## 绝对禁止
- ❌ 不要写任何小说正文、段落、对话、描写
- ❌ 不要编造具体情节细节（"某天晚上，十美又挤在他那张一米五的床上"这种）
- ❌ 不要替用户做创作决策，而是引导用户自己想清楚

## 完成判断
当你确认以上 6 个方面都聊得差不多了（通常 5-8 轮），在回复末尾加上：
> ✅ **信息已充足 — 你可以点击「生成设定」按钮了，我会根据咱们的对话生成完整的小说设定文档。**

如果还有明显缺失的关键信息，继续追问那一方面就好。

开场：先简单自我介绍（说明你是来帮忙规划设定的），然后问用户想写什么样的故事。"""


GENERATE_SETTINGS_PROMPT = """你是一位资深的小说策划编辑。以下是和作者的全部对话记录。

请根据这些对话，生成一份完整的小说初始设定文档。必须包含以下所有部分：

## 书名建议
（3 个备选书名）

## 一句话简介
（30字以内概括核心卖点）

## 世界观概述
（200-300字描述故事世界的核心设定）

## 主角设定
（姓名/身份/性格/目标/困境，各50-100字）

## 核心冲突
（100-200字描述主要矛盾和对抗力量）

## 力量/社会体系
（如有修炼、权谋、科技等体系，描述其架构）

## 故事线大纲
（开篇/发展/高潮/结局，各100字）

## 风格定位
（类型/基调/节奏/建议字数）

请用清晰的 Markdown 格式输出，每个部分用 ## 标题分隔。"""


# ================================================================
# Dialog
# ================================================================
class ConversationCreationDialog(QDialog):
    """自由对话式创建项目 — 流式输出版.

    Usage:
        dlg = ConversationCreationDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            project_id = dlg.created_project_id
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("💬 对话创建项目 — 和写作助手聊聊你的故事")
        self.setModal(True)
        self.resize(780, 680)

        # 状态
        self._conv_messages: list[dict] = []
        self._worker: Optional[_StreamChatWorker] = None
        self._created_pid: Optional[str] = None
        self._has_llm: bool = self._check_llm()
        self._mock_round: int = 0
        self._settings_text: str = ""

        # 流式 UI 状态
        self._chat_messages: list[tuple[str, str]] = []  # (sender, content) 已确认的消息
        self._streaming_content: str = ""   # 当前轮正在流式的正文 (未进 _chat_messages)
        self._accumulated_thinking: str = ""
        self._thinking_visible: bool = False  # 思考面板是否展开

        self._build_ui()
        self._init_conversation()

    # ------------------------------------------------------------------
    # LLM 探测
    # ------------------------------------------------------------------
    @staticmethod
    def _check_llm() -> bool:
        """检查是否有可用的真实 LLM 模型（每次都从 DB 刷新，确保拿到最新 API Key）."""
        try:
            from app.ai.registry import get_registry
            reg = get_registry()
            reg.reload()                              # 刷新 DB 里用户新配的 Key
            primary = reg.get_primary()
            if primary is None:
                return False
            # 必须配置了真正的 API Key（预设模版 key 为空）
            if not primary.api_key or not primary.api_key.strip():
                return False
            from app.services.router.real_client import create_real_client
            create_real_client()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(6)

        # — 标题行 —
        title_row = QHBoxLayout()
        title = QLabel("🤖 写作助手")
        title.setStyleSheet(
            f"font-size:15px; font-weight:700; color:{text_primary()};"
        )
        title_row.addWidget(title)
        title_row.addStretch()
        self._status_label = QLabel("正在连接 AI...")
        self._status_label.setStyleSheet(
            f"color:{text_muted()}; font-size:11px;"
        )
        title_row.addWidget(self._status_label)
        outer.addLayout(title_row)

        # — Mock 提示 —
        self._mock_banner = QLabel(
            "⚠️ 未配置 AI 模型 — 将使用模板对话（非 AI 生成）\n"
            "   请到 设置 → AI 模型 中配置模型以获得真实 AI 对话体验"
        )
        self._mock_banner.setWordWrap(True)
        self._mock_banner.setStyleSheet(
            "background: rgba(245,158,11,0.12); color:#f59e0b; "
            "padding:6px 10px; border-radius:4px; font-size:11px; "
            "border:1px solid rgba(245,158,11,0.25);"
        )
        self._mock_banner.setVisible(not self._has_llm)
        outer.addWidget(self._mock_banner)

        # — 主体: 聊天 + 设定预览 (用 Splitter) —
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 上半: 聊天区域 (思考面板 + 聊天视图 + 输入行)
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(4)

        # —— 思考面板 (可折叠) ——
        self._thinking_container = QWidget()
        self._thinking_container.setVisible(False)
        think_layout = QVBoxLayout(self._thinking_container)
        think_layout.setContentsMargins(0, 0, 0, 2)
        think_layout.setSpacing(2)

        # 思考标题行 (可点击折叠)
        think_header = QHBoxLayout()
        think_header.setSpacing(4)
        self._thinking_toggle = QLabel("💭 AI 思考过程 ▾")
        self._thinking_toggle.setStyleSheet(
            f"color:{text_muted()}; font-size:11px; font-style:italic; "
            "padding:2px 0; cursor:pointer;"
        )
        self._thinking_toggle.mousePressEvent = self._toggle_thinking
        think_header.addWidget(self._thinking_toggle)
        think_header.addStretch()
        think_layout.addLayout(think_header)

        border_c = border_color()
        # 思考内容
        self._thinking_view = QTextEdit()
        self._thinking_view.setReadOnly(True)
        self._thinking_view.setMaximumHeight(160)
        self._thinking_view.setStyleSheet(
            f"QTextEdit {{ border:1px solid {border_color()}; border-radius:4px; "
            f"background: rgba(108,122,224,0.06); padding:6px 8px; "
            f"font-size:11px; color:{text_muted()}; font-style:italic; }}"
        )
        think_layout.addWidget(self._thinking_view)
        chat_layout.addWidget(self._thinking_container)

        # —— 聊天视图 ——
        surface_c = deep_bg()
        self._chat_view = QTextBrowser()
        self._chat_view.setOpenExternalLinks(False)
        self._chat_view.setStyleSheet(
            f"QTextBrowser {{ border:1px solid {border_c}; border-radius:6px; "
            f"background:{surface_c}; padding:8px; font-size:13px; }}"
        )
        chat_layout.addWidget(self._chat_view)

        # —— 输入行 ——
        input_row = QHBoxLayout()
        ibg = input_bg()
        self._input_edit = QPlainTextEdit()
        self._input_edit.setPlaceholderText("输入你想说的... (Ctrl+Enter 发送)")
        self._input_edit.setMaximumHeight(72)
        self._input_edit.setStyleSheet(
            f"QPlainTextEdit {{ border:1px solid {border_c}; border-radius:4px; "
            f"padding:4px 8px; font-size:13px; "
            f"background:{ibg}; color:{text_primary()}; }}"
        )
        input_row.addWidget(self._input_edit)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        self._btn_send = QPushButton("发 送")
        self._btn_send.setObjectName("btnPrimary")
        self._btn_send.setStyleSheet(
            "QPushButton#btnPrimary { padding:6px 16px; border-radius:4px; "
            "font-weight:600; min-width:72px; }"
        )
        self._btn_send.clicked.connect(self._send_message)
        btn_col.addWidget(self._btn_send)

        self._btn_gen_settings = QPushButton("生成设定")
        self._btn_gen_settings.setToolTip("结束对话, 让 AI 根据聊天记录生成完整小说设定")
        self._btn_gen_settings.setStyleSheet(
            "QPushButton { padding:6px 12px; border-radius:4px; font-size:12px; }"
        )
        self._btn_gen_settings.clicked.connect(self._generate_settings)
        btn_col.addWidget(self._btn_gen_settings)
        input_row.addLayout(btn_col)
        chat_layout.addLayout(input_row)

        splitter.addWidget(chat_widget)

        # 下半: 设定预览 (默认隐藏)
        self._settings_widget = QWidget()
        settings_layout = QVBoxLayout(self._settings_widget)
        settings_layout.setContentsMargins(0, 4, 0, 0)
        settings_layout.setSpacing(4)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"QFrame {{ color:{border_c}; }}")
        settings_layout.addWidget(sep)

        settings_layout.addWidget(QLabel(
            f"📝 AI 生成的小说设定 (可编辑):"
        ))
        self._settings_edit = QPlainTextEdit()
        self._settings_edit.setMinimumHeight(140)
        self._settings_edit.setStyleSheet(
            f"QPlainTextEdit {{ border:1px solid {text_accent()}; border-radius:4px; "
            f"padding:6px; font-size:12px; "
            f"background:{surface_c}; color:{text_primary()}; }}"
        )
        settings_layout.addWidget(self._settings_edit)

        self._btn_create = QPushButton("🚀 创建项目")
        self._btn_create.setObjectName("btnPrimary")
        self._btn_create.setStyleSheet(
            "QPushButton#btnPrimary { padding:8px 24px; border-radius:4px; "
            "font-weight:700; font-size:14px; }"
        )
        self._btn_create.clicked.connect(self._on_create_project)

        btn_row2 = QHBoxLayout()
        btn_row2.addStretch()
        btn_row2.addWidget(self._btn_create)
        btn_row2.addStretch()
        settings_layout.addLayout(btn_row2)

        self._settings_widget.setVisible(False)
        splitter.addWidget(self._settings_widget)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter)

        # — 底部按钮 —
        bottom_row = QHBoxLayout()
        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.clicked.connect(self.reject)
        bottom_row.addWidget(self._btn_cancel)
        bottom_row.addStretch()
        outer.addLayout(bottom_row)

        # 回车发送
        self._input_edit.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        """Ctrl+Enter 发送消息."""
        from PySide6.QtCore import QEvent
        if obj is self._input_edit and event.type() == QEvent.Type.KeyPress:
            from PySide6.QtGui import QKeyEvent
            ke = event
            if ke.key() == Qt.Key.Key_Return and ke.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._send_message()
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # 思考面板折叠
    # ------------------------------------------------------------------
    def _toggle_thinking(self, _event=None) -> None:
        """点击标题切换思考内容的显示."""
        visible = self._thinking_view.isVisible()
        self._thinking_view.setVisible(not visible)
        arrow = "▸" if visible else "▾"
        self._thinking_toggle.setText(f"💭 AI 思考过程 {arrow}")

    # ------------------------------------------------------------------
    # 对话初始化
    # ------------------------------------------------------------------
    def _init_conversation(self) -> None:
        """初始化对话: 设 system prompt → 让 LLM 先开口."""
        self._conv_messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT}
        ]
        self._set_ui_busy(True, "正在连接...")
        self._run_llm_stream(
            self._conv_messages,
            is_first=True,
        )

    # ------------------------------------------------------------------
    # 流式 LLM 调用
    # ------------------------------------------------------------------
    def _run_llm_stream(self, messages: list[dict], *,
                         is_first: bool = False,
                         is_settings: bool = False,
                         max_tokens: int = 2000) -> None:
        """启动流式 Worker."""
        if self._worker and self._worker.isRunning():
            return

        use_mock = not self._has_llm
        mock_fn = None
        if use_mock:
            if is_settings:
                mock_fn = self._mock_settings
            else:
                mock_fn = self._mock_chat_response

        self._worker = _StreamChatWorker(
            messages,
            max_tokens=max_tokens,
            use_mock=use_mock,
            mock_fn=mock_fn,
        )
        # 连接信号（一次性连接，worker 完成后自动断开）
        self._worker.thinking.connect(self._on_thinking)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.done.connect(
            lambda content, thinking, first=is_first, settings=is_settings:
                self._on_done(content, thinking, is_first=first, is_settings=settings)
        )
        self._worker.fail.connect(
            lambda err, first=is_first, settings=is_settings:
                self._on_fail(err, is_first=first, is_settings=settings)
        )
        # 完成后清理
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self) -> None:
        """Worker 结束，断开信号."""
        if self._worker:
            try:
                self._worker.thinking.disconnect(self._on_thinking)
                self._worker.chunk.disconnect(self._on_chunk)
                self._worker.done.disconnect()
                self._worker.fail.disconnect()
                self._worker.finished.disconnect(self._on_worker_finished)
            except Exception:
                pass
            self._worker = None

    # ------------------------------------------------------------------
    # 流式信号处理
    # ------------------------------------------------------------------
    def _on_thinking(self, text: str) -> None:
        """收到思考 chunk."""
        self._accumulated_thinking += text
        # 显示思考面板
        if not self._thinking_container.isVisible():
            self._thinking_container.setVisible(True)
            self._thinking_view.setVisible(True)
            self._thinking_toggle.setText("💭 AI 思考过程 ▾")
        # 追加到思考面板
        self._thinking_view.setPlainText(self._accumulated_thinking)
        # 滚动到底部
        sb = self._thinking_view.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())
        # 更新状态栏
        self._status_label.setText("AI 正在思考...")
        self._status_label.setStyleSheet(f"color:{text_accent_violet()}; font-size:11px;")

    def _on_chunk(self, text: str) -> None:
        """收到正文 chunk — 累积到 _streaming_content，全量重渲染."""
        self._streaming_content += text
        if self._thinking_container.isVisible():
            self._thinking_view.setVisible(False)
            self._thinking_toggle.setText("💭 AI 思考过程 ▸")
        self._status_label.setText("AI 正在输入...")
        self._status_label.setStyleSheet(f"color:{text_accent()}; font-size:11px;")
        self._render_chat()

    def _on_done(self, content: str, thinking: str,
                 is_first: bool = False, is_settings: bool = False) -> None:
        """流式完成 — 把流式内容写入消息列表，重渲染."""
        if content:
            self._chat_messages.append(("写作助手", content))
        self._streaming_content = ""
        self._accumulated_thinking = ""
        if self._thinking_container.isVisible():
            self._thinking_view.setVisible(False)
            self._thinking_toggle.setText("💭 AI 思考过程 ▸")
        if not is_settings:
            self._conv_messages.append({"role": "assistant", "content": content})

        self._render_chat()

        if is_settings:
            self._settings_text = content
            self._settings_edit.setPlainText(content)
            self._settings_widget.setVisible(True)
            self._set_ui_busy(False, "设定已生成 — 可编辑后点「创建项目」")
            self._chat_messages.append(("系统", "📝 设定已生成 (见下方编辑区). 确认无误后点「创建项目」."))
            self._render_chat()
            self._settings_edit.setFocus()
        else:
            self._set_ui_busy(False)
            # 检测 AI 是否提示信息已充足
            if "信息已充足" in content or "生成设定" in content:
                self._highlight_gen_button()
                self._status_label.setText("✅ 信息已充足 — 可以点击「生成设定」了")
                self._status_label.setStyleSheet(
                    f"color:#34d399; font-size:11px; font-weight:600;"
                )
            else:
                muted = text_muted()
                self._status_label.setText("可以输入回复  ·  Ctrl+Enter 发送")
                self._status_label.setStyleSheet(f"color:{muted}; font-size:11px;")
            if is_first:
                self._input_edit.setPlaceholderText("描述你的故事想法... (Ctrl+Enter 发送)")
                self._input_edit.setFocus()

    def _highlight_gen_button(self) -> None:
        """高亮「生成设定」按钮，引导用户点击."""
        accent = text_accent()
        self._btn_gen_settings.setStyleSheet(
            f"QPushButton {{"
            f"  padding:8px 16px; border-radius:6px; font-size:13px; font-weight:600;"
            f"  background:{accent}; color:#ffffff;"
            f"  border:2px solid {accent};"
            f"}}"
            f"QPushButton:hover {{"
            f"  background:{accent}; opacity:0.85;"
            f"}}"
        )

    def _on_fail(self, error: str, is_first: bool = False,
                 is_settings: bool = False) -> None:
        """流式失败 — 降级到 mock."""
        log.warning("Stream worker failed, fallback to mock: %s", error)
        if is_settings:
            mock_text = self._mock_settings()
            self._on_done(mock_text, "", is_settings=True)
        else:
            mock_text = self._mock_chat_response()
            self._on_done(mock_text, "", is_first=is_first)

    # ------------------------------------------------------------------
    # 聊天渲染（全量重建 HTML → setHtml）
    # ------------------------------------------------------------------
    def _render_chat(self) -> None:
        """从 _chat_messages + _streaming_content 重建整个聊天区 HTML.

        策略简单粗暴但可靠：
          - 每条消息是一个 (sender, text) 元组
          - 流式内容追加在最后（带光标）
          - 用 setHtml() 一次性替换全部，不操作 QTextDocument block
        """
        parts = []
        for sender, text in self._chat_messages:
            parts.append(self._build_bubble_html(sender, text))
        # 如果有正在流式的内容，追加到末尾（带光标）
        if self._streaming_content:
            parts.append(self._build_bubble_html("写作助手", self._streaming_content,
                                                  is_streaming=True))
        html = "".join(parts)
        if not html:
            html = '<div style="color:' + text_muted() + '; font-size:12px; padding:12px;">'
            html += "等待 AI 回复...</div>"
        self._chat_view.setHtml(html)
        self._scroll_to_bottom()

    def _build_bubble_html(self, sender: str, text: str,
                           is_streaming: bool = False) -> str:
        """构建一条聊天气泡的 HTML."""
        if sender == "你":
            color = text_accent()
            bg = "rgba(108,122,224,0.20)" if is_dark() else "rgba(90,104,201,0.10)"
            align = "right"
        elif sender == "写作助手":
            color = text_secondary()
            bg = "#222326" if is_dark() else "#f3f4f6"
            align = "left"
        else:
            color = text_muted()
            bg = "transparent"
            align = "center"

        safe_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        cursor = '<span class="stream-cursor">|</span>' if is_streaming else ""
        html = (
            f'<div style="text-align:{align}; margin:6px 0;">'
            f'<span style="font-weight:700; color:{color};">{sender}：</span>'
            f'<span style="background:{bg}; padding:6px 10px; border-radius:8px; '
            f'display:inline-block; max-width:85%; text-align:left; '
            f'font-size:13px; line-height:1.5; color:{text_primary()};">{safe_text}{cursor}</span>'
            f'</div>'
        )
        return html

    def _append_chat(self, sender: str, text: str) -> None:
        """在消息列表中追加一条并渲染."""
        self._chat_messages.append((sender, text))
        self._render_chat()

    def _scroll_to_bottom(self) -> None:
        """滚动聊天视图到底部."""
        sb = self._chat_view.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    # ------------------------------------------------------------------
    # 发送消息
    # ------------------------------------------------------------------
    def _send_message(self) -> None:
        user_text = self._input_edit.toPlainText().strip()
        if not user_text:
            return
        if self._worker and self._worker.isRunning():
            return

        # 加入消息列表并渲染
        self._chat_messages.append(("你", user_text))
        self._render_chat()
        self._conv_messages.append({"role": "user", "content": user_text})
        self._input_edit.clear()
        self._input_edit.setPlaceholderText("AI 正在思考...")
        self._set_ui_busy(True, "AI 正在思考...")

        self._run_llm_stream(self._conv_messages)

    def _set_ui_busy(self, busy: bool, status: str = "") -> None:
        """设置 UI 为忙碌/空闲状态."""
        muted = text_muted()
        if status:
            self._status_label.setText(status)
            if not busy:
                self._status_label.setStyleSheet(f"color:{muted}; font-size:11px;")
        self._btn_send.setEnabled(not busy)
        self._btn_gen_settings.setEnabled(not busy)
        self._input_edit.setReadOnly(busy)

    # ------------------------------------------------------------------
    # 生成设定
    # ------------------------------------------------------------------
    def _generate_settings(self) -> None:
        """用户点击「生成设定」: 把聊天记录发给 LLM, 生成结构化设定."""
        user_msgs = [m for m in self._conv_messages if m["role"] != "system"]
        if not user_msgs:
            Dialogs.warning("没有对话内容", "请先和写作助手聊聊你的故事再生成设定。")
            return

        self._set_ui_busy(True, "AI 正在生成设定...")
        gen_messages = [
            {"role": "system", "content": GENERATE_SETTINGS_PROMPT},
        ]
        for m in user_msgs:
            prefix = "作者" if m["role"] == "user" else "写作助手"
            gen_messages.append({"role": "user", "content": f"[{prefix}]: {m['content']}"})
        gen_messages.append({"role": "user", "content": "请根据以上对话，生成完整的小说设定。"})

        self._run_llm_stream(
            gen_messages,
            max_tokens=3000,
            is_settings=True,
        )

    # ------------------------------------------------------------------
    # 创建项目
    # ------------------------------------------------------------------
    def _on_create_project(self) -> None:
        setting = self._settings_edit.toPlainText().strip()
        if not setting:
            Dialogs.warning("没有设定", "请先生成或输入小说设定。", parent=self)
            return

        parsed = self._parse_setting(setting)
        from app.services import project_service, ServiceError
        try:
            p = project_service.create(
                name=parsed["project_name"],
                book_title=parsed["book_title"],
                author=None,
                genre=parsed["genre"],
                platform=None,
                word_target=parsed["word_target"],
                volumes=1, chapters_per_volume=100, words_per_chapter=2000,
                sub_genres=[],
                create_books=True,
            )
        except ServiceError as e:
            Dialogs.warning("创建失败", f"创建项目失败: {e}", parent=self)
            return
        self._created_pid = p["id"]
        self._sync_settings(setting)
        self.accept()

    # ------------------------------------------------------------------
    # 辅助: 解析 / 同步
    # ------------------------------------------------------------------
    def _parse_setting(self, setting: str) -> dict:
        from app.services.genre_presets import GENRE_PRESETS
        valid_genres = {name for (_id, name, _desc, _kw) in GENRE_PRESETS}

        m = re.search(r"《([^》]+)》", setting)
        book_title = m.group(1).strip() if m else "未命名小说"
        project_name = f"{book_title}-对话创建"

        genre = "未分类"
        for g in valid_genres:
            if g in setting:
                genre = g
                break

        word_target = 200_000
        m = re.search(r"(\d+)\s*[-~到至]\s*(\d+)\s*万\s*字", setting)
        if m:
            word_target = int((int(m.group(1)) + int(m.group(2))) / 2 * 10_000)
        else:
            m = re.search(r"(\d+)\s*万\s*字", setting)
            if m:
                word_target = int(m.group(1)) * 10_000

        return {
            "project_name": project_name[:64],
            "book_title": book_title[:128],
            "genre": genre,
            "word_target": word_target,
        }

    def _sync_settings(self, setting: str) -> None:
        from app.services.setting_service import set_setting
        from app.services.setting_io import _md_text_to_setting_data, _parse_md_sections

        pid = self._created_pid
        sections = _parse_md_sections(setting)
        _sync_map = {
            "worldbuilding":     {"世界观概述", "世界观", "力量", "社会体系", "世界设定"},
            "characters":        {"主角设定", "角色", "主角", "人物"},
            "style_fingerprint": {"风格定位", "风格", "文风"},
            "plot_outline":      {"书名建议", "一句话简介", "核心冲突", "故事线大纲", "大纲"},
        }
        collected: dict[str, list[str]] = {k: [] for k in _sync_map}

        for title, body in sections:
            if not body:
                continue
            for key, hints in _sync_map.items():
                if any(h in title for h in hints):
                    collected[key].append(f"## {title}\n\n{body}")
                    break

        for key, parts in collected.items():
            if not parts:
                continue
            merged = "\n\n".join(parts)
            try:
                data = _md_text_to_setting_data(merged, key)
                set_setting(pid, key, data)
            except Exception as e:
                log.warning("sync setting %s failed: %s", key, e)

        try:
            set_setting(pid, "plot_outline", setting)
        except Exception as e:
            log.warning("save plot_outline failed: %s", e)

    # ------------------------------------------------------------------
    # Mock 对话
    # ------------------------------------------------------------------
    def _mock_chat_response(self) -> str:
        """根据轮次返回模板回复."""
        self._mock_round += 1
        if self._mock_round == 1:
            return (
                "你好！我是你的小说创作助手。跟我说说你想写什么样的故事吧？\n\n"
                "比如：什么题材？发生在什么时代/世界？主角大概是什么样的人？"
            )
        elif self._mock_round == 2:
            return (
                "有意思！那咱们聊聊主角——他/她有什么特别之处？\n\n"
                "性格怎么样？有什么目标或者困境吗？"
            )
        elif self._mock_round == 3:
            return (
                "好的，主角形象慢慢清晰了。那这个世界呢？有什么特别的规则或力量体系吗？\n\n"
                "另外，故事的核心冲突是什么？谁或什么在阻碍主角？"
            )
        elif self._mock_round == 4:
            return (
                "明白了。风格方面呢？是热血爽文、轻松搞笑、还是偏严肃正剧？\n\n"
                "你打算在哪里发布？番茄、起点、还是其他地方？目标写多少字？"
            )
        else:
            return (
                "我觉得已经了解得差不多了！你讲的故事框架很清晰。\n\n"
                "✅ **信息已充足 — 你可以点击「生成设定」按钮了**，"
                "我会根据咱们的对话生成完整的小说设定文档。"
            )

    def _mock_settings(self) -> str:
        """生成 mock 设定."""
        user_msgs = [m["content"] for m in self._conv_messages if m["role"] == "user"]
        combined = " ".join(user_msgs)[:200] or "我的新小说"
        seed = combined.split("。")[0][:15] or "新世界"
        return (
            f"## 书名建议\n1. 《{seed}》\n2. 《纪元》\n3. 《破晓》\n\n"
            f"## 一句话简介\n一个关于{seed[:30]}的故事。\n\n"
            f"## 世界观概述\n这是一个架空世界，存在独特的社会结构和规则体系，主角在其中逐渐成长、发现真相。\n\n"
            f"## 主角设定\n姓名: 林逸\n身份: 普通人 / 隐藏潜力\n性格: 坚毅 / 聪明\n目标: 寻找真相 / 保护重要的人\n困境: 资源匮乏 / 强敌环伺\n\n"
            f"## 核心冲突\n主角发现世界的真相，与传统秩序产生根本冲突，必须在两难中做出选择。\n\n"
            f"## 力量/社会体系\n境界划分: 入门 / 精进 / 大师 / 宗师 / 传说\n\n"
            f"## 故事线大纲\n开篇: 主角平凡生活被打破\n发展: 遇到同伴, 逐步成长\n高潮: 与最终反派决战\n结局: 完成使命, 找到归属\n\n"
            f"## 风格定位\n类型: 玄幻/升级流\n基调: 热血/友情\n节奏: 中等偏快\n建议字数: 200-300万字\n"
        )

    # ------------------------------------------------------------------
    # 聊天 UI 工具（非流式单条消息）
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------
    @property
    def created_project_id(self) -> Optional[str]:
        return self._created_pid
