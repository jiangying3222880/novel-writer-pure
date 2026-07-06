"""
nw.py - VS Code 兼容的扩展 API 实现 (P0 完整, P1/P2 占位).

用法 (插件作者):
    from app.extension_api import nw
    nw.commands.register_command("novel.generate", my_callback)
    nw.window.show_information_message("生成完毕!")

内部实现:
    - 弹窗调 app.core.dialogs_protocol (M1 已落地)
    - 配置调 app.core.config (已有)
    - 事件调 app.core.event_bus (已有)
    - 业务调 app.services (services 0 PySide6 依赖)

ADR: docs/decisions/0002-vscode-compatible-api.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# 数据类型 (跟 vscode.* 一一对应)
# ============================================================================


@dataclass
class Disposable:
    """vscode.Disposable - 资源句柄, dispose() 时清理."""
    _dispose: Callable[[], None]

    def dispose(self) -> None:
        if self._dispose:
            try:
                self._dispose()
            except Exception as e:
                logger.warning("dispose error: %s", e)
            finally:
                self._dispose = lambda: None  # type: ignore[assignment]


class EventEmitter:
    """vscode.EventEmitter - 事件发射器."""

    def __init__(self) -> None:
        self._listeners: List[Callable] = []

    @property
    def event(self) -> Callable:
        """vscode.Event - 注册 listener."""
        def on(listener: Callable) -> Disposable:
            self._listeners.append(listener)
            return Disposable(lambda: self._listeners.remove(listener) if listener in self._listeners else None)
        return on

    def fire(self, *args: Any) -> None:
        for listener in list(self._listeners):
            try:
                listener(*args)
            except Exception as e:
                logger.warning("event listener error: %s", e)


@dataclass
class WorkspaceConfiguration:
    """vscode.WorkspaceConfiguration - 配置节 (key-value + has/get/update)."""
    _section: str
    _values: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def has(self, key: str) -> bool:
        return key in self._values

    def update(self, key: str, value: Any) -> None:
        self._values[key] = value

    def inspect(self, key: str) -> dict:
        return {"key": key, "defaultValue": None, "globalValue": self._values.get(key), "workspaceValue": None}


@dataclass
class OutputChannel:
    """vscode.OutputChannel - 文本输出通道."""
    name: str
    _buffer: List[str] = field(default_factory=list)

    def append(self, value: str) -> None:
        self._buffer.append(value)

    def append_line(self, value: str) -> None:
        self._buffer.append(value + "\n")
        logger.info("[%s] %s", self.name, value)

    def clear(self) -> None:
        self._buffer.clear()

    def show(self, preserve_focus: bool = False) -> None:
        # 桌面端用 logging 输出
        if self._buffer:
            logger.info("[OutputChannel:%s]\n%s", self.name, "".join(self._buffer))


# ============================================================================
# nw.commands - 命令注册/执行
# ============================================================================


class Commands:
    """vscode.commands.*"""

    def __init__(self) -> None:
        self._registry: Dict[str, Callable] = {}

    def register_command(self, command: str, callback: Callable, this_arg: Any = None) -> Disposable:
        """注册命令. command 是 'namespace.action' 形式 (e.g. 'novel.generate')."""
        if not command or not isinstance(command, str):
            raise ValueError("command must be non-empty string")
        if command in self._registry:
            logger.warning("command '%s' 重复注册, 覆盖", command)
        self._registry[command] = callback if this_arg is None else (lambda *a, **kw: callback(this_arg, *a, **kw))
        logger.info("command registered: %s", command)
        return Disposable(lambda: self._registry.pop(command, None))

    def execute_command(self, command: str, *args: Any) -> Any:
        """执行命令. 返回 callback 的返回值."""
        if command not in self._registry:
            raise KeyError(f"未注册命令: {command}")
        return self._registry[command](*args)

    def get_commands(self, filter_internal: bool = False) -> List[str]:
        """列出所有已注册命令."""
        return list(self._registry.keys())

    def has_command(self, command: str) -> bool:
        return command in self._registry


# ============================================================================
# nw.window - 弹窗/状态栏/输出
# ============================================================================


class Window:
    """vscode.window.* (P0: 弹窗 + OutputChannel)"""

    def show_information_message(self, message: str, *items: str) -> Optional[str]:
        """vscode.window.showInformationMessage. 返回用户点击的 item (PySide6 弹窗可能 None)."""
        from app.core.dialogs_protocol import info as _info
        _info("Information", message)
        # VS Code 风格: 返回用户点击的按钮. PySide6 Dialogs.info 不支持按钮, 固定返回 None
        return items[0] if items else None

    def show_warning_message(self, message: str, *items: str) -> Optional[str]:
        from app.core.dialogs_protocol import warning as _warning
        _warning("Warning", message)
        return items[0] if items else None

    def show_error_message(self, message: str, *items: str) -> Optional[str]:
        from app.core.dialogs_protocol import error as _error
        _error("Error", message)
        return items[0] if items else None

    def show_input_box(self, options: Optional[dict] = None) -> Optional[str]:
        """vscode.window.showInputBox. options: {prompt, placeHolder, value, password}."""
        from app.core.dialogs_protocol import input_text as _input
        opts = options or {}
        return _input(opts.get("prompt", "Input"), opts.get("prompt", "Input"), opts.get("value", ""))

    def show_quick_pick(self, items: List[str], options: Optional[dict] = None) -> Optional[str]:
        """vscode.window.showQuickPick. PySide6 简化: 退化为 confirm."""
        # TODO: 真实现要弹一个列表选择对话框
        from app.core.dialogs_protocol import confirm as _confirm
        if not items:
            return None
        msg = options.get("title", "Select") if options else "Select"
        picked = items[0] if _confirm(msg, "\n".join(items)) else None
        return picked

    def create_output_channel(self, name: str) -> OutputChannel:
        return OutputChannel(name=name)

    def with_progress(self, options: dict, task: Callable) -> Any:
        """vscode.window.withProgress. options: {location, title, cancellable}.
        PySide6 简化: 直接跑 task, 不显示 progress 弹窗."""
        logger.info("[progress] %s", options.get("title", ""))
        return task({"isCanceled": False, "report": lambda r: logger.info("[progress.report] %s", r)})


# ============================================================================
# nw.workspace - 配置/工作区
# ============================================================================


class Workspace:
    """vscode.workspace.* (P0: 配置)"""

    def get_configuration(self, section: Optional[str] = None) -> WorkspaceConfiguration:
        """vscode.workspace.getConfiguration. 返回配置节 (简化版, 内存 dict)."""
        from app.core import config as _config
        values: Dict[str, Any] = {}
        if section:
            # 简化: 从 _config 取整段
            try:
                values = _config.get(section) or {}
                if not isinstance(values, dict):
                    values = {}
            except Exception:
                values = {}
        return WorkspaceConfiguration(_section=section or "", _values=values)

    def as_relative_path(self, path_or_uri: str) -> str:
        """vscode.workspace.asRelativePath. 简化: 去掉 STORY_DIR 前缀."""
        try:
            from app.app_paths import get_story_dir
            story = str(get_story_dir())
            if path_or_uri.startswith(story):
                rel = path_or_uri[len(story):].lstrip("\\/").replace("\\", "/")
                return rel or "."
        except Exception:
            pass
        return path_or_uri

    def get_workspace_folder(self) -> Optional[Dict[str, str]]:
        """vscode.workspace.workspaceFolders. 简化: 返回当前 STORY_DIR."""
        try:
            from app.app_paths import get_story_dir
            return {"uri": f"file:///{str(get_story_dir()).replace(chr(92), '/')}", "name": "story", "index": 0}
        except Exception:
            return None

    @property
    def on_did_change_configuration(self) -> Callable:
        """vscode.workspace.onDidChangeConfiguration. 简化: 返回 dummy 事件."""
        emitter = EventEmitter()
        return emitter.event


# ============================================================================
# nw.languages - 补全/Hover/诊断 (P1 完整)
# ============================================================================


@dataclass
class CompletionItem:
    """vscode.CompletionItem - 补全项."""
    label: str
    kind: Optional[int] = None
    detail: Optional[str] = None
    documentation: Optional[str] = None
    insert_text: Optional[str] = None


@dataclass
class Hover:
    """vscode.Hover - 悬浮提示."""
    contents: List[str]
    range: Optional[Dict[str, Any]] = None


@dataclass
class Position:
    """vscode.Position - 文本位置."""
    line: int
    character: int


@dataclass
class Range:
    """vscode.Range - 文本范围."""
    start: Position
    end: Position


@dataclass
class Diagnostic:
    """vscode.Diagnostic - 诊断信息 (G11-G16 validator 用)."""
    range: Range
    message: str
    severity: int = 1  # 0=Error, 1=Warning, 2=Information, 3=Hint
    source: Optional[str] = None
    code: Any = None


@dataclass
class DiagnosticCollection:
    """vscode.DiagnosticCollection - 诊断集合."""
    name: str
    _items: Dict[str, List[Diagnostic]] = field(default_factory=dict)  # uri -> diagnostics

    def set(self, uri: str, diagnostics: List[Diagnostic]) -> None:
        self._items[uri] = list(diagnostics)

    def delete(self, uri: str) -> None:
        self._items.pop(uri, None)

    def clear(self) -> None:
        self._items.clear()

    def get(self, uri: str) -> List[Diagnostic]:
        return list(self._items.get(uri, []))

    def for_each(self, callback: Callable[[str, List[Diagnostic]], None]) -> None:
        for uri, items in self._items.items():
            callback(uri, items)

    def dispose(self) -> None:
        self._items.clear()


def _selector_matches(selector: dict, doc: dict) -> bool:
    """简化: scheme + language 匹配."""
    if not selector:
        return True
    if "scheme" in selector and selector["scheme"] != doc.get("scheme", "file"):
        return False
    if "language" in selector and selector["language"] != doc.get("language", ""):
        return False
    return True


class Languages:
    """vscode.languages.* (P1 完整).

    PySide6 桌面端: 注册到内存 dict, 实际 UI 渲染由编辑器/QScintilla 处理.
    VS Code 端: 通过 nw.languages 拿 provider, 实现补全/Hover/Diagnostics.
    """

    def __init__(self) -> None:
        self._completion_providers: List[Dict[str, Any]] = []
        self._hover_providers: List[Dict[str, Any]] = []
        self._code_action_providers: List[Dict[str, Any]] = []
        self._diagnostic_collections: Dict[str, DiagnosticCollection] = {}

    def register_completion_item_provider(
        self, selector: dict, provider: Any, *trigger_chars: str
    ) -> Disposable:
        """vscode.languages.registerCompletionItemProvider.
        provider 必须有 provide_completion_items(document, position, context, token) -> List[CompletionItem].
        """
        if not hasattr(provider, "provide_completion_items"):
            raise ValueError("provider must have provide_completion_items method")
        entry = {
            "selector": selector or {},
            "provider": provider,
            "trigger_chars": list(trigger_chars),
        }
        self._completion_providers.append(entry)
        logger.info("completion provider registered, trigger=%s", trigger_chars)
        return Disposable(
            lambda: self._completion_providers.remove(entry)
            if entry in self._completion_providers else None
        )

    def register_hover_provider(self, selector: dict, provider: Any) -> Disposable:
        """vscode.languages.registerHoverProvider.
        provider 必须有 provide_hover(document, position, token) -> Optional[Hover].
        """
        if not hasattr(provider, "provide_hover"):
            raise ValueError("provider must have provide_hover method")
        entry = {"selector": selector or {}, "provider": provider}
        self._hover_providers.append(entry)
        logger.info("hover provider registered")
        return Disposable(
            lambda: self._hover_providers.remove(entry)
            if entry in self._hover_providers else None
        )

    def register_code_actions_provider(
        self, selector: dict, provider: Any, *metadata: str
    ) -> Disposable:
        """vscode.languages.registerCodeActionsProvider."""
        if not hasattr(provider, "provide_code_actions"):
            raise ValueError("provider must have provide_code_actions method")
        entry = {"selector": selector or {}, "provider": provider, "metadata": list(metadata)}
        self._code_action_providers.append(entry)
        return Disposable(
            lambda: self._code_action_providers.remove(entry)
            if entry in self._code_action_providers else None
        )

    def create_diagnostic_collection(self, name: str) -> DiagnosticCollection:
        """vscode.languages.createDiagnosticCollection. 同名重复拿同一个."""
        if name not in self._diagnostic_collections:
            self._diagnostic_collections[name] = DiagnosticCollection(name)
        return self._diagnostic_collections[name]

    def get_completion_providers(self, document: dict) -> List[Dict[str, Any]]:
        """UI/VS Code 端用: 拿所有匹配 document selector 的补全 provider."""
        return [p for p in self._completion_providers if _selector_matches(p["selector"], document)]

    def get_hover_providers(self, document: dict) -> List[Dict[str, Any]]:
        """UI/VS Code 端用: 拿所有匹配 document selector 的 hover provider."""
        return [p for p in self._hover_providers if _selector_matches(p["selector"], document)]


# ============================================================================
# nw.extensions - 扩展管理 (P1 完整)
# ============================================================================


@dataclass
class Extension:
    """vscode.Extension - 扩展对象."""
    id: str
    package_json: Dict[str, Any]
    extension_path: str
    is_active: bool = False
    exports: Any = None  # activate() 的返回值
    _activate: Optional[Callable] = field(default=None, repr=False)

    def activate(self) -> Any:
        """激活扩展 (VS Code 风格: 第一次 getExtension() 时 lazy 激活)."""
        if self.is_active:
            return self.exports
        if self._activate is None:
            raise RuntimeError(f"Extension '{self.id}' has no activate() entry point")
        from app.extension_api.nw import nw as _nw  # 避免循环 import
        context = _ExtensionContext(self.id)
        self.exports = self._activate(context)
        self.is_active = True
        logger.info("extension activated: %s", self.id)
        return self.exports


@dataclass
class _ExtensionContext:
    """传给 activate(context) 的句柄 - 跟 VS Code ExtensionContext 子集对齐."""
    extension_id: str
    subscriptions: List[Disposable] = field(default_factory=list)

    def subscribe(self, disposable: Disposable) -> None:
        """VS Code 风格: context.subscriptions.push(disposable)."""
        self.subscriptions.append(disposable)

    def dispose(self) -> None:
        for d in self.subscriptions:
            try:
                d.dispose()
            except Exception:
                pass
        self.subscriptions.clear()


class Extensions:
    """vscode.extensions.* (P1 完整).

    管理已装扩展的生命周期 (注册/激活/卸载)."""

    def __init__(self) -> None:
        self._registry: Dict[str, Extension] = {}
        self._on_did_change = EventEmitter()

    def get_extension(self, extension_id: str) -> Optional[Extension]:
        """vscode.extensions.getExtension."""
        ext = self._registry.get(extension_id)
        if ext and not ext.is_active:
            try:
                ext.activate()
            except Exception as e:
                logger.warning("failed to activate '%s': %s", extension_id, e)
        return ext

    @property
    def all(self) -> List[Extension]:
        """vscode.extensions.all."""
        return list(self._registry.values())

    @property
    def on_did_change(self) -> Callable:
        """vscode.extensions.onDidChange."""
        return self._on_did_change.event

    def _register(self, ext: Extension) -> None:
        """内部注册 (由插件加载器调)."""
        self._registry[ext.id] = ext
        self._on_did_change.fire()
        logger.info("extension registered: %s", ext.id)

    def _unregister(self, extension_id: str) -> None:
        """内部卸载."""
        ext = self._registry.pop(extension_id, None)
        if ext:
            self._on_did_change.fire()
            logger.info("extension unregistered: %s", extension_id)


# ============================================================================
# nw.env - 环境/剪贴板/外部链接 (P1 完整)
# ============================================================================


class Env:
    """vscode.env.* (P1 完整: 桌面 + 剪贴板 + 外部链接)."""

    def open_external(self, target: str) -> bool:
        """vscode.env.openExternal. PySide6 用 QDesktopServices."""
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            return QDesktopServices.openUrl(QUrl(target))
        except Exception as e:
            logger.warning("env.open_external failed: %s", e)
            return False

    def clipboard_write(self, text: str) -> None:
        """vscode.env.clipboard.writeText."""
        try:
            from PySide6.QtGui import QGuiApplication
            cb = QGuiApplication.clipboard()
            if cb is not None:
                cb.setText(text)
        except Exception as e:
            logger.warning("env.clipboard_write failed: %s", e)

    def clipboard_read(self) -> str:
        """vscode.env.clipboard.readText."""
        try:
            from PySide6.QtGui import QGuiApplication
            cb = QGuiApplication.clipboard()
            if cb is not None:
                return cb.text() or ""
        except Exception as e:
            logger.warning("env.clipboard_read failed: %s", e)
        return ""

    @property
    def app_name(self) -> str:
        """vscode.env.appName."""
        return "Novel Writer Pure"

    @property
    def app_root(self) -> str:
        """novel-writer 特有: 应用根目录."""
        return str(Path(__file__).resolve().parent.parent.parent)

    @property
    def language(self) -> str:
        """vscode.env.language."""
        return "zh-CN"

    @property
    def session_id(self) -> str:
        """vscode.env.sessionId."""
        return "novel-writer-pure-3.4"

    @property
    def is_telemetry_enabled(self) -> bool:
        """vscode.env.isTelemetryEnabled. 默认关闭."""
        return False

    @property
    def machine_id(self) -> str:
        """vscode.env.machineId. 简化: 用 host 名."""
        import socket
        try:
            return socket.gethostname()
        except Exception:
            return "unknown"


# ============================================================================
# 顶层单例 nw
# ============================================================================


class _NW:
    """novel-writer 扩展 API 主入口. 1:1 对齐 vscode.*."""

    def __init__(self) -> None:
        self.commands = Commands()
        self.window = Window()
        self.workspace = Workspace()
        self.languages = Languages()
        self.extensions = Extensions()
        self.env = Env()
        self.version = "3.4.0-dev"


# 全局单例
nw = _NW()


# 便捷导入
__all__ = [
    "nw",
    "Disposable",
    "EventEmitter",
    "WorkspaceConfiguration",
    "OutputChannel",
]
