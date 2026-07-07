"""
Editor tab (Phase 3 M3) - 章节编辑 + 段落重写 + 评估面板.

三栏布局:
  左:  books + chapters 列表
  中:  正文编辑 (QPlainTextEdit) + 软提示卡 (v3.0 Layer 5)
  右:  评估面板 (Critic 6 维 + Hook 5 维 + 段落重写)

v3.0 集成 (edit-signals 沉淀 + 进化):
  - 30s 防抖 → textChanged → 落盘 manual_edit 信号 (Layer 1)
  - 章节保存 → 封存 + 触发 worker (Layer 2)
  - 编辑器顶栏 [📚 提示 (N)] 折叠卡 → 显示 top-3 BM25 候选 (Layer 5)
  - [采纳]/[✗ 不对] 按钮 → use_count++ / patch_count++
  - [📚 关] 按钮 → per-chapter 永久关
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from PySide6.QtCore import Qt, QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QListWidget,
    QListWidgetItem, QTreeWidget, QTreeWidgetItem, QLabel, QPushButton, QPlainTextEdit,
    QInputDialog, QGroupBox, QFormLayout, QProgressBar, QFrame, QSizePolicy,
)

from app.services import (
    book_service, chapter_service, app_setting_service, subtext as subtext_svc,
    character_tracker,
    ServiceError,
)
from app.services.writing.paragraph_rewriter import (
    LLMScopedRewriter, MockScopedRewriter, split_paragraphs, join_paragraphs,
)
from app.ui.tokens_hint import PriceBar, show_first_use_if_needed
from app.ui.widgets import Dialogs
from app.ui.widgets.export_dialog import ExportDialog
from app.ui.widgets.feature_gate_widgets import (  # M10-C
    FeatureGateBadge, assert_feature_or_dialog,
    get_current_tier_label, refresh_all_badges,
)

# v3.0 Edit Signals (L1-L5) - 静默导入, 关了也不报错
try:
    from app.workflow import edit_signals as _es
    _HAS_ES = True
except Exception:
    _es = None
    _HAS_ES = False

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# Worker: 段落重写 (QThread + Signal)
# --------------------------------------------------------------------- #

class ParagraphRewriteWorker(QObject):
    chunk = Signal(str)
    done = Signal(dict)
    error = Signal(str)
    finished = Signal()
    info = Signal(str)

    def __init__(self, chapter: dict, paragraph_index: int,
                 instruction: str = "") -> None:
        super().__init__()
        self.chapter = chapter
        self.paragraph_index = paragraph_index
        self.instruction = instruction
        # 跟 generate_tab 一样: 按 active provider 构造, 无则 mock
        p = app_setting_service.get_active()
        self._info_msg: Optional[str] = None
        if p:
            try:
                from app.core.llm import LLMClient, ProviderConfig, ProviderType
                cfg = ProviderConfig(
                    name=p["name"],
                    provider_type=ProviderType(p.get("provider_type", "openai_compat")),
                    api_base=p.get("api_base", ""),
                    api_key=p.get("api_key", ""),
                    model=p.get("model", ""),
                    max_tokens=int(p.get("max_tokens", 4096)),
                    temperature=float(p.get("temperature", 0.7)),
                    timeout=float(p.get("timeout", 120.0)),
                    priority=int(p.get("priority", 0)),
                )
                client = LLMClient()
                client.configure([cfg])
                self.rewriter = LLMScopedRewriter(client)
            except Exception as e:
                log.warning(f"[PRW] bad config, fallback to mock: {e}")
                self.rewriter = MockScopedRewriter()
                self._info_msg = f"provider 配置异常: {e}. 已用 mock."
        else:
            self.rewriter = MockScopedRewriter()
            self._info_msg = "未配 active provider, 已用 mock 重写."

    def run(self) -> None:
        try:
            if self._info_msg:
                self.info.emit(self._info_msg)
            result = self.rewriter.run(
                chapter=self.chapter,
                paragraph_index=self.paragraph_index,
                instruction=self.instruction,
            )
            self.done.emit(result)
        except Exception as e:
            log.exception("[PRW] failed")
            self.error.emit(str(e))
        finally:
            self.finished.emit()


# --------------------------------------------------------------------- #
# 评估面板
# --------------------------------------------------------------------- #

class EvaluationPanel(QWidget):
    """右侧面板: 显示当前章节的 critic + hook 数据, 段落重写入口."""

    def __init__(self, host: Optional[object] = None) -> None:
        # host: 持有 editor 引用的外部对象 (通常是 EditorTab 实例).
        # 显式保留 host 引用, 不依赖 QWidget 父子链 (因为 EvaluationPanel
        # 嵌在 QSplitter 中, QWidget parent 是 splitter 不是 EditorTab).
        super().__init__()
        self.host = host
        self.current_chapter: Optional[dict] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[ParagraphRewriteWorker] = None
        self._build_ui()

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        # ---- Critic ----
        critic_box = QGroupBox("📖 Critic 文学分")
        cb = QVBoxLayout(critic_box)
        self.critic_score = QLabel("—")
        from app.ui.theme import text_score_blue
        self.critic_score.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {text_score_blue()};")
        cb.addWidget(self.critic_score)
        self.critic_axes = QLabel("(无数据)")
        from app.ui.theme import text_muted
        self.critic_axes.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        self.critic_axes.setWordWrap(True)
        cb.addWidget(self.critic_axes)
        self.critic_summary = QLabel("")
        self.critic_summary.setWordWrap(True)
        from app.ui.theme import text_secondary
        self.critic_summary.setStyleSheet(f"color: {text_secondary()}; font-size: 12px;")
        cb.addWidget(self.critic_summary)
        v.addWidget(critic_box)

        # ---- Hook ----
        hook_box = QGroupBox("🪝 Hook 追读分")
        hb = QVBoxLayout(hook_box)
        self.hook_score = QLabel("—")
        from app.ui.theme import text_score_purple
        self.hook_score.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {text_score_purple()};")
        hb.addWidget(self.hook_score)
        self.hook_axes = QLabel("(无数据)")
        from app.ui.theme import text_muted
        self.hook_axes.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        self.hook_axes.setWordWrap(True)
        hb.addWidget(self.hook_axes)
        self.hook_summary = QLabel("")
        self.hook_summary.setWordWrap(True)
        from app.ui.theme import text_secondary
        self.hook_summary.setStyleSheet(f"color: {text_secondary()}; font-size: 12px;")
        hb.addWidget(self.hook_summary)
        v.addWidget(hook_box)

        # ---- P2: 反 AI 味 Issues ----
        self.issues_box = QGroupBox("⚠️ 反 AI 味问题")
        ib = QVBoxLayout(self.issues_box)
        self.issues_list = QLabel("(生成章节后自动检测)")
        from app.ui.theme import text_muted
        self.issues_list.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        self.issues_list.setWordWrap(True)
        ib.addWidget(self.issues_list)
        v.addWidget(self.issues_box)

        # ---- 段落重写 ----
        rw_box = QGroupBox("✏️ 段落重写")
        rb = QFormLayout(rw_box)
        self.spn_paragraph = QPushButton("在光标段重写")
        self.spn_paragraph.clicked.connect(self._on_rewrite_cursor_paragraph)
        self.spn_paragraph.setEnabled(False)
        rb.addRow(self.spn_paragraph)
        self.spn_specific = QPushButton("按序号重写…")
        self.spn_specific.clicked.connect(self._on_rewrite_specific_paragraph)
        self.spn_specific.setEnabled(False)
        rb.addRow(self.spn_specific)
        self.pr_status = QLabel("")
        from app.ui.theme import text_muted
        self.pr_status.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        self.pr_status.setWordWrap(True)
        rb.addRow(self.pr_status)
        v.addWidget(rw_box)

        v.addStretch(1)

    # ---- public ----

    def set_chapter(self, chapter: Optional[dict]) -> None:
        self.current_chapter = chapter
        self._load_evaluation(chapter)
        has_text = bool(chapter and (chapter.get("draft") or chapter.get("final")))
        self.spn_paragraph.setEnabled(has_text)
        self.spn_specific.setEnabled(has_text)

    def set_paragraph_rewrite_status(self, msg: str) -> None:
        self.pr_status.setText(msg)

    # ---- internals ----

    def _load_evaluation(self, chapter: Optional[dict]) -> None:
        if not chapter:
            self.critic_score.setText("—")
            self.critic_axes.setText("(无数据)")
            self.critic_summary.setText("")
            self.hook_score.setText("—")
            self.hook_axes.setText("(无数据)")
            self.hook_summary.setText("")
            self.issues_list.setText("(生成章节后自动检测)")
            from app.ui.theme import text_muted
            self.issues_list.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
            return
        # critic
        crit_raw = chapter.get("critique")
        critic: dict = {}
        hook: dict = {}
        if crit_raw:
            try:
                d = json.loads(crit_raw)
                if isinstance(d, dict):
                    critic = d.get("critic", {}) or {}
                    hook = d.get("hook", {}) or {}
            except (json.JSONDecodeError, TypeError):
                pass
        if critic:
            self.critic_score.setText(str(critic.get("score", "—")))
            axes = critic.get("axes", {}) or {}
            ax_lines = [f"· {k}: {v}" for k, v in axes.items()]
            self.critic_axes.setText("\n".join(ax_lines) if ax_lines else "(无 axes)")
            self.critic_summary.setText(str(critic.get("summary", "")))
        else:
            self.critic_score.setText("—")
            self.critic_axes.setText("(未生成)")
            self.critic_summary.setText("(生成章节后这里会显示 Critic 评语)")
        if hook:
            self.hook_score.setText(str(hook.get("score", "—")))
            axes = hook.get("axes", {}) or {}
            ax_lines = [f"· {k}: {v}" for k, v in axes.items()]
            self.hook_axes.setText("\n".join(ax_lines) if ax_lines else "(无 axes)")
            self.hook_summary.setText(str(hook.get("summary", "")))
        else:
            self.hook_score.setText("—")
            self.hook_axes.setText("(未生成)")
            self.hook_summary.setText("(生成章节后这里会显示 Hook 评语)")
        # P2: 反 AI 味 issues 列表
        issues = critic.get("issues", []) if critic else []
        if issues:
            sev_emoji = {"block": "🔴", "warn": "🟡", "info": "🔵"}
            lines = []
            for iss in issues[:10]:  # 最多显示 10 条
                emoji = sev_emoji.get(iss.get("severity", "info"), "🔵")
                label = iss.get("label", iss.get("kind", ""))
                loc = iss.get("location", "")
                snippet = iss.get("snippet", "")
                # 截断 snippet 避免撑爆 UI
                if snippet and len(snippet) > 40:
                    snippet = snippet[:40] + "…"
                line = f"{emoji} {label}" + (f" @ {loc}" if loc else "")
                if snippet:
                    line += f"\n   {snippet}"
                lines.append(line)
            self.issues_list.setText("\n".join(lines))
            from app.ui.theme import text_secondary
            self.issues_list.setStyleSheet(f"color: {text_secondary()}; font-size: 11px;")
        else:
            self.issues_list.setText("(无问题 — AI 味检测通过)")
            from app.ui.theme import text_success
            self.issues_list.setStyleSheet(f"color: {text_success()}; font-size: 11px;")

    # ---- paragraph rewrite ----

    def _on_rewrite_cursor_paragraph(self) -> None:
        editor = self.parent_editor()
        if editor is None:
            return
        cursor = editor.textCursor()
        block_text = cursor.block().text()
        if not block_text.strip():
            Dialogs.info("段落重写", "当前光标不在有效段落", parent=self)
            return
        # 找该段在全文章节中的序号
        full_text = editor.toPlainText()
        paragraphs = split_paragraphs(full_text)
        target_idx = -1
        for i, p in enumerate(paragraphs):
            if p.strip() == block_text.strip():
                target_idx = i
                break
        if target_idx < 0:
            Dialogs.info("段落重写", "无法定位当前段", parent=self)
            return
        instruction, _ = QInputDialog.getText(
            self, "段落重写", "可选 - 重写要求 (留空 = 通用):",
        )
        self._start_rewrite(target_idx, instruction or "")

    def _on_rewrite_specific_paragraph(self) -> None:
        editor = self.parent_editor()
        if editor is None:
            return
        full_text = editor.toPlainText()
        paragraphs = split_paragraphs(full_text)
        if not paragraphs:
            Dialogs.info("段落重写", "当前章节无正文", parent=self)
            return
        idx_str, ok = QInputDialog.getText(
            self, "段落重写",
            f"段序号 (0..{len(paragraphs)-1}):",
        )
        if not ok:
            return
        try:
            idx = int(idx_str.strip())
        except ValueError:
            Dialogs.warning("段落重写", "请输入有效整数", parent=self)
            return
        if idx < 0 or idx >= len(paragraphs):
            Dialogs.warning("段落重写", f"超出范围 (0..{len(paragraphs)-1})", parent=self)
            return
        instruction, _ = QInputDialog.getText(
            self, "段落重写", "可选 - 重写要求 (留空 = 通用):",
        )
        self._start_rewrite(idx, instruction or "")

    def _start_rewrite(self, paragraph_index: int, instruction: str) -> None:
        if not self.current_chapter:
            return
        if self._thread is not None:
            Dialogs.info("段落重写", "已有重写任务在跑", parent=self)
            return
        # ---- 首次使用提示 (一次性 dialog) ----
        show_first_use_if_needed("editor_rewrite", self)
        self.pr_status.setText("⏳ 重写中…")
        self.spn_paragraph.setEnabled(False)
        self.spn_specific.setEnabled(False)
        self._thread = QThread()
        self._worker = ParagraphRewriteWorker(self.current_chapter, paragraph_index, instruction)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.info.connect(self._on_rewrite_info)
        self._worker.done.connect(self._on_rewrite_done)
        self._worker.error.connect(self._on_rewrite_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._on_rewrite_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.start()
        self._pending_para_idx = paragraph_index
        self._pending_instr = instruction

    def _on_rewrite_info(self, msg: str) -> None:
        self.pr_status.setText(f"ℹ️ {msg}")

    def _on_rewrite_done(self, result: dict) -> None:
        new_para = result.get("new_paragraph", "")
        summary = result.get("summary", "")
        diff_hint = result.get("diff_hint", "")
        success = result.get("success", False)
        if not success:
            self.pr_status.setText(f"❌ {summary} ({diff_hint})")
            return
        # 拿到当前编辑器文本, 替换段
        editor = self.parent_editor()
        if editor is None:
            return
        full = editor.toPlainText()
        paragraphs = split_paragraphs(full)
        idx = self._pending_para_idx
        if idx < 0 or idx >= len(paragraphs):
            self.pr_status.setText(f"⚠️ 段序号越界, 未替换 ({summary})")
            return
        old = paragraphs[idx]
        paragraphs[idx] = new_para
        new_text = join_paragraphs(paragraphs)
        editor.setPlainText(new_text)
        # 落库 (chapter_service.update draft) + change_log
        if self.current_chapter:
            try:
                # 写新 draft
                chapter_service.update(
                    self.current_chapter["id"],
                    draft=new_text,
                    word_count=len(new_text),
                )
                # 建一个 paragraph_rewrite 类型 draft 快照
                new_draft = chapter_service.create_draft(
                    self.current_chapter["id"], new_text, "paragraph_rewrite",
                )
                chapter_service.add_change_log(
                    self.current_chapter["id"],
                    "paragraph_rewrite", "paragraph",
                    new_draft["id"],
                    note=f"段{idx}: {summary} ({diff_hint})",
                )
                chapter_service.set_current_draft(
                    self.current_chapter["id"], new_draft["id"],
                )
            except ServiceError as e:
                log.warning(f"[PRW] persist failed: {e}")
        # 高亮新段 (粗略: 把光标移过去)
        cursor = editor.textCursor()
        # 找第 idx 段位置
        pos = 0
        for i in range(idx):
            pos = full.find("\n\n", pos)
            if pos < 0:
                break
            pos += 2
        cursor.setPosition(min(pos, len(new_text)))
        editor.setTextCursor(cursor)
        self.pr_status.setText(
            f"✅ 已重写段{idx} | 原 {len(old)} 字 -> 新 {len(new_para)} 字 | {summary} | {diff_hint}"
        )
        # 通知父 EditorTab 刷新标题等
        host = getattr(self, "host", None)
        if host is not None and hasattr(host, "_after_paragraph_rewrite"):
            host._after_paragraph_rewrite(self.current_chapter["id"], new_text)
        # 自动同步 character_tracker
        try:
            if host and self.current_chapter:
                host._sync_character_tracker(str(self.current_chapter["id"]), new_para)
        except Exception:
            pass

    def _on_rewrite_error(self, msg: str) -> None:
        self.pr_status.setText(f"❌ {msg}")

    def _on_rewrite_finished(self) -> None:
        if self._thread is not None:
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
        has_text = bool(self.current_chapter and
                        (self.current_chapter.get("draft") or self.current_chapter.get("final")))
        self.spn_paragraph.setEnabled(has_text)
        self.spn_specific.setEnabled(has_text)

    def parent_editor(self) -> Optional[QPlainTextEdit]:
        host = getattr(self, "host", None)
        if host is not None and hasattr(host, "editor"):
            return host.editor
        # 回退: 沿 QWidget 父链找有 'editor' 属性的祖先
        p = self.parentWidget()
        while p is not None:
            if hasattr(p, "editor"):
                return getattr(p, "editor")
            p = p.parentWidget()
        return None


# --------------------------------------------------------------------- #
# V4.0-P2-新: 卷结构小卡 — 显示全书的卷/章/字 进度概览
# --------------------------------------------------------------------- #

class _VolumeStructureCard(QFrame):
    """紧凑型小卡, 放在章节管理左侧顶部.

    显示:
      - 全书:  N 卷 × M 章/卷 (已写 X/Y 章)
      - 全书:  已写 W 字 / 目标 T 字 (Z% 完成)
    视觉: 一个总进度条 (1 行) + 简短文字, 不抢眼但随时可看.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("volumeStructureCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMaximumHeight(80)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(4)

        self.lbl_summary = QLabel("📚 全书结构: —")
        self.lbl_summary.setObjectName("volumeStructureSummary")
        self.lbl_summary.setStyleSheet("font-size: 11px; font-weight: 600;")
        v.addWidget(self.lbl_summary)

        self.progress = QProgressBar()
        self.progress.setObjectName("volumeStructureProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setMaximumHeight(14)
        v.addWidget(self.progress)

        self.lbl_words = QLabel("✍️ 0 / 0 字 (0%)")
        self.lbl_words.setObjectName("volumeStructureWords")
        from app.ui.theme import text_muted
        self.lbl_words.setStyleSheet(f"font-size: 10px; color: {text_muted()};")
        v.addWidget(self.lbl_words)

    def set_data(self, *, volumes: int, chapters_per_volume: int,
                 chapters_written: int, words_written: int, words_target: int) -> None:
        """V4.0-P2-新: 卷结构数据汇总.

        chapters_written: 已写章节数 (任意 status, 包括 draft)
        words_written:    已写总字数
        words_target:     目标总字数 (来自 project.word_target)
        """
        total_chap_planned = volumes * chapters_per_volume
        self.lbl_summary.setText(
            f"📚 全书结构: {volumes} 卷 × {chapters_per_volume} 章/卷"
            f"  (已写 {chapters_written} / {total_chap_planned} 章)"
        )
        pct = (words_written / words_target * 100) if words_target > 0 else 0
        pct_clamped = max(0, min(100, int(pct)))
        self.progress.setValue(pct_clamped)
        self.lbl_words.setText(
            f"✍️ {words_written:,} / {words_target:,} 字 ({pct:.1f}%)"
        )


# --------------------------------------------------------------------- #
# EditorTab (3 栏)
# --------------------------------------------------------------------- #

class EditorTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.current_project: Optional[dict] = None
        self.current_book_id: Optional[str] = None
        self.current_chapter_id: Optional[str] = None
        # v3.0 Edit Signals 状态
        self._last_saved_text: str = ""
        self._edit_signal_timer = QTimer(self)
        self._edit_signal_timer.setSingleShot(True)
        debounce_ms = _es.get_signal_debounce_ms() if _HAS_ES else 30_000
        self._edit_signal_timer.setInterval(int(debounce_ms))
        self._edit_signal_timer.timeout.connect(self._flush_manual_edit_signal)
        # 软提示卡 状态
        self._hint_card_expanded = False
        self._hint_skills: list[dict] = []
        self._hint_disabled: bool = False  # per-chapter 关
        self._build_ui()

    def _build_ui(self) -> None:
        self.title = QLabel("章节编辑")
        self.title.setObjectName("projectTitle")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(self.title)

        # ---- Tokens 提示价格条 (永远在 tab 顶部显眼位置) ----
        self.price_bar = PriceBar("editor_rewrite")
        outer.addWidget(self.price_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # ---- 左: 树状章节目录 ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        # V4.0-P2-新: 卷结构小卡 (放在树上方, 一眼看到 全书 N 卷 / M 章 完成度)
        self.structure_card = _VolumeStructureCard()
        left_layout.addWidget(self.structure_card)
        left_layout.addWidget(QLabel("📂 章节目录"))
        self.chapter_tree = QTreeWidget()
        self.chapter_tree.setHeaderHidden(True)
        self.chapter_tree.setRootIsDecorated(True)
        self.chapter_tree.setAnimated(True)
        self.chapter_tree.setIndentation(18)
        self.chapter_tree.itemSelectionChanged.connect(self._on_tree_selection)
        left_layout.addWidget(self.chapter_tree, 1)
        btn_new_book = QPushButton("+ 新建卷册")
        btn_new_book.clicked.connect(self._on_new_book)
        left_layout.addWidget(btn_new_book)
        btn_new_chapter = QPushButton("+ 新建章节")
        btn_new_chapter.clicked.connect(self._on_new_chapter)
        left_layout.addWidget(btn_new_chapter)
        splitter.addWidget(left)
        splitter.setSizes([220, 500, 220])  # 左窄(目录) / 中(编辑器) / 右(面板)

        # ---- 中: 编辑器 ----
        mid = QWidget()
        mid_layout = QVBoxLayout(mid)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        # v3.0 软提示卡 (Layer 5) - 编辑器顶栏
        self.hint_card = self._build_hint_card()
        mid_layout.addWidget(self.hint_card)
        self.chapter_title_label = QLabel("(未选章节)")
        self.chapter_title_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        mid_layout.addWidget(self.chapter_title_label)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("选择左侧章节以加载正文…")
        mid_layout.addWidget(self.editor, 1)
        btn_row = QHBoxLayout()
        # V4.0-P4-新: 「开始写作」流程按钮 — 核心入口, 一键打开 7 步 AI 生成对话框
        self.btn_start_writing = QPushButton("✨ 开始写作")
        self.btn_start_writing.setObjectName("btnStartWriting")
        self.btn_start_writing.setToolTip(
            "AI 自动 7 步生成流程 (大纲注入 → 写作风格 → 选段 → 段落重写 → 评估 → 修补 → 收口), "
            "完成后可一键写入章节"
        )
        self.btn_start_writing.clicked.connect(self._on_start_writing)
        self.btn_start_writing.setEnabled(False)
        btn_row.addWidget(self.btn_start_writing)
        self.btn_save = QPushButton("保存草稿")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setEnabled(False)
        btn_row.addWidget(self.btn_save)
        # M8: TTS 朗读按钮
        self.btn_tts = QPushButton("🔊 朗读章节")
        self.btn_tts.setToolTip("合成当前章节的语音 (TTS)")
        self.btn_tts.clicked.connect(self._on_tts_synth)
        self.btn_tts.setEnabled(False)
        btn_row.addWidget(self.btn_tts)
        self.btn_tts_open = QPushButton("📁 打开音频")
        self.btn_tts_open.setToolTip("用系统播放器打开已合成的音频文件")
        self.btn_tts_open.clicked.connect(self._on_tts_open)
        self.btn_tts_open.setEnabled(False)
        btn_row.addWidget(self.btn_tts_open)
        # M10-A: 一键出版 (M9-B 后端)
        self.btn_export = QPushButton("📦 导出全书")
        self.btn_export.setToolTip("导出当前卷 (EPUB/DOCX/MD/TXT) + 封面, 0 第三方依赖")
        self.btn_export.clicked.connect(self._on_export)
        self.btn_export.setEnabled(False)
        btn_row.addWidget(self.btn_export)
        # M11-D: 4 步出版向导 (publish_wizard)
        self.btn_publish_wizard = QPushButton("🧙 出版向导")
        self.btn_publish_wizard.setToolTip("M11-D: 4 步引导 (选卷 → 选格式 → 封面/元信息 → 输出进度)")
        self.btn_publish_wizard.clicked.connect(self._on_publish_wizard)
        self.btn_publish_wizard.setEnabled(False)
        btn_row.addWidget(self.btn_publish_wizard)
        # M10-C: PRO 角标 (publish.oneclick 是 PRO 专属)
        self.badge_export = FeatureGateBadge("publish.oneclick", parent=self)
        btn_row.addWidget(self.badge_export)
        # M10-C: 当前 tier 指示
        self.lbl_tier = QLabel(get_current_tier_label())
        self.lbl_tier.setStyleSheet(
            "color: #7b1fa2; font-size: 10px; font-weight: bold; "
            "padding: 2px 6px; border: 1px solid #7b1fa2; border-radius: 4px;"
        )
        self.lbl_tier.setToolTip("当前 license 等级 (设置 → 🔐 License 可升级)")
        btn_row.addWidget(self.lbl_tier)
        self.lbl_tts_status = QLabel("")
        from app.ui.theme import text_info
        self.lbl_tts_status.setStyleSheet(f"color: {text_info()}; font-size: 11px;")
        btn_row.addWidget(self.lbl_tts_status)
        self.lbl_para_count = QLabel("")
        from app.ui.theme import text_muted
        self.lbl_para_count.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        btn_row.addStretch(1)
        btn_row.addWidget(self.lbl_para_count)
        mid_layout.addLayout(btn_row)
        splitter.addWidget(mid)

        # ---- 右: 评估面板 ----
        # host=self: 让 panel 显式拿到 EditorTab 引用, 避免 QSplitter 切断
        self.eval_panel = EvaluationPanel(host=self)
        splitter.addWidget(self.eval_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([220, 600, 360])

        # editor 文字变化时刷新段数
        self.editor.textChanged.connect(self._on_text_changed)

    # ---- public ----

    def set_project(self, project: Optional[dict]) -> None:
        self.current_project = project
        self.current_book_id = None
        self.current_chapter_id = None
        self.editor.clear()
        self.chapter_title_label.setText("(未选章节)")
        self.btn_save.setEnabled(False)
        self.eval_panel.set_chapter(None)
        # v3.0: 清软提示
        self._last_saved_text = ""
        self._hint_skills = []
        self._hint_disabled = False
        self.hint_card.setVisible(False)
        if project is None:
            self.title.setText("章节编辑（未选择项目）")
            self.chapter_tree.clear()
            # M11-D: 没项目时禁用
            if hasattr(self, "btn_publish_wizard"):
                self.btn_publish_wizard.setEnabled(False)
            return
        self.title.setText(f"章节编辑 — {project.get('name', '')}")
        # M11-D: 有项目即启用 (后续选不选卷都行, 出版向导 Step 1 有"全部"选项)
        if hasattr(self, "btn_publish_wizard"):
            self.btn_publish_wizard.setEnabled(True)
        self._reload_tree()
        # V4.0-P2-新: 刷新卷结构小卡
        self._reload_structure_card()

    def _after_paragraph_rewrite(self, chapter_id: str, new_text: str) -> None:
        """段落重写后回调: 同步 self.current_chapter 的 draft, 不重载编辑器."""
        if self.current_chapter_id == chapter_id:
            self.current_chapter["draft"] = new_text
            self.current_chapter["word_count"] = len(new_text)
            # v3.0: 同步 _last_saved_text (避免触发 30s 防抖当 diff)
            self._last_saved_text = new_text
            self._on_text_changed()

    # ---- internals ----

    def _reload_tree(self) -> None:
        """从数据源重新构建树状章节目录 (卷册→章节)."""
        if not self.current_project:
            return
        # 记住展开状态
        expanded_ids: set[str] = set()
        for i in range(self.chapter_tree.topLevelItemCount()):
            vol_item = self.chapter_tree.topLevelItem(i)
            if vol_item.isExpanded():
                d = vol_item.data(0, Qt.ItemDataRole.UserRole)
                if d:
                    expanded_ids.add(d.get("id", ""))
        # 记住当前选中
        selected_items = self.chapter_tree.selectedItems()
        prev_selected_id = None
        prev_selected_type = None
        if selected_items:
            d = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
            if d:
                prev_selected_id = d.get("id")
                prev_selected_type = d.get("type")

        self.chapter_tree.clear()

        try:
            data = book_service.list_for_project(self.current_project["id"])
        except ServiceError as e:
            Dialogs.warning("加载卷册", str(e), parent=self)
            return

        matched_item = None
        for b in data.get("books", []):
            vol_label = f"第{b.get('volume_no', '?')}卷  {b.get('title') or ''}"
            vol_item_obj = QTreeWidgetItem([vol_label])
            vol_data = {"type": "volume", **b}
            vol_item_obj.setData(0, Qt.ItemDataRole.UserRole, vol_data)
            self.chapter_tree.addTopLevelItem(vol_item_obj)

            # 恢复展开
            if b.get("id") in expanded_ids:
                vol_item_obj.setExpanded(True)

            # 加载章节
            try:
                ch_data = chapter_service.list_for_book(b["id"])
            except ServiceError:
                ch_data = {"chapters": []}
            for c in ch_data.get("chapters", []):
                # 潜文本标记
                mark = ""
                try:
                    from app.services import subtext as subtext_svc
                    card = subtext_svc.get_subtext_card(c.get("id"))
                    mark = subtext_svc.SUBTEXT_MARK if card else ""
                except Exception:
                    pass
                ch_label = (
                    f"第{c.get('chapter_no', '?')}章  "
                    f"{c.get('title') or '(无题)'}  [{c.get('status')}]{mark}"
                )
                ch_item = QTreeWidgetItem([ch_label])
                ch_data_full = {"type": "chapter", "book_id": b["id"],
                                "volume_no": b.get("volume_no"), **c}
                ch_item.setData(0, Qt.ItemDataRole.UserRole, ch_data_full)
                vol_item_obj.addChild(ch_item)
                # 匹配上次选中
                if prev_selected_id == c.get("id") and prev_selected_type == "chapter":
                    matched_item = ch_item

        if matched_item:
            self.chapter_tree.setCurrentItem(matched_item)
        if prev_selected_type == "volume" and not matched_item:
            for i in range(self.chapter_tree.topLevelItemCount()):
                item = self.chapter_tree.topLevelItem(i)
                d = item.data(0, Qt.ItemDataRole.UserRole)
                if d and d.get("id") == prev_selected_id:
                    self.chapter_tree.setCurrentItem(item)
                    break

        # V4.0-P2-新: 同步刷新卷结构小卡 (books 数变了)
        if hasattr(self, "_reload_structure_card"):
            self._reload_structure_card()

    def _reload_structure_card(self) -> None:
        """V4.0-P2-新: 把 project 的分卷/章节/字数 拉一遍, 写到 structure_card.

        数据来源:
          - project.volumes / chapters_per_volume / word_target (从 project dict)
          - 遍历 project 下所有 books, 每本 list_for_book 取章节, 数章节数和合计字数
        """
        if not self.current_project:
            self.structure_card.set_data(
                volumes=0, chapters_per_volume=0,
                chapters_written=0, words_written=0, words_target=0,
            )
            return
        p = self.current_project
        pid = p.get("id")
        volumes = int(p.get("volumes") or 0)
        cpv = int(p.get("chapters_per_volume") or 0)
        target = int(p.get("word_target") or 0)
        chap_count = 0
        words_total = 0
        try:
            from app.services import book_service, chapter_service
            books_data = book_service.list_for_project(pid) or {}
            for b in books_data.get("books", []):
                bid = b.get("id")
                if not bid:
                    continue
                chs = chapter_service.list_for_book(bid) or {}
                ch_list = chs.get("chapters", [])
                chap_count += len(ch_list)
                for c in ch_list:
                    words_total += int(c.get("word_count") or 0)
        except Exception as e:
            log.debug(f"structure card: list chapters failed: {e}")
        self.structure_card.set_data(
            volumes=volumes,
            chapters_per_volume=cpv,
            chapters_written=chap_count,
            words_written=words_total,
            words_target=target,
        )

    def _on_tree_selection(self) -> None:
        """树节点选择: 卷册→展开/折叠, 章节→加载正文."""
        items = self.chapter_tree.selectedItems()
        if not items:
            self.current_chapter_id = None
            self.current_chapter = None
            self.editor.clear()
            self.chapter_title_label.setText("(未选章节)")
            self.btn_save.setEnabled(False)
            self.btn_tts.setEnabled(False)
            self.btn_tts_open.setEnabled(False)
            self.lbl_tts_status.setText("")
            self.btn_export.setEnabled(False)
            if hasattr(self, "btn_start_writing"):
                self.btn_start_writing.setEnabled(False)
            self.eval_panel.set_chapter(None)
            return

        item = items[0]
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if not d:
            return

        if d.get("type") == "volume":
            # 卷册选中: 记录当前卷, 启用导出/新建章节
            self.current_book_id = d.get("id")
            self.btn_export.setEnabled(self.current_book_id is not None)
            return

        if d.get("type") == "chapter":
            self.current_book_id = d.get("book_id")
            self.current_chapter_id = d.get("id")
            self.current_chapter = d
            self.chapter_title_label.setText(
                f"第{d.get('chapter_no', '?')}章  {d.get('title') or '(无题)'}  [{d.get('status')}]"
            )
            self.editor.setPlainText(d.get("draft") or d.get("final") or "")
            self.btn_save.setEnabled(True)
            self.btn_export.setEnabled(self.current_book_id is not None)
            # 检查 TTS 是否可用
            try:
                from app.services.tts_edge import TTSEdgePlugin
                self.btn_tts.setEnabled(True)
            except Exception:
                self.btn_tts.setEnabled(False)
            # V4.0-P4-新: 选好章节后, 启用「开始写作」按钮
            if hasattr(self, "btn_start_writing"):
                self.btn_start_writing.setEnabled(True)
            self.eval_panel.set_chapter(d)
            # v3.0 切章节: 重置 _last_saved_text + per-chapter 提示状态 + 刷新软提示
            self._last_saved_text = self.editor.toPlainText()
            self._hint_disabled = False
            self.hint_card.setVisible(True)
            self._refresh_hints()
            # M8: 刷新 TTS 状态 (是否已合成)
            self._refresh_tts_status()

    # ---- M8: TTS 朗读 ----

    def _refresh_tts_status(self) -> None:
        """根据 chapter + book 反查 project, 看是否已合成 TTS."""
        if not self.current_chapter_id or not self.current_chapter:
            self.btn_tts_open.setEnabled(False)
            self.lbl_tts_status.setText("")
            return
        
        try:
            from app.services import book_service
            ch = self.current_chapter
            b = book_service.get(ch["book_id"])
            pid = b["project_id"]
            from app.services.tts_edge import TTSEdgePlugin
            plugin = TTSEdgePlugin()
            ap = plugin.get_audio_path(self.current_chapter_id, pid)
            if ap:
                self.btn_tts_open.setEnabled(True)
                self.lbl_tts_status.setText("🎵 已合成")
                from app.ui.theme import text_warn_ok
                self.lbl_tts_status.setStyleSheet(f"color: {text_warn_ok()}; font-size: 11px;")
            else:
                self.btn_tts_open.setEnabled(False)
                self.lbl_tts_status.setText("🔇 未合成")
                from app.ui.theme import text_subtle
                self.lbl_tts_status.setStyleSheet(f"color: {text_subtle()}; font-size: 11px;")
        except Exception as e:
            log.debug("tts status refresh failed: %s", e)
            self.btn_tts_open.setEnabled(False)
            self.lbl_tts_status.setText("")

    # ---- V4.0-P4-新: 开始写作 (AI 7 步生成流程) ----

    def _on_start_writing(self) -> None:
        """V4.0-P4-新: 弹出 7 步 AI 写作流程对话框 (复用 GenerateTab).

        流程:
          1) 校验当前项目 / 章节已选
          2) 弹 WritingDialog → 内嵌 GenerateTab → 自动选好当前 book/chapter
          3) 用户点「生成 (7 步)」, 流式输出章节内容
          4) 完成后, 用户可点「写入章节」把 output 落到 chapter.draft
        """
        if not self.current_chapter_id or not self.current_chapter:
            Dialogs.warning(
                "开始写作",
                "请先在左侧选一个章节 (新建章节: 章节管理 → + 新建章节)",
                parent=self,
            )
            return
        if not self.current_project:
            Dialogs.warning("开始写作", "请先在「项目管理」选一个项目", parent=self)
            return
        from app.ui.tabs.editor_tab_writing_dialog import WritingFlowDialog
        dlg = WritingFlowDialog(
            project=self.current_project,
            project_id=self.current_project["id"],
            book_id=self.current_book_id,
            chapter_id=self.current_chapter_id,
            chapter_title=self.current_chapter.get("title")
                       or f"第{self.current_chapter.get('chapter_no', '?')}章",
            parent=self,
        )
        # 写回信号: 写完章节后, EditorTab 自己也 reload 一下当前章节
        dlg.written_back.connect(self._on_chapter_written_back)
        dlg.exec()

    def _on_chapter_written_back(self, chapter_id: str, new_text: str) -> None:
        """V4.0-P4-新: WritingDialog 写回章节后, 同步刷新 EditorTab 当前显示."""
        if chapter_id == self.current_chapter_id:
            self.editor.setPlainText(new_text)
            self.btn_save.setEnabled(True)
            self.statusBar().showMessage(
                f"已从写作对话框写入 {len(new_text)} 字符", 3000
            ) if hasattr(self, "statusBar") else None

    def _on_tts_synth(self) -> None:
        """调 TTS 服务合成当前章节, mock 模式 (秒完成)."""
        if not self.current_chapter_id:
            return
        # 首次使用提示
        if not show_first_use_if_needed("editor_tts", self):
            return
        self.btn_tts.setEnabled(False)
        self.lbl_tts_status.setText("⏳ 合成中...")
        from app.ui.theme import text_orange
        self.lbl_tts_status.setStyleSheet(f"color: {text_orange()}; font-size: 11px;")
        try:
            from app.services.tts_edge import TTSEdgePlugin
            plugin = TTSEdgePlugin()
            result = plugin.synthesize_chapter(self.current_chapter_id, engine="mock")
            self.lbl_tts_status.setText(
                f"✅ {result.duration_sec:.0f}s  (mock, {result.text_len}字)"
            )
            from app.ui.theme import text_warn_ok
            self.lbl_tts_status.setStyleSheet(f"color: {text_warn_ok()}; font-size: 11px;")
            self.btn_tts_open.setEnabled(True)
            Dialogs.info(
                "TTS 合成完成",
                f"音频已保存到:\n{result.out_path}\n\n"
                f"时长估算: {result.duration_sec:.1f} 秒\n"
                f"引擎: {result.engine}\n"
                f"voice: {result.voice}\n\n"
                f"点击 [📁 打开音频] 用系统播放器播放。",
                parent=self,
            )
        except Exception as e:
            self.lbl_tts_status.setText(f"❌ 失败: {e}")
            from app.ui.theme import text_danger_strong
            self.lbl_tts_status.setStyleSheet(f"color: {text_danger_strong()}; font-size: 11px;")
            Dialogs.error("TTS 合成失败", str(e), parent=self)
        finally:
            self.btn_tts.setEnabled(True)

    def _on_tts_open(self) -> None:
        """用 OS 默认程序打开已合成的音频文件."""
        if not self.current_chapter_id or not self.current_chapter:
            return
        try:
            from app.services import book_service
            from app.services.tts_edge import TTSEdgePlugin
            ch = self.current_chapter
            b = book_service.get(ch["book_id"])
            pid = b["project_id"]
            plugin = TTSEdgePlugin()
            ap = plugin.get_audio_path(self.current_chapter_id, pid)
            if not ap:
                Dialogs.info("提示", "该章节还没有合成 TTS。", parent=self)
                return
            import os
            if os.name == "nt":
                os.startfile(ap)  # type: ignore[attr-defined]
            elif os.name == "posix":
                import subprocess, sys
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, ap])
            self.lbl_tts_status.setText(f"🎵 已打开: {os.path.basename(ap)}")
        except Exception as e:
            Dialogs.error("打开失败", str(e), parent=self)

    def refresh_tier_indicator(self) -> None:
        """M10-C: 刷新 tier 指示 + 所有 FeatureGateBadge (license 切换后调用)."""
        if hasattr(self, "lbl_tier"):
            self.lbl_tier.setText(get_current_tier_label())
        if hasattr(self, "badge_export"):
            self.badge_export.refresh()
        # 递归刷所有子 badge
        refresh_all_badges(self)

    # ---- M10-A: 一键出版 ----
    def _on_export(self) -> None:
        """M9-B 后端: 弹 ExportDialog, 选卷/格式/封面, 调 BookExporter."""
        if not self.current_project:
            Dialogs.warning("提示", "请先打开项目", parent=self)
            return
        if not self.current_book_id:
            Dialogs.warning("提示", "请先在左侧选一个卷册", parent=self)
            return
        # M10-C: feature gate 校验 (publish.oneclick 是 PRO 专属)
        if not assert_feature_or_dialog("publish.oneclick", parent=self):
            return
        # 首次使用提示 (弹"vs 不用"对比 + 0 元)
        if not show_first_use_if_needed("editor_export", self):
            return
        # 收集所有卷 (供 dialog 下拉), 默认选当前卷
        books: list = []
        for i in range(self.chapter_tree.topLevelItemCount()):
            it = self.chapter_tree.topLevelItem(i)
            b = it.data(0, Qt.ItemDataRole.UserRole)
            if b:
                title = b.get("title") or f"第{b.get('volume_no', '?')}卷"
                books.append((b["id"], title))
        if not books:
            Dialogs.warning("提示", "当前项目没有卷册, 无法导出", parent=self)
            return
        # 弹 ExportDialog
        dlg = ExportDialog(
            project_id=self.current_project["id"],
            books=books,
            current_book_id=self.current_book_id,
            parent=self,
        )
        dlg.exec()

    # ---- M11-D: 4 步出版向导 ----
    def _on_publish_wizard(self) -> None:
        """M11-D: 弹 PublishWizard 4 步向导 (Book → Format → Cover → Output)."""
        if not self.current_project:
            Dialogs.warning("提示", "请先打开项目", parent=self)
            return
        # M10-C: feature gate 校验
        if not assert_feature_or_dialog("publish.oneclick", parent=self):
            return
        # 首次使用提示 (复用 editor_export hint)
        if not show_first_use_if_needed("editor_export", self):
            return
        # 收集所有卷
        books: list = []
        for i in range(self.chapter_tree.topLevelItemCount()):
            it = self.chapter_tree.topLevelItem(i)
            b = it.data(0, Qt.ItemDataRole.UserRole)
            if b:
                title = b.get("title") or f"第{b.get('volume_no', '?')}卷"
                books.append((b["id"], title))
        # 弹 PublishWizard
        from app.ui.widgets import PublishWizard
        dlg = PublishWizard(
            project_id=self.current_project["id"],
            project_name=self.current_project.get("name", ""),
            books=books,
            current_book_id=self.current_book_id,
            parent=self,
        )
        dlg.exec()

    def _on_new_book(self) -> None:
        if not self.current_project:
            return
        vol_str, ok = QInputDialog.getText(self, "新建卷册", "卷号 (1, 2, 3…):")
        if not ok or not vol_str.strip().isdigit():
            return
        title, _ = QInputDialog.getText(self, "新建卷册", "卷名 (可空):")
        try:
            book_service.create(
                project_id=self.current_project["id"],
                volume_no=int(vol_str.strip()),
                title=title.strip() or None,
            )
        except ServiceError as e:
            Dialogs.warning("新建卷册", str(e), parent=self)
            return
        self._reload_tree()

    def _on_new_chapter(self) -> None:
        if not self.current_book_id:
            Dialogs.info("新建章节", "请先选择/创建一个卷册。", parent=self)
            return
        ch_str, ok = QInputDialog.getText(self, "新建章节", "章节号 (1, 2, 3…):")
        if not ok or not ch_str.strip().isdigit():
            return
        title, _ = QInputDialog.getText(self, "新建章节", "章名 (可空):")
        try:
            chapter_service.create(
                book_id=self.current_book_id,
                chapter_no=int(ch_str.strip()),
                title=title.strip() or None,
                status="draft",
            )
        except ServiceError as e:
            Dialogs.warning("新建章节", str(e), parent=self)
            return
        self._reload_tree()

    def _on_save(self) -> None:
        if not self.current_chapter_id:
            return
        text = self.editor.toPlainText()
        try:
            chapter_service.update(
                self.current_chapter_id,
                draft=text,
                word_count=len(text),
            )
        except ServiceError as e:
            Dialogs.warning("保存", str(e), parent=self)
            return
        if self.current_chapter is not None:
            self.current_chapter["draft"] = text
            self.current_chapter["word_count"] = len(text)
        # v3.0: 章节封存 + 触发 worker
        committed = self._commit_chapter_signals(self.current_chapter_id)
        self._last_saved_text = text
        msg = "草稿已保存。"
        if committed:
            msg += f"（已封存 {committed} 条改稿信号）"
        Dialogs.info("保存", msg, parent=self)

    def _on_text_changed(self) -> None:
        text = self.editor.toPlainText()
        n = len(split_paragraphs(text))
        self.lbl_para_count.setText(f"{len(text)} 字 / {n} 段")
        # v3.0 启动 30s 防抖 (Layer 1)
        if _HAS_ES and _es.is_signal_enabled() and self.current_chapter_id:
            self._edit_signal_timer.start()

    # ── v3.0 Edit Signals: 3 埋点 + 章节封存 ──

    def _flush_manual_edit_signal(self) -> None:
        """30s 防抖后: 落盘 manual_edit 信号 (Layer 1)."""
        if not (_HAS_ES and _es.is_signal_enabled() and self.current_project and self.current_chapter_id):
            return
        current = self.editor.toPlainText()
        if current == self._last_saved_text:
            return
        try:
            collector = _es.get_collector(int(self.current_project["id"]))
            # 简易 meaningful diff: 改 ≥ 10 字
            if collector.is_meaningful_diff(self._last_saved_text, current, min_chars=10):
                # 段落删除检测 (埋点 3)
                if self._last_saved_text:
                    discards = collector.detect_paragraph_discard(self._last_saved_text, current)
                    for idx, content in discards:
                        collector.ingest_discard(
                            chapter_id=self.current_chapter_id,
                            paragraph_index=int(idx),
                            content=content,
                        )
                # 手动编辑 (埋点 2)
                collector.ingest_manual_edit(
                    chapter_id=self.current_chapter_id,
                    before=self._last_saved_text,
                    after=current,
                )
            self._last_saved_text = current
        except Exception as e:
            log.warning("[edit_signals] flush failed: %s", e)
        # 自动同步 character_tracker: 检测是否涉及已知角色
        try:
            self._sync_character_tracker(self.current_chapter_id, current)
        except Exception as e:
            log.debug("[ct-sync] auto-sync failed: %s", e)

    def _sync_character_tracker(self, chapter_id: str, text: str) -> None:
        """用户修订后: 检测修改文本中是否涉及已知角色, 是则自动记录快照.

        从项目角色设定中提取角色名列表, 在 text 中匹配,
        匹配到则调用 character_tracker.record() (5 维度留空, 仅标记出现).
        仅在 edit_signals 开启时运行, 避免无效写库.
        """
        if not _HAS_ES or not _es.is_signal_enabled():
            return
        if not self.current_project or not text.strip():
            return
        try:
            from app.services import setting_service
            pid = str(self.current_project["id"])
            result = setting_service.get_setting(pid, "characters") or {}
            char_list = result.get("data")
            if not char_list:
                return

            # 提取角色名列表
            names: set[str] = set()
            if isinstance(char_list, list):
                for c in char_list:
                    if isinstance(c, dict):
                        n = c.get("name", "").strip()
                        if n and len(n) >= 2:
                            names.add(n)
            elif isinstance(char_list, dict):
                for k in char_list:
                    if k.strip() and len(k.strip()) >= 2:
                        names.add(k.strip())

            if not names:
                return

            # 在文本中匹配角色名
            found = [n for n in names if n in text]
            if not found:
                return

            # 防抖: 同一角色同一章节 60s 内不重复记录
            if not hasattr(self, "_ct_last_sync"):
                self._ct_last_sync = {}
            import time
            now = time.time()
            for name in found:
                key = f"{pid}:{chapter_id}:{name}"
                last = self._ct_last_sync.get(key, 0)
                if now - last < 60:
                    continue
                try:
                    character_tracker.record(
                        pid, chapter_id, name,
                        state=f"user_edited_ch{chapter_id}",
                    )
                    self._ct_last_sync[key] = now
                except Exception as e:
                    log.debug("[ct-sync] record failed for %s: %s", name, e)
        except Exception as e:
            log.debug("[ct-sync] failed: %s", e)

    def notify_paragraph_rewrite(self, paragraph_index: int, before_text: str) -> None:
        """段落重写前调 (埋点 1: regen 入口)."""
        if not (_HAS_ES and _es.is_signal_enabled() and self.current_project and self.current_chapter_id):
            return
        try:
            collector = _es.get_collector(int(self.current_project["id"]))
            collector.ingest_regen(
                chapter_id=self.current_chapter_id,
                paragraph_index=int(paragraph_index),
                before_text=before_text or "",
                instruction="",
            )
        except Exception as e:
            log.warning("[edit_signals] regen ingest failed: %s", e)

    def notify_paragraph_rewrite_result(self, paragraph_index: int, after_text: str, accepted: bool) -> None:
        """段落重写后调 (埋点 1: regen 出口)."""
        if not (_HAS_ES and _es.is_signal_enabled() and self.current_project and self.current_chapter_id):
            return
        try:
            collector = _es.get_collector(int(self.current_project["id"]))
            collector.ingest_regen_result(
                chapter_id=self.current_chapter_id,
                paragraph_index=int(paragraph_index),
                after_text=after_text or "",
                accepted=bool(accepted),
            )
        except Exception as e:
            log.warning("[edit_signals] regen result failed: %s", e)

    def _commit_chapter_signals(self, chapter_id: int) -> int:
        """章节保存后: 封存 + 触发 worker (Layer 2)."""
        if not (_HAS_ES and _es.is_signal_enabled()):
            return 0
        try:
            _es.notify_chapter_committed(self.current_project["id"] if self.current_project else None, chapter_id)
            return 1
        except Exception as e:
            log.warning("[edit_signals] chapter commit failed: %s", e)
            return 0

    # ── v3.0 软提示卡 UI (Layer 5) ──

    def _build_hint_card(self) -> QWidget:
        """软提示卡 (默认折叠, 点 [📚 提示 (N)] 展开, §21.3)."""
        wrap = QFrame()
        wrap.setObjectName("hintCard")
        wrap.setFrameShape(QFrame.Shape.StyledPanel)
        wrap.setStyleSheet(
            "QFrame#hintCard { background: #fff8e1; border: 1px solid #ffcc02; border-radius: 6px; }"
        )
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        # 头部: 折叠/展开 + 关
        head = QHBoxLayout()
        self.hint_toggle = QPushButton("📚 提示 (0)")
        self.hint_toggle.setFlat(True)
        self.hint_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hint_toggle.clicked.connect(self._toggle_hint_card)
        head.addWidget(self.hint_toggle)
        head.addStretch(1)
        self.hint_close_btn = QPushButton("📚 关")
        self.hint_close_btn.setFlat(True)
        self.hint_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hint_close_btn.clicked.connect(self._disable_hints_for_chapter)
        head.addWidget(self.hint_close_btn)
        layout.addLayout(head)
        # 内容区 (展开时填充)
        self.hint_content = QWidget()
        self.hint_content_layout = QVBoxLayout(self.hint_content)
        self.hint_content_layout.setContentsMargins(0, 0, 0, 0)
        self.hint_content_layout.setSpacing(4)
        layout.addWidget(self.hint_content)
        self.hint_content.setVisible(False)
        wrap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        return wrap

    def _toggle_hint_card(self) -> None:
        self._hint_card_expanded = not self._hint_card_expanded
        self.hint_content.setVisible(self._hint_card_expanded)
        if self._hint_card_expanded:
            self.hint_toggle.setText(f"📚 提示 ({len(self._hint_skills)})  ▼")
        else:
            self.hint_toggle.setText(f"📚 提示 ({len(self._hint_skills)})  ▶")

    def _disable_hints_for_chapter(self) -> None:
        self._hint_disabled = True
        self.hint_card.setVisible(False)

    def _refresh_hints(self) -> None:
        """切章节时: 调 SkillInjector 选 top-K (§21.2)."""
        if not _HAS_ES:
            self.hint_card.setVisible(False)
            return
        if not _es.is_signal_enabled():
            self.hint_card.setVisible(False)
            return
        if not (self.current_project and self.current_chapter):
            self.hint_card.setVisible(False)
            return
        if self._hint_disabled:
            self.hint_card.setVisible(False)
            return
        try:
            injector = _es.get_injector(self.current_project["id"])
            chapter = dict(self.current_chapter or {})
            chapter["id"] = self.current_chapter_id
            chapter["content"] = self.editor.toPlainText()[:2000]
            skills = injector.select_for_chapter(
                chapter,
                max_skills=_es.get_signal_inject_max_skills(),
                max_tokens=_es.get_signal_inject_max_tokens(),
            )
            self._hint_skills = skills
            self.hint_toggle.setText(f"📚 提示 ({len(skills)})  ▶")
            # 填充内容
            self._populate_hint_content(skills)
            # 没有候选就隐藏卡
            self.hint_card.setVisible(len(skills) > 0)
        except Exception as e:
            log.warning("[edit_signals] refresh hints failed: %s", e)
            self.hint_card.setVisible(False)

    def _populate_hint_content(self, skills: list[dict]) -> None:
        # 清旧
        while self.hint_content_layout.count():
            item = self.hint_content_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for i, s in enumerate(skills, 1):
            row = QFrame()
            row.setStyleSheet("background: transparent;")
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(2)
            name = s.get("name", "?")
            rule = s.get("generalized_rule") or s.get("pattern_hint") or name
            state = s.get("state", "candidate")
            label = QLabel(f"{i}. [{state}] {rule[:80]}")
            label.setWordWrap(True)
            from app.ui.theme import text_secondary
            label.setStyleSheet(f"font-size: 11px; color: {text_secondary()};")
            row_layout.addWidget(label)
            # 按钮行
            btn_row = QHBoxLayout()
            accept = QPushButton("采纳")
            accept.setFixedHeight(22)
            accept.clicked.connect(lambda _=False, n=name: self._on_hint_accept(n))
            reject = QPushButton("✗ 不对")
            reject.setFixedHeight(22)
            reject.clicked.connect(lambda _=False, n=name: self._on_hint_reject(n))
            btn_row.addWidget(accept)
            btn_row.addWidget(reject)
            btn_row.addStretch(1)
            row_layout.addLayout(btn_row)
            self.hint_content_layout.addWidget(row)

    def _on_hint_accept(self, name: str) -> None:
        if not (_HAS_ES and self.current_project):
            return
        try:
            injector = _es.get_injector(self.current_project["id"])
            injector.on_user_accept(name)
            Dialogs.info("已采纳", f"已采纳候选 Skill: {name}", parent=self)
            self._refresh_hints()
        except Exception as e:
            log.warning("[edit_signals] accept failed: %s", e)

    def _on_hint_reject(self, name: str) -> None:
        if not (_HAS_ES and self.current_project):
            return
        try:
            injector = _es.get_injector(self.current_project["id"])
            injector.on_user_reject(name)
            self._refresh_hints()
        except Exception as e:
            log.warning("[edit_signals] reject failed: %s", e)
