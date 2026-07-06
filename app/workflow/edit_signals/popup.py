"""
app/workflow/edit_signals/popup.py

SignalPopup - 7 天节流弹窗 (§10.2).

首次发现 candidate 时弹 1 次:
  - 7 天节流 (last_popup_at)
  - 不在编辑器焦点 (避免打断心流)
  - 5 秒无操作自动消失
  - 默认焦点在 [暂不]
"""
from __future__ import annotations
import logging
import time
from pathlib import Path
from typing import Optional

_logger = logging.getLogger("NovelWriter.edit_signals.popup")

# 节流 (v3.0 §10.2)
POPUP_COOLDOWN_DAYS = 7
POPUP_AUTODISMISS_SEC = 5


class SignalPopup:
    """7 天节流弹窗控制器.

    持久化 (用 project 的 sidecar 目录):
      - last_popup_at: 上次弹窗时间戳
      - popup_muted: 用户点过 [不再提醒]
    """

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.config_path = self.project_dir / "sidecar" / "popup_config.json"
        self._config = self._load()

    def _load(self) -> dict:
        if not self.config_path.exists():
            return {}
        try:
            import json
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        import json
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self._config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @property
    def is_muted(self) -> bool:
        return bool(self._config.get("muted", False))

    def mute(self) -> None:
        """用户点 [不再提醒]."""
        self._config["muted"] = True
        self._save()

    def unmute(self) -> None:
        """用户重新开启."""
        self._config["muted"] = False
        self._save()

    def should_popup(self, *, candidate_count: int, now: Optional[float] = None) -> bool:
        """判断是否该弹.

        全部满足才弹:
          - candidate_count >= 1
          - 没被 mute
          - 距上次弹窗 ≥ 7 天
        """
        if candidate_count < 1:
            return False
        if self.is_muted:
            return False
        cur = now if now is not None else time.time()
        last = float(self._config.get("last_popup_at", 0) or 0)
        if last and (cur - last) < POPUP_COOLDOWN_DAYS * 86400:
            return False
        return True

    def mark_popped(self, *, now: Optional[float] = None) -> None:
        """标记已弹 (写入 last_popup_at)."""
        cur = now if now is not None else time.time()
        self._config["last_popup_at"] = cur
        self._save()

    # ── UI 弹窗 (PySide6, 失败不阻塞) ──

    def show(self, candidate_count: int, sample_pattern: str = "") -> Optional[str]:
        """弹窗 (PySide6). Returns 用户选择: "view" / "later" / "mute" / None.

        如果 should_popup() False, 静默 return None (不弹).
        """
        if not self.should_popup(candidate_count=candidate_count):
            return None
        try:
            from PySide6.QtCore import Qt, QTimer
            from PySide6.QtWidgets import QMessageBox
            box = QMessageBox()
            box.setWindowTitle("📚 发现候选 Skill")
            box.setText(f"📚 发现 {candidate_count} 条可沉淀 Skill")
            if sample_pattern:
                box.setInformativeText(f"示例: {sample_pattern}\n\n(下次弹窗: 7 天后)")
            view_btn = box.addButton("查看", QMessageBox.ActionRole)
            later_btn = box.addButton("暂不", QMessageBox.RejectRole)
            mute_btn = box.addButton("不再提醒", QMessageBox.DestructiveRole)
            box.setDefaultButton(later_btn)
            # 5 秒自动消失
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(box.reject)
            timer.start(POPUP_AUTODISMISS_SEC * 1000)
            box.exec()
            clicked = box.clickedButton()
            result: Optional[str] = None
            if clicked is view_btn:
                result = "view"
            elif clicked is later_btn:
                result = "later"
            elif clicked is mute_btn:
                self.mute()
                result = "mute"
            self.mark_popped()
            return result
        except Exception as e:
            # 测试 / 缺 GUI 时静默
            _logger.debug("弹窗失败 (silently): %s", e)
            return None


# ────────────────────── 全局辅助 ──────────────────────

def should_popup_for_project(project_dir: Path, candidate_count: int) -> bool:
    return SignalPopup(project_dir).should_popup(candidate_count=candidate_count)
