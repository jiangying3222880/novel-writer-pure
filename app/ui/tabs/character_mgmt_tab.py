# -*- coding: utf-8 -*-
"""
角色管理 Tab (Character Management Tab)

卡片式展示角色列表，点击卡片查看详情。
集成声音档案功能，每个角色关联各自的声音档案。
"""
from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QDialog, QFormLayout,
    QLineEdit, QTextEdit, QComboBox, QMessageBox,
    QSizePolicy, QGroupBox
)

from app.services import setting_service, ServiceError
from app.services.voice_profile import (
    get as get_voice_profile,
    upsert as upsert_voice_profile,
    VoiceProfile,
    DIMENSION_LABELS
)
from app.ui.widgets import Dialogs
from app.ui.widgets._number_input import NumberInput

# 角色在 project_settings 中的 key
CHARACTERS_KEY = "characters"


# --------------------------------------------------------------------- #
# 角色卡片组件
# --------------------------------------------------------------------- #

# ── 身份 → 卡片颜色映射 ──
IDENTITY_COLORS: dict[str, dict[str, str]] = {
    "主角": {"border": "#8b5cf6", "bg": "rgba(139,92,246,0.08)", "accent": "#a78bfa", "icon": "🧑"},
    "反派": {"border": "#ff4757", "bg": "rgba(255,71,87,0.08)",  "accent": "#ff6b7a", "icon": "💀"},
    "配角": {"border": "#4ec970", "bg": "rgba(78,201,112,0.08)",  "accent": "#6dd98a", "icon": "🙂"},
    "路人": {"border": "#9ca3af", "bg": "rgba(156,163,175,0.06)", "accent": "#b0b7c3", "icon": "🚶"},
}
IDENTITY_DEFAULT_COLOR = {"border": "#6c7ae0", "bg": "rgba(108,122,224,0.06)", "accent": "#8b96f0", "icon": "👤"}

# ── 排序优先级 (越小越靠前) ──
IDENTITY_SORT_ORDER: dict[str, int] = {
    "主角": 0, "配角": 1, "反派": 2, "路人": 3,
}


