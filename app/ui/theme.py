"""
主题模块 - 暗/亮主题 stylesheet + 切换 (v3.0 对齐 mockup).

设计参考 docs/novel-writer-ui-mockup.html (2026-06-10 批准).
设计 token 直接镜像 mockup CSS 变量:
  --bg-deep / --bg / --surface / --surface-hover / --surface-active
  --fg / --fg-secondary / --fg-muted / --fg-subtle
  --accent / --accent-hover / --accent-subtle
  --border / --border-subtle
  --success / --warn / --danger / --info
  --radius / --radius-sm / --radius-lg
"""
from __future__ import annotations

import logging
from typing import Literal

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

ThemeName = Literal["dark", "light"]


# ---- 暗色 (默认, 镜像 mockup body.dark) ----
DARK_QSS = """
* { outline: 0; }

/* ===== 基础 ===== */
QMainWindow, QWidget {
    background: #0f1011;
    color: #f0f1f2;
    font-family: "Inter", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", -apple-system, system-ui, sans-serif;
    font-size: 13px;
}
QToolTip {
    background: #28282c;
    color: #f0f1f2;
    border: 1px solid #3a3b3e;
    border-radius: 4px;
    padding: 4px 6px;
    font-size: 12px;
}

/* ===== TITLE BAR (v4.0 mockup 1:1) ===== */
QWidget#titleBar { background: #0a0b0d; border-bottom: 1px solid rgba(255,255,255,0.04); }
QLabel#titleBarLogo { color: #c8cdd4; font-size: 12px; font-weight: 600; }
QLabel#titleBarLogoAccent { color: #6c7ae0; font-weight: 600; }
QFrame#titleBarDotR { background: #e05050; border-radius: 6px; }
QFrame#titleBarDotY { background: #e0b040; border-radius: 6px; }
QFrame#titleBarDotG { background: #40b060; border-radius: 6px; }
QWidget#sidebarHeader { background: transparent; }

/* ===== SIDEBAR FOOTER ===== */
QLabel#sidebarFooter { color: #555a63; font-size: 11px; padding: 2px 4px; }

/* ===== SIDEBAR ===== */
QWidget#sidebar { background: #0a0b0d; border-right: 1px solid rgba(255,255,255,0.08); }
QLabel#sidebarHeader { color: #c8cdd4; font-size: 13px; font-weight: 600; padding: 6px 4px; }
QListWidget#navList {
    background: transparent; border: none; outline: 0;
    color: #8a8f98; font-size: 13px; padding: 0;
}
QListWidget#navList::item {
    padding: 7px 12px 7px 28px;
    border-radius: 0;
    border-left: 2px solid transparent;
    color: #8a8f98;
}
QListWidget#navList::item:hover { background: #191a1b; color: #c8cdd4; }
QListWidget#navList::item:selected {
    background: rgba(108,122,224,0.12);
    color: #6c7ae0;
    border-left: 2px solid #6c7ae0;
    font-weight: 600;
}
QListWidget#navList::item[groupLabel="true"] {
    color: #555a63;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 10px 12px 4px 12px;
    background: transparent;
    border-left: 0;
}
QListWidget#navList::item:disabled { color: #555a63; }
QFrame#sidebarProject {
    background: rgba(108,122,224,0.12);
    border-radius: 6px;
    padding: 6px 8px;
    margin: 0 10px 8px 10px;
}
QLabel#sidebarProjectName { color: #f0f1f2; font-size: 12px; font-weight: 600; }
QLabel#sidebarProjectMeta { color: #8a8f98; font-size: 11px; }

/* ===== CONTENT TOPBAR ===== */
QFrame#contentTopbar {
    background: #0f1011;
    border-bottom: 1px solid rgba(255,255,255,0.08);
}
QLabel#contentTopbarTitle {
    color: #f0f1f2;
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.01em;
}
QLabel#contentTopbarBadge {
    background: rgba(108,122,224,0.18);
    color: #7d8aff;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 500;
}

/* ===== STATUS BAR ===== */
QStatusBar {
    background: #0a0b0d;
    color: #8a8f98;
    border-top: 1px solid rgba(255,255,255,0.04);
    font-size: 11px;
}
QStatusBar::item { border: none; }
QLabel#statusBarSep { color: #3a3b3e; padding: 0 8px; }
QLabel#statusBarIndicator { color: #8a8f98; font-size: 11px; }
QLabel#statusBarIndicatorOk { color: #34a853; font-weight: 600; }
QLabel#statusBarIndicatorWarn { color: #e8a23a; font-weight: 600; }

/* ===== CONTENT BODY ===== */
QWidget#contentBody { background: #0f1011; }

/* ===== CARDS ===== */
QFrame#card {
    background: #191a1b;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    padding: 16px;
}
QFrame#cardHoverable:hover { border-color: rgba(255,255,255,0.16); }
QLabel#cardTitle { color: #f0f1f2; font-size: 13px; font-weight: 600; }
QLabel#cardSub { color: #8a8f98; font-size: 11px; }

/* ===== LOG VIEWER (4.0 修复: 之前硬编码 #0a0b0d, 亮色主题下还是黑底) ===== */
QPlainTextEdit#logViewer {
    background: #0a0b0d;
    color: #c8cdd4;
    font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    border: 1px solid #2a2b2f;
    border-radius: 6px;
}
/* 4.0 修复: 仪表盘 StatCard / RouterStatusBar 之前硬编码白色, 暗色下白得刺眼 */
QFrame#statCard {
    background: #191a1b;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 6px;
}
QLabel#statCardLabel { color: #8a8f98; font-size: 12px; }
/* 仪表盘卡片 — 标题被包在底色方框内 */
QFrame#rhythmCard, QFrame#weakCard {
    background: #191a1b;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 6px;
}
QLabel#cardTitle {
    color: #c8cdd4;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}
QFrame#router_status_bar {
    background: #191a1b;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 4px;
}
QLabel#routerStatusLabel { color: #c8cdd4; font-size: 11px; }

/* ===== TABLES ===== */
QHeaderView::section {
    background: #191a1b;
    color: #8a8f98;
    border: none;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    padding: 6px 8px;
    font-weight: 600;
    font-size: 11px;
}
QTableWidget, QTableView {
    background: #191a1b;
    alternate-background-color: #222326;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 6px;
    gridline-color: rgba(255,255,255,0.04);
    selection-background-color: rgba(108,122,224,0.30);
    color: #f0f1f2;
}
QTableWidget::item, QTableView::item {
    padding: 6px 8px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
    color: #c8cdd4;
}

/* ===== BUTTONS ===== */
QPushButton {
    background: #191a1b;
    color: #c8cdd4;
    border: 1px solid #2a2b2f;
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton:hover { background: #222326; border-color: #3a3b3e; color: #f0f1f2; }
QPushButton:pressed { background: #28282c; }
QPushButton:disabled { color: #555a63; background: #191a1b; border-color: #2a2b2f; }
QPushButton#btnPrimary {
    background: #6c7ae0; color: #ffffff; border: 1px solid #6c7ae0; font-weight: 600;
}
QPushButton#btnPrimary:hover { background: #7d8aff; border-color: #7d8aff; }
QPushButton#btnGhost { background: transparent; border-color: transparent; }
QPushButton#btnGhost:hover { background: #222326; }
QPushButton#btnDanger { color: #d94040; border-color: rgba(217,64,64,0.30); }
QPushButton#btnDanger:hover { background: rgba(217,64,64,0.10); }
QPushButton#btnSm { padding: 3px 8px; font-size: 11px; }
QPushButton#btnIcon { padding: 3px 5px; font-size: 13px; min-width: 22px; }

/* v4.0 patch: ModuleNav 导航按钮 (替代硬编码暗色 QSS) */
QPushButton#navBtn {
    text-align: left;
    padding: 6px 4px 6px 14px;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: #a6adc8;
    font-size: 12px;
}
QPushButton#navBtn:hover {
    background: rgba(255,255,255,0.06);
    color: #cdd6f4;
}
QPushButton#navBtn:checked {
    background: rgba(108,122,224,0.18);
    color: #cdd6f4;
    font-weight: 700;
}

/* v4.0 patch: 侧边栏底部齿轮按钮 */
QPushButton#gearBtn {
    background: transparent; border: none;
    font-size: 15px; color: #6c7086;
}
QPushButton#gearBtn:hover { color: #cdd6f4; }

/* v4.0 patch: ModuleNav 容器 (背景透明, 由 #sidebar 控制) */
QWidget#moduleNav { background: transparent; border: none; }

/* ===== CHECKBOXES ===== */
QCheckBox {
    color: #c8cdd4;
    spacing: 8px;
    font-size: 13px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #3a3b3e;
    border-radius: 4px;
    background: #191a1b;
}
QCheckBox::indicator:hover {
    border-color: #6c7ae0;
}
QCheckBox::indicator:checked {
    background: #6c7ae0;
    border-color: #6c7ae0;
}
QCheckBox::indicator:checked:hover {
    background: #7d8aff;
    border-color: #7d8aff;
}
QCheckBox::indicator:disabled {
    border-color: #2a2b2f;
    background: #0f1011;
}
QCheckBox::indicator:checked:disabled {
    background: #3a3b3e;
    border-color: #3a3b3e;
}

/* ===== INPUTS ===== */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {
    background: #191a1b;
    color: #f0f1f2;
    border: 1px solid #2a2b2f;
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 13px;
    selection-background-color: rgba(108,122,224,0.30);
}
QSpinBox, QDoubleSpinBox {
    background: #191a1b;
    color: #f0f1f2;
    border: 1px solid #2a2b2f;
    border-radius: 6px;
    font-size: 13px;
    selection-background-color: rgba(108,122,224,0.30);
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #6c7ae0;
}

/* ===== LISTS / TREES ===== */
QListWidget, QTreeWidget {
    background: #191a1b;
    color: #f0f1f2;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 6px;
    alternate-background-color: #222326;
}
QListWidget::item, QTreeWidget::item { padding: 5px 8px; border-radius: 3px; color: #c8cdd4; }
QListWidget::item:selected, QTreeWidget::item:selected {
    background: rgba(108,122,224,0.18);
    color: #f0f1f2;
}

/* ===== TABS ===== */
QTabWidget::pane { border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; top: -1px; background: #191a1b; }
QTabBar::tab {
    background: transparent;
    color: #8a8f98;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 7px 14px;
    font-size: 12px;
    font-weight: 500;
    margin-right: 4px;
}
QTabBar::tab:selected { color: #7d8aff; border-bottom: 2px solid #6c7ae0; }
QTabBar::tab:hover:!selected { color: #c8cdd4; }

/* ===== GROUP BOX ===== */
QGroupBox {
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 6px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
    color: #c8cdd4;
    font-weight: 600;
    font-size: 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    background: #0f1011;
}

/* ===== SCROLLBAR ===== */
QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
QScrollBar::handle:vertical { background: #2a2b2f; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3a3b3e; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 6px; margin: 0; }
QScrollBar::handle:horizontal { background: #2a2b2f; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ===== PROGRESS BAR ===== */
QProgressBar {
    background: #191a1b;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 6px;
    text-align: center;
    color: #c8cdd4;
    height: 14px;
}
QProgressBar::chunk { background: #6c7ae0; border-radius: 5px; }

/* ===== DIALOGS / MENUS ===== */
QMessageBox, QDialog { background: #191a1b; color: #c8cdd4; }
QMenu { background: #191a1b; border: 1px solid #2a2b2f; padding: 4px; color: #c8cdd4; }
QMenu::item { padding: 5px 18px; border-radius: 3px; }
QMenu::item:selected { background: rgba(108,122,224,0.20); color: #f0f1f2; }

/* ===== PRICE BAR (Tokens 提示价格条) ===== */
QFrame#priceBar {
    background: rgba(108,122,224,0.06);
    border: 1px solid rgba(108,122,224,0.20);
    border-radius: 6px;
    padding: 8px 12px;
}
QLabel#priceBarIcon { font-size: 14px; }
QLabel#priceBarName { color: #f0f1f2; font-size: 12px; font-weight: 500; }
QLabel#priceBarPrice { color: #e8a23a; font-weight: 600; }
QLabel#priceBarUpdated { color: #8a8f98; font-size: 11px; }
QLabel#priceBarSub { color: #8a8f98; font-size: 11px; }
QFrame#popupFeeBox {
    background: rgba(232,162,58,0.08);
    border: 1px solid rgba(232,162,58,0.25);
    border-radius: 6px;
}

/* ===== TOKEN BANNER ===== */
QFrame#tokenBanner {
    background: rgba(232,162,58,0.08);
    border: 1px solid rgba(232,162,58,0.20);
    border-radius: 6px;
    padding: 8px 12px;
}
QLabel#tokenBannerText { color: #e8a23a; font-size: 11px; }

/* ===== SUBTEXT UI (🎭 潜文本卡) ===== */
QFrame#subtextModeHeader {
    background: rgba(108,122,224,0.06);
    border: 1px solid rgba(108,122,224,0.18);
    border-radius: 6px;
    padding: 10px 12px;
}
QLabel#subtextHeaderTitle { font-size: 13px; font-weight: 600; color: #f0f1f2; }
QLabel#subtextModeLabel { color: #c8cdd4; font-size: 12px; }
QLabel#subtextListLabel { color: #8a8f98; font-size: 11px; padding: 2px 4px; }
QLabel#subtextChapterStatus { color: #c8cdd4; font-size: 11px; padding: 2px 4px; }
QLabel#fieldLabel { color: #c8cdd4; font-size: 12px; padding-top: 4px; }
QPlainTextEdit#fieldEditor {
    background: #0f1011;
    color: #f0f1f2;
    border: 1px solid #2a2b2f;
    border-radius: 4px;
    padding: 4px 6px;
    font-size: 12px;
}
QPlainTextEdit#fieldEditor:focus { border-color: #6c7ae0; }
QToolButton#fieldHelpBtn {
    background: #191a1b;
    color: #7d8aff;
    border: 1px solid #2a2b2f;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 700;
    padding: 0;
}
QToolButton#fieldHelpBtn:hover { background: #222326; border-color: #6c7ae0; }

/* 4.0 修复: ThemeToggle 之前 setStyleSheet 硬编码 #191a1b, 亮色下整个切换器还是黑块 */
QWidget#themeToggle {
    background: #191a1b;
    border: 1px solid #2a2b2f;
    border-radius: 4px;
    padding: 2px;
}
QPushButton#themeBtn {
    background: transparent; color: #8a8f98; border: none;
    border-radius: 3px; padding: 4px 12px; font-size: 12px;
}
QPushButton#themeBtn:hover { color: #c8cdd4; }
QPushButton#themeBtn:checked { background: #6c7ae0; color: #ffffff; }

/* 4.0 修复: 一键出版 (PublishWizard) 4 处硬编码暗色 — 切到亮色主题整页变黑 */
QFrame#formatCard {
    background: #191a1b;
    border: 1px solid #2a2b2f;
    border-radius: 6px;
    padding: 10px;
}
QRadioButton#formatRadio { color: #f0f1f2; font-weight: 600; font-size: 14px; }
QLabel#formatSub { color: #8a8f98; font-size: 11px; }

QFrame#pwHeader {
    background: #0a0b0d;
    border-bottom: 1px solid #2a2b2f;
}
QFrame#pwHeader QLabel { color: #f0f1f2; }
QLabel#pwTitle { font-size: 15px; font-weight: 600; }
QLabel#pwSubtitle { color: #8a8f98; font-size: 11px; }

/* 4.1 修复: 补齐 statLabel/statValue/statSub 暗色样式, 之前只在 LIGHT 出现 */
QLabel#statLabel { color: #8a8f98; font-size: 11px; font-weight: 500; }
QLabel#statValue { color: #f0f1f2; font-size: 26px; font-weight: 600; letter-spacing: -0.02em; }
QLabel#statSub { color: #555a63; font-size: 11px; }

/* 4.0 修复: settings 左导航 _NAV_QSS 硬编码 #cbd5e1/#ffffff — 亮色主题下文字看不清 */
QListWidget#settingsNav {
    background: transparent;
    border: none;
    outline: 0;
    padding: 4px 0;
}
QListWidget#settingsNav::item {
    color: #c8cdd4;
    padding: 9px 14px 9px 16px;
    border-left: 3px solid transparent;
    margin: 0;
    font-size: 12px;
}
QListWidget#settingsNav::item:hover {
    background: rgba(255, 255, 255, 0.06);
    color: #f0f1f2;
}
QListWidget#settingsNav::item:selected {
    background: rgba(108, 122, 224, 0.18);
    color: #f0f1f2;
    border-left: 3px solid #6c7ae0;
    font-weight: 600;
}

/* 4.1 修复: 当前项目卡片高亮 (暗色) */
QFrame#card[is_current="true"] {
    border: 2px solid #6c7ae0;
    background: rgba(108, 122, 224, 0.08);
}
"""


