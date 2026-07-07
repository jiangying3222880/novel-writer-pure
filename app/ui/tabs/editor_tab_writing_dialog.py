"""
WritingFlowDialog — 「开始写作」对话框 (V4.0-P4-新).

设计:
  - 一个 QDialog, 内嵌 GenerateTab (复用 7 步流式生成 UI)
  - 自动选好传入的 book/chapter (set_focus_chapter)
  - 底部多一条 [📝 写入章节] 按钮: 把 GenerateTab.output 落到 chapter.draft
  - written_back(chapter_id, text) 信号通知 EditorTab 同步刷新
  - V4.0-P4-新: 顶部 7 步「流程概览」卡, 显式展示每步调用的工作流组件
    (memory_manager.assemble_for_writing / anti_ai / subtext /
     prompt_assembler / writer_agent / critic_agent / 落库),
    跑的时候对应行高亮, 让用户看到自己的 workflow 真的在跑.
"""
from __future__ import annotations
import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QTextBrowser,
)
from PySide6.QtGui import QFont

from app.ui.widgets import Dialogs
from app.services import chapter_service, ServiceError

log = logging.getLogger(__name__)


# V4.0-P4-新: 7 步流程概览
#   每条 = (步骤名, 调用的 workflow 组件, 简短说明)
WORKFLOW_STEPS: list[tuple[str, str, str]] = [
    ("Step 1 — L1-L4 拼装",  "memory_manager.assemble_for_writing",  "项目上下文 + 改稿信号 L1-L4 + 压力区"),
    ("Step 2 — 6 大去 AI 味", "anti_ai.format_report",                "检测段落「AI 味」(套话/链词/假共鸣/滥形容/解释癖/装饰对仗)"),
    ("Step 3 — 压力决策",     "pressure_zone + can_open_hook",        "L4 判断当前压力 + 是否能开新钩子"),
    ("Step 4 — RAG 检索",     "_retrieve_for_chapter",                "从 setting_service 拉相关片段 (世界/角色/伏笔)"),
    ("Step 5 — 写作",         "subtext(6 问) + prompt_assembler + writer_agent",
                              "潜文本卡注入 → 项目基础信息 + 体裁/字数 → 调 LLM 流式输出"),
    ("Step 6 — 评估",         "critic_agent",                         "6 维: plot/character/writing/rhythm/style/foreshadow"),
    ("Step 7 — 落库",         "chapter_service.create_draft + change_log + set_current_draft",
                              "写 draft + 记改稿日志 + 设为 current_draft"),
]


