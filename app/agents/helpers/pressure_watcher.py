"""
PressureWatcher (压力计)
业务场景: 评估当前章节的叙事压力 (green/yellow/orange/red) + 是否可开新钩子.

真实数据: 从 narrative_pressures 表读取项目最新压力记录.
无记录时: 根据伏笔/支线数计算默认压力.
"""
from __future__ import annotations
import logging
from typing import Any

from app.agents.base import AgentBase, AgentRole
from app.agents.report import Report, ReportKind

_logger = logging.getLogger("NovelWriter.agents.pressure_watcher")


class PressureWatcher(AgentBase):
    """压力计 (叙事张力)."""

    DEFAULT_KIND = ReportKind.PRESSURE

    def __init__(self, *, name: str = "PressureWatcher") -> None:
        super().__init__(name=name, role=AgentRole.PRESSURE)

    def _do_execute(self, task: dict) -> Report:
        ctx = task.get("context", {})
        project_id = ctx.get("project_id", "")
        # memory_zone 来自 MemoryKeeper 拼装结果 (Orchestrator 透传)
        memory_zone = ctx.get("memory_zone", "green")

        zone = memory_zone
        can_hook = True
        pressure_val = 0
        anti_rules_text = ""

        try:
            from app.services import pressure

            # 1) 优先读取项目最新压力记录
            latest = pressure.get_latest(project_id)
            if latest is not None:
                pressure_val = latest.pressure
                zone = latest.zone
            else:
                # 2) 无记录时: 根据伏笔数估算
                try:
                    from app.services import setting_service
                    hooks_data = setting_service.get_setting(project_id, "hooks")
                    hooks_raw = hooks_data.get("data", "") if hooks_data else ""
                    # 简单估: 每行一条伏笔 ≈ 1 个 active_hook
                    active_hooks = len([l for l in str(hooks_raw).split("\n") if l.strip()])
                except Exception:
                    active_hooks = 0
                pressure_val = pressure.compute_pressure(
                    active_hooks=max(0, min(active_hooks, 20)),
                    open_promises=max(0, min(active_hooks // 2, 10)),
                    unresolved_subplots=max(0, min(active_hooks // 3, 5)),
                )
                zone = pressure.compute_zone(pressure_val)

            # 3) 判断是否可开新钩子
            if zone in ("orange", "red"):
                can_hook = False

            # 4) 反规则格式化
            anti_rules_text = self._load_anti_rules(project_id)

        except Exception as e:
            _logger.debug("[pressure] 读取压力失败, 用 memory_zone: %s", e)

        suggestions = []
        if zone == "red":
            suggestions.append("压力过高, 优先收束旧线, 避免开新钩子")
        elif zone == "orange":
            suggestions.append("压力偏高, 慎开新钩子, 建议先收1-2条")
        elif zone == "yellow":
            suggestions.append("压力预警, 适度铺垫")

        return self._build_report(task, {
            "zone": zone,
            "can_open_hook": can_hook,
            "pressure": pressure_val,
            "anti_rules_text": anti_rules_text,
        }, suggestions=suggestions)

    def _load_anti_rules(self, project_id: str) -> str:
        """加载并格式化反规则, 预算 ~300 字."""
        try:
            from app.services import setting_service
            result = setting_service.get_setting(project_id, "anti_rules")
            data = result.get("data") if isinstance(result, dict) else None
            if not data:
                return ""
            if isinstance(data, list):
                lines = [f"- {x}" for x in data[:15] if str(x).strip()]
            elif isinstance(data, dict):
                lines = [f"- {k}: {v}" for k, v in list(data.items())[:15]]
            else:
                lines = [str(data)]
            return "\n".join(lines)[:300]
        except Exception as e:
            _logger.debug("[pressure] 加载反规则失败: %s", e)
            return ""