# ---- 亮色 (镜像 mockup body.light) ----
LIGHT_QSS = """
* { outline: 0; }

/* ===== 基础 ===== */
QMainWindow, QWidget {
    background: #f5f6f7;
    color: #1a1c1e;
    font-family: "Inter", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", -apple-system, system-ui, sans-serif;
    font-size: 13px;
}
QToolTip {
    background: #ffffff;
    color: #1a1c1e;
    border: 1px solid #d0d4db;
    border-radius: 4px;
    padding: 4px 6px;
    font-size: 12px;
}

/* ===== TITLE BAR (v4.0 mockup 1:1) ===== */
QWidget#titleBar { background: #ffffff; border-bottom: 1px solid #eef0f3; }
QLabel#titleBarLogo { color: #4a5058; font-size: 12px; font-weight: 600; }
QLabel#titleBarLogoAccent { color: #5a68c9; font-weight: 600; }
QFrame#titleBarDotR { background: #e05050; border-radius: 6px; }
QFrame#titleBarDotY { background: #e0b040; border-radius: 6px; }
QFrame#titleBarDotG { background: #40b060; border-radius: 6px; }
QWidget#sidebarHeader { background: transparent; }

/* ===== SIDEBAR FOOTER ===== */
QLabel#sidebarFooter { color: #9ca3ad; font-size: 11px; padding: 2px 4px; }

/* ===== SIDEBAR ===== */
QWidget#sidebar { background: #ffffff; border-right: 1px solid #e0e3e8; }
QLabel#sidebarHeader { color: #4a5058; font-size: 13px; font-weight: 600; padding: 6px 4px; }
QListWidget#navList {
    background: transparent; border: none; outline: 0;
    color: #6b727c; font-size: 13px; padding: 0;
}
QListWidget#navList::item {
    padding: 7px 12px 7px 28px;
    border-radius: 0;
    border-left: 2px solid transparent;
    color: #6b727c;
}
QListWidget#navList::item:hover { background: #f0f1f3; color: #4a5058; }
QListWidget#navList::item:selected {
    background: rgba(90,104,201,0.10);
    color: #5a68c9;
    border-left: 2px solid #5a68c9;
    font-weight: 600;
}
QListWidget#navList::item[groupLabel="true"] {
    color: #9ca3ad;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 10px 12px 4px 12px;
    background: transparent;
    border-left: 0;
}
QListWidget#navList::item:disabled { color: #9ca3ad; }
QFrame#sidebarProject {
    background: rgba(90,104,201,0.10);
    border-radius: 6px;
    padding: 6px 8px;
    margin: 0 10px 8px 10px;
}
QLabel#sidebarProjectName { color: #1a1c1e; font-size: 12px; font-weight: 600; }
QLabel#sidebarProjectMeta { color: #6b727c; font-size: 11px; }

/* ===== CONTENT TOPBAR ===== */
QFrame#contentTopbar { background: #f5f6f7; border-bottom: 1px solid #e0e3e8; }
QLabel#contentTopbarTitle { color: #1a1c1e; font-size: 15px; font-weight: 600; letter-spacing: -0.01em; }
QLabel#contentTopbarBadge {
    background: rgba(90,104,201,0.10);
    color: #5a68c9;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 500;
}

/* ===== STATUS BAR ===== */
QStatusBar {
    background: #ffffff;
    color: #6b727c;
    border-top: 1px solid #e0e3e8;
    font-size: 11px;
}
QStatusBar::item { border: none; }
QLabel#statusBarSep { color: #d0d4db; padding: 0 8px; }
QLabel#statusBarIndicator { color: #6b727c; font-size: 11px; }
QLabel#statusBarIndicatorOk { color: #1a8a3e; font-weight: 600; }
QLabel#statusBarIndicatorWarn { color: #c58a1a; font-weight: 600; }

/* ===== CONTENT BODY ===== */
QWidget#contentBody { background: #f5f6f7; }

/* ===== CARDS ===== */
QFrame#card {
    background: #ffffff;
    border: 1px solid #e0e3e8;
    border-radius: 8px;
    padding: 16px;
}
QFrame#cardHoverable:hover { border-color: #b0b5bd; }
QLabel#cardTitle { color: #1a1c1e; font-size: 13px; font-weight: 600; }
QLabel#cardSub { color: #6b727c; font-size: 11px; }

/* ===== STAT CARDS ===== */
QLabel#statLabel { color: #6b727c; font-size: 11px; font-weight: 500; }
QLabel#statValue { color: #1a1c1e; font-size: 26px; font-weight: 600; letter-spacing: -0.02em; }
QLabel#statSub { color: #9ca3ad; font-size: 11px; }
/* 4.0 修复: 跟暗色主题对应, 亮色主题下也走 QSS 而不是硬编码 */
QFrame#statCard {
    background: #ffffff;
    border: 1px solid #e0e3e8;
    border-radius: 6px;
}
QLabel#statCardLabel { color: #6b727c; font-size: 12px; }
/* 仪表盘卡片 — 亮色主题 */
QFrame#rhythmCard, QFrame#weakCard {
    background: #ffffff;
    border: 1px solid #e0e3e8;
    border-radius: 6px;
}
QLabel#cardTitle {
    color: #4a5058;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}
QFrame#router_status_bar {
    background: #f8f9fa;
    border: 1px solid #e0e3e8;
    border-radius: 4px;
}
QLabel#routerStatusLabel { color: #4a5058; font-size: 11px; }
/* LOG VIEWER 亮色: 跟暗色同样的布局, 背景/文字/边框 用浅色 token */
QPlainTextEdit#logViewer {
    background: #ffffff;
    color: #1a1c1e;
    font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    border: 1px solid #e0e3e8;
    border-radius: 6px;
}

/* ===== TABLES ===== */
QHeaderView::section {
    background: #f0f1f3;
    color: #4a5058;
    border: none;
    border-bottom: 1px solid #e0e3e8;
    padding: 6px 8px;
    font-weight: 600;
    font-size: 11px;
}
QTableWidget, QTableView {
    background: #ffffff;
    alternate-background-color: #fafbfc;
    border: 1px solid #e0e3e8;
    border-radius: 6px;
    gridline-color: #eef0f3;
    selection-background-color: rgba(90,104,201,0.18);
    color: #1a1c1e;
}
QTableWidget::item, QTableView::item {
    padding: 6px 8px;
    border-bottom: 1px solid #eef0f3;
    color: #4a5058;
}

/* ===== BUTTONS ===== */
QPushButton {
    background: #ffffff;
    color: #1a1c1e;
    border: 1px solid #d0d4db;
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton:hover { background: #f0f1f3; border-color: #b0b5bd; }
QPushButton:pressed { background: #e8eaed; }
QPushButton:disabled { color: #9ca3ad; background: #f5f6f7; border-color: #eef0f3; }
QPushButton#btnPrimary { background: #5a68c9; color: #ffffff; border: 1px solid #5a68c9; font-weight: 600; }
QPushButton#btnPrimary:hover { background: #4b58b0; border-color: #4b58b0; }
QPushButton#btnGhost { background: transparent; border-color: transparent; }
QPushButton#btnGhost:hover { background: #f0f1f3; }
QPushButton#btnDanger { color: #c43030; border-color: rgba(196,48,48,0.30); }
QPushButton#btnDanger:hover { background: rgba(196,48,48,0.06); }
QPushButton#btnSm { padding: 3px 8px; font-size: 11px; }
QPushButton#btnIcon { padding: 3px 5px; font-size: 13px; min-width: 22px; }

/* v4.0 patch: ModuleNav 导航按钮 (亮色主题) */
QPushButton#navBtn {
    text-align: left;
    padding: 6px 4px 6px 14px;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: #6b727c;
    font-size: 12px;
}
QPushButton#navBtn:hover {
    background: rgba(90,104,201,0.06);
    color: #1a1c1e;
}
QPushButton#navBtn:checked {
    background: rgba(90,104,201,0.12);
    color: #5a68c9;
    font-weight: 700;
}

/* v4.0 patch: 侧边栏底部齿轮按钮 (亮色) */
QPushButton#gearBtn {
    background: transparent; border: none;
    font-size: 15px; color: #9ca3ad;
}
QPushButton#gearBtn:hover { color: #4a5058; }

/* v4.0 patch: ModuleNav 容器 (背景透明, 由 #sidebar 控制) */
QWidget#moduleNav { background: transparent; border: none; }

/* ===== CHECKBOXES ===== */
QCheckBox {
    color: #1a1c1e;
    spacing: 8px;
    font-size: 13px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #bcc2cc;
    border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #5a68c9;
}
QCheckBox::indicator:checked {
    background: #5a68c9;
    border-color: #5a68c9;
}
QCheckBox::indicator:checked:hover {
    background: #6b7adc;
    border-color: #6b7adc;
}
QCheckBox::indicator:disabled {
    border-color: #d0d4db;
    background: #f0f1f3;
}
QCheckBox::indicator:checked:disabled {
    background: #bcc2cc;
    border-color: #bcc2cc;
}

/* ===== INPUTS ===== */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {
    background: #ffffff;
    color: #1a1c1e;
    border: 1px solid #d0d4db;
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 13px;
    selection-background-color: rgba(90,104,201,0.30);
}
QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    color: #1a1c1e;
    border: 1px solid #d0d4db;
    border-radius: 6px;
    font-size: 13px;
    selection-background-color: rgba(90,104,201,0.30);
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #5a68c9;
}

/* ===== LISTS / TREES ===== */
QListWidget, QTreeWidget {
    background: #ffffff;
    color: #1a1c1e;
    border: 1px solid #e0e3e8;
    border-radius: 6px;
    alternate-background-color: #fafbfc;
}
QListWidget::item, QTreeWidget::item { padding: 5px 8px; border-radius: 3px; color: #4a5058; }
QListWidget::item:selected, QTreeWidget::item:selected {
    background: rgba(90,104,201,0.12);
    color: #1a1c1e;
}

/* ===== TABS ===== */
QTabWidget::pane { border: 1px solid #e0e3e8; border-radius: 6px; top: -1px; background: #ffffff; }
QTabBar::tab {
    background: transparent;
    color: #6b727c;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 7px 14px;
    font-size: 12px;
    font-weight: 500;
    margin-right: 4px;
}
QTabBar::tab:selected { color: #5a68c9; border-bottom: 2px solid #5a68c9; }
QTabBar::tab:hover:!selected { color: #4a5058; }

/* ===== GROUP BOX ===== */
QGroupBox {
    border: 1px solid #e0e3e8;
    border-radius: 6px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
    color: #4a5058;
    font-weight: 600;
    font-size: 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    background: #f5f6f7;
}

/* ===== SCROLLBAR ===== */
QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
QScrollBar::handle:vertical { background: #d0d4db; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #b0b5bd; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 6px; margin: 0; }
QScrollBar::handle:horizontal { background: #d0d4db; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ===== PROGRESS BAR ===== */
QProgressBar {
    background: #f0f1f3;
    border: 1px solid #e0e3e8;
    border-radius: 6px;
    text-align: center;
    color: #4a5058;
    height: 14px;
}
QProgressBar::chunk { background: #5a68c9; border-radius: 5px; }

/* ===== DIALOGS / MENUS ===== */
QMessageBox, QDialog { background: #ffffff; color: #1a1c1e; }
QMenu { background: #ffffff; border: 1px solid #e0e3e8; padding: 4px; color: #1a1c1e; }
QMenu::item { padding: 5px 18px; border-radius: 3px; }
QMenu::item:selected { background: rgba(90,104,201,0.12); color: #1a1c1e; }

/* ===== PRICE BAR (Tokens 提示价格条) ===== */
QFrame#priceBar {
    background: rgba(90,104,201,0.04);
    border: 1px solid rgba(90,104,201,0.18);
    border-radius: 6px;
    padding: 8px 12px;
}
QLabel#priceBarIcon { font-size: 14px; }
QLabel#priceBarName { color: #1a1c1e; font-size: 12px; font-weight: 500; }
QLabel#priceBarPrice { color: #c58a1a; font-weight: 600; }
QLabel#priceBarUpdated { color: #6b727c; font-size: 11px; }
QLabel#priceBarSub { color: #6b727c; font-size: 11px; }
QFrame#popupFeeBox {
    background: rgba(197,138,26,0.06);
    border: 1px solid rgba(197,138,26,0.25);
    border-radius: 6px;
}

/* ===== TOKEN BANNER ===== */
QFrame#tokenBanner {
    background: rgba(197,138,26,0.06);
    border: 1px solid rgba(197,138,26,0.25);
    border-radius: 6px;
    padding: 8px 12px;
}
QLabel#tokenBannerText { color: #c58a1a; font-size: 11px; }

/* ===== SUBTEXT UI (🎭 潜文本卡) ===== */
QFrame#subtextModeHeader {
    background: rgba(90,104,201,0.04);
    border: 1px solid rgba(90,104,201,0.16);
    border-radius: 6px;
    padding: 10px 12px;
}
QLabel#subtextHeaderTitle { font-size: 13px; font-weight: 600; color: #1a1c1e; }
QLabel#subtextModeLabel { color: #4a5058; font-size: 12px; }
QLabel#subtextListLabel { color: #6b727c; font-size: 11px; padding: 2px 4px; }
QLabel#subtextChapterStatus { color: #4a5058; font-size: 11px; padding: 2px 4px; }
QLabel#fieldLabel { color: #4a5058; font-size: 12px; padding-top: 4px; }
QPlainTextEdit#fieldEditor {
    background: #ffffff;
    color: #1a1c1e;
    border: 1px solid #d0d4db;
    border-radius: 4px;
    padding: 4px 6px;
    font-size: 12px;
}
QPlainTextEdit#fieldEditor:focus { border-color: #5a68c9; }
QToolButton#fieldHelpBtn {
    background: #ffffff;
    color: #5a68c9;
    border: 1px solid #d0d4db;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 700;
    padding: 0;
}
QToolButton#fieldHelpBtn:hover { background: #f0f1f3; border-color: #5a68c9; }

/* 4.0 修复: ThemeToggle 亮色版本 — 之前暗色硬编码, 切到亮色下切换器还是黑底 */
QWidget#themeToggle {
    background: #ffffff;
    border: 1px solid #d0d4db;
    border-radius: 4px;
    padding: 2px;
}
QPushButton#themeBtn {
    background: transparent; color: #6b727c; border: none;
    border-radius: 3px; padding: 4px 12px; font-size: 12px;
}
QPushButton#themeBtn:hover { color: #1a1c1e; }
QPushButton#themeBtn:checked { background: #5a68c9; color: #ffffff; }

/* 4.0 修复: 一键出版 (PublishWizard) 亮色版本 */
QFrame#formatCard {
    background: #ffffff;
    border: 1px solid #d0d4db;
    border-radius: 6px;
    padding: 10px;
}
QRadioButton#formatRadio { color: #1a1c1e; font-weight: 600; font-size: 14px; }
QLabel#formatSub { color: #6b727c; font-size: 11px; }

QFrame#pwHeader {
    background: #ffffff;
    border-bottom: 1px solid #e0e3e8;
}
QFrame#pwHeader QLabel { color: #1a1c1e; }
QLabel#pwTitle { font-size: 15px; font-weight: 600; }
QLabel#pwSubtitle { color: #6b727c; font-size: 11px; }

/* 4.0 修复: settings 左导航 _NAV_QSS 亮色版本 */
QListWidget#settingsNav {
    background: transparent;
    border: none;
    outline: 0;
    padding: 4px 0;
}
QListWidget#settingsNav::item {
    color: #4a5058;
    padding: 9px 14px 9px 16px;
    border-left: 3px solid transparent;
    margin: 0;
    font-size: 12px;
}
QListWidget#settingsNav::item:hover {
    background: rgba(90, 104, 201, 0.06);
    color: #1a1c1e;
}
QListWidget#settingsNav::item:selected {
    background: rgba(90, 104, 201, 0.12);
    color: #5a68c9;
    border-left: 3px solid #5a68c9;
    font-weight: 600;
}

/* 4.0 修复: 当前项目卡片高亮 (亮色) */
QFrame#card[is_current="true"] {
    border: 2px solid #5a68c9;
    background: rgba(90, 104, 201, 0.06);
}
QFrame#card[is_current="true"]:hover {
    border-color: #4b58b0;
}
"""


