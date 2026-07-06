"""
Novel Writer Pure v4.0 — Story OS 架构

从 v3.4 重构: 保留成熟模块 (ai/core/db/knowledge/story/state),
重写问题模块 (ui/agents/guide), 新建 v4 新模块 (isolation/event_store/guide sources).
"""
from app.core.version import VERSION, get_full_info, format_about_text

__version__ = VERSION

__all__ = ["VERSION", "__version__", "get_full_info", "format_about_text"]
