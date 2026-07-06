"""
app/services/writing/  (写作相关子领域服务)
============================================================

子模块:
  - paragraph_rewriter   段落级重写器
  - prompt_assembler     prompt 资产组装器
  - scanner              实体/关键词扫前后
  - entity_manager       实体索引管理 (重塑)
  - hook_analyzer        追读力诊断
"""
from __future__ import annotations

from . import (
    paragraph_rewriter,
    prompt_assembler,
    scanner,
    entity_manager,
    hook_analyzer,
)

__all__ = [
    "paragraph_rewriter",
    "prompt_assembler",
    "scanner",
    "entity_manager",
    "hook_analyzer",
]