class ThemeManager(QObject):
    """全局主题切换. 单例."""

    changed = Signal(str)  # theme name

    _instance: "ThemeManager | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._current: ThemeName = "dark"

    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def current(self) -> ThemeName:
        return self._current

    def apply(self, app: QApplication, name: ThemeName) -> None:
        qss = DARK_QSS if name == "dark" else LIGHT_QSS
        app.setStyleSheet(qss)
        self._current = name
        log.info("主题已切换: %s", name)
        self.changed.emit(name)

    def toggle(self, app: QApplication) -> ThemeName:
        new = "light" if self._current == "dark" else "dark"
        self.apply(app, new)
        return new


# ---- 模块级单例辅助函数 ----

def get_theme() -> ThemeManager:
    return ThemeManager.instance()


# --------------------------------------------------------------------- #
# 4.0 修复: 自绘图表的 QPainter 没法走 QSS, 需要在 paintEvent 取主题色.
# 抽到 theme 模块统一管, 避免每个图表 (TrendChart / _SimpleLineChart /
# _WorldGraphView) 都自己 _palette() 重复实现.
# --------------------------------------------------------------------- #

def chart_palette() -> "tuple[str, str, str, str]":
    """返回当前主题下的图表 4 绘图色: (bg, fg_title, fg_label, grid).

    4.0 修复: 之前 dashboard / world-graph / usage-analytics 3 个自绘图表
    全部硬编码 #191a1b 等暗色, 切到亮色主题还是黑底. 现在都改用这个函数.
    """
    if get_theme().current() == "dark":
        return ("#191a1b", "#c8cdd4", "#8a8f98", "#2a2b2f")
    return ("#ffffff", "#1a1c1e", "#6b727c", "#eef0f3")


