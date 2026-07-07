"""
M10-D: AI Router 状态条 (DashboardTab 顶部).

M11-B: 实时刷新 (订阅 router.* 业务事件, 自动 refresh).

展示 4 个实时指标:
  1. 当前主模型 (从 registry.get_primary())
  2. 当前路由策略 (从 config ai.strategy)
  3. 缓存命中率 (从 router.cache.stats())
  4. 累计调用次数 (从 usage_records)

设计:
  - L4 UI 组件, 只读 app.ai.router / app.ai.cache / app.core.config / app.db
  - 软依赖: router 不可用时显示 'router 不可用', 不崩
  - 加 PRO 角标 (ai.cache / ai.router.parallel / ai.router.fallback 都是 PRO 专属)
  - 调 refresh() 即可刷新
  - M11-B 增: 订阅 router.used / router.cache_hit / router.failed, 用 QTimer coalesce
    多次事件, 200ms 内只刷一次 (避免高频事件时 UI 卡顿)
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from app.ui.widgets.feature_gate_widgets import FeatureGateBadge, get_current_tier_label

log = logging.getLogger(__name__)


class RouterStatusBar(QFrame):
    """AI Router 状态条 — DashboardTab 顶部显示.

    用法:
        bar = RouterStatusBar()
        # 嵌进 dashboard 顶部 layout
        # 用户每次点 '刷新' 时调 bar.refresh()
        # M11-B: 也可什么都不做, bar 内部自动订阅 router.* 事件实时刷
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # 4.0 修复: 4.x 早期版本 setStyleSheet 硬编码 #f8f9fa, 暗色主题下显示成白色.
        # 现在只设 objectName, 真正的背景色在 app/ui/theme.py 的 QFrame#router_status_bar 节点.
        self.setObjectName("router_status_bar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(16)

        # 1) 当前模型
        self.lbl_model = QLabel("🤖 —")
        # 2) 路由策略
        self.lbl_strategy = QLabel("📡 —")
        # 3) 缓存命中率
        self.lbl_cache = QLabel("💾 —")
        # 4) 累计调用
        self.lbl_calls = QLabel("📊 —")
        for lbl in (self.lbl_model, self.lbl_strategy, self.lbl_cache, self.lbl_calls):
            lbl.setObjectName("routerStatusLabel")
            layout.addWidget(lbl)

        layout.addStretch(1)

        # M10-D: 当前 tier 标签 (复用 M10-C 风格)
        self.lbl_tier = QLabel(get_current_tier_label())
        self.lbl_tier.setStyleSheet(
            "color: #7b1fa2; font-size: 10px; font-weight: bold; "
            "padding: 2px 6px; border: 1px solid #7b1fa2; border-radius: 4px;"
        )
        self.lbl_tier.setToolTip("当前 license 等级 (设置 → 🔐 License 可升级)")
        layout.addWidget(self.lbl_tier)

        # M10-D: PRO 角标 — 3 个 PRO 功能 (parallel / fallback / cache) 任一锁住即显示
        # 用 ai.cache 作代表 (cache 命中率展示, 锁住时降级到 '无缓存' 提示)
        self.badge = FeatureGateBadge("ai.cache", parent=self)
        layout.addWidget(self.badge)

        # M11-B: coalesce timer — 200ms 内多次事件合并成一次 refresh
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(200)
        self._refresh_timer.timeout.connect(self.refresh)

        # M11-B: 订阅 router.* 业务事件
        self._subscribed = False
        self._subscribe_router_signals()

        self.refresh()

    # ------------------------------------------------------------------ #
    # M11-B: 实时刷新 (订阅 router.* 业务事件)
    # ------------------------------------------------------------------ #

    def _subscribe_router_signals(self) -> None:
        """订阅 L2 router.* 业务事件, 自动 schedule refresh.

        幂等: 重复调不会重复订阅. 业务模块调 install_relay() 启动 L1→L2 桥.
        """
        if self._subscribed:
            return
        try:
            # 确保 L1→L2 relay 已装
            from app.services.router.signals import (
                install_relay, ROUTER_USED, ROUTER_FAILED,
                ROUTER_CACHE_HIT, ROUTER_FALLBACK,
            )
            install_relay()
            from app.core.event_bus import get_bus
            bus = get_bus()
            bus.subscribe(ROUTER_USED, self._on_router_event)
            bus.subscribe(ROUTER_FAILED, self._on_router_event)
            bus.subscribe(ROUTER_CACHE_HIT, self._on_router_event)
            bus.subscribe(ROUTER_FALLBACK, self._on_router_event)
            self._subscribed = True
        except Exception as e:  # noqa: BLE001
            log.debug("RouterStatusBar 订阅失败 (offscreen?): %s", e)

    def _on_router_event(self, _event) -> None:
        """事件回调: 200ms 内多次事件合并成一次 refresh."""
        self._refresh_timer.start()  # 重启 timer (coalesce)

    def showEvent(self, event) -> None:  # type: ignore[override]
        """widget 第一次显示时强制刷一次 (防订阅前调用 refresh)."""
        super().showEvent(event)
        if not self._subscribed:
            self._subscribe_router_signals()
        self.refresh()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """widget 销毁时清订阅 + timer (避免内存泄漏)."""
        if self._subscribed:
            try:
                from app.services.router.signals import (
                    ROUTER_USED, ROUTER_FAILED,
                    ROUTER_CACHE_HIT, ROUTER_FALLBACK,
                )
                from app.core.event_bus import get_bus
                bus = get_bus()
                bus.unsubscribe(ROUTER_USED, self._on_router_event)
                bus.unsubscribe(ROUTER_FAILED, self._on_router_event)
                bus.unsubscribe(ROUTER_CACHE_HIT, self._on_router_event)
                bus.unsubscribe(ROUTER_FALLBACK, self._on_router_event)
                self._subscribed = False
            except Exception:
                pass
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
        super().closeEvent(event)

    def refresh(self) -> None:
        """刷新所有 4 个字段 + tier 标签 + PRO 角标."""
        try:
            self._refresh_inner()
        except Exception as e:
            log.warning("RouterStatusBar.refresh 失败: %s", e)
            self.lbl_model.setText("🤖 router 不可用")
            self.lbl_strategy.setText("📡 —")
            self.lbl_cache.setText(f"💾 err")
            self.lbl_calls.setText("📊 —")
        # 同步 tier 标签 + PRO 角标
        try:
            self.lbl_tier.setText(get_current_tier_label())
            self.badge.refresh()
        except Exception:
            pass

    def _refresh_inner(self) -> None:
        # 1) 当前主模型
        from app.ai.registry import get_registry
        registry = get_registry()
        primary = registry.get_primary() if registry else None
        # ModelConfig 没有 name 字段, 用 model_name (e.g. "gpt-4o-mini") 或 id
        if primary is not None:
            display = getattr(primary, "model_name", None) or getattr(primary, "id", "?")
        else:
            display = None
        self.lbl_model.setText(
            f"🤖 {display}" if display else "🤖 未配置"
        )

        # 2) 当前路由策略
        from app.core import config as _cfg
        strategy = _cfg.get("ai.strategy", "single")
        strat_label = {
            "single": "单模型 (含降级)",
            "parallel": "并行 N 模型",
            "cache_first": "缓存优先",
        }.get(strategy, strategy)
        self.lbl_strategy.setText(f"📡 {strat_label}")

        # 3) 缓存命中率
        try:
            from app.ai.router import get_router
            router = get_router()
            cs = router.cache.stats() if hasattr(router.cache, "stats") else {}
            hit, miss, size = self._parse_cache_stats(cs)
            total = hit + miss
            hr = (hit / total) if total else 0.0
            self.lbl_cache.setText(
                f"💾 hit={hit} miss={miss} rate={hr*100:.0f}% size={size}"
            )
        except Exception as e:
            self.lbl_cache.setText(f"💾 —")

        # 4) 累计调用次数 (从 usage_records 表)
        try:
            from app.db import _impl as _db_conn
            conn = _db_conn.get_conn()
            cur = conn.execute("SELECT COUNT(*), COALESCE(SUM(cost_usd), 0) FROM usage_records")
            row = cur.fetchone()
            cnt = row[0] if row else 0
            cost = row[1] if row else 0.0
            self.lbl_calls.setText(f"📊 调用 {cnt} 次 / ${cost:.4f}")
        except Exception:
            # DB 未初始化时的兜底
            self.lbl_calls.setText("📊 —")

    @staticmethod
    def _parse_cache_stats(cs: dict) -> tuple[int, int, int]:
        """支持 TieredCache 嵌套格式 ({l1, l2}) 和扁平格式 (单层)."""
        if not isinstance(cs, dict):
            return (0, 0, 0)
        if "l1" in cs:
            l1 = cs.get("l1", {}) or {}
            l2 = cs.get("l2", {}) or {}
            hit = l1.get("hit", 0) + l2.get("hit", 0)
            miss = l1.get("miss", 0) + l2.get("miss", 0)
            size = l1.get("size", 0) + l2.get("size", 0)
            return (hit, miss, size)
        return (
            cs.get("hit", 0),
            cs.get("miss", 0),
            cs.get("size", 0),
        )
