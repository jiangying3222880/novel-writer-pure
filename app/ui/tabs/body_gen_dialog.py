"""
H1 AI 多版本正文生成 UI (重构版 v2).

核心设计: 3 条并行的 7 步写作流，每条线使用不同的风格指纹变体.
  - 第 1 轮: 3 版本风格差异大 (spread=±4), 让用户感受截然不同的文字风格
  - 第 2+ 轮: 基于用户选定的版本, 缩小差异 (spread 递减), 逐渐收敛
  - 最终: 风格稳定在 ±1 的波动区间 (不固定死, 保留创作弹性)

用户选择后，将选定版本写入编辑器，并更新项目风格指纹.
"""
from __future__ import annotations
import logging
import os
from typing import Optional

from PySide6.QtCore import Qt, QObject, QThread, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QLabel,
    QGroupBox,
    QProgressBar,
    QDialog,
    QFrame,
)

from app.services import writing_engine
from app.services.style_fingerprint import get_author_fp
from app.services.style_variant import (
    StyleVariant,
    generate_variants,
    next_spread,
    format_variant_summary,
    INITIAL_SPREAD,
)
from app.ui.widgets import Dialogs

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# Worker: 单个版本的 7 步生成 (带风格指纹注入)
# --------------------------------------------------------------------- #

class SingleVersionWorker(QObject):
    """单个版本 (A/B/C) 的 7 步生成 worker, 注入风格指纹变体."""

    step = Signal(int, str)
    chunk = Signal(str)
    done = Signal(dict)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        project_id: str,
        chapter_id: str,
        version: str,
        style_variant: StyleVariant,
        use_ai: bool = True,
    ) -> None:
        super().__init__()
        self.project_id = project_id
        self.chapter_id = chapter_id
        self.version = version
        self.style_variant = style_variant
        self.use_ai = use_ai
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            # 检查 API key 是否配置
            from app.services import app_setting_service
            p = app_setting_service.get_active()
            if self.use_ai and not p:
                self.error.emit("未配置 active provider，请在「设置 - 模型」配置 API key")
                return

            engine = writing_engine.get_engine()

            # 构建增强 system prompt: 基础 + 风格指纹变体
            base_system = writing_engine.WRITER_SYSTEM
            style_block = self.style_variant.to_prompt_block()
            enhanced_system = base_system + "\n\n" + style_block

            result = engine.run(
                self.project_id,
                self.chapter_id,
                on_step=lambda s, lbl: self.step.emit(s, lbl),
                on_chunk=lambda c: self.chunk.emit(c),
                should_cancel=lambda: self._cancelled,
                use_ai=self.use_ai,
                system_prompt_override=enhanced_system,
            )

            if result.ok:
                self.done.emit({
                    "version": self.version,
                    "content": result.ctx.content,
                    "content_chars": len(result.ctx.content),
                    "critic_score": result.ctx.critic.score if result.ctx.critic else 0,
                    "cost_usd": result.ctx.cost_usd,
                    "duration_ms": result.ctx.duration_ms,
                    "style": self.style_variant.to_dict(),
                })
            else:
                self.error.emit(
                    f"[版本 {self.version}] Step {result.error_step}: {result.error}"
                )
        except Exception as e:
            log.exception(f"[Worker {self.version}] failed")
            self.error.emit(f"[版本 {self.version}] {type(e).__name__}: {e}")
        finally:
            self.finished.emit()


# --------------------------------------------------------------------- #
# Worker: 3 版本并行生成管理器
# --------------------------------------------------------------------- #

class MultiVersionWorker(QObject):
    """3 版本并行生成管理器."""

    version_step = Signal(str, int, str)
    version_chunk = Signal(str, str)
    version_done = Signal(str, dict)
    version_error = Signal(str, str)
    all_finished = Signal()
    progress = Signal(str)

    def __init__(
        self,
        project_id: str,
        chapter_id: str,
        variants: list[StyleVariant],
        use_ai: bool = True,
    ) -> None:
        super().__init__()
        self.project_id = project_id
        self.chapter_id = chapter_id
        self.variants = variants
        self.use_ai = use_ai
        self.workers: dict[str, SingleVersionWorker] = {}
        self.threads: dict[str, QThread] = {}
        self._finished_count = 0

    def start(self) -> None:
        for v in self.variants:
            worker = SingleVersionWorker(
                self.project_id, self.chapter_id, v.label, v, self.use_ai,
            )
            thread = QThread()
            worker.moveToThread(thread)
            thread.started.connect(worker.run)

            worker.step.connect(lambda s, l, ver=v.label: self.version_step.emit(ver, s, l))
            worker.chunk.connect(lambda c, ver=v.label: self.version_chunk.emit(ver, c))
            worker.done.connect(lambda r, ver=v.label: self.version_done.emit(ver, r))
            worker.error.connect(lambda e, ver=v.label: self.version_error.emit(ver, e))
            worker.finished.connect(thread.quit)
            worker.finished.connect(self._on_worker_finished)

            thread.finished.connect(thread.deleteLater)
            worker.finished.connect(worker.deleteLater)

            self.workers[v.label] = worker
            self.threads[v.label] = thread
            thread.start()
            self.progress.emit(f"🚀 版本 {v.label} 开始生成…")

    def _on_worker_finished(self) -> None:
        self._finished_count += 1
        if self._finished_count >= 3:
            self.all_finished.emit()

    def cancel_all(self) -> None:
        for w in self.workers.values():
            w.cancel()