def graph_palette() -> "tuple[str, str, str, str]":
    """世界图谱 4 绘图色: (bg, edge, node_stroke, label).

    4.0 修复: 跟 chart_palette 一样, 暗色/亮色 主题自适应.
    """
    if get_theme().current() == "dark":
        return ("#191a1b", "#3a3b3e", "#f0f1f2", "#c8cdd4")
    return ("#ffffff", "#e0e3e8", "#1a1c1e", "#1a1c1e")


# --------------------------------------------------------------------- #
# 4.0 修复: pages.py 散布 hardcoded 颜色字符串, 切主题后 inline 样式不跟随.
# 抽到 theme 模块统一管, pages.py 里只写 setStyleSheet(font_size/font_weight),
# 颜色改走这些函数.
# --------------------------------------------------------------------- #

def text_primary() -> str:
    """主文字色 (标题、卡片名)。"""
    return "#f0f1f2" if get_theme().current() == "dark" else "#1a1c1e"


def text_secondary() -> str:
    """次文字色 (sidebar header、title bar logo)。"""
    return "#c8cdd4" if get_theme().current() == "dark" else "#4a5058"


def text_muted() -> str:
    """辅助文字色 (meta、stat label、project sub)。"""
    return "#8a8f98" if get_theme().current() == "dark" else "#6b727c"