class WritingFlowDialog(QDialog):
    """「开始写作」7 步 AI 写作流程对话框."""

    # 写入章节后发出 (chapter_id, new_text)
    written_back = Signal(str, str)

    def __init__(self, *, project: dict, project_id: str, book_id: str,
                 chapter_id: str, chapter_title: str,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"✨ 开始写作 — {chapter_title}")
        self.setMinimumSize(960, 760)
        self.setObjectName("writingFlowDialog")
        from app.ui.theme import DARK_QSS
        self.setStyleSheet(DARK_QSS)

        self._project = project
        self._project_id = project_id
        self._book_id = book_id
        self._chapter_id = chapter_id
        self._chapter_title = chapter_title
        # V4.0-P4-新: 每步的状态 ("pending" / "running" / "done")
        self._step_states: list[str] = ["pending"] * 7
        # 每步对应的 QLabel (流程概览里的「状态」那一列)
        self._step_state_labels: list[QLabel] = []
        # 每步对应的整行 Frame
        self._step_rows: list[QFrame] = []
        # P3: 每步对应的描述 QLabel (用于回填 Step 1-4 真实数据)
        self._step_desc_labels: list[QLabel] = []
        # P3: 原始静态描述 (作为 fallback)
        self._step_desc_default: list[str] = []

        self._build_ui()
        self._init_generate_tab()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        # 顶部标题
        title = QLabel(
            f"✨ 写作流程  —  {self._chapter_title}  "
            f"<span style='color:#9aa0a6;font-size:12px;'>"
            f"AI 自动 7 步: 大纲注入 → 风格 → 选段 → 段落重写 → 评估 → 修补 → 收口</span>"
        )
        title.setObjectName("writingFlowTitle")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        title.setWordWrap(True)
        outer.addWidget(title)

        # 4 步上手说明
        tips = QLabel(
            "📖 上手:\n"
            "  ① 左侧已自动选好当前卷/章节, 可手动切换\n"
            "  ② 点「✨ 生成 (7 步)」, 流式输出章节内容\n"
            "  ③ 生成完不满意 → 重新生成 (覆盖上一次的输出)\n"
            "  ④ 点「📝 写入章节」, 把 output 落到 chapter.draft"
        )
        tips.setObjectName("writingFlowTips")
        tips.setStyleSheet(
            "color: #9aa0a6; font-size: 11px; padding: 8px 10px;"
            "background: rgba(99,102,241,0.08); border-radius: 4px;"
        )
        tips.setWordWrap(True)
        outer.addWidget(tips)

        # V4.0-P4-新: 7 步流程概览卡 (替代原来 4 步上手 tips 的一部分)
        #   - 用户能看到自己的 workflow 真的被调用
        #   - 跑的时候, 对应行高亮
        self._build_workflow_overview(outer)

        # 内嵌 GenerateTab
        from app.ui.tabs.generate_tab import GenerateTab
        self._gen_tab = GenerateTab()
        outer.addWidget(self._gen_tab, 1)

        # 底部按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.lbl_word_count = QLabel("字数: 0")
        self.lbl_word_count.setObjectName("writingFlowWordCount")
        self.lbl_word_count.setStyleSheet(
            "color: #9aa0a6; font-size: 11px; padding: 4px 8px;"
        )
        btn_row.addWidget(self.lbl_word_count)

        btn_row.addStretch(1)

        self.btn_write_back = QPushButton("📝 写入章节")
        self.btn_write_back.setObjectName("btnWriteBack")
        self.btn_write_back.setToolTip("把右侧生成的内容落到 chapter.draft, 同步刷新章节管理")
        self.btn_write_back.clicked.connect(self._on_write_back)
        self.btn_write_back.setEnabled(False)  # 等生成完启用
        btn_row.addWidget(self.btn_write_back)

        btn_close = QPushButton("关闭")
        btn_close.setObjectName("btnWritingClose")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)

        outer.addLayout(btn_row)

    def _build_workflow_overview(self, outer) -> None:
        """V4.0-P4-新: 7 步流程概览卡, 每行: 步骤名 / 调用组件 / 简短说明 / 状态."""
        card = QFrame()
        card.setObjectName("workflowOverviewCard")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet(
            "QFrame#workflowOverviewCard {"
            "  background: rgba(99,102,241,0.06);"
            "  border: 1px solid rgba(99,102,241,0.20);"
            "  border-radius: 6px;"
            "}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(4)

        # 标题
        h = QLabel("📋 流程概览 — 调用的 workflow 组件 (点击可折叠)")
        from app.ui.theme import text_muted
        h.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {text_muted()};")
        card_layout.addWidget(h)

        # 7 行
        for i, (step_name, component, desc) in enumerate(WORKFLOW_STEPS):
            row = QFrame()
            row.setObjectName(f"workflowRow_{i}")
            row.setStyleSheet(self._row_style("pending"))
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 4, 8, 4)
            row_layout.setSpacing(8)

            lbl_step = QLabel(step_name)
            lbl_step.setStyleSheet("font-weight: 600; font-size: 11px; min-width: 150px;")
            row_layout.addWidget(lbl_step)

            lbl_comp = QLabel(f"<code>{component}</code>")
            lbl_comp.setStyleSheet(
                "color: #9aa0a6; font-size: 11px; min-width: 220px;"
                "font-family: 'Consolas', monospace;"
            )
            lbl_comp.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row_layout.addWidget(lbl_comp)

            lbl_desc = QLabel(desc)
            lbl_desc.setStyleSheet(
                "color: #9aa0a6; font-size: 11px;"
            )
            lbl_desc.setWordWrap(True)
            row_layout.addWidget(lbl_desc, 1)

            lbl_state = QLabel("⏳")
            lbl_state.setObjectName(f"workflowState_{i}")
            lbl_state.setStyleSheet("font-size: 14px; min-width: 24px;")
            lbl_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row_layout.addWidget(lbl_state)
            self._step_state_labels.append(lbl_state)
            self._step_rows.append(row)
            # P3: 跟踪描述 label 和默认描述
            self._step_desc_labels.append(lbl_desc)
            self._step_desc_default.append(desc)

            card_layout.addWidget(row)

        outer.addWidget(card)

    @staticmethod
    def _row_style(state: str) -> str:
        """根据状态返回整行背景色."""
        if state == "running":
            return ("QFrame#workflowRow_X {"
                    "  background: rgba(245, 158, 11, 0.18);"
                    "  border-radius: 4px;"
                    "}").replace("X", "PLACEHOLDER")
        if state == "done":
            return ("QFrame#workflowRow_X {"
                    "  background: rgba(34, 197, 94, 0.14);"
                    "  border-radius: 4px;"
                    "}").replace("X", "PLACEHOLDER")
        return ("QFrame#workflowRow_X {"
                "  background: transparent;"
                "  border-radius: 4px;"
                "}").replace("X", "PLACEHOLDER")

    def _set_step_state(self, step_idx: int, state: str) -> None:
        """更新 step_idx (0-6) 的状态 + 行样式."""
        if not (0 <= step_idx < 7):
            return
        self._step_states[step_idx] = state
        # 状态 emoji
        emoji = {"pending": "⏳", "running": "🔄", "done": "✅"}.get(state, "⏳")
        self._step_state_labels[step_idx].setText(emoji)
        # 行样式 (因为 objectName 含数字, 用 setProperty + dynamic style)
        row = self._step_rows[step_idx]
        bg = {
            "running": "rgba(245, 158, 11, 0.18)",
            "done":    "rgba(34, 197, 94, 0.14)",
            "pending": "transparent",
        }.get(state, "transparent")
        row.setStyleSheet(
            f"QFrame#{row.objectName()} {{"
            f"  background: {bg};"
            f"  border-radius: 4px;"
            f"}}"
        )

    def _init_generate_tab(self) -> None:
        """初始化 GenerateTab: 设置项目, 锁定到传入的 book/chapter, 钩 step 进度."""
        self._gen_tab.set_project(self._project)
        if hasattr(self._gen_tab, "set_focus_chapter"):
            self._gen_tab.set_focus_chapter(self._book_id, self._chapter_id)

        # 监听 editor 变化, 更新字数 + 写入按钮
        self._gen_tab.editor.textChanged.connect(self._on_output_changed)

        # P3: 监听 step_with_meta, 回填概览卡描述文字
        if hasattr(self._gen_tab, "step_with_meta"):
            self._gen_tab.step_with_meta.connect(self._on_step_with_meta)

        # V4.0-P4-新: 钩 GenerateTab._on_step 看不到的 worker.step signal — 不能
        # 重新连接 (会被原 handler 消耗), 用 timer 轮询 GenerateTab.step_progress
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(300)
        self._poll_timer.timeout.connect(self._poll_step_progress)
        self._poll_timer.start()

    def _poll_step_progress(self) -> None:
        """V4.0-P4-新: 轮询 GenerateTab.step_progress.value() 同步到概览卡.

        GenerateTab 的 worker.step signal 被它的 _on_step 接收, 我们这里拿不到
        直接推送, 所以用「步进差值」同步:
          - step_progress.value() = 0: 还没开始, 全 pending
          - step_progress.value() = v (1-7): 1..v-1 已 done, 第 v 步 running
          - step_progress.value() = 7: 全部 done (生成完)
        """
        v = self._gen_tab.step_progress.value()
        for i in range(7):
            idx = i + 1  # step_progress 用 1-7
            if v >= 7 or idx < v:
                # 全部已完 / 该步之前: done
                if self._step_states[i] != "done":
                    self._set_step_state(i, "done")
            elif idx == v and v > 0:
                # 当前正在跑
                if self._step_states[i] not in ("done", "running"):
                    self._set_step_state(i, "running")
                elif self._step_states[i] == "running" and v >= 7:
                    # 兜底: v=7 时 (全部完成), 把 running 收尾成 done
                    self._set_step_state(i, "done")

    def _on_step_with_meta(self, step: int, label: str, meta: dict) -> None:
        """P3: 每步真实回填 — 更新概览卡第 step 行的描述文字."""
        idx = step - 1  # 0-based
        if not (0 <= idx < 7):
            return
        # 从 meta 提取有用信息回填到 desc label
        desc_parts: list[str] = []
        if meta.get("tokens_in"):
            desc_parts.append(f"输入 {meta['tokens_in']:,} token")
        if meta.get("tokens_out"):
            desc_parts.append(f"输出 {meta['tokens_out']:,} token")
        if meta.get("chars"):
            desc_parts.append(f"{meta['chars']:,} 字")
        if meta.get("rag_hits") is not None:
            desc_parts.append(f"RAG {meta['rag_hits']} 条")
        if meta.get("pressure_zone"):
            desc_parts.append(f"压力区: {meta['pressure_zone']}")
        if meta.get("memory_chars"):
            desc_parts.append(f"记忆 {meta['memory_chars']:,} 字")
        new_desc = ", ".join(desc_parts) if desc_parts else self._step_desc_default[idx]
        self._step_desc_labels[idx].setText(new_desc)

    def _on_output_changed(self) -> None:
        text = self._gen_tab.editor.toPlainText()
        n = len(text.replace(" ", "").replace("\n", ""))
        self.lbl_word_count.setText(f"字数: {n:,}")
        self.btn_write_back.setEnabled(n > 0)

    def _on_write_back(self) -> None:
        """把 editor 落到 chapter.draft, 写回数据库 + 通知 EditorTab."""
        text = self._gen_tab.editor.toPlainText().strip()
        if not text:
            Dialogs.warning("写入章节", "生成内容为空, 先点「✨ 生成」", parent=self)
            return
        try:
            updated = chapter_service.update(self._chapter_id, draft=text)
        except ServiceError as e:
            Dialogs.warning("写入失败", str(e), parent=self)
            return
        except Exception as e:
            log.exception("write back failed")
            Dialogs.warning("写入失败", f"{type(e).__name__}: {e}", parent=self)
            return

        n = len(text.replace(" ", "").replace("\n", ""))
        self.written_back.emit(self._chapter_id, text)
        Dialogs.info(
            "已写入",
            f"已把 {n:,} 字符写入章节草稿\n"
            f"章节: {self._chapter_title}\n"
            f"chapter_id: {self._chapter_id}",
            parent=self,
        )
        self.accept()
