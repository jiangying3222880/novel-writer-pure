"""
ConversationWizardDialog (V4.0-P4-新) — 3 步引导式对话, 从灵感 → 完整设定 → 创建项目.

复用 app.services.conversation_service (run_step1 / run_step2).

流程:
  Step 1: 用户填灵感 (一段文字) → AI 生成 3-5 个追问
  Step 2: 用户回答追问 → AI 生成完整小说设定 (Markdown)
  Step 3: 展示 AI 生成的设定 (可编辑), 确认后 → 解析书名/项目名/题材 → 创建项目

UI 形态: QStackedWidget, 每步一页, 上一步/下一步 按钮.
"""
from __future__ import annotations
import logging
import re
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QStackedWidget, QProgressBar, QFrame, QWidget,
)

from app.ui.widgets import Dialogs

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# 异步 step 调用 (LLM 可能慢, 不阻塞 UI)
# --------------------------------------------------------------------- #
class _StepWorker(QThread):
    ok = Signal(object)  # ConversationState
    fail = Signal(str)

    def __init__(self, fn, *args) -> None:
        super().__init__()
        self._fn = fn
        self._args = args

    def run(self) -> None:
        try:
            state = self._fn(*self._args)
            self.ok.emit(state)
        except Exception as e:
            log.exception("step worker failed")
            self.fail.emit(str(e))