def text_subtle() -> str:
    """淡化文字色 (footer、hint)。"""
    return "#555a63" if get_theme().current() == "dark" else "#9ca3ad"


def text_warn() -> str:
    """警告/高亮文字色 (错误提示、价格)。"""
    return "#e8a23a" if get_theme().current() == "dark" else "#c58a1a"


def text_accent() -> str:
    """强调/品牌色 (高亮元素、链接)。"""
    return "#7d8aff" if get_theme().current() == "dark" else "#5a68c9"


def surface_bg() -> str:
    """卡片/输入框背景色 (QSS 中的 surface)。"""
    return "#191a1b" if get_theme().current() == "dark" else "#ffffff"


def deep_bg() -> str:
    """主内容区底色 (QSS 中的 bg-deep)。"""
    return "#0f1011" if get_theme().current() == "dark" else "#f5f6f7"


def border_color() -> str:
    """边框色 (QSS 中的 border)。"""
    return "rgba(255,255,255,0.08)" if get_theme().current() == "dark" else "#e0e3e8"


def input_bg() -> str:
    """输入控件背景色。"""
    return "#191a1b" if get_theme().current() == "dark" else "#ffffff"


def is_dark() -> bool:
    """当前是否为暗色主题."""
    return get_theme().current() == "dark"