class CharacterCard(QFrame):
    """角色卡片组件 (身份着色)"""
    
    clicked = Signal(str)  # 点击信号，传递角色名
    
    def __init__(self, character_data: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.character_name = character_data.get("name", "未知角色")
        self.character_data = character_data
        self._identity = character_data.get("identity", "") or ""
        self._color = IDENTITY_COLORS.get(self._identity, IDENTITY_DEFAULT_COLOR)
        self._build_ui()
    
    def _build_ui(self):
        """构建卡片UI"""
        self.setObjectName("characterCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        border = self._color["border"]
        bg = self._color["bg"]
        accent = self._color["accent"]
        identity_icon = self._color["icon"]
        identity_text = self._identity or "其他"
        
        # 动态样式 (按身份着色)
        self.setStyleSheet(f"""
            QFrame#characterCard {{
                background-color: #2a2a2a;
                border: 2px solid {border};
                border-radius: 8px;
                padding: 12px;
            }}
            QFrame#characterCard:hover {{
                border: 2px solid {accent};
                background-color: {bg};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # 身份标签
        identity_badge = QLabel(f"{identity_icon} {identity_text}")
        identity_badge.setStyleSheet(
            f"font-size: 11px; color: {accent}; font-weight: 600; "
            f"background: {bg}; border-radius: 4px; padding: 2px 8px;"
        )
        identity_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(identity_badge)
        
        # 角色名
        name_label = QLabel(self.character_name)
        from app.ui.theme import text_primary
        name_label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {text_primary()};")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_label)
        
        # 角色简介（截取前50字）
        desc = self.character_data.get("description", "")
        if desc:
            desc_preview = desc[:50] + "..." if len(desc) > 50 else desc
            desc_label = QLabel(desc_preview)
            from app.ui.theme import text_chip
            desc_label.setStyleSheet(f"font-size: 12px; color: {text_chip()};")
            desc_label.setWordWrap(True)
            desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(desc_label)
        
        # 声音档案标识
        voice_label = QLabel("🎙️ 声音档案")
        from app.ui.theme import text_indigo
        voice_label.setStyleSheet(f"font-size: 11px; color: {text_indigo()};")
        voice_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(voice_label)
        
        layout.addStretch()
    
    def mousePressEvent(self, event):
        """点击事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.character_name)
        super().mousePressEvent(event)


# --------------------------------------------------------------------- #
# 角色详情对话框
# --------------------------------------------------------------------- #

class CharacterDetailDialog(QDialog):
    """角色详情对话框（集成声音档案）"""
    
    deleted = Signal(str)  # 删除信号，传递角色名
    
    def __init__(self, character_data: dict, project_id: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.character_data = character_data
        self.project_id = project_id
        self.character_name = character_data.get("name", "未知角色")
        self._build_ui()
        self._load_voice_profile()
    
    def _build_ui(self):
        """构建对话框UI"""
        self.setWindowTitle(f"角色详情 - {self.character_name}")
        self.setMinimumSize(750, 650)
        self.setObjectName("characterDetailDialog")
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        # 角色基本信息
        basic_group = QGroupBox("基本信息")
        basic_layout = QFormLayout(basic_group)
        
        # 角色名
        self.name_edit = QLineEdit(self.character_name)
        basic_layout.addRow("角色名:", self.name_edit)
        
        # 角色身份 — 下拉选择 (仅叙事身份，不含人际关系)
        self.IDENTITY_OPTIONS = [
            "", "主角", "反派", "配角", "路人", "其他"
        ]
        identity = self.character_data.get("identity", "")
        self.identity_combo = QComboBox()
        self.identity_combo.setEditable(True)
        self.identity_combo.addItems(self.IDENTITY_OPTIONS)
        if identity in self.IDENTITY_OPTIONS:
            self.identity_combo.setCurrentText(identity)
        else:
            self.identity_combo.setCurrentText(identity)  # 兼容已有非标准身份
        self.identity_combo.setToolTip("故事中的叙事身份 — 由作者维护\n（如主角/反派/配角等）")
        basic_layout.addRow("身份:", self.identity_combo)

        # 性别
        gender = self.character_data.get("gender", "")
        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["", "男", "女", "未知"])
        if gender in ["男", "女", "未知"]:
            self.gender_combo.setCurrentText(gender)
        else:
            self.gender_combo.setCurrentText("")
        basic_layout.addRow("性别:", self.gender_combo)

        # 角色描述 — 带示例 placeholder
        description = self.character_data.get("description", "")
        self.description_edit = QTextEdit()
        self.description_edit.setPlainText(description)
        self.description_edit.setMaximumHeight(140)
        self.description_edit.setPlaceholderText(
            "角色描述示例：\n"
            "- 外貌特征：身高八尺、浓眉大眼、常穿素色长袍\n"
            "- 性格特点：外冷内热、做事果决、不善社交\n"
            "- 背景故事：出身寒门，少年时被逐出师门\n"
            "- 核心动机：寻找失散多年的亲人 / 为师父报仇\n"
            "- 与其他角色关系：XX的师弟、YY的暗恋对象"
        )
        basic_layout.addRow("描述:", self.description_edit)
        
        layout.addWidget(basic_group)
        
        # 声音档案
        voice_group = QGroupBox("🎙️ 声音档案")
        voice_layout = QFormLayout(voice_group)
        
        # 性格 (1-10) — 带 min/max 标注
        perso_row = QHBoxLayout()
        self.personality_spin = NumberInput(lo=1, hi=10, default=5)
        perso_row.addWidget(QLabel("1= 沉静内敛"))
        perso_row.addWidget(self.personality_spin)
        perso_row.addWidget(QLabel("10= 张扬外放"))
        perso_row.addStretch()
        voice_layout.addRow("性格:", perso_row)
        
        # 句长 (1-10)
        sent_row = QHBoxLayout()
        self.sentence_length_spin = NumberInput(lo=1, hi=10, default=5)
        sent_row.addWidget(QLabel("1= 惜字如金（对白极短）"))
        sent_row.addWidget(self.sentence_length_spin)
        sent_row.addWidget(QLabel("10= 滔滔不绝（大段对白）"))
        sent_row.addStretch()
        voice_layout.addRow("句长:", sent_row)
        
        # 语气词
        self.tone_words_edit = QLineEdit()
        self.tone_words_edit.setPlaceholderText("例如: 啊/呀/呢/吧  (用 / 分隔多个)")
        voice_layout.addRow("语气词:", self.tone_words_edit)
        
        # 口头禅
        self.catchphrases_edit = QLineEdit()
        self.catchphrases_edit.setPlaceholderText("例如: 岂有此理/有意思  (用 / 分隔多个)")
        voice_layout.addRow("口头禅:", self.catchphrases_edit)
        
        # 隐喻偏好 (1-10)
        meta_row = QHBoxLayout()
        self.metaphor_pref_spin = NumberInput(lo=1, hi=10, default=5)
        meta_row.addWidget(QLabel("1= 直白不用比喻"))
        meta_row.addWidget(self.metaphor_pref_spin)
        meta_row.addWidget(QLabel("10= 善用类比/典故"))
        meta_row.addStretch()
        voice_layout.addRow("隐喻偏好:", meta_row)
        
        layout.addWidget(voice_group)
        
        # 按钮
        btn_layout = QHBoxLayout()
        
        delete_btn = QPushButton("🗑 删除")
        delete_btn.setMinimumWidth(100)
        delete_btn.clicked.connect(self._on_delete)
        btn_layout.addWidget(delete_btn)
        
        btn_layout.addStretch()
        
        save_btn = QPushButton("💾 保存")
        save_btn.setMinimumWidth(100)
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
    
    def _load_voice_profile(self):
        """加载声音档案"""
        try:
            profile = get_voice_profile(self.project_id, self.character_name)
            self.personality_spin.setValue(profile.personality)
            self.sentence_length_spin.setValue(profile.sentence_length)
            self.tone_words_edit.setText(profile.tone_words)
            self.catchphrases_edit.setText(profile.catchphrases)
            self.metaphor_pref_spin.setValue(profile.metaphor_pref)
        except Exception as e:
            print(f"加载声音档案失败: {e}")
    
    def _on_save(self):
        """保存角色信息和声音档案"""
        try:
            # 更新角色基本信息
            self.character_data["name"] = self.name_edit.text().strip()
            self.character_data["identity"] = self.identity_combo.currentText().strip()
            self.character_data["gender"] = self.gender_combo.currentText().strip()
            self.character_data["description"] = self.description_edit.toPlainText().strip()
            
            # 更新声音档案
            upsert_voice_profile(
                self.project_id,
                self.character_name,
                personality=self.personality_spin.value(),
                sentence_length=self.sentence_length_spin.value(),
                tone_words=self.tone_words_edit.text().strip(),
                catchphrases=self.catchphrases_edit.text().strip(),
                metaphor_pref=self.metaphor_pref_spin.value()
            )
            
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
    
    def _on_delete(self):
        """删除角色"""
        name = self.character_data.get("name", "")
        reply = QMessageBox.question(
            self,
            "删除角色",
            f"确定要删除角色「{name}」吗？此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.deleted.emit(name)
            self.accept()


# --------------------------------------------------------------------- #
# 角色管理 Tab
# --------------------------------------------------------------------- #

class CharacterMgmtTab(QWidget):
    """角色管理 Tab"""
    
    def __init__(self):
        super().__init__()
        self.current_project: Optional[dict] = None
        self.characters: list[dict] = []
        self._build_ui()
    
    def _build_ui(self):
        """构建UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # 标题
        title = QLabel("👥 角色管理")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)
        
        # 说明
        desc = QLabel("以卡片形式展示角色，点击卡片查看和编辑角色详情（含声音档案）")
        from app.ui.theme import text_muted
        desc.setStyleSheet(f"color: {text_muted()}; font-size: 13px;")
        layout.addWidget(desc)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        
        add_btn = QPushButton("➕ 新建角色")
        add_btn.setMinimumWidth(120)
        add_btn.clicked.connect(self._on_add_character)
        btn_layout.addWidget(add_btn)
        
        import_btn = QPushButton("📥 导入角色")
        import_btn.setMinimumWidth(120)
        import_btn.clicked.connect(self._on_import_characters)
        btn_layout.addWidget(import_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # 角色卡片滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        self.cards_container = QWidget()
        self.cards_layout = QGridLayout(self.cards_container)
        self.cards_layout.setSpacing(16)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll.setWidget(self.cards_container)
        layout.addWidget(scroll, 1)
    
    def set_project(self, project: Optional[dict]):
        """设置当前项目"""
        self.current_project = project
        if project:
            self._load_characters()
        else:
            self.characters = []
            self._refresh_cards()
    
    def _load_characters(self):
        """加载角色列表"""
        if not self.current_project:
            return
        
        try:
            data = setting_service.get_setting(
                self.current_project["id"],
                CHARACTERS_KEY
            )
            self.characters = data.get("data") or []
        except ServiceError as e:
            print(f"加载角色失败: {e}")
            self.characters = []
        
        self._refresh_cards()
    
    def _refresh_cards(self):
        """刷新卡片显示 (按身份排序 + 颜色区分)"""
        # 清空现有卡片
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 按身份排序: 主角 → 配角 → 反派 → 路人 → 其他
        sorted_characters = sorted(
            self.characters,
            key=lambda c: IDENTITY_SORT_ORDER.get(c.get("identity", ""), 99)
        )
        
        # 添加角色卡片
        for idx, char_data in enumerate(sorted_characters):
            card = CharacterCard(char_data)
            card.clicked.connect(self._on_card_clicked)
            
            # 每行3个卡片
            row = idx // 3
            col = idx % 3
            self.cards_layout.addWidget(card, row, col)
        
        # 如果没有角色，显示提示
        if not self.characters:
            hint = QLabel("暂无角色，点击「新建角色」或「导入角色」开始")
            from app.ui.theme import text_muted
            hint.setStyleSheet(f"color: {text_muted()}; font-size: 14px; padding: 40px;")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cards_layout.addWidget(hint, 0, 0, 1, 3)
    
    def _on_card_clicked(self, character_name: str):
        """卡片点击事件"""
        # 找到对应的角色数据
        char_data = None
        for c in self.characters:
            if c.get("name") == character_name:
                char_data = c
                break
        
        if not char_data:
            return
        
        # 打开详情对话框
        dialog = CharacterDetailDialog(char_data, self.current_project["id"], self)
        dialog.deleted.connect(self._on_delete_character)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 保存更新后的角色数据
            self._save_characters()
            self._refresh_cards()
    
    def _on_delete_character(self, character_name: str):
        """删除角色"""
        self.characters = [c for c in self.characters if c.get("name") != character_name]
        self._save_characters()
        self._refresh_cards()
    
    def _on_add_character(self):
        """新建角色"""
        if not self.current_project:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        
        # 创建新角色数据
        new_char = {
            "name": "新角色",
            "identity": "",
            "gender": "",
            "description": ""
        }
        
        # 打开详情对话框编辑
        dialog = CharacterDetailDialog(new_char, self.current_project["id"], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.characters.append(new_char)
            self._save_characters()
            self._refresh_cards()
    
    def _on_import_characters(self):
        """导入角色"""
        if not self.current_project:
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        
        from PySide6.QtWidgets import QFileDialog
        from app.services import setting_io
        
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择角色文件",
            "",
            "JSON/Markdown (*.json *.md);;All files (*.*)"
        )
        
        if not path:
            return
        
        try:
            result = setting_io.import_setting(
                self.current_project["id"],
                CHARACTERS_KEY,
                path
            )
            self._load_characters()
            QMessageBox.information(
                self,
                "导入成功",
                f"已导入 {result.get('count', 0)} 个角色"
            )
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))
    
    def _save_characters(self):
        """保存角色列表"""
        if not self.current_project:
            return
        
        try:
            setting_service.set_setting(
                self.current_project["id"],
                CHARACTERS_KEY,
                self.characters
            )
        except ServiceError as e:
            QMessageBox.critical(self, "保存失败", str(e))
