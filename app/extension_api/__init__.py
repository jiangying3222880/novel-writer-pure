"""
app.extension_api - VS Code 兼容扩展 API 入口.

包含:
- nw: 6 命名空间单例 (commands/window/workspace/languages/extensions/env)
- http_bridge: HTTP REST 服务, 把 nw.* 暴露给 VS Code 扩展
"""
from app.extension_api.nw import (
    nw,
    Disposable,
    EventEmitter,
    WorkspaceConfiguration,
    OutputChannel,
    CompletionItem,
    Hover,
    Position,
    Range,
    Diagnostic,
    DiagnosticCollection,
    Extension,
)

__all__ = [
    "nw",
    "Disposable",
    "EventEmitter",
    "WorkspaceConfiguration",
    "OutputChannel",
    "CompletionItem",
    "Hover",
    "Position",
    "Range",
    "Diagnostic",
    "DiagnosticCollection",
    "Extension",
]
