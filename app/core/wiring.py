"""
M3-A wiring (简化版)

v4.0-P2 简化: 写作相关的 ChapterReader/Writer/ProjectReader/SettingReader
已删除，services/writing 下的模块直接 import services 层。

本模块保留 wire_default_services() 空函数，保持向后兼容。
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)


def wire_default_services() -> None:
    """注册默认 services 到 Container (v4.0-P2 简化版: 无操作)。

    保留此函数只为向后兼容，旧代码调用不会报错。
    """
    log.debug("[wiring] wire_default_services (no-op, v4.0-P2 simplified)")


def wire_for_tests(overrides: dict | None = None) -> None:
    """测试用 (no-op, 保留兼容)。"""
    pass