# --------------------------------------------------------------------- #
# Dialog
# --------------------------------------------------------------------- #
class ConversationWizardDialog(QDialog):
    """3 步对话 → 创建项目.

    Usage:
        dlg = ConversationWizardDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            project_id = dlg.created_project_id  # 已在 dialog 内创建好
    """

    PAGE_INTRO = 0
    PAGE_STEP1_INPUT = 1   # 填灵感
    PAGE_STEP1_WAIT = 2    # 调 AI 拿追问
    PAGE_STEP2_INPUT = 3   # 回答追问
    PAGE_STEP2_WAIT = 4    # 调 AI 拿设定
    PAGE_STEP3_PREVIEW = 5  # 看生成设定, 确认创建
    PAGE_DONE = 6           # 创建成功

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("💬 通过对话创建项目")
        self.setModal(True)
        self.resize(720, 600)

        self._conv_id: Optional[str] = None
        self._worker: Optional[_StepWorker] = None
        self._created_pid: Optional[str] = None
        self._has_llm: bool = self._check_llm()

        self._build_ui()
        self._go_to(self.PAGE_STEP1_INPUT)  # 跳过欢迎页, 直接进填灵感

    @staticmethod
    def _check_llm() -> bool:
        """探测是否配置了可用的 LLM 模型。"""
        try:
            from app.services.router.real_client import create_real_client
            create_real_client()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        # 进度条 (1/3, 2/3, 3/3)
        self.progress = QProgressBar()
        self.progress.setRange(0, 3)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("步骤 %v / 3")
        outer.addWidget(self.progress)

        # step 描述
        self.lbl_step = QLabel("准备开始")
        self.lbl_step.setObjectName("wizardStep")
        self.lbl_step.setStyleSheet("font-size: 14px; font-weight: 600;")
        outer.addWidget(self.lbl_step)

        # mock 兜底提示 (仅无 LLM 时显示)
        self.lbl_mock_banner = QLabel(
            "⚠️  未配置 AI 模型 — 将使用内置模板回答（非 AI 生成）\n"
            "   请到 设置 → AI 模型 中配置模型以获得真实 AI 对话体验"
        )
        self.lbl_mock_banner.setObjectName("mockBanner")
        self.lbl_mock_banner.setWordWrap(True)
        self.lbl_mock_banner.setStyleSheet(
            "background: rgba(245, 158, 11, 0.12); color: #f59e0b; "
            "padding: 8px 12px; border-radius: 6px; font-size: 12px; "
            "border: 1px solid rgba(245, 158, 11, 0.25);"
        )
        self.lbl_mock_banner.setVisible(not self._has_llm)
        outer.addWidget(self.lbl_mock_banner)

        # Stacked
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        # ===== Page: INTRO =====
        p_intro = QWidget()
        v = QVBoxLayout(p_intro)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(QLabel("🎉 欢迎使用对话式创建项目"))
        v.addWidget(QLabel(
            "接下来 AI 会用 3 步引导帮你从模糊灵感梳理出完整小说设定:\n"
            "  ① 你给一段灵感/想法\n"
            "  ② AI 反问你 3-5 个关键问题, 你回答\n"
            "  ③ AI 生成完整设定 (书名/简介/世界观/主角/大纲), 确认后自动建项目"
        ))
        v.addWidget(QLabel(
            "💡 提示: 如果没有配置 AI 模型, 系统会使用内置模板回答 (不影响流程)."
        ))
        v.addStretch(1)
        self.stack.addWidget(p_intro)

        # ===== Page: STEP1_INPUT =====
        p1 = QWidget()
        v = QVBoxLayout(p1)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel("第 1 步  ·  你的灵感 / 想法 (尽量具体):"))
        self.ed_inspiration = QPlainTextEdit()
        self.ed_inspiration.setPlaceholderText(
            "例: 一个程序员穿越到仙侠世界, 发现自己是废柴, 但有金手指系统, "
            "一路逆袭成为最强剑修, 同时揭露一个大阴谋..."
        )
        self.ed_inspiration.setMinimumHeight(280)
        v.addWidget(self.ed_inspiration, 1)
        self.stack.addWidget(p1)

        # ===== Page: STEP1_WAIT =====
        p1w = QWidget()
        v = QVBoxLayout(p1w)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_wait1_title = QLabel("🤖  AI 正在根据你的灵感想问题...")
        v.addWidget(self.lbl_wait1_title)
        self.lbl_wait1_hint = QLabel("(通常 5-15 秒)")
        v.addWidget(self.lbl_wait1_hint)
        v.addStretch(1)
        self.stack.addWidget(p1w)

        # ===== Page: STEP2_INPUT =====
        p2 = QWidget()
        v = QVBoxLayout(p2)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel("第 2 步  ·  AI 的追问, 请依次回答:"))
        self.lbl_questions = QLabel("(加载中...)")
        self.lbl_questions.setObjectName("questionsLabel")
        self.lbl_questions.setWordWrap(True)
        self.lbl_questions.setStyleSheet(
            "background: rgba(99, 102, 241, 0.08); padding: 10px; border-radius: 6px;"
        )
        v.addWidget(self.lbl_questions)
        v.addWidget(QLabel("✍️  你的回答 (可以每问一答, 也可以整体回答):"))
        self.ed_answers = QPlainTextEdit()
        self.ed_answers.setPlaceholderText(
            "例:\nQ1: 玄幻\nQ2: 主角是穿越者, 性格冷静, 目标回原世界\n..."
        )
        self.ed_answers.setMinimumHeight(200)
        v.addWidget(self.ed_answers, 1)
        self.stack.addWidget(p2)

        # ===== Page: STEP2_WAIT =====
        p2w = QWidget()
        v = QVBoxLayout(p2w)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_wait2_title = QLabel("🤖  AI 正在生成完整小说设定...")
        v.addWidget(self.lbl_wait2_title)
        self.lbl_wait2_hint = QLabel("(可能需要 15-30 秒)")
        v.addWidget(self.lbl_wait2_hint)
        v.addStretch(1)
        self.stack.addWidget(p2w)

        # ===== Page: STEP3_PREVIEW =====
        p3 = QWidget()
        v = QVBoxLayout(p3)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel("第 3 步  ·  AI 生成的设定 (可编辑, 确认后建项目):"))
        self.ed_setting = QPlainTextEdit()
        self.ed_setting.setMinimumHeight(320)
        v.addWidget(self.ed_setting, 1)
        self.stack.addWidget(p3)

        # ===== Page: DONE =====
        pd = QWidget()
        v = QVBoxLayout(pd)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(QLabel("✅  项目已创建!"))
        self.lbl_done_detail = QLabel(
            "世界观、角色、大纲等设定已全部同步。\n"
            "关闭对话框后可到小说设定页查看调整，满意后再到章节管理页开始写作。"
        )
        self.lbl_done_detail.setWordWrap(True)
        v.addWidget(self.lbl_done_detail)
        v.addStretch(1)
        self.stack.addWidget(pd)

        # ===== Bottom buttons =====
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        outer.addWidget(sep)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addStretch(1)
        self.btn_prev = QPushButton("← 上一步")
        self.btn_prev.clicked.connect(self._on_prev)
        btn_row.addWidget(self.btn_prev)
        self.btn_next = QPushButton("下一步 →")
        self.btn_next.setObjectName("btnWizardNext")
        self.btn_next.setDefault(True)
        self.btn_next.clicked.connect(self._on_next)
        btn_row.addWidget(self.btn_next)
        self.btn_finish = QPushButton("完成")
        self.btn_finish.setObjectName("btnWizardFinish")
        self.btn_finish.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_finish)
        outer.addLayout(btn_row)

    # ------------------------------------------------------------------
    # 状态切换
    # ------------------------------------------------------------------
    def _go_to(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        # 进度
        if page in (self.PAGE_INTRO,):
            self.progress.setValue(0)
            self.lbl_step.setText("准备开始")
            self.btn_prev.setVisible(False)
            self.btn_next.setVisible(True)
            self.btn_finish.setVisible(False)
        elif page in (self.PAGE_STEP1_INPUT, self.PAGE_STEP1_WAIT):
            self.progress.setValue(1)
            self.lbl_step.setText("第 1 步  ·  灵感")
            self.btn_prev.setVisible(False)  # 已无 INTRO, 不可回退
            self.btn_next.setVisible(page != self.PAGE_STEP1_WAIT)
            self.btn_finish.setVisible(False)
            if page == self.PAGE_STEP1_WAIT:
                self._update_wait_hints(1)
        elif page in (self.PAGE_STEP2_INPUT, self.PAGE_STEP2_WAIT):
            self.progress.setValue(2)
            self.lbl_step.setText("第 2 步  ·  追问")
            self.btn_prev.setVisible(page != self.PAGE_STEP2_WAIT)
            self.btn_next.setVisible(page != self.PAGE_STEP2_WAIT)
            self.btn_finish.setVisible(False)
            if page == self.PAGE_STEP2_WAIT:
                self._update_wait_hints(2)
        elif page == self.PAGE_STEP3_PREVIEW:
            self.progress.setValue(3)
            self.lbl_step.setText("第 3 步  ·  确认设定")
            self.btn_prev.setVisible(True)
            self.btn_next.setVisible(False)
            self.btn_finish.setVisible(False)
        elif page == self.PAGE_DONE:
            self.progress.setValue(3)
            self.lbl_step.setText("🎉 创建完成")
            self.btn_prev.setVisible(False)
            self.btn_next.setVisible(False)
            self.btn_finish.setVisible(True)
            self.btn_finish.setDefault(True)

    def _update_wait_hints(self, step: int) -> None:
        """根据 _has_llm 更新等待页提示文字。mock 模式提示模板, 真 AI 提示等待时间。"""
        if self._has_llm:
            hints = {1: "(通常 5-15 秒)", 2: "(可能需要 15-30 秒)"}
        else:
            hints = {1: "(使用模板生成, 1-2 秒...)", 2: "(使用模板生成, 1-2 秒...)"}
        if step == 1:
            self.lbl_wait1_hint.setText(hints[1])
        elif step == 2:
            self.lbl_wait2_hint.setText(hints[2])

    def _on_prev(self) -> None:
        cur = self.stack.currentIndex()
        if cur == self.PAGE_STEP1_INPUT:
            return  # 已无 INTRO 可回退, btn_prev 隐藏
        elif cur == self.PAGE_STEP2_INPUT:
            self._go_to(self.PAGE_STEP1_INPUT)
        elif cur == self.PAGE_STEP3_PREVIEW:
            # 回退到 Step 2 时重置 conversation 状态，否则 submit_step2 会因
            # 当前状态是 step3_done 而非 step1_done 而校验失败
            if self._conv_id:
                try:
                    from app.services import conversation_service
                    state = conversation_service.get_conversation(self._conv_id)
                    state.step = conversation_service.ConversationStep.STEP1_DONE
                except Exception:
                    pass
            self._go_to(self.PAGE_STEP2_INPUT)

    def _on_next(self) -> None:
        cur = self.stack.currentIndex()
        if cur == self.PAGE_INTRO:
            self._go_to(self.PAGE_STEP1_INPUT)
        elif cur == self.PAGE_STEP1_INPUT:
            # 校验 + 调 LLM
            inspiration = self.ed_inspiration.toPlainText().strip()
            if not inspiration:
                Dialogs.warning("需要灵感", "请先写一段你的灵感 / 想法", parent=self)
                return
            self._start_step1(inspiration)
        elif cur == self.PAGE_STEP2_INPUT:
            answers = self.ed_answers.toPlainText().strip()
            if not answers:
                Dialogs.warning("需要回答", "请先回答 AI 的追问", parent=self)
                return
            self._start_step2(answers)
        # step3 preview 的 "下一步" 改成 "创建项目" (text 变)

    # ------------------------------------------------------------------
    # 异步 step 调用
    # ------------------------------------------------------------------
    def _start_step1(self, inspiration: str) -> None:
        from app.services import conversation_service
        if not self._conv_id:
            self._conv_id = conversation_service.new_conversation().conversation_id
        self._go_to(self.PAGE_STEP1_WAIT)
        self._worker = _StepWorker(conversation_service.run_step1, self._conv_id, inspiration)
        self._worker.ok.connect(self._on_step1_done)
        self._worker.fail.connect(self._on_step_fail)
        self._worker.start()

    def _on_step1_done(self, state) -> None:
        questions = state.follow_up_questions or "(无追问)"
        self.lbl_questions.setText(questions)
        self._go_to(self.PAGE_STEP2_INPUT)

    def _start_step2(self, answers: str) -> None:
        from app.services import conversation_service
        self._go_to(self.PAGE_STEP2_WAIT)
        self._worker = _StepWorker(conversation_service.run_step2, self._conv_id, answers)
        self._worker.ok.connect(self._on_step2_done)
        self._worker.fail.connect(self._on_step_fail)
        self._worker.start()

    def _on_step2_done(self, state) -> None:
        setting = state.generated_setting or ""
        self.ed_setting.setPlainText(setting)
        # 先切换页面（_go_to 会隐藏 btn_next）
        self._go_to(self.PAGE_STEP3_PREVIEW)
        # 再把 btn_next 改成 "创建项目" 并显示
        self.btn_next.setText("🚀 创建项目")
        self.btn_next.setVisible(True)
        self.btn_prev.setVisible(True)
        # 改信号连接
        try:
            self.btn_next.clicked.disconnect()
        except TypeError:
            pass
        self.btn_next.clicked.connect(self._on_create_project)

    def _on_step_fail(self, err: str) -> None:
        Dialogs.warning("AI 调用失败", f"对话失败: {err}\n可重试或继续 (会使用 mock 兜底)", parent=self)
        # 兜底: 回到上一步让用户继续
        if self.stack.currentIndex() == self.PAGE_STEP1_WAIT:
            self._go_to(self.PAGE_STEP1_INPUT)
        elif self.stack.currentIndex() == self.PAGE_STEP2_WAIT:
            self._go_to(self.PAGE_STEP2_INPUT)

    # ------------------------------------------------------------------
    # Step 3: 创建项目
    # ------------------------------------------------------------------
    def _on_create_project(self) -> None:
        setting = self.ed_setting.toPlainText().strip()
        if not setting:
            Dialogs.warning("没有设定", "请先确认设定不为空", parent=self)
            return
        # 解析: 项目名 / 书名 / 题材
        parsed = self._parse_setting(setting)
        # 创建项目 (调 project_service.create)
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
        # 同步设定到多个 setting key (V4.0-P4: 之前只存 plot_outline, 其他为空)
        self._sync_settings(setting)
        self._go_to(self.PAGE_DONE)

    def _sync_settings(self, setting: str) -> None:
        """把生成的 Markdown 设定同步到各个 setting key.

        之前只存了 plot_outline 一个字段, 小说设定页的 worldbuilding /
        characters / style_fingerprint 都是空的, 用户体验割裂。
        """
        from app.services.setting_service import set_setting
        from app.services.setting_io import _md_text_to_setting_data, _parse_md_sections

        pid = self._created_pid
        sections = _parse_md_sections(setting)

        # 按标题关键词分发到对应 key
        # key → 匹配此 key 的 section 标题集合
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

        # 写各 key
        for key, parts in collected.items():
            if not parts:
                continue
            merged = "\n\n".join(parts)
            try:
                data = _md_text_to_setting_data(merged, key)
                set_setting(pid, key, data)
            except Exception as e:
                log.warning("sync setting %s failed: %s", key, e)

        # 整篇也存 plot_outline (兜底)
        try:
            set_setting(pid, "plot_outline", setting)
        except Exception as e:
            log.warning("save plot_outline failed: %s", e)

    def _parse_setting(self, setting: str) -> dict:
        """从生成的 Markdown 设定里解析:
          - project_name: 取 "灵感" 前 8 字 / 第 1 个书名 / 默认
          - book_title:   取第 1 个《》/ 默认
          - genre:        匹配 GENRE_PRESETS 的主题材, 没有则 "未分类"
          - word_target:  从"风格定位"提取"X-Y 万字"的中位数, 默认 200000
        """
        from app.services.genre_presets import GENRE_PRESETS
        valid_genres = {name for (_id, name, _desc, _kw) in GENRE_PRESETS}

        # 书名
        m = re.search(r"《([^》]+)》", setting)
        book_title = m.group(1).strip() if m else "未命名小说"

        # 项目名: 用第 1 个书名 + "-对话创建"
        project_name = f"{book_title}-对话创建"

        # 题材
        genre = "未分类"
        for g in valid_genres:
            if g in setting:
                genre = g
                break

        # 字数目标
        word_target = 200_000
        m = re.search(r"(\d+)\s*[-~到至]\s*(\d+)\s*万\s*字", setting)
        if m:
            avg = (int(m.group(1)) + int(m.group(2))) / 2
            word_target = int(avg * 10_000)
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

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------
    @property
    def created_project_id(self) -> Optional[str]:
        return self._created_pid
