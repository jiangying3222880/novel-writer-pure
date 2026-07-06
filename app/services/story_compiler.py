"""
Story Compiler (v4.0 雏形)

修改 Unit → 自动分析影响范围 → 列出需同步修改的 Unit.

设计原则:
  - 雏形阶段: 基于 entry/exit 状态 + hook plant/payoff + event 关系
  - 不调 LLM, 不做自动改写——只列影响列表
  - 因果链分析: 修改 Unit A → 影响 Unit B (因为 B 承接了 A 的 Exit)

API:
  - analyze_impact(unit_id) → ImpactReport
  - ImpactReport 可直接注入 prompt 或 UI 展示
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

_logger = logging.getLogger("NovelWriter.services.story_compiler")


@dataclass
class ImpactedUnit:
    unit_id: str
    title: str = ""
    reason: str = ""
    impact_type: str = ""   # "exit_inherit" / "hook_depend" / "event_cascade" / "character_state"
    severity: float = 0.5   # 0-1 影响严重度


@dataclass
class ImpactReport:
    unit_id: str
    unit_title: str = ""
    impacted_units: list[ImpactedUnit] = field(default_factory=list)

    @property
    def has_impact(self) -> bool:
        return len(self.impacted_units) > 0

    @property
    def by_type(self) -> dict[str, list[ImpactedUnit]]:
        out: dict[str, list[ImpactedUnit]] = {}
        for u in self.impacted_units:
            out.setdefault(u.impact_type, []).append(u)
        return out

    def to_dict(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "unit_title": self.unit_title,
            "impacted_units": [
                {"unit_id": u.unit_id, "title": u.title, "reason": u.reason,
                 "impact_type": u.impact_type, "severity": u.severity}
                for u in self.impacted_units
            ],
            "by_type": {t: [u.unit_id for u in units] for t, units in self.by_type.items()},
        }

    def to_prompt_block(self) -> str:
        """格式化为 prompt 注入块."""
        if not self.has_impact:
            return ""

        lines = [
            f"\n## 📐 Impact Analysis (修改 {self.unit_title or self.unit_id[:8]} 的影响范围)",
            f"以下 {len(self.impacted_units)} 个 Unit 可能受本次修改影响, 建议检查:",
        ]

        for t, units in sorted(self.by_type.items()):
            type_label = {
                "exit_inherit": "入口状态继承",
                "hook_depend": "钩子依赖",
                "event_cascade": "事件级联",
                "character_state": "角色状态同步",
            }.get(t, t)
            lines.append(f"\n### {type_label}")
            for u in units:
                lines.append(f"- Unit {u.title or u.unit_id[:8]}: {u.reason}")

        return "\n".join(lines)


def analyze_impact(unit_id: str) -> ImpactReport:
    """分析修改 unit_id 对其他 Unit 的影响范围.

    四维度:
      1. exit_inherit: 后继 Unit 的 entry 继承自当前 Unit 的 exit
      2. hook_depend: 其他 Unit 的 hook plant/payoff 依赖当前 Unit 的 hook
      3. event_cascade: 其他 Unit 有事件引用当前 Unit 涉及的角色/世界状态
      4. character_state: 角色 tracker 最新记录的章节与当前 Unit 重叠
    """
    try:
        from app.services import story_unit_service_v2 as _unit_svc
        unit = _unit_svc.get(unit_id)
    except Exception:
        _logger.warning("无法获取 unit: %s", unit_id)
        return ImpactReport(unit_id=unit_id)

    report = ImpactReport(unit_id=unit_id, unit_title=unit.title or "")
    project_id = unit.project_id
    seen: set[str] = {unit_id}

    # ---- 维度 1: 后继 Unit 继承 entry ----
    try:
        next_unit = _unit_svc.get_next_unit(unit_id, order_type="story")
    except Exception:
        next_unit = None

    if next_unit and next_unit.id not in seen:
        # 检查后继 Unit 的 entry 是否来自当前 Unit 的 exit
        try:
            import json
            exit_commitments = json.loads(unit.exit_commitments) if unit.exit_commitments else []
            entry_chars = json.loads(next_unit.entry_characters) if next_unit.entry_characters else {}
            if exit_commitments or entry_chars or unit.exit_characters:
                report.impacted_units.append(ImpactedUnit(
                    unit_id=next_unit.id,
                    title=next_unit.title or "",
                    reason=f"继承当前 Unit 的 exit 状态 (commitments={len(exit_commitments)}, "
                           f"exit_chars={len(json.loads(unit.exit_characters or '{}'))})",
                    impact_type="exit_inherit",
                    severity=0.80,
                ))
                seen.add(next_unit.id)
        except Exception:
            pass

    # ---- 维度 2: 钩子依赖 ----
    try:
        from app.services import unit_hook_service as _hook_svc
        hooks = _hook_svc.list_for_unit(unit_id)
        hook_ids = {h.hook_id for h in hooks if h.hook_id}
        if hook_ids:
            all_project_hooks = _hook_svc.list_for_project(project_id)
            for h in all_project_hooks:
                if h.hook_id in hook_ids and h.unit_id != unit_id and h.unit_id not in seen:
                    report.impacted_units.append(ImpactedUnit(
                        unit_id=h.unit_id,
                        title="",
                        reason=f"共享钩子 {h.hook_id} (当前 plant ↔ 此处 {h.hook_type})",
                        impact_type="hook_depend",
                        severity=0.65,
                    ))
                    seen.add(h.unit_id)
    except Exception:
        pass

    # ---- 维度 3: 事件级联 ----
    try:
        from app.services import unit_event_service as _ev_svc
        events = _ev_svc.list_events_as_of_unit(project_id, unit_id)
        affected_entities: set[str] = set()
        for ev in events:
            if ev.get("entity_name"):
                affected_entities.add(str(ev["entity_name"]))
            if ev.get("field_name"):
                affected_entities.add(str(ev["field_name"]))

        if affected_entities:
            # 查整个项目的 event, 找其他 Unit 是否也涉及相同 entity
            # 用 project 级别检索——简化: 只查最近 50 条 event
            try:
                from app.db import _impl as _db_conn
                conn = _db_conn.get_conn()
                for entity in list(affected_entities)[:5]:
                    rows = conn.execute(
                        """
                        SELECT DISTINCT unit_id FROM story_events
                        WHERE project_id = ? AND unit_id != ?
                          AND (entity_name = ? OR field_name = ?)
                        ORDER BY created_at DESC
                        LIMIT 10
                        """,
                        (project_id, unit_id, entity, entity),
                    ).fetchall()
                    for row in rows:
                        uid = row["unit_id"]
                        if uid and uid not in seen:
                            report.impacted_units.append(ImpactedUnit(
                                unit_id=uid,
                                title="",
                                reason=f"共享事件实体: {entity}",
                                impact_type="event_cascade",
                                severity=0.55,
                            ))
                            seen.add(uid)
            except Exception:
                pass
    except Exception:
        pass

    # ---- 维度 4: 角色状态同步 ----
    try:
        from app.services import character_tracker as _ct
        all_latest = _ct.get_all_latest(project_id)
        unit_char_names: set[str] = set()
        import json
        for field_name in ("entry_characters", "exit_characters"):
            raw = getattr(unit, field_name, "") or ""
            try:
                chars = json.loads(raw)
                unit_char_names.update(str(k) for k in chars.keys())
            except Exception:
                pass
        if unit.pov_character:
            unit_char_names.add(unit.pov_character)

        for name in unit_char_names:
            if name in all_latest:
                snap = all_latest[name]
                if snap.chapter_id and snap.chapter_id != unit_id and snap.chapter_id not in seen:
                    report.impacted_units.append(ImpactedUnit(
                        unit_id=snap.chapter_id,
                        title="",
                        reason=f"角色 {name} 的最新 tracker 记录在该 Unit",
                        impact_type="character_state",
                        severity=0.50,
                    ))
                    seen.add(snap.chapter_id)
    except Exception:
        pass

    # 排序: 按 severity 倒序
    report.impacted_units.sort(key=lambda u: -u.severity)

    _logger.info("Impact analysis: unit=%s → %d impacted units",
                 unit_id[:8], len(report.impacted_units))
    return report