# --------------------------------------------------------------------- #
# 4.1 修复: 引入与 QSS token 一一对应的 helper, 替代 pages.py / settings_tab.py
# 散布的 setStyleSheet 硬编码颜色, 实现主题切换真正一致.
# --------------------------------------------------------------------- #

def text_warn_ok() -> str:
    """成功/绿色提示文字色 (status ok / success label)。"""
    return "#34a853" if get_theme().current() == "dark" else "#1a8a3e"


def text_danger() -> str:
    """危险/红色提示文字色 (error / required)。"""
    return "#d94040" if get_theme().current() == "dark" else "#c43030"


def text_indigo() -> str:
    """强调/品牌主色 (btnPrimary / active 边框, 比 text_accent 更饱和)。"""
    return "#6c7ae0" if get_theme().current() == "dark" else "#5a68c9"


def text_indigo_strong() -> str:
    """强调/品牌 hover 色。"""
    return "#7d8aff" if get_theme().current() == "dark" else "#4b58b0"


def hover_bg() -> str:
    """通用 hover 底色。"""
    return "#222326" if get_theme().current() == "dark" else "#f0f1f3"


def pressed_bg() -> str:
    """通用 pressed/active 底色。"""
    return "#28282c" if get_theme().current() == "dark" else "#e8eaed"


