"""
Generate tab (v4.0) - Unit 编辑器三栏布局

三栏:
  - 左: UnitTree (卷→Unit 列表)
  - 中: UnitEditor (Unit 详情 + 正文编辑器 + 生成按钮)
  - 右: StoryHUD (Goal/Guide/Pressure/Hooks/Memory)

生成: 调用 Orchestrator.run_unit() (v4.0 默认 Guide 开启)
导出: ChapterExporter.export_from_unit()
"""
from __future__ import annotations
import json
import logging
import os
from typing import Optional

from PySide6.QtCore import Qt, QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QListWidget,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QGroupBox,
    QFormLayout,
    QInputDialog,
    QCheckBox,
    QSpinBox,
    QSlider,
    QComboBox,
)

# TTS 支持 (可选, 无模块也能启动)
try:
    from PySide6.QtTextToSpeech import QTextToSpeech, QVoice
    _HAS_TTS = True
except ImportError:
    _HAS_TTS = False
    QTextToSpeech = None  # type: ignore
    QVoice = None  # type: ignore

from app.services import (
    book_service,
    chapter_service,
    project_service,
    app_setting_service,
    ServiceError,
)
from app.agents.orchestrator import (
    Orchestrator, OrchestratorConfig, OrchestratorResult, build_orchestrator,
)
from app.services.writing.paragraph_rewriter import (
    LLMScopedRewriter, MockScopedRewriter, split_paragraphs, join_paragraphs,
)
from app.ui.tokens_hint import PriceBar, show_first_use_if_needed
from app.ui.widgets import Dialogs

log = logging.getLogger(__name__)

# v3.4: edit_signals (静默导入, 关了也不报错)
try:
    from app.workflow import edit_signals as _es
    _HAS_ES = True
except Exception:
    _es = None
    _HAS_ES = False


# --------------------------------------------------------------------- #
# Worker: 生成章节 (统一走 Orchestrator)
# --------------------------------------------------------------------- #

class GenerateWorker(QObject):
    """QObject worker. 跑在 QThread 里, 通过 signal 推回主线程.
    统一走 Orchestrator，单版本模式 = 关闭评估改稿循环.
    """
    step = Signal(int, str, dict)
    chunk = Signal(str)
    thinking = Signal(str)
    info = Signal(str)
    done = Signal(dict)
    error = Signal(str)
    finished = Signal()

    def __init__(self, project_id: str, chapter_id: str, *,
                 use_ai: bool = True, auto_save: bool = False,
                 enable_revision: bool = False) -> None:
        super().__init__()
        self.project_id = project_id
        self.chapter_id = chapter_id
        self.use_ai = use_ai
        self.auto_save = auto_save
        self.enable_revision = enable_revision  # 是否开启评估改稿循环
        self._cancelled = False
        self._orch = None

    def cancel(self) -> None:
        self._cancelled = True
        if self._orch:
            self._orch.cancel()

    def run(self) -> None:
        try:
            p = app_setting_service.get_active()
            if self.use_ai and not p:
                self.info.emit("未配置 active provider, 已用 mock 生成. 请在「设置 - 模型」选一个 provider.")

            from app.agents.orchestrator import Orchestrator, OrchestratorConfig
            config = OrchestratorConfig(
                enable_revision_loop=self.enable_revision,
            )
            orch = Orchestrator(config=config)
            self._orch = orch

            result = orch.run_chapter(
                self.project_id,
                self.chapter_id,
                on_step=lambda s, lbl: self.step.emit(s, lbl, {}),
            )

            if result.ok:
                self.done.emit(result.to_dict())
            else:
                self.error.emit(result.error)
        except Exception as e:
            log.exception("[GenerateWorker] unexpected error")
            self.error.emit(f"{type(e).__name__}: {e}")
        finally:
            self.finished.emit()


# --------------------------------------------------------------------- #
# Worker: Orchestrator (将军) 模式
# --------------------------------------------------------------------- #

class OrchWorker(QObject):
    """Orchestrator worker. 跑在 QThread 里, 通过 signal 推回主线程."""
    step = Signal(int, str, dict)
    chunk = Signal(str)
    thinking = Signal(str)
    info = Signal(str)
    done = Signal(dict)
    error = Signal(str)
    finished = Signal()

    def __init__(self, project_id: str, chapter_id: str) -> None:
        super().__init__()
        self.project_id = project_id
        self.chapter_id = chapter_id
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        if self._orch:
            self._orch.cancel()

    def run(self) -> None:
        self._orch = None
        try:
            p = app_setting_service.get_active()
            if not p:
                self.info.emit("未配置 active provider, 将军将以 mock 模式运行。请在「设置 - 模型」选一个 provider。")

            orch = build_orchestrator()
            self._orch = orch

            result = orch.run_chapter(
                self.project_id,
                self.chapter_id,
                on_step=lambda s, lbl: self.step.emit(s, lbl, {}),
            )

            self.done.emit(result.to_dict())
        except Exception as e:
            log.exception("[OrchWorker] unexpected error")
            self.error.emit(f"{type(e).__name__}: {e}")
        finally:
            self.finished.emit()


