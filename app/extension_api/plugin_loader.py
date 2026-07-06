"""
plugin_loader.py - 插件加载器 (PySide6 桌面 / VS Code 扩展共用).

读 plugin/package.json + plugin/extension.py, 调 activate(context) 注册到 nw.

设计:
- 兼容 VS Code package.json 子集 (name/version/main/engines/activationEvents/contributes)
- 1 个目录 = 1 个插件 (扁平加载, 不递归)
- 失败时 raise 详细错误 (告诉用户哪个文件哪行)
- 提供批量加载 (load_plugins_from_dir)
"""
from __future__ import annotations

import importlib.util
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.extension_api.nw import nw, Extension, _ExtensionContext

logger = logging.getLogger("nw.plugin_loader")


@dataclass
class PluginSpec:
    """从 package.json 解析出来的插件元数据."""
    name: str
    version: str
    main: str
    engines: dict
    activation_events: List[str]
    contributes: dict
    package_json: dict
    path: str  # 插件根目录


def parse_package_json(plugin_dir: str) -> PluginSpec:
    """读 plugin_dir/package.json, 解析成 PluginSpec."""
    pkg_path = Path(plugin_dir) / "package.json"
    if not pkg_path.is_file():
        raise FileNotFoundError(f"插件目录无 package.json: {plugin_dir}")
    with open(pkg_path, "r", encoding="utf-8") as fp:
        try:
            data = json.load(fp)
        except json.JSONDecodeError as e:
            raise ValueError(f"package.json JSON 解析失败 ({plugin_dir}): {e}") from e

    name = data.get("name", "")
    if not name:
        raise ValueError(f"package.json 缺少 'name' ({plugin_dir})")
    main = data.get("main", "./extension.py")
    if not main:
        raise ValueError(f"package.json 缺少 'main' ({plugin_dir})")

    return PluginSpec(
        name=name,
        version=data.get("version", "0.0.0"),
        main=main,
        engines=data.get("engines", {}),
        activation_events=data.get("activationEvents", []),
        contributes=data.get("contributes", {}),
        package_json=data,
        path=str(Path(plugin_dir).resolve()),
    )


def _load_module(spec: PluginSpec) -> object:
    """动态加载 plugin_dir/main 模块."""
    main_path = Path(spec.path) / spec.main
    if not main_path.is_file():
        raise FileNotFoundError(f"插件 main 文件不存在: {main_path}")
    module_name = f"_plugin_{spec.name.replace('-', '_').replace('.', '_')}_{spec.version.replace('.', '_')}"
    mod = importlib.util.spec_from_file_location(module_name, str(main_path))
    if mod is None or mod.loader is None:
        raise ImportError(f"无法加载模块: {main_path}")
    module = importlib.util.module_from_spec(mod)
    sys.modules[module_name] = module
    mod.loader.exec_module(module)
    return module


def load_plugin(plugin_dir: str) -> Extension:
    """加载单个插件. 返回已激活的 Extension 对象.

    用法:
        ext = load_plugin("./examples/plugins/hello-world")
        nw.commands.execute_command("novel.hello.sayHello")
    """
    spec = parse_package_json(plugin_dir)
    module = _load_module(spec)

    if not hasattr(module, "activate"):
        raise AttributeError(f"插件 {spec.name} 没有 activate(context) 函数")

    # 构造 Extension 对象 (未激活态)
    ext = Extension(
        id=spec.name,
        package_json=spec.package_json,
        extension_path=spec.path,
        is_active=False,
        _activate=lambda ctx: _run_activate(spec, module, ctx),
    )
    # 注册到 nw.extensions
    nw.extensions._register(ext)
    # 立即激活 (简化, 不做 lazy activation)
    nw.extensions.get_extension(spec.name)
    return ext


def _run_activate(spec: PluginSpec, module: object, context) -> dict:
    """调用 plugin.activate(context)."""
    logger.info("activating plugin '%s' v%s", spec.name, spec.version)
    result = module.activate(context)
    logger.info("plugin '%s' activated: %s", spec.name, result)
    return result or {}


def load_plugins_from_dir(plugins_dir: str) -> List[Extension]:
    """批量加载 plugins_dir 下所有子目录 (每个子目录 = 1 个插件)."""
    p = Path(plugins_dir)
    if not p.is_dir():
        raise FileNotFoundError(f"插件目录不存在: {plugins_dir}")

    loaded: List[Extension] = []
    errors: List[str] = []
    for sub in sorted(p.iterdir()):
        if not sub.is_dir():
            continue
        pkg = sub / "package.json"
        if not pkg.is_file():
            continue
        try:
            ext = load_plugin(str(sub))
            loaded.append(ext)
        except Exception as e:
            logger.error("加载插件失败: %s - %s", sub, e)
            errors.append(f"{sub.name}: {e}")
    if errors:
        logger.warning("共 %d 个插件加载失败:\n  %s", len(errors), "\n  ".join(errors))
    return loaded


def unload_plugin(extension_id: str) -> bool:
    """卸载插件 (反激活 + 清资源)."""
    return nw.extensions._unregister(extension_id) is not None or extension_id in [e.id for e in nw.extensions.all]