def border_strong() -> str:
    """强边框色 (input / 分割线) - 比 border_color 饱和度高。"""
    return "#2a2b2f" if get_theme().current() == "dark" else "#d0d4db"


def list_header_bg() -> str:
    """列表头/分隔标题底色 (lbl_list_header, projListHeader) - 比 bg_surface 略深/浅。"""
    return "rgba(255,255,255,0.04)" if get_theme().current() == "dark" else "rgba(0,0,0,0.03)"


def accent_tint_bg(opacity: float = 0.12) -> str:
    """品牌色淡底 (current project state, active chip 等)。"""
    if get_theme().current() == "dark":
        r, g, b = 108, 122, 224  # #6c7ae0
    else:
        r, g, b = 90, 104, 201   # #5a68c9
    return f"rgba({r},{g},{b},{opacity})"


def accent_tint_border(opacity: float = 0.25) -> str:
    """品牌色淡边。"""
    if get_theme().current() == "dark":
        r, g, b = 108, 122, 224
    else:
        r, g, b = 90, 104, 201
    return f"rgba({r},{g},{b},{opacity})"


def mock_mode_bg() -> str:
    """Mock 模式标签背景色 (明暗主题下都是高对比橙色, 用于警示)"""
    return "#e67e22"


# --------------------------------------------------------------------- #
# 4.1 颜色 token 补齐: 覆盖残留的硬编码 (蓝/紫/绿/橙/红系列)
# --------------------------------------------------------------------- #