# --------------------------------------------------------------------- #
# v4.0 Worker: run_unit() 直接调用
# --------------------------------------------------------------------- #

class _OrchUnitWorker(QObject):
    progress = Signal(int, bool)
    done = Signal(str, str)
    error = Signal(str)
    finished = Signal()

    def __init__(self, orch, project_id: str, unit_id: str,
                 use_v4_pipeline: bool = False) -> None:
        super().__init__()
        self._orch = orch
        self._project_id = project_id
        self._unit_id = unit_id
        self._use_v4 = use_v4_pipeline

    def run(self) -> None:
        try:
            result = self._orch.run_unit(
                self._project_id, self._unit_id,
                use_v4_pipeline=self._use_v4,
            )
            if result.ok:
                text = ""
                for r in result.reports:
                    data = r.data if hasattr(r, "data") else {}
                    if isinstance(data, dict):
                        text = data.get("content", text) or data.get("text", text) or text
                self.done.emit(self._unit_id, text or "generated")
            else:
                self.error.emit(result.error or "unknown error")
        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")
        finally:
            self.finished.emit()


# --------------------------------------------------------------------- #
# Worker: 段落重写
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


class ParagraphRewriteAllWorker(QObject):
    """全部重写 worker: 重写整个章节的所有段落."""
    chunk = Signal(str)
    done = Signal(dict)
    error = Signal(str)
    finished = Signal()
    info = Signal(str)

    def __init__(self, chapter: dict, instruction: str = "") -> None:
        super().__init__()
        self.chapter = chapter
        self.instruction = instruction
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
                log.warning(f"[PRW-ALL] bad config, fallback to mock: {e}")
                self.rewriter = MockScopedRewriter()
                self._info_msg = f"provider 配置异常: {e}. 已用 mock."
        else:
            self.rewriter = MockScopedRewriter()
            self._info_msg = "未配 active provider, 已用 mock 重写."

    def run(self) -> None:
        try:
            if self._info_msg:
                self.info.emit(self._info_msg)
            
            # 获取当前内容并分段
            draft = self.chapter.get("draft") or self.chapter.get("final") or ""
            paragraphs = split_paragraphs(draft)
            if not paragraphs:
                self.done.emit({
                    "new_text": "",
                    "summary": "无内容可重写",
                    "success": False,
                })
                return
            
            # 逐段重写
            new_paragraphs = []
            for idx, para in enumerate(paragraphs):
                result = self.rewriter.run(
                    chapter=self.chapter,
                    paragraph_index=idx,
                    instruction=self.instruction,
                )
                if result.get("success"):
                    new_paragraphs.append(result["new_paragraph"])
                else:
                    new_paragraphs.append(para)  # 失败则保留原文
            
            new_text = join_paragraphs(new_paragraphs)
            self.done.emit({
                "new_text": new_text,
                "summary": f"已重写 {len(new_paragraphs)} 段",
                "success": True,
            })
        except Exception as e:
            log.exception("[PRW-ALL] failed")
            self.error.emit(str(e))
        finally:
            self.finished.emit()


# --------------------------------------------------------------------- #
# 评估面板 (从 EditorTab 搬过来)
# --------------------------------------------------------------------- #

