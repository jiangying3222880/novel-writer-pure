"""
L0 数据访问门面 (保留最小集: 兼容旧代码)

v4.0-P2 简化: 写作相关的 ChapterReader/Writer/ProjectReader/SettingReader
已删除，services/writing 下的模块直接 import services 层。
本模块保留只为兼容可能存在的第三方引用，内容已缩减。
"""
from __future__ import annotations


def reset_cache() -> None:
    """测试用: 清空 accessor 缓存 (空实现, 保留兼容)."""
    pass
