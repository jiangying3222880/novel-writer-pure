"""
Story Engine 章节导出器（v3.5.1+）

核心设计：
- Unit 是创作单位，Chapter 是 Render 输出
- Orchestrator 只产 Unit 流，Chapter 由 Exporter 按需生成
- 支持 preview() 干跑模式，让 UI 在导出前看到切章位置 + truncation 警告

策略：
- auto_split: 按 target_chars 自动拆章（基于段落边界）
- manual: 用户指定断章点
- whole: 整个 Unit 作为一章

平台支持：
- 番茄: 2500 字
- 起点: 4000 字
- WebNovel: 1800 字
"""
from __future__ import annotations

from app.exporter.chapter_exporter import (
    ChapterExporter,
    ChapterPreview,
    PLATFORM_WORD_TARGETS,
)

__all__ = [
    "ChapterExporter",
    "ChapterPreview",
    "PLATFORM_WORD_TARGETS",
]