class EvaluationPanel(QWidget):
    """右侧面板: 显示当前章节的 critic + hook 数据, 段落重写入口."""

    def __init__(self, host: Optional[object] = None) -> None:
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

        # Critic
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

        # Hook
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

        # 反 AI 味 Issues
        self.issues_box = QGroupBox("⚠️ 反 AI 味问题")
        ib = QVBoxLayout(self.issues_box)
        self.issues_list = QLabel("(生成章节后自动检测)")
        from app.ui.theme import text_muted
        self.issues_list.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        self.issues_list.setWordWrap(True)
        ib.addWidget(self.issues_list)
        v.addWidget(self.issues_box)

        # 段落重写
        rw_box = QGroupBox("✏️ 段落重写")
        rb = QFormLayout(rw_box)
        self.spn_paragraph = QPushButton("在光标段重写")
        self.spn_paragraph.clicked.connect(self._on_rewrite_cursor_paragraph)
        self.spn_paragraph.setEnabled(False)
        rb.addRow(self.spn_paragraph)
        self.spn_all = QPushButton("全部重写")
        self.spn_all.clicked.connect(self._on_rewrite_all)
        self.spn_all.setEnabled(False)
        rb.addRow(self.spn_all)
        self.pr_status = QLabel("")
        from app.ui.theme import text_muted
        self.pr_status.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        self.pr_status.setWordWrap(True)
        rb.addRow(self.pr_status)
        v.addWidget(rw_box)

        v.addStretch(1)

    def set_chapter(self, chapter: Optional[dict]) -> None:
        self.current_chapter = chapter
        self._load_evaluation(chapter)
        has_text = bool(chapter and (chapter.get("draft") or chapter.get("final")))
        self.spn_paragraph.setEnabled(has_text)
        self.spn_all.setEnabled(has_text)

    def set_paragraph_rewrite_status(self, msg: str) -> None:
        self.pr_status.setText(msg)

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
        issues = critic.get("issues", []) if critic else []
        if issues:
            sev_emoji = {"block": "🔴", "warn": "🟡", "info": "🔵"}
            lines = []
            for iss in issues[:10]:
                emoji = sev_emoji.get(iss.get("severity", "info"), "🔵")
                label = iss.get("label", iss.get("kind", ""))
                loc = iss.get("location", "")
                snippet = iss.get("snippet", "")
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

    def _on_rewrite_cursor_paragraph(self) -> None:
        editor = self.parent_editor()
        if editor is None:
            return
        cursor = editor.textCursor()
        block_text = cursor.block().text()
        if not block_text.strip():
            Dialogs.info("段落重写", "当前光标不在有效段落", parent=self)
            return
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

    def _on_rewrite_all(self) -> None:
        """重写整个章节的所有段落."""
        editor = self.parent_editor()
        if editor is None:
            return
        full_text = editor.toPlainText()
        paragraphs = split_paragraphs(full_text)
        if not paragraphs:
            Dialogs.info("全部重写", "当前章节无正文", parent=self)
            return
        instruction, _ = QInputDialog.getText(
            self, "全部重写", "可选 - 重写要求 (留空 = 通用):",
        )
        self._start_rewrite_all(instruction or "")

    def _start_rewrite_all(self, instruction: str) -> None:
        """启动全部重写任务."""
        if not self.current_chapter:
            return
        if self._thread is not None:
            Dialogs.info("全部重写", "已有重写任务在跑", parent=self)
            return
        show_first_use_if_needed("editor_rewrite", self)
        self.pr_status.setText("⏳ 全部重写中…")
        self.spn_paragraph.setEnabled(False)
        self.spn_all.setEnabled(False)
        
        # 创建全部重写worker
        self._thread = QThread()
        self._worker = ParagraphRewriteAllWorker(self.current_chapter, instruction)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.info.connect(self._on_rewrite_info)
        self._worker.done.connect(self._on_rewrite_all_done)
        self._worker.error.connect(self._on_rewrite_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._on_rewrite_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.start()

    def _on_rewrite_all_done(self, result: dict) -> None:
        """全部重写完成回调."""
        new_text = result.get("new_text", "")
        summary = result.get("summary", "")
        success = result.get("success", False)
        if not success:
            self.pr_status.setText(f"❌ {summary}")
            return
        editor = self.parent_editor()
        if editor is None:
            return
        editor.setPlainText(new_text)
        if self.current_chapter:
            try:
                chapter_service.update(
                    self.current_chapter["id"],
                    draft=new_text,
                    word_count=len(new_text),
                )
            except ServiceError as e:
                log.warning(f"[PRW] persist failed: {e}")
        self.pr_status.setText(f"✅ 全部重写完成 | {summary}")

    def _start_rewrite(self, paragraph_index: int, instruction: str) -> None:
        if not self.current_chapter:
            return
        if self._thread is not None:
            Dialogs.info("段落重写", "已有重写任务在跑", parent=self)
            return
        show_first_use_if_needed("editor_rewrite", self)
        self.pr_status.setText("⏳ 重写中…")
        self.spn_paragraph.setEnabled(False)
        self.spn_all.setEnabled(False)
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
        if self.current_chapter:
            try:
                chapter_service.update(
                    self.current_chapter["id"],
                    draft=new_text,
                    word_count=len(new_text),
                )
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
        cursor = editor.textCursor()
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

    def _on_rewrite_error(self, msg: str) -> None:
        self.pr_status.setText(f" {msg}")

    def _on_rewrite_finished(self) -> None:
        if self._thread is not None:
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
        has_text = bool(self.current_chapter and
                        (self.current_chapter.get("draft") or self.current_chapter.get("final")))
        self.spn_paragraph.setEnabled(has_text)
        self.spn_all.setEnabled(has_text)

    def parent_editor(self) -> Optional[QPlainTextEdit]:
        host = getattr(self, "host", None)
        if host is not None and hasattr(host, "editor"):
            return getattr(host, "editor")
        p = self.parentWidget()
        while p is not None:
            if hasattr(p, "editor"):
                return getattr(p, "editor")
            p = p.parentWidget()
        return None


# --------------------------------------------------------------------- #
# GenerateTab (合并了 EditorTab 的编辑/评估/段落重写功能)
# --------------------------------------------------------------------- #

class GenerateTab(QWidget):
    step_with_meta = Signal(int, str, dict)

    def __init__(self) -> None:
        super().__init__()
        self.current_project: Optional[dict] = None
        self.current_project_id: Optional[str] = None
        self.current_book_id: Optional[str] = None
        self.current_chapter_id: Optional[str] = None
        self.current_chapter: Optional[dict] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[GenerateWorker] = None
        # v3.4 edit_signals: 防抖采集
        self._last_committed_text: str = ""
        self._edit_signal_timer = QTimer(self)
        self._edit_signal_timer.setSingleShot(True)
        debounce_ms = _es.get_signal_debounce_ms() if _HAS_ES else 30_000
        self._edit_signal_timer.setInterval(int(debounce_ms))
        self._edit_signal_timer.timeout.connect(self._flush_edit_signal)
        # TTS 引擎 (懒初始化)
        self._tts: Optional["QTextToSpeech"] = None
        self._tts_paused: bool = False
        self._build_ui()

    def _build_ui(self) -> None:
        self.title = QLabel("Current Unit")
        from app.ui.theme import score_value
        self.title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {score_value()};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(self.title)

        self.price_bar = PriceBar("generate")
        outer.addWidget(self.price_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # ---- 左侧: UnitTree ----
        from app.ui.widgets.unit_tree import UnitTree
        self.unit_tree = UnitTree()
        self.unit_tree.unit_selected.connect(self._on_unit_selected)
        splitter.addWidget(self.unit_tree)

        # ---- 中间: UnitEditor ----
        from app.ui.widgets.unit_editor import UnitEditor
        self.unit_editor = UnitEditor()
        self.unit_editor.generate_requested.connect(self._on_unit_generate)
        self.unit_editor.export_requested.connect(self._on_unit_export)
        splitter.addWidget(self.unit_editor)
        splitter.setStretchFactor(1, 3)

        # ---- 右侧: StoryHUD ----
        from app.ui.widgets.story_hud import StoryHUD
        self.story_hud = StoryHUD()
        splitter.addWidget(self.story_hud)

        splitter.setSizes([220, 500, 280])

        # 保留旧 worker 引用以兼容
        self.chapter_tree = QTreeWidget()
        self.chapter_tree.hide()
        self.chapter_title_label = QLabel("")
        self.chapter_title_label.hide()
        self.editor = QPlainTextEdit()
        self.editor.hide()
        self.status_label = QLabel("")
        self.status_label.hide()
        self.thinking_view = QPlainTextEdit()
        self.thinking_view.hide()
        self.btn_generate = QPushButton("")
        self.btn_generate.hide()
        self.btn_cancel = QPushButton("")
        self.btn_cancel.hide()
        self.btn_save = QPushButton("")
        self.btn_save.hide()
        self.chk_multi = QCheckBox()
        self.chk_multi.hide()
        self.chk_orch = QCheckBox()
        self.chk_orch.hide()
        self.chk_v4 = QCheckBox("v4 Pipeline")
        self.chk_v4.setToolTip("使用 v4 Story OS 全链路 (State→Signals→Decision→Prompt)")
        self.chk_v4.hide()
    def set_project(self, project: Optional[dict]) -> None:
        self.current_project = project
        self.current_project_id = project.get("id") if project else None
        self.current_book_id = None
        self.current_chapter_id = None
        self.current_chapter = None

        if project is None:
            self.title.setText("\u5f53\u524d\u521b\u4f5c\uff08\u65e0\u9879\u76ee\uff09")
            self.unit_tree._reload()
            return

        self.title.setText(f"Current Unit — {project.get('name', '')}")
        self.unit_tree.set_project(self.current_project_id)

    def _on_unit_selected(self, unit_id: str) -> None:
        self.current_chapter_id = unit_id
        self.unit_editor.set_unit(unit_id)
        self.story_hud.set_unit(unit_id, self.current_project_id or "")

    def _on_unit_generate(self, unit_id: str, use_v4: bool = False) -> None:
        if not self.current_project_id:
            return
        self.unit_editor.set_progress(0, True)

        from app.agents.orchestrator import Orchestrator, OrchestratorConfig
        self._orch = Orchestrator(config=OrchestratorConfig(enable_revision_loop=False))
        self._thread = QThread()
        self._worker = _OrchUnitWorker(
            self._orch, self.current_project_id, unit_id,
            use_v4_pipeline=use_v4,
        )
        self._worker.moveToThread(self._thread)
        self._worker.progress.connect(self.unit_editor.set_progress)
        self._worker.done.connect(self._on_unit_done)
        self._worker.error.connect(self._on_unit_error)
        self._thread.started.connect(self._worker.run)
        self._thread.start()

    def _on_unit_done(self, unit_id: str, text: str) -> None:
        self.unit_editor.set_content(text)
        self.unit_editor.set_progress(100, False)
        self.story_hud.set_unit(unit_id, self.current_project_id or "")
        self._cleanup_thread()

    def _on_unit_error(self, msg: str) -> None:
        self.unit_editor.set_progress(0, False)
        self._cleanup_thread()

    def _on_unit_export(self, unit_id: str) -> None:
        try:
            from app.exporter.chapter_exporter import ChapterExporter
            exporter = ChapterExporter()
            preview = exporter.preview(unit_id)
            if preview:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self, "\u7ae0\u8282\u5bfc\u51fa\u9884\u89c8",
                    f"\u5355\u5143 {unit_id[:8]} \u9884\u89c8:\n\n{preview[:500]}..."
                )
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "\u5bfc\u51fa\u9519\u8bef", str(e))

    def _cleanup_thread(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None

    def _reload_tree(self) -> None:
        """从数据源重新构建树状章节目录 (卷册→章节)."""
        if not self.current_project_id:
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
            data = book_service.list_for_project(self.current_project_id)
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
                ch_label = f"第{c.get('chapter_no', '?')}章  {c.get('title') or '(无题)'}  [{c.get('status')}]"
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

    def _on_tree_selection(self) -> None:
        """树节点选择: 卷册→展开/折叠, 章节→加载正文."""
        items = self.chapter_tree.selectedItems()
        if not items:
            self.current_chapter_id = None
            self.current_chapter = None
            self.btn_generate.setEnabled(False)
            self.chk_multi.setEnabled(False)
            self.btn_save.setEnabled(False)
            if _HAS_TTS:
                self.btn_tts_play.setEnabled(False)
            self.eval_panel.set_chapter(None)
            self.chapter_title_label.setText("(未选章节)")
            self.editor.clear()
            return

        item = items[0]
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if not d:
            return

        if d.get("type") == "volume":
            # 卷册选中: 记录当前卷
            self.current_book_id = d.get("id")
            return

        if d.get("type") == "chapter":
            self.current_book_id = d.get("book_id")
            self.current_chapter = d
            self.current_chapter_id = d["id"]
            self.btn_generate.setEnabled(True)
            self.chk_multi.setEnabled(True)
            self.chk_orch.setEnabled(True)
            self.btn_save.setEnabled(True)
            if _HAS_TTS:
                self.btn_tts_play.setEnabled(True)
            self.chapter_title_label.setText(
                f"第{d.get('chapter_no', '?')}章  {d.get('title') or '(无题)'}"
            )
            # 加载正文: 仅当编辑器为空或切换了不同章节时才从数据库加载
            draft = d.get("draft") or d.get("final") or ""
            editor_has_content = bool(self.editor.toPlainText().strip())
            if not editor_has_content or draft:
                self.editor.setPlainText(draft)
            self.eval_panel.set_chapter(d)

    def _on_save_draft(self) -> None:
        if not self.current_chapter_id:
            return
        text = self.editor.toPlainText()
        try:
            chapter_service.update(
                self.current_chapter_id,
                draft=text,
                word_count=len(text),
            )
            self.status_label.setText(f"✅ 已保存草稿 ({len(text)} 字)")
            self._last_committed_text = text
            # v3.4: 章节保存后封存 edit_signals (Layer 2)
            self._commit_chapter_signals()
        except ServiceError as e:
            Dialogs.warning("保存草稿", str(e), parent=self)

    # ---- v3.4 edit_signals 采集 (Layer 1) ----

    def _flush_edit_signal(self) -> None:
        """30s 防抖后落盘 manual_edit 信号."""
        if not (_HAS_ES and _es.is_signal_enabled() and self.current_project_id and self.current_chapter_id):
            return
        current = self.editor.toPlainText()
        prev = self._last_committed_text
        if not prev or current == prev:
            return
        try:
            collector = _es.get_collector(int(self.current_project_id))
            if collector.is_meaningful_diff(prev, current, min_chars=10):
                collector.ingest_manual_edit(
                    chapter_id=self.current_chapter_id,
                    before=prev,
                    after=current,
                )
                log.info("[generate_tab] edit_signal flushed")
        except Exception as e:
            log.warning("[generate_tab] edit_signal flush failed: %s", e)

    def _commit_chapter_signals(self) -> None:
        """章节保存后封存信号 + 触发 worker (Layer 2)."""
        if not (_HAS_ES and _es.is_signal_enabled() and self.current_project_id and self.current_chapter_id):
            return
        try:
            _es.notify_chapter_committed(
                self.current_project_id, self.current_chapter_id
            )
        except Exception as e:
            log.warning("[generate_tab] chapter commit signals failed: %s", e)

    def _on_text_changed(self) -> None:
        """编辑器文字变化时刷新段数 + 启动 edit_signal 30s 防抖."""
        text = self.editor.toPlainText()
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        # v3.4: 启动改稿信号防抖采集 (Layer 1)
        if _HAS_ES and _es.is_signal_enabled() and self.current_chapter_id:
            self._edit_signal_timer.start()

    def set_focus_chapter(self, book_id: str, chapter_id: str) -> None:
        """选中 book_id + chapter_id 并触发树节点高亮."""
        if not self.current_project_id:
            return
        self._reload_tree()
        # 遍历树节点找匹配的章节
        def _find_chapter(item):
            d = item.data(0, Qt.ItemDataRole.UserRole)
            if d and d.get("type") == "chapter" and d.get("id") == chapter_id:
                return item
            for j in range(item.childCount()):
                result = _find_chapter(item.child(j))
                if result:
                    return result
            return None

        for i in range(self.chapter_tree.topLevelItemCount()):
            vol = self.chapter_tree.topLevelItem(i)
            ch_item = _find_chapter(vol)
            if ch_item:
                vol.setExpanded(True)
                self.chapter_tree.setCurrentItem(ch_item)
                break

    # ----- 7 步工作流 ----- #

    def _on_orch_toggled(self, checked: bool) -> None:
        """将军模式切换: 更新按钮文字."""
        if checked:
            self.btn_generate.setText("✨ 将军出阵")
            self.chk_multi.setChecked(False)
            self.chk_multi.setEnabled(False)
        else:
            self.btn_generate.setText("✨ 生成 (7 步)")
            self.chk_multi.setEnabled(True)

    def _start_generate(self) -> None:
        if not self.current_chapter_id or not self.current_project_id:
            return
        if self._thread is not None:
            return

        # 将军模式
        if self.chk_orch.isChecked():
            self._start_orch_generate()
            return

        # 如果勾选了多版本生成，打开多版本对话框
        if self.chk_multi.isChecked():
            Dialogs.info(
                "功能重构中",
                "多版本生成功能正在重构中，暂时不可用。\n\n"
                "当前推荐使用「将军模式」生成正文，\n"
                "该模式使用新的编排器架构，效果更好。",
                parent=self,
            )
            self.chk_multi.setChecked(False)
            return

        # 单版本模式: 走原有7步生成流程
        show_first_use_if_needed("generate", self)
        use_ai = os.environ.get("NW_AI_MOCK", "0") != "1"

        self.editor.clear()
        self.thinking_view.clear()
        self.thinking_view.setVisible(True)
        self.status_label.setText("⏳ 生成中…")
        self.btn_generate.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        self._thread = QThread()
        self._worker = GenerateWorker(
            project_id=self.current_project_id,
            chapter_id=self.current_chapter_id,
            use_ai=use_ai,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.step.connect(self._on_step)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.thinking.connect(self._on_thinking)
        self._worker.info.connect(self._on_info)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._on_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.start()
        log.info(f"[Tab] generate started project={self.current_project_id} chapter={self.current_chapter_id} use_ai={use_ai}")

    def _start_orch_generate(self) -> None:
        """启动将军模式生成."""
        self.editor.clear()
        self.thinking_view.clear()
        self.thinking_view.setVisible(True)
        self.status_label.setText("🎖️ 将军出阵…")
        self.btn_generate.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        self._thread = QThread()
        self._worker = OrchWorker(
            project_id=self.current_project_id,
            chapter_id=self.current_chapter_id,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.step.connect(self._on_step)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.thinking.connect(self._on_thinking)
        self._worker.info.connect(self._on_info)
        self._worker.done.connect(self._on_orch_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._on_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.start()
        log.info(f"[Tab] 将军模式 started project={self.current_project_id} chapter={self.current_chapter_id}")

    def _on_orch_done(self, result_dict: dict) -> None:
        """将军模式完成回调."""
        content = result_dict.get("content", "")
        if content:
            self.editor.setPlainText(content)
        score = result_dict.get("score", 0)
        revisions = result_dict.get("revisions", 0)
        duration = result_dict.get("duration_ms", 0)
        self.status_label.setText(
            f"🎖️ 将军收兵 — 评分: {score} | 改稿 {revisions} 轮 | {duration}ms"
        )
        if result_dict.get("retention_adjusted"):
            self.status_label.setText(self.status_label.text() + " | 追读率已调")
        if result_dict.get("error"):
            self.status_label.setText(self.status_label.text() + f" | ⚠ {result_dict['error']}")
        log.info(f"[Tab] 将军完成: {result_dict}")

    def _open_multi_version_dialog(self) -> None:
        """打开多版本正文生成对话框."""
        if not self.current_project or not self.current_chapter_id:
            return

        # tokens 提醒
        from app.ui.widgets import Dialogs
        Dialogs.info(
            "多版本生成提醒",
            "️ 多版本生成将消耗额外 tokens\n\n"
            "将为当前章节生成 A/B/C 3个版本正文\n"
            "每个版本使用独立的 7 步写作流程，并行运行\n\n"
            "生成后可对比选择最符合你风格的版本。",
            parent=self,
        )

        from app.ui.tabs.body_gen_dialog import BodyGenDialog
        dlg = BodyGenDialog(
            self.current_project,
            self.current_chapter_id,
            parent=self,
        )
        dlg.exec()

        # Dialog 关闭后，检查用户是否选定了版本
        selected_text = dlg.get_selected_body_text()
        if selected_text:
            # 将选定版本的正文插入编辑器
            self.editor.setPlainText(selected_text)
            self.status_label.setText(f"✅ 已插入版本 {dlg.selected_version} 正文 ({len(selected_text)} 字)")

            # 更新作者风格指纹 (基于用户选定的版本)
            selected_style = dlg.get_selected_style()
            if selected_style:
                try:
                    from app.services.style_fingerprint import upsert_author_fp
                    upsert_author_fp(
                        source="ai_learned",
                        **selected_style,
                    )
                    log.info(f"[Tab] 作者风格指纹已更新: {selected_style}")
                except Exception as e:
                    log.warning(f"[Tab] 更新作者风格指纹失败: {e}")

    def _on_cancel(self) -> None:
        if self._worker is not None:
            log.info("[Tab] cancel requested")
            self._worker.cancel()
            self.btn_cancel.setEnabled(False)
            self.status_label.setText("⏸ 取消中…")

    def _on_step(self, step: int, label: str, meta: dict | None = None) -> None:
        if meta is None:
            meta = {}
        self.step_with_meta.emit(step, label, meta)
        self.status_label.setText(f"Step {step}/7  {label}")
        log.info(f"[Tab] step {step}/7 {label} meta={meta}")

    def _on_chunk(self, chunk: str) -> None:
        self.editor.moveCursor(self.editor.textCursor().MoveOperation.End)
        self.editor.insertPlainText(chunk)
        self.editor.repaint()

    def _on_thinking(self, text: str) -> None:
        if not text:
            return
        self.thinking_view.setVisible(True)
        self.thinking_view.moveCursor(self.thinking_view.textCursor().MoveOperation.End)
        self.thinking_view.insertPlainText(text)
        self.thinking_view.repaint()

    def _on_info(self, msg: str) -> None:
        self.status_label.setText(f"ℹ️ {msg}")

    def _on_done(self, result: dict) -> None:
        critic_score = result.get("critic_score", 0)
        cost = result.get("cost_usd", 0.0)
        content_chars = result.get("content_chars", 0)
        duration = result.get("duration_ms", 0)
        content = result.get("content", "")

        log.info(f"[Tab] _on_done: content={len(content)}chars editor_now={len(self.editor.toPlainText())}chars")

        # 将生成的内容写入编辑器
        # 优先使用 result 里的完整 content（流式 chunk 可能不完整）
        if content:
            self.editor.setPlainText(content)
            log.info(f"[Tab] content written to editor: {len(content)} chars")
        elif not self.editor.toPlainText().strip():
            # fallback: result 无 content 且编辑器也是空的，说明流式也没收到
            log.warning("[Tab] no content in result AND editor is empty — 生成内容丢失")
        else:
            # 流式 chunk 已经填了编辑器，result.content 为空只是序列化问题，保留现有内容
            log.info(f"[Tab] result.content empty but editor has {len(self.editor.toPlainText())} chars (from chunks), kept")

        # v3.4: 记录生成文本作为 edit_signal diff 基线
        self._last_committed_text = self.editor.toPlainText()
        
        self.status_label.setText(
            f"✅ 完成 | 📊 {critic_score}分 | 📝 {content_chars}字 | "
            f"💰 ${cost:.4f} | ⏱ {duration}ms"
        )
        # 刷新评估面板
        if self.current_chapter_id:
            try:
                ch = chapter_service.get(self.current_chapter_id)
                self.eval_panel.set_chapter(ch)
            except Exception:
                pass
        log.info(f"[Tab] done score={critic_score} cost=${cost:.4f}")

    def _on_error(self, msg: str) -> None:
        self.status_label.setText(f" {msg}")
        log.warning(f"[Tab] error: {msg}")

    def _on_finished(self) -> None:
        has_chapter = self.current_chapter_id is not None
        self.btn_generate.setEnabled(has_chapter)
        self.chk_multi.setEnabled(has_chapter and not self.chk_orch.isChecked())
        self.chk_orch.setEnabled(has_chapter)
        self.btn_cancel.setEnabled(False)
        # 恢复按钮文字
        if self.chk_orch.isChecked():
            self.btn_generate.setText("✨ 将军出阵")
        else:
            self.btn_generate.setText("✨ 生成 (7 步)")
        if self._thread is not None:
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
        log.info("[Tab] generate finished, thread cleaned")

    # ------------------------------------------------------------------ #
    # TTS 朗读相关方法
    # ------------------------------------------------------------------ #

    def _get_tts(self) -> Optional["QTextToSpeech"]:
        """懒初始化 QTextToSpeech 实例，优先 winrt > sapi > 默认."""
        if not _HAS_TTS:
            return None
        if self._tts is None:
            engines = QTextToSpeech.availableEngines()
            engine = "winrt" if "winrt" in engines else ("sapi" if "sapi" in engines else "")
            self._tts = QTextToSpeech(engine) if engine else QTextToSpeech()
            # 设置默认值
            self._tts.setRate(0.0)
            self._tts.setPitch(0.0)
            self._tts.setVolume(1.0)
            self._tts.stateChanged.connect(self._on_tts_state_changed)
            # 填充声音下拉框
            self.cmb_tts_voice.blockSignals(True)
            self.cmb_tts_voice.clear()
            voices = self._tts.availableVoices()
            auto_idx = 0
            for i, v in enumerate(voices):
                self.cmb_tts_voice.addItem(v.name(), v)
                name = v.name().lower()
                if any(k in name for k in ("xiaoxiao", "xiaoyi", "yunxi", "huihui", "yaoyao", "kangkang")):
                    auto_idx = i
            if voices:
                self.cmb_tts_voice.setCurrentIndex(auto_idx)
                self._tts.setVoice(voices[auto_idx])
            self.cmb_tts_voice.blockSignals(False)
            # 同步语速滑块
            self.sld_tts_rate.blockSignals(True)
            self.sld_tts_rate.setValue(int(self._tts.rate() * 10))
            self.lbl_tts_rate.setText(f"{self._tts.rate():+.1f}")
            self.sld_tts_rate.blockSignals(False)
        return self._tts

    def _on_tts_play(self) -> None:
        """开始/恢复朗读."""
        tts = self._get_tts()
        if tts is None:
            return
        from PySide6.QtTextToSpeech import QTextToSpeech as _TTS
        state = tts.state()
        # 暂停状态 → 继续
        if state == _TTS.State.Paused:
            tts.resume()
            self._tts_paused = False
            self.btn_tts_play.setText("▶ 朗读中…")
            self.btn_tts_play.setEnabled(False)
            self.btn_tts_pause.setEnabled(True)
            self.btn_tts_stop.setEnabled(True)
            self.lbl_tts_status.setText("▶ 朗读中")
            return
        # 取正文内容
        text = self.editor.toPlainText().strip()
        if not text:
            self.lbl_tts_status.setText("⚠ 无正文可朗读")
            return
        tts.say(text)
        self._tts_paused = False
        self.btn_tts_play.setText("▶ 朗读中…")
        self.btn_tts_play.setEnabled(False)
        self.btn_tts_pause.setEnabled(True)
        self.btn_tts_stop.setEnabled(True)
        self.lbl_tts_status.setText("▶ 朗读中")

    def _on_tts_pause(self) -> None:
        """暂停/继续 切换."""
        tts = self._get_tts()
        if tts is None:
            return
        from PySide6.QtTextToSpeech import QTextToSpeech as _TTS
        if tts.state() == _TTS.State.Speaking:
            tts.pause()
            self._tts_paused = True
            self.btn_tts_pause.setText("▶ 继续")
            self.btn_tts_play.setText("▶ 继续")
            self.btn_tts_play.setEnabled(True)
            self.lbl_tts_status.setText("⏸ 已暂停")
        elif tts.state() == _TTS.State.Paused:
            tts.resume()
            self._tts_paused = False
            self.btn_tts_pause.setText("⏸ 暂停")
            self.btn_tts_play.setText("▶ 朗读中…")
            self.btn_tts_play.setEnabled(False)
            self.lbl_tts_status.setText("▶ 朗读中")

    def _on_tts_stop(self) -> None:
        """停止朗读."""
        tts = self._get_tts()
        if tts is None:
            return
        tts.stop()
        self._tts_paused = False
        self._reset_tts_buttons()
        self.lbl_tts_status.setText("⏹ 已停止")

    def _on_tts_state_changed(self, state) -> None:
        """TTS 状态变化回调."""
        from PySide6.QtTextToSpeech import QTextToSpeech as _TTS
        if state == _TTS.State.Ready:
            self._reset_tts_buttons()
            if not self._tts_paused:
                self.lbl_tts_status.setText("✅ 朗读完毕")
        elif state == _TTS.State.Speaking:
            self.btn_tts_play.setEnabled(False)
            self.btn_tts_pause.setEnabled(True)
            self.btn_tts_stop.setEnabled(True)

    def _reset_tts_buttons(self) -> None:
        """复位 TTS 按钮到初始可播放状态."""
        has_chapter = self.current_chapter_id is not None
        self.btn_tts_play.setText("▶ 开始朗读")
        self.btn_tts_play.setEnabled(has_chapter and _HAS_TTS)
        self.btn_tts_pause.setText("⏸ 暂停")
        self.btn_tts_pause.setEnabled(False)
        self.btn_tts_stop.setEnabled(False)

    def _on_tts_voice_changed(self, idx: int) -> None:
        """内联声音下拉切换."""
        tts = self._get_tts()
        if tts is None or idx < 0:
            return
        voice = self.cmb_tts_voice.itemData(idx)
        if voice:
            tts.setVoice(voice)

    def _on_tts_rate_changed(self, val: int) -> None:
        """内联语速滑块变化."""
        rate = val / 10.0
        self.lbl_tts_rate.setText(f"{rate:+.1f}")
        tts = self._get_tts()
        if tts:
            tts.setRate(rate)
        self.accept()