def text_info() -> str:
    """信息色 (蓝色, TTS status / editor 评分)"""
    return "#4a90e2" if get_theme().current() == "dark" else "#1976d2"


def text_score_purple() -> str:
    """评分紫色 (Hook score)"""
    return "#b39ddb" if get_theme().current() == "dark" else "#7b1fa2"


def text_score_blue() -> str:
    """评分蓝色 (Critic score)"""
    return "#64b5f6" if get_theme().current() == "dark" else "#1976d2"


def text_success() -> str:
    """成功绿 (issues list 空)"""
    return "#81c784" if get_theme().current() == "dark" else "#388e3c"


def text_orange() -> str:
    """橙色 (TTS loading / round label)"""
    return "#ffb74d" if get_theme().current() == "dark" else "#f57c00"


def text_danger_strong() -> str:
    """强红 (TTS error / error state)"""
    return "#ef5350" if get_theme().current() == "dark" else "#c62828"


def text_accent_violet() -> str:
    """紫罗兰 (conv creation status)"""
    return "#a78bfa" if get_theme().current() == "dark" else "#7c3aed"


def score_value() -> str:
    """评分高亮色 (数字)"""
    return "#cdd6f4" if get_theme().current() == "dark" else "#1a1c1e"


def text_meta() -> str:
    """次级 meta 文字 (stat value)"""
    return "#a6adc8" if get_theme().current() == "dark" else "#4a5058"


def text_hint() -> str:
    """提示文字 (hint label)"""
    return "#585b70" if get_theme().current() == "dark" else "#8a8f98"


def text_chip() -> str:
    """多色 chip 文字 (placeholder/label)"""
    return "#8a8a8a" if get_theme().current() == "dark" else "#6b727c"


def text_chip_dim() -> str:
    """chip dim (detail)"""
    return "#808080" if get_theme().current() == "dark" else "#8a8f98"


def text_chip_secondary() -> str:
    """chip secondary"""
    return "#909090" if get_theme().current() == "dark" else "#6b727c"


def text_card_emphasis() -> str:
    """卡片强调 (advice label)"""
    return "#e0e0e0" if get_theme().current() == "dark" else "#1a1c1e"


def text_card_label() -> str:
    """卡片 label (title in guide panel)"""
    return "#c0c0c0" if get_theme().current() == "dark" else "#4a5058"


def border_success() -> str:
    """成功绿边框 (3px edit border)"""
    return "#4ade80" if get_theme().current() == "dark" else "#16a34a"


def mock_mode_fg() -> str:
    """Mock 模式标签文字色 (高对比白色, 不分主题)"""
    return "#ffffff"
