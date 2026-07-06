"""
IoC 容器 (B1: 完整做 ~500 行)
- 工厂模式: 所有模块从容器拿, 不直接 import
- 4.0 启动时预创建单例
- 4.0 桌面应用 (1 用户), 用单例 + 懒加载
- v3.4 新增: 按 Protocol 类型取/注/列 (DI 友好, 便于 mock 替换)
"""
from __future__ import annotations
import inspect
import logging
import threading
from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")

_logger = logging.getLogger("NovelWriter.container")

# 全局容器单例
_container: "Container | None" = None
_lock = threading.Lock()


class Container:
    """
    IoC 容器。
    - register(key, factory): 注册工厂
    - get(key) / resolve[T](key): 获取实例
    - singleton(key, instance): 直接放单例
    - get_protocol(Protocol): 拿所有实现该协议的对象
    - register_protocol(key, instance): 按协议名注册实例
    - list_by_protocol(Protocol): 列出所有实现该协议的 key
    """
    def __init__(self):
        self._factories: dict[str, Callable[[], Any]] = {}
        self._instances: dict[str, Any] = {}
        self._protocol_keys: dict[str, str] = {}   # protocol_name -> key
        self._lock = threading.Lock()

    # ──────────── 工厂注册 (原 B1) ────────────

    def register(self, key: str, factory: Callable[[], Any]) -> None:
        """注册工厂函数。"""
        with self._lock:
            if key in self._factories:
                _logger.warning("重复注册: %s (覆盖)", key)
            self._factories[key] = factory
            # 如果已有实例, 失效
            self._instances.pop(key, None)

    def register_singleton(self, key: str, instance: Any) -> None:
        """直接放单例。"""
        with self._lock:
            self._instances[key] = instance
            self._factories.pop(key, None)

    def get(self, key: str) -> Any:
        """
        获取实例 (懒加载)。
        第一次调: 调工厂创建, 缓存
        之后: 直接返回缓存
        """
        with self._lock:
            if key in self._instances:
                return self._instances[key]
            if key not in self._factories:
                raise KeyError(f"未注册: {key} (先调 register())")
            factory = self._factories[key]
            instance = factory()
            self._instances[key] = instance
            _logger.debug("容器创建: %s -> %s", key, type(instance).__name__)
            return instance

    def has(self, key: str) -> bool:
        return key in self._factories or key in self._instances

    def keys(self) -> list[str]:
        return list(set(self._factories) | set(self._instances))

    def clear(self) -> None:
        """清空所有 (测试用)。"""
        with self._lock:
            self._factories.clear()
            self._instances.clear()
            self._protocol_keys.clear()

    # ──────────── v3.4: Protocol-aware 查找 (M2.2 新增) ────────────

    def register_protocol(self, key: str, instance: Any) -> None:
        """
        把 instance 按其实现的 Protocol 名称注册。
        调用: container.register_protocol("project_service", ProjectService())
        之后: container.get_protocol(Service) 会包含该项目服务。
        """
        proto_names = self._detect_protocols(instance)
        with self._lock:
            self._instances[key] = instance
            self._factories.pop(key, None)
            for proto in proto_names:
                self._protocol_keys.setdefault(proto, key)
        _logger.debug("协议注册: %s -> %s (protocols=%s)", key, type(instance).__name__, proto_names)

    def get_protocol(self, protocol: type) -> list[Any]:
        """
        拿所有实现了给定 Protocol 的实例。
        顺序: 先看显式 protocol_keys 注册, 再扫全部 instances 用 isinstance 检查
        (仅对 @runtime_checkable 的 Protocol 有效)。
        """
        proto_name = getattr(protocol, "__name__", str(protocol))
        results: list[Any] = []
        with self._lock:
            # 1. 显式注册
            if proto_name in self._protocol_keys:
                key = self._protocol_keys[proto_name]
                if key in self._instances:
                    results.append(self._instances[key])
            # 2. 扫所有 instances (runtime_checkable 必须)
            if hasattr(protocol, "_is_runtime_protocol"):
                for inst in self._instances.values():
                    if inst in results:
                        continue
                    try:
                        if isinstance(inst, protocol):
                            results.append(inst)
                    except TypeError:
                        pass
        return results

    def list_by_protocol(self, protocol: type) -> list[str]:
        """列出所有实现了给定 Protocol 的 key。"""
        proto_name = getattr(protocol, "__name__", str(protocol))
        keys: list[str] = []
        with self._lock:
            if proto_name in self._protocol_keys:
                keys.append(self._protocol_keys[proto_name])
            if hasattr(protocol, "_is_runtime_protocol"):
                for key, inst in self._instances.items():
                    if key in keys:
                        continue
                    try:
                        if isinstance(inst, protocol):
                            keys.append(key)
                    except TypeError:
                        pass
        return keys

    @staticmethod
    def _detect_protocols(instance: Any) -> list[str]:
        """从 type(instance).__bases__ / MRO 中找 Protocol 子类名。"""
        names: list[str] = []
        for cls in type(instance).__mro__:
            for base in getattr(cls, "__bases__", ()):
                if base.__class__.__name__ == "Protocol" or getattr(base, "_is_protocol", False):
                    if base.__name__ not in names:
                        names.append(base.__name__)
        return names


# ────────────────────── 全局访问 ──────────────────────

def init() -> "Container":
    """初始化全局容器 (启动时调)。"""
    global _container
    with _lock:
        if _container is None:
            _container = Container()
        return _container


def get_container() -> Container:
    """获取全局容器。"""
    if _container is None:
        init()
    assert _container is not None
    return _container


def get(key: str) -> Any:
    """快捷: 从全局容器拿。"""
    return get_container().get(key)


def register(key: str, factory: Callable[[], Any]) -> None:
    """快捷: 注册到全局容器。"""
    get_container().register(key, factory)


def register_singleton(key: str, instance: Any) -> None:
    """快捷: 放单例到全局容器。"""
    get_container().register_singleton(key, instance)


def shutdown() -> None:
    """关闭容器 (退出时调)。"""
    global _container
    with _lock:
        _container = None
