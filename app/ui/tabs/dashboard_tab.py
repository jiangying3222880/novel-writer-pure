"""
仪表盘 Tab (Phase 3 M3).

展示全书三组数据:
  - 3 个关键数字: 章节数 / 总字数 / 平均综合分
  - 2 条趋势曲线: Critic 文学分 / HookAnalyzer 追读分  (QPainter 自绘)
  - Top 5 弱章: 综合分升序, 颜色编码

数据来源: dashboard_service.collect(project_id).
"""
from __future__ import annotations
import logging
from typing import Optional

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy, QPlainTextEdit,
    QScrollArea, QComboBox, QGroupBox,
)

from app.services import dashboard_service, ServiceError
from app.ui.widgets.router_status_bar import RouterStatusBar  # M10-D
from app.ui.tabs.hud_tab import HUDTab  # v4.0 StoryState 动态面板

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# 自绘趋势小图
# --------------------------------------------------------------------- #

class TrendChart(QWidget):
    """折线图: 展示一条 (chapter_no -> score) 序列."""

    def __init__(self, title: str, color: str = "#1976d2",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.title = title
        self.color = QColor(color)
        self.points: list[tuple[int, int]] = []  # (chapter_no, score)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # 4.0 修复: 4.x 早期版本 paintEvent 硬编码 QColor("#fafafa") 背景 / "#333" 文本,
        # 暗色主题下图表背景是亮的, 刺眼. 现在 paintEvent 调 _palette() 取当前主题色.
        self.setObjectName("trendChart")

    def set_data(self, points: list[tuple[int, int]]) -> None:
        self.points = points
        self.update()

    def _palette(self) -> "tuple[QColor, QColor, QColor, QColor]":
        """返回当前主题下的 4 个绘图色: (bg, fg_title, fg_label, grid).

        4.0 修复: 委托给 theme.chart_palette(), 不再本地重复实现. 同时也修了一个
        隐患: 之前每次 paintEvent 都 import 一次 theme 模块, 性能微差.
        """
        from app.ui.theme import chart_palette
        return tuple(QColor(c) for c in chart_palette())

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        bg, fg_title, fg_label, grid_color = self._palette()
        # 背景
        p.fillRect(0, 0, w, h, bg)
        # 标题
        p.setPen(fg_title)
        p.setFont(QFont("", 10, QFont.Weight.Bold))
        p.drawText(QRect(8, 4, w - 16, 20), Qt.AlignmentFlag.AlignLeft, self.title)
        if not self.points:
            p.setPen(fg_label)
            p.setFont(QFont("", 9))
            p.drawText(QRect(0, h // 2 - 10, w, 20),
                       Qt.AlignmentFlag.AlignCenter, "暂无数据")
            return
        # 坐标区域
        margin_l, margin_r, margin_t, margin_b = 32, 16, 28, 24
        cw, ch = w - margin_l - margin_r, h - margin_t - margin_b
        # y 轴 (0/50/100)
        p.setPen(QPen(grid_color, 1))
        for y_val, label in [(0, "0"), (50, "50"), (100, "100")]:
            y = margin_t + ch - int(ch * y_val / 100)
            p.drawLine(margin_l, y, w - margin_r, y)
            p.setPen(fg_label)
            p.setFont(QFont("", 8))
            p.drawText(QRect(2, y - 8, margin_l - 4, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
            p.setPen(QPen(grid_color, 1))
        # x 轴标签 (取首/中/末)
        p.setPen(fg_label)
        p.setFont(QFont("", 8))
        if len(self.points) >= 1:
            first_no = self.points[0][0]
            last_no = self.points[-1][0]
            mid_no = (first_no + last_no) // 2 if last_no > first_no else first_no
            for ch_no, x_pos in [
                (first_no, margin_l),
                (mid_no, margin_l + cw // 2),
                (last_no, margin_l + cw),
            ]:
                p.drawText(QRect(int(x_pos) - 24, h - margin_b + 4, 48, 16),
                           Qt.AlignmentFlag.AlignCenter, f"ch{ch_no}")
        # 折线
        if len(self.points) == 1:
            x = margin_l + cw // 2
            y = margin_t + ch - int(ch * self.points[0][1] / 100)
            p.setPen(QPen(self.color, 2))
            p.setBrush(QBrush(self.color))
            p.drawEllipse(int(x) - 4, int(y) - 4, 8, 8)
            return
        p.setPen(QPen(self.color, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path_pts: list[tuple[int, int]] = []
        for i, (ch_no, score) in enumerate(self.points):
            x = margin_l + int(cw * i / max(1, len(self.points) - 1))
            y = margin_t + ch - int(ch * score / 100)
            path_pts.append((x, y))
        for i in range(len(path_pts) - 1):
            p.drawLine(path_pts[i][0], path_pts[i][1],
                       path_pts[i + 1][0], path_pts[i + 1][1])
        # 节点
        p.setBrush(QBrush(self.color))
        for x, y in path_pts:
            p.drawEllipse(int(x) - 3, int(y) - 3, 6, 6)


# --------------------------------------------------------------------- #
# 关键数字卡片
# --------------------------------------------------------------------- #

class StatCard(QFrame):
    def __init__(self, label: str, value: str, accent: str = "#1976d2",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # 4.0 修复: 4.x 早期版本 setStyleSheet 硬编码 #fff, 暗色主题下白得扎眼.
        # 现在只设 objectName, 真正的背景色在 app/ui/theme.py 的 QFrame#statCard 节点.
        self.setObjectName("statCard")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(2)
        self.lbl_label = QLabel(label)
        self.lbl_label.setObjectName("statCardLabel")
        self.lbl_value = QLabel(value)
        # accent 由调用方传入, 仍需 inline (因不同 stat card 用不同高亮色, QSS 没法覆盖)
        self._accent = accent
        self.lbl_value.setObjectName("statCardValue")
        self.lbl_value.setStyleSheet(
            f"color: {accent}; font-size: 22px; font-weight: 700;"
        )
        v.addWidget(self.lbl_label)
        v.addWidget(self.lbl_value)

    def set_value(self, v: str) -> None:
        self.lbl_value.setText(v)


# --------------------------------------------------------------------- #
# 进度环 (V4.0-P2-新) — 自绘 QPainter, 显示「已写 / 目标」圆形进度
# --------------------------------------------------------------------- #

class ProgressRing(QWidget):
    """环形进度图. 中心显示百分比, 周围是字数字.

    V4.0-P2-新: 之前仪表盘只有「总字数」一个绝对值, 用户看不到
    「已写 vs 计划目标」. 现在加进度环, 让用户一眼看到完成度.
    """

    def __init__(self, title: str = "全书进度",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.title = title
        self.written = 0
        self.target = 0  # 0 表示没目标
        self.setMinimumSize(160, 160)
        self.setObjectName("progressRing")

    def set_values(self, written: int, target: int) -> None:
        self.written = max(0, int(written or 0))
        self.target = max(0, int(target or 0))
        self.update()

    def _palette(self) -> "tuple[QColor, QColor, QColor, QColor, QColor]":
        """(bg, fg_label, fg_value, ring_track, ring_progress)"""
        from app.ui.theme import chart_palette
        cps = chart_palette()
        return (
            QColor(cps[0]),  # bg
            QColor(cps[2]),  # fg_label
            QColor(cps[1]),  # fg_value (title color)
            QColor("#3a3b40"),  # ring track (灰, 半透明)
            QColor("#5a68c9"),  # ring progress (靛)
        )

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        bg, fg_label, fg_title, ring_track, ring_progress = self._palette()

        # 背景
        p.fillRect(0, 0, w, h, bg)
        # 标题
        p.setPen(fg_title)
        p.setFont(QFont("", 10, QFont.Weight.Bold))
        p.drawText(QRect(0, 4, w, 20), Qt.AlignmentFlag.AlignCenter, self.title)

        # 环区域
        ring_size = min(w - 32, 130)
        cx, cy = w // 2, h // 2 + 6
        r = ring_size // 2
        rect = QRect(cx - r, cy - r, ring_size, ring_size)

        # 1) track (背景环)
        p.setPen(QPen(ring_track, 8, Qt.PenStyle.SolidLine))
        p.drawEllipse(rect)

        # 2) progress (前景弧) — 用百分比覆盖
        if self.target > 0:
            pct = min(1.0, self.written / self.target)
            # 0 起点 = 3 点钟方向, 顺时针
            start_angle = 90 * 16  # 12 点钟方向 (Qt 用 1/16 度)
            span = -int(pct * 360 * 16)  # 负数 = 顺时针
            p.setPen(QPen(ring_progress, 8, Qt.PenStyle.SolidLine))
            p.drawArc(rect, start_angle, span)
            # 中心百分比
            p.setPen(fg_title)
            p.setFont(QFont("", 16, QFont.Weight.Bold))
            p.drawText(QRect(0, cy - 14, w, 28),
                       Qt.AlignmentFlag.AlignCenter, f"{pct * 100:.1f}%")
        else:
            # 没目标, 显示 ——
            p.setPen(fg_label)
            p.setFont(QFont("", 14))
            p.drawText(QRect(0, cy - 12, w, 24),
                       Qt.AlignmentFlag.AlignCenter, "—")

        # 底部数值
        p.setPen(fg_label)
        p.setFont(QFont("", 9))
        bottom = f"{self.written:,} / {self.target:,} 字"
        p.drawText(QRect(0, h - 22, w, 18),
                   Qt.AlignmentFlag.AlignCenter, bottom)


# --------------------------------------------------------------------- #
# 多项目进度表 (V4.0-P2-新) — 跨项目对比「已写 / 目标 / 完成度」
# --------------------------------------------------------------------- #

class ProjectProgressTable(QTableWidget):
    """展示所有项目一行一条, 6 列: 名称/体裁/总字数/已写/目标/完成度条."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(0, 6, parent)
        self.setHorizontalHeaderLabels(
            ["项目", "体裁", "结构", "已写字数", "目标字数", "完成度"]
        )
        self.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setObjectName("projectProgressTable")

    def load_data(self, rows: list[dict]) -> None:
        """rows: [{name, genre, structure_text, written, target}, ...]

        V4.0-P2-新: 内部按完成度百分比降序排序, 这样 UI 端总是
        "完成度高的在前", 不用调用方关心排序.
        """
        # 内部排序: 完成度百分比降序
        rows_sorted = sorted(
            rows,
            key=lambda r: ((int(r.get("written") or 0) / int(r.get("target") or 1))
                           if int(r.get("target") or 0) > 0 else 0),
            reverse=True,
        )
        self.setRowCount(0)
        for r in rows_sorted:
            row_idx = self.rowCount()
            self.insertRow(row_idx)
            self.setItem(row_idx, 0, QTableWidgetItem(str(r.get("name") or "—")))
            self.setItem(row_idx, 1, QTableWidgetItem(str(r.get("genre") or "—")))
            self.setItem(row_idx, 2, QTableWidgetItem(str(r.get("structure_text") or "—")))
            self.setItem(row_idx, 3, QTableWidgetItem(f"{int(r.get('written') or 0):,}"))
            self.setItem(row_idx, 4, QTableWidgetItem(f"{int(r.get('target') or 0):,}"))
            # 完成度: 用 "X.X% | ████░░" 文字条
            target = int(r.get("target") or 0)
            written = int(r.get("written") or 0)
            pct = (written / target * 100) if target > 0 else 0
            filled = int(min(20, pct / 5))  # 20 格的 bar
            bar = "█" * filled + "░" * (20 - filled)
            pct_item = QTableWidgetItem(f"{pct:5.1f}%  {bar}")
            # 颜色编码: 红(<25%)/橙(25-50%)/黄(50-75%)/绿(≥75%)
            if pct < 25:
                pct_item.setForeground(QColor("#c62828"))
            elif pct < 50:
                pct_item.setForeground(QColor("#e65100"))
            elif pct < 75:
                pct_item.setForeground(QColor("#f9a825"))
            else:
                pct_item.setForeground(QColor("#2e7d32"))
            self.setItem(row_idx, 5, pct_item)


# --------------------------------------------------------------------- #
# DashboardTab
# --------------------------------------------------------------------- #

class DashboardTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.current_project: Optional[dict] = None
        self._build_ui()

    def _build_ui(self) -> None:
        # 外层用 QScrollArea 包裹，内容过多时可滚动
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # 内容容器 (放在 scroll area 里)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # header
        header = QHBoxLayout()
        self.title = QLabel("创作总览（未选择项目）")
        self.title.setObjectName("projectTitle")
        header.addWidget(self.title)
        header.addStretch(1)
        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_refresh.clicked.connect(self._reload)
        header.addWidget(self.btn_refresh)
        layout.addLayout(header)

        # M10-D: AI Router 状态条 (展示 model / 策略 / cache 命中率 / 累计)
        self.router_bar = RouterStatusBar(parent=content)
        layout.addWidget(self.router_bar)

        # 3 个数字
        stat_row = QHBoxLayout()
        stat_row.setSpacing(10)
        self.card_chapters = StatCard("📚 章节数", "—", "#1976d2")
        self.card_words = StatCard("✍️ 总字数", "—", "#388e3c")
        self.card_avg = StatCard("⭐ 平均综合分", "—", "#f57c00")
        stat_row.addWidget(self.card_chapters)
        stat_row.addWidget(self.card_words)
        stat_row.addWidget(self.card_avg)
        # V4.0-P2-新: 进度环 — 直观显示「已写 / 目标」
        self.progress_ring = ProgressRing("全书进度 (本章目标)")
        stat_row.addWidget(self.progress_ring)
        layout.addLayout(stat_row)

        # P1: 写作 KPI (tokens / 成本 / 时长)
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)
        self.card_tokens_in = StatCard("📥 Token 输入", "—", "#7b1fa2")
        self.card_tokens_out = StatCard("📤 Token 输出", "—", "#c2185b")
        self.card_cost = StatCard("💰 AI 成本 (USD)", "—", "#e64a19")
        self.card_duration = StatCard("⏱️ 写作时长", "—", "#00695c")
        kpi_row.addWidget(self.card_tokens_in)
        kpi_row.addWidget(self.card_tokens_out)
        kpi_row.addWidget(self.card_cost)
        kpi_row.addWidget(self.card_duration)
        layout.addLayout(kpi_row)

        # 中段：左(最小化Critic+Hook)  |  右(节奏与弱章并排)  — 25:75
        self.chart_critic = TrendChart("Critic 文学分", "#1976d2")
        self.chart_critic.setMinimumHeight(100)  # 最小化
        self.chart_hook = TrendChart("Hook 追读分", "#9c27b0")
        self.chart_hook.setMinimumHeight(100)  # 最小化
        middle_row = QHBoxLayout()
        middle_row.setSpacing(10)

        # 左栏: Critic + Hook 最小化纵排
        left_mid = QVBoxLayout()
        left_mid.setSpacing(4)
        left_mid.addWidget(self.chart_critic)
        left_mid.addWidget(self.chart_hook)
        middle_row.addLayout(left_mid, 1)

        # 右栏: 节奏报告与弱章并排 (横向)
        right_mid = QHBoxLayout()
        right_mid.setSpacing(8)

        # 节奏报告 (左子栏) — 卡片式：标题+内容包在同一个深色底色方框内
        rhythm_card = QFrame()
        rhythm_card.setObjectName("rhythmCard")
        rhythm_card_layout = QVBoxLayout(rhythm_card)
        rhythm_card_layout.setContentsMargins(8, 6, 8, 6)
        rhythm_card_layout.setSpacing(2)
        lbl_rhythm = QLabel("📈 节奏报告")
        lbl_rhythm.setObjectName("cardTitle")
        rhythm_card_layout.addWidget(lbl_rhythm)
        self.rhythm_panel = QPlainTextEdit()
        self.rhythm_panel.setReadOnly(True)
        self.rhythm_panel.setObjectName("rhythmPanel")
        self.rhythm_panel.setFrameShape(QFrame.Shape.NoFrame)
        self.rhythm_panel.setPlaceholderText("暂无节奏数据，请先写几章再查看报告")
        rhythm_card_layout.addWidget(self.rhythm_panel, 1)
        right_mid.addWidget(rhythm_card, 1)

        # 弱章 (右子栏) — 卡片式：标题+表格包在同一个深色底色方框内
        weak_card = QFrame()
        weak_card.setObjectName("weakCard")
        weak_card_layout = QVBoxLayout(weak_card)
        weak_card_layout.setContentsMargins(8, 6, 8, 6)
        weak_card_layout.setSpacing(2)
        lbl_weak = QLabel("🔻 Top 5 弱章")
        lbl_weak.setObjectName("cardTitle")
        weak_card_layout.addWidget(lbl_weak)
        self.weak_table = QTableWidget(0, 4)
        self.weak_table.setFrameShape(QFrame.Shape.NoFrame)
        self.weak_table.setHorizontalHeaderLabels(
            ["章节", "标题", "综合分", "Critic/Hook"]
        )
        self.weak_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.weak_table.verticalHeader().setVisible(False)
        self.weak_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.weak_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        weak_card_layout.addWidget(self.weak_table, 1)
        right_mid.addWidget(weak_card, 1)

        middle_row.addLayout(right_mid, 3)
        layout.addLayout(middle_row, 1)

        # 底部：所有项目进度 — 卡片式包裹，标题在方框内
        proj_card = QFrame()
        proj_card.setObjectName("weakCard")  # 复用弱章相同的卡片样式
        proj_card_layout = QVBoxLayout(proj_card)
        proj_card_layout.setContentsMargins(8, 6, 8, 6)
        proj_card_layout.setSpacing(4)
        proj_header = QHBoxLayout()
        proj_header.setSpacing(8)
        proj_header.addWidget(QLabel("📊 所有项目进度"))
        self.progress_filter_combo = QComboBox()
        self.progress_filter_combo.addItems(["全部", "≥ 25%", "≥ 50%", "≥ 75%", "≥ 90%", "已完成"])
        self.progress_filter_combo.setCurrentIndex(0)
        self.progress_filter_combo.currentIndexChanged.connect(self._on_progress_filter_changed)
        proj_header.addWidget(self.progress_filter_combo)
        proj_header.addStretch(1)
        self.lbl_progress_summary = QLabel("")
        self.lbl_progress_summary.setObjectName("progressSummary")
        proj_header.addWidget(self.lbl_progress_summary)
        proj_card_layout.addLayout(proj_header)
        self.project_progress_table = ProjectProgressTable()
        self.project_progress_table.setFrameShape(QFrame.Shape.NoFrame)
        proj_card_layout.addWidget(self.project_progress_table, 1)
        layout.addWidget(proj_card, 1)

        # v4.0: StoryState 动态面板 (复用已按 StoryState 设计的 HUDTab)
        self._state_hud = HUDTab()
        state_group = QGroupBox("StoryState 动态（最新单元）")
        state_group.setStyleSheet(
            "QGroupBox { border: 1px solid #313244; border-radius: 8px; "
            "margin-top: 12px; padding-top: 16px; font-weight: bold; color: #cdd6f4; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }"
        )
        sg_layout = QVBoxLayout(state_group)
        sg_layout.setContentsMargins(0, 0, 0, 0)
        sg_layout.addWidget(self._state_hud)
        layout.addWidget(state_group)

    # ---- public ----

    def set_project(self, project: Optional[dict]) -> None:
        self.current_project = project
        if project is None:
            self.title.setText("创作总览（未选择项目）")
            self._clear_all()
            self.router_bar.refresh()  # M10-D: 项目切换时也刷 router 状态
            return
        self.title.setText(f"创作总览 — {project.get('name', '')}")
        self._reload()
        self._refresh_story_state(project)  # v4.0: 真实 StoryState 动态数据
        self.router_bar.refresh()  # M10-D

    # ---- data ----

    def _refresh_story_state(self, project) -> None:
        """v4.0: 从 StateBridge 取真实 StoryState（最新单元）喂给 HUDTab.

        降级策略: 取不到（无单元 / 异常）时静默不显示，不影响主仪表盘。
        """
        if not hasattr(self, "_state_hud"):
            return
        pid = project.get("id") if isinstance(project, dict) else getattr(project, "id", None)
        if not pid:
            try:
                self._state_hud.set_state(None)
            except Exception:
                pass
            return
        try:
            from app.services import story_unit_service_v2 as us
            units = us.list_for_project(pid, order_by="present")
            if not units:
                self._state_hud.set_state(None)
                return
            unit = units[-1]  # present 序最大 = 最新书写单元
            from story.state.state_bridge import StateBridge
            state = StateBridge.from_unit_v2(unit)
            self._state_hud.set_state(state)
        except Exception as e:
            log.debug("[dashboard] StoryState 加载失败(降级): %s", e)
            try:
                self._state_hud.set_state(None)
            except Exception:
                pass

    def _reload(self) -> None:
        if not self.current_project:
            return
        pid = self.current_project["id"]
        try:
            data = dashboard_service.collect(pid)
        except ServiceError as e:
            log.error(f"[dashboard] collect failed: {e}")
            self._clear_all()
            self.card_chapters.set_value("err")
            return
        s = data.get("summary", {})
        self.card_chapters.set_value(str(s.get("chapter_count", 0)))
        self.card_words.set_value(f"{s.get('total_words', 0):,}")
        avg = s.get("avg_critic_score")
        avg_hook = s.get("avg_hook_score")
        if avg is not None and avg_hook is not None:
            self.card_avg.set_value(f"{(avg + avg_hook) / 2:.1f}")
        elif avg is not None:
            self.card_avg.set_value(f"{avg:.1f} (C)")
        elif avg_hook is not None:
            self.card_avg.set_value(f"{avg_hook:.1f} (H)")
        else:
            self.card_avg.set_value("—")
        # P1: 写作 KPI
        kpi = data.get("writing_kpi", {})
        self.card_tokens_in.set_value(f"{kpi.get('total_tokens_in', 0):,}")
        self.card_tokens_out.set_value(f"{kpi.get('total_tokens_out', 0):,}")
        cost = kpi.get("total_cost", 0.0)
        self.card_cost.set_value(f"${cost:.4f}" if cost else "—")
        dur_ms = kpi.get("total_duration_ms", 0)
        if dur_ms:
            secs = dur_ms / 1000
            if secs < 60:
                self.card_duration.set_value(f"{secs:.0f}s")
            elif secs < 3600:
                self.card_duration.set_value(f"{secs/60:.1f}m")
            else:
                self.card_duration.set_value(f"{secs/3600:.1f}h")
        else:
            self.card_duration.set_value("—")
        # 趋势
        crit_pts: list[tuple[int, int]] = []
        hook_pts: list[tuple[int, int]] = []
        for entry in data.get("trend", []):
            ch_no = entry.get("chapter_no") or 0
            cs = entry.get("critic_score")
            hs = entry.get("hook_score")
            if cs is not None:
                crit_pts.append((ch_no, cs))
            if hs is not None:
                hook_pts.append((ch_no, hs))
        self.chart_critic.set_data(crit_pts)
        self.chart_hook.set_data(hook_pts)
        # Top 5 弱章
        weak = data.get("weak_chapters", [])
        self.weak_table.setRowCount(len(weak))
        for i, w in enumerate(weak):
            ch_no = w.get("chapter_no") or "?"
            title = (w.get("title") or "(无题)")[:50]
            combined = w.get("combined", 0)
            cs = w.get("critic_score")
            hs = w.get("hook_score")
            self.weak_table.setItem(i, 0, QTableWidgetItem(f"第{ch_no}章"))
            self.weak_table.setItem(i, 1, QTableWidgetItem(title))
            score_item = QTableWidgetItem(f"{combined:.1f}")
            # 颜色编码: <50 红, 50-70 黄, >=70 绿
            if combined < 50:
                score_item.setForeground(QColor("#c62828"))
            elif combined < 70:
                score_item.setForeground(QColor("#f9a825"))
            else:
                score_item.setForeground(QColor("#2e7d32"))
            self.weak_table.setItem(i, 2, score_item)
            cs_str = f"{cs}" if cs is not None else "—"
            hs_str = f"{hs}" if hs is not None else "—"
            self.weak_table.setItem(i, 3, QTableWidgetItem(f"{cs_str} / {hs_str}"))

        # V4.0-P2-新: 进度环 — 已写 / 目标
        written = int(s.get("total_words") or 0)
        target = int(self.current_project.get("word_target") or 0)
        self.progress_ring.set_values(written, target)

        # V4.0-P2-新: 多项目进度表
        self._load_project_progress_table()

        # v3.4 新增: 长篇节奏报告
        self._load_rhythm_report()

    def _load_project_progress_table(self) -> None:
        """跨项目对比: 拉取所有项目 + 每个的 written (用 chapter_service 算) + 目标.

        V4.0-P2-新: 之前用户只能单项目看, 不知道 5 个项目里哪个进度最快. 现在
        列 6 列: 项目 / 体裁 / 结构 / 已写 / 目标 / 完成度.
        
        V4.0-P3-新: 支持完成度筛选, 通过 self.progress_filter_combo 控制.
        "全部"=不过滤, "≥ N%"=仅保留完成度≥N%的项目, "已完成"=100%.
        同时在 lbl_progress_summary 显示筛选后/总项目数.
        """
        try:
            from app.services import project_service, chapter_service
            data = project_service.list_all()
            projects = data.get("projects", [])
        except Exception as e:
            log.warning(f"[dashboard] list projects failed: {e}")
            projects = []

        rows: list[dict] = []
        total_count = 0
        for p in projects:
            pid = p.get("id")
            if not pid:
                continue
            total_count += 1
            try:
                # written = 该项目所有 chapter 的字数合计
                chs = chapter_service.list_by_project(pid) or []
                written = sum(int(c.get("word_count") or 0) for c in chs)
            except Exception:
                written = 0
            target = int(p.get("word_target") or 0)
            # 副题材 + 分卷数
            subs = p.get("sub_genres") or []
            sub_str = "、".join(subs[:3]) if isinstance(subs, list) else ""
            if len(subs) > 3:
                sub_str += f"+{len(subs) - 3}"
            structure = f"{p.get('volumes') or 1}卷 × {p.get('chapters_per_volume') or 0}章"
            if sub_str:
                structure = f"{structure}\n副: {sub_str}"
            # 计算完成度百分比
            pct = (written / target * 100) if target > 0 else 0.0
            rows.append({
                "name": p.get("name"),
                "genre": p.get("genre") or "—",
                "structure_text": structure,
                "written": written,
                "target": target,
                "pct": pct,
            })

        # --- 完成度筛选 ---
        filter_idx = self.progress_filter_combo.currentIndex()
        if filter_idx == 0:
            # 全部 — 不过滤
            filtered = rows
        elif filter_idx == 5:
            # 已完成 (100%)
            filtered = [r for r in rows if r["pct"] >= 100.0]
        else:
            # ≥ 25% / 50% / 75% / 90%
            thresholds = {1: 25, 2: 50, 3: 75, 4: 90}
            th = thresholds.get(filter_idx, 0)
            filtered = [r for r in rows if r["pct"] >= th]

        # 按完成度百分比降序
        filtered.sort(
            key=lambda r: r["pct"],
            reverse=True,
        )

        # 更新统计标签
        if filter_idx == 0:
            self.lbl_progress_summary.setText(f"共 {total_count} 个项目")
        else:
            self.lbl_progress_summary.setText(f"{len(filtered)}/{total_count} 个项目")

        self.project_progress_table.load_data(filtered)

    def _on_progress_filter_changed(self) -> None:
        """完成度筛选切换时刷新项目进度表."""
        self._load_project_progress_table()

    def _load_rhythm_report(self) -> None:
        """v3.4 新增: 加载长篇节奏报告 (最近10章的压力分布/钩子密度/情绪曲线)."""
        if not self.current_project:
            self.rhythm_panel.setPlainText("")
            return
        
        pid = self.current_project.get("id")
        if not pid:
            self.rhythm_panel.setPlainText("")
            return
        
        try:
            from app.services.pressure import rhythm_report, format_rhythm_report
            report = rhythm_report(pid, last_n_chapters=10)
            report_text = format_rhythm_report(report)
            self.rhythm_panel.setPlainText(report_text)
        except Exception as e:
            log.warning(f"[dashboard] load rhythm report failed: {e}")
            self.rhythm_panel.setPlainText(f"加载节奏报告失败: {e}")

    def _clear_all(self) -> None:
        self.card_chapters.set_value("—")
        self.card_words.set_value("—")
        self.card_avg.set_value("—")
        self.card_tokens_in.set_value("—")
        self.card_tokens_out.set_value("—")
        self.card_cost.set_value("—")
        self.card_duration.set_value("—")
        self.chart_critic.set_data([])
        self.chart_hook.set_data([])
        self.weak_table.setRowCount(0)
        # V4.0-P2-新
        self.progress_ring.set_values(0, 0)
        self.project_progress_table.load_data([])
        self.lbl_progress_summary.setText("")
        self.progress_filter_combo.setCurrentIndex(0)
        # v3.4 新增
        self.rhythm_panel.setPlainText("")