# --------------------------------------------------------------------- #
# 主体: BodyGenDialog
# --------------------------------------------------------------------- #

_VERSION_COLORS = {
    "A": "#16a34a",  # green
    "B": "#2563eb",  # blue
    "C": "#d97706",  # amber
}

_VERSION_DESCS = {
    "A": "版本 A",
    "B": "版本 B",
    "C": "版本 C",
}


class BodyGenDialog(QDialog):
    """多版本正文生成对话框 — 支持迭代收敛."""

    def __init__(
        self,
        project: dict,
        chapter_id: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.project_id = project["id"]
        self.chapter_id = chapter_id

        # 迭代状态
        self._round = 0
        self._spread = INITIAL_SPREAD
        self._selected_label: Optional[str] = None  # 上一轮用户选定的版本

        # 结果
        self.results: dict[str, dict] = {}
        self.selected_version: Optional[str] = None

        self.setWindowTitle(f"多版本正文生成 — {project.get('name', '')}")
        self.resize(900, 600)
        self._build_ui()

    # ---- UI ---- #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # 顶部: 轮次 + 说明
        self.round_label = QLabel("第 1 轮 — 风格差异最大 (spread=±4)")
        self.round_label.setObjectName("roundLabel")
        from app.ui.theme import text_warn
        self.round_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {text_warn()};")
        outer.addWidget(self.round_label)

        info = QLabel(
            "💡 3 条并行的 7 步写作流程，每条线使用不同的风格指纹变体。\n"
            "  第 1 轮差异最大，之后每轮基于你的选择逐渐收敛。\n"
            "  选定一版后可点「再生成一轮」继续微调，或点「关闭」确认。"
        )
        info.setWordWrap(True)
        info.setObjectName("infoLabel")
        outer.addWidget(info)

        # 风格指纹摘要
        self.fp_summary = QLabel("")
        self.fp_summary.setWordWrap(True)
        from app.ui.theme import text_muted
        self.fp_summary.setStyleSheet(f"color: {text_muted()}; font-size: 11px; font-family: monospace;")
        self.fp_summary.setVisible(False)
        outer.addWidget(self.fp_summary)

        # 状态条
        self.status_label = QLabel("就绪 — 点击「开始生成」启动 3 条并行写作流")
        outer.addWidget(self.status_label)

        # 3 列正文 (A / B / C)
        cols = QHBoxLayout()
        self.edits: dict[str, QPlainTextEdit] = {}
        self.progress_bars: dict[str, QProgressBar] = {}
        self.step_labels: dict[str, QLabel] = {}
        self.titles: dict[str, QLabel] = {}
        self.fp_labels: dict[str, QLabel] = {}
        self._select_buttons: dict[str, QPushButton] = {}

        for ver in ("A", "B", "C"):
            color = _VERSION_COLORS[ver]
            box = QGroupBox(_VERSION_DESCS[ver])
            v = QVBoxLayout(box)

            # 标题
            t = QLabel("(未开始)")
            t.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 13px;")
            v.addWidget(t)

            # 风格指纹标签
            fp = QLabel("")
            from app.ui.theme import text_muted
            fp.setStyleSheet(f"color: {text_muted()}; font-size: 10px; font-family: monospace;")
            fp.setVisible(False)
            v.addWidget(fp)

            # 进度
            pb = QProgressBar()
            pb.setRange(0, 7)
            pb.setValue(0)
            pb.setFormat("%v / 7")
            pb.setVisible(False)
            v.addWidget(pb)

            sl = QLabel("")
            sl = QLabel("")
            from app.ui.theme import text_chip
            sl.setStyleSheet(f"color: {text_chip()}; font-size: 11px;")
            sl.setVisible(False)
            v.addWidget(sl)

            # 编辑器
            e = QPlainTextEdit()
            e.setReadOnly(True)
            e.setPlaceholderText(
                f"版本 {ver} 正文将在这里流式显示…\n\n"
                "7 步流程：记忆拼装 → 反 AI 味 → 压力决策 → 知识检索 → 写作 → 评估 → 落库"
            )
            v.addWidget(e, 1)

            # 选此版按钮
            btn = QPushButton(f"✅ 选 {ver} 版")
            btn.clicked.connect(lambda _, v=ver: self._on_select_version(v))
            btn.setEnabled(False)
            v.addWidget(btn)

            cols.addWidget(box, 1)
            self.edits[ver] = e
            self.progress_bars[ver] = pb
            self.step_labels[ver] = sl
            self.titles[ver] = t
            self.fp_labels[ver] = fp
            self._select_buttons[ver] = btn

        outer.addLayout(cols, 1)

        # 底部按钮
        bottom = QHBoxLayout()
        self.btn_start = QPushButton("🚀 开始生成 (3 线并行)")
        self.btn_start.clicked.connect(self._on_start_generate)
        bottom.addWidget(self.btn_start)

        self.btn_rerun = QPushButton(" 再生成一轮 (收敛)")
        self.btn_rerun.clicked.connect(self._on_rerun)
        self.btn_rerun.setEnabled(False)
        self.btn_rerun.setVisible(False)
        bottom.addWidget(self.btn_rerun)

        self.btn_cancel = QPushButton("停止")
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_cancel.setEnabled(False)
        bottom.addWidget(self.btn_cancel)

        bottom.addStretch(1)

        self.btn_close = QPushButton("关闭 (确认选择)")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.setEnabled(False)
        bottom.addWidget(self.btn_close)

        outer.addLayout(bottom)

    # ---- 生成逻辑 ---- #

    def _generate_variants(self) -> list[StyleVariant]:
        """基于当前迭代状态生成 3 个风格变体 (L1 作者指纹 6 维)."""
        base_fp = get_author_fp()
        base_dict = base_fp.to_dict()
        return generate_variants(
            base_dict,
            spread=self._spread,
            selected_label=self._selected_label,
        )

    def _update_fp_summary(self, variants: list[StyleVariant]) -> None:
        """更新风格指纹摘要显示."""
        text = format_variant_summary(variants, self._round)
        self.fp_summary.setText(text)
        self.fp_summary.setVisible(True)

    def _on_start_generate(self) -> None:
        """启动第 1 轮生成."""
        self._round = 1
        self._spread = INITIAL_SPREAD
        self._selected_label = None
        self._run_round()

    def _on_rerun(self) -> None:
        """再生成一轮 (收敛)."""
        if not self._selected_label:
            Dialogs.warning("提示", "请先选定一个版本作为锚点", parent=self)
            return
        self._round += 1
        self._spread = next_spread(self._spread)
        self._run_round()

    def _run_round(self) -> None:
        """执行一轮 3 版本并行生成."""
        variants = self._generate_variants()
        self._update_fp_summary(variants)

        # 更新轮次标签
        spread_desc = f"spread=±{self._spread}"
        if self._selected_label:
            self.round_label.setText(
                f"第 {self._round} 轮 — 基于版本 {self._selected_label} 收敛 ({spread_desc})"
            )
        else:
            self.round_label.setText(f"第 {self._round} 轮 — 风格差异最大 ({spread_desc})")

        # 清空 UI
        for v in ("A", "B", "C"):
            self.edits[v].clear()
            self.titles[v].setText(f"版本 {v} (生成中…)")
            self.fp_labels[v].setVisible(False)
            self.progress_bars[v].setVisible(True)
            self.progress_bars[v].setValue(0)
            self.step_labels[v].setVisible(True)
            self.step_labels[v].setText(" 准备中…")
            self._select_buttons[v].setEnabled(False)
            self._select_buttons[v].setText(f"✅ 选 {v} 版")

        self.btn_start.setEnabled(False)
        self.btn_rerun.setEnabled(False)
        self.btn_rerun.setVisible(False)
        self.btn_cancel.setEnabled(True)
        self.btn_close.setEnabled(False)
        self.results = {}

        use_ai = os.environ.get("NW_AI_MOCK", "0") != "1"

        self._worker = MultiVersionWorker(
            self.project_id, self.chapter_id, variants, use_ai,
        )
        self._worker.version_step.connect(self._on_version_step)
        self._worker.version_chunk.connect(self._on_version_chunk)
        self._worker.version_done.connect(self._on_version_done)
        self._worker.version_error.connect(self._on_version_error)
        self._worker.all_finished.connect(self._on_all_finished)
        self._worker.progress.connect(self.status_label.setText)

        self._worker.start()
        self.status_label.setText(" 3 条并行写作流已启动…")

    # ---- 信号处理 ---- #

    def _on_version_step(self, version: str, step: int, label: str) -> None:
        self.progress_bars[version].setValue(step)
        self.step_labels[version].setText(f"Step {step}/7  {label}")

    def _on_version_chunk(self, version: str, chunk: str) -> None:
        edit = self.edits[version]
        edit.moveCursor(edit.textCursor().MoveOperation.End)
        edit.insertPlainText(chunk)
        edit.repaint()

    def _on_version_done(self, version: str, result: dict) -> None:
        self.results[version] = result
        chars = result.get("content_chars", 0)
        score = result.get("critic_score", 0)
        dur = result.get("duration_ms", 0)
        self.titles[version].setText(
            f"版本 {version} ✅ | {chars}字 | {score}分 | ⏱{dur}ms"
        )
        # 显示风格指纹 (L1 作者指纹 6 维)
        style = result.get("style", {})
        fp_parts = []
        for d, label in [("sentence_rhythm", "节奏"), ("dialogue_density", "对话"),
                         ("description_style", "描写"), ("emotion_expression", "情绪"),
                         ("paragraph_density", "段落"), ("language_level", "语言")]:
            fp_parts.append(f"{label}{style.get(d, '?')}")
        fp_text = " ".join(fp_parts)
        self.fp_labels[version].setText(fp_text)
        self.fp_labels[version].setVisible(True)

        self.progress_bars[version].setValue(7)
        self.step_labels[version].setText("Step 7/7  落库 ✓")
        self._select_buttons[version].setEnabled(True)
        self.status_label.setText(f"✅ 版本 {version} 已完成 — 等待其他版本…")
        
        # 确保编辑器显示完整内容 (防止流式输出未触发的情况)
        edit = self.edits[version]
        content = result.get("content", "")
        if content and not edit.toPlainText().strip():
            edit.setPlainText(content)

    def _on_version_error(self, version: str, error: str) -> None:
        self.titles[version].setText(f"版本 {version}  失败")
        self.step_labels[version].setText(f"错误: {error}")
        self.status_label.setText(f"❌ 版本 {version} 失败: {error}")

    def _on_all_finished(self) -> None:
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)
        # 如果已选定过版本，显示「再生成一轮」
        if self._selected_label:
            self.btn_rerun.setEnabled(True)
            self.btn_rerun.setVisible(True)
            self.status_label.setText(
                f"✅ 第 {self._round} 轮生成完毕 — 可继续收敛或确认选择"
            )
        else:
            self.status_label.setText(
                f"✅ 第 {self._round} 轮生成完毕 — 请选择最符合你风格的一版"
            )

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel_all()
            self.status_label.setText(" 取消中…")
            self.btn_cancel.setEnabled(False)

    def _on_select_version(self, version: str) -> None:
        self.selected_version = version
        self._selected_label = version

        for v in ("A", "B", "C"):
            edit = self.edits[v]
            btn = self._select_buttons[v]
            if v == version:
                from app.ui.theme import border_success
                edit.setStyleSheet(f"border: 3px solid {border_success()};")
                btn.setText(f"✅ 已选 {v} 版 (锚点)")
                btn.setEnabled(False)
            else:
                edit.setStyleSheet("")
                btn.setText(f"切换为 {v} 版")
                btn.setEnabled(True)

        result = self.results.get(version, {})
        self.status_label.setText(
            f"✅ 已选定版本 {version} 作为锚点 | "
            f"{result.get('content_chars', 0)}字 | "
            f"📊{result.get('critic_score', 0)}分 — "
            f"可点「再生成一轮」继续收敛，或「关闭」确认"
        )
        # 启用「再生成一轮」
        self.btn_rerun.setEnabled(True)
        self.btn_rerun.setVisible(True)

    # ---- 公开 API ---- #

    def get_selected_body_text(self) -> str:
        if not self.selected_version or not self.results:
            return ""
        return self.results.get(self.selected_version, {}).get("content", "")

    def get_selected_style(self) -> Optional[dict]:
        """获取选定版本的风格指纹 (用于更新项目风格指纹)."""
        if not self.selected_version or not self.results:
            return None
        return self.results.get(self.selected_version, {}).get("style")
