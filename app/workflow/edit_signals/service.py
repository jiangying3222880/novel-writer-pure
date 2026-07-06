"""
app/workflow/edit_signals/service.py

Service 层: 把 edit_signals 暴露给 container / main / editor_tab.
- 单例: per-project collector / curator / evolver / injector / worker
- 启动: start() 接 EditorTab 的 chapter_committed 事件
- 关闭: stop() 清空后台 thread
- LLM 注入 prompt: build_prompt_segment() 给 prompt_assembler 用
"""
from __future__ import annotations
import logging
import threading
from typing import Optional

from app.core import container, config
from .collector import EditSignalCollector
from .analytics import Curator, Evolver
from .injection import SkillInjector
from .worker import EditSignalWorker
from .jsonl_store import get_project_dir

_logger = logging.getLogger("NovelWriter.edit_signals.service")

# 全局 worker 句柄 (per project_id, 防止多开)
_workers: dict[int, EditSignalWorker] = {}
_workers_lock = threading.Lock()

CONTAINER_KEY_COLLECTOR = "edit_signal.collector"
CONTAINER_KEY_CURATOR = "edit_signal.curator"
CONTAINER_KEY_EVOLVER = "edit_signal.evolver"
CONTAINER_KEY_INJECTOR = "edit_signal.injector"
CONTAINER_KEY_WORKER = "edit_signal.worker"


def get_collector(project_id) -> EditSignalCollector:
    """从 container 拿 collector (按 project_id 隔离)."""
    return EditSignalCollector(project_id)


def get_curator(project_id) -> Curator:
    return Curator(project_id)


def get_evolver(project_id) -> Evolver:
    return Evolver(project_id)


def get_injector(project_id) -> SkillInjector:
    return SkillInjector(project_id)


def get_worker(project_id, *, llm_client=None) -> EditSignalWorker:
    """拿 worker (单例 per project_id)."""
    with _workers_lock:
        w = _workers.get(project_id)
        if w is None:
            w = EditSignalWorker(
                project_id,
                llm_client=llm_client,
                llm_enabled=bool(config.get("signal_llm_generalize_enabled", False)),
            )
            _workers[project_id] = w
        return w


def start_worker(project_id, *, llm_client=None) -> EditSignalWorker:
    """启动 worker (后台 daemon thread)."""
    w = get_worker(project_id, llm_client=llm_client)
    w.start()
    return w


def stop_worker(project_id) -> None:
    """停止 worker."""
    with _workers_lock:
        w = _workers.pop(project_id, None)
    if w is not None:
        w.stop()


def stop_all_workers() -> None:
    """关闭所有 worker (app 退出时)."""
    with _workers_lock:
        all_w = list(_workers.values())
        _workers.clear()
    for w in all_w:
        try:
            w.stop()
        except Exception as e:
            _logger.warning("关 worker 失败: %s", e)


def notify_chapter_committed(project_id, chapter_id) -> None:
    """editor_tab 在 chapter_save 后调这个."""
    if not config.get("signal_enabled", True):
        return
    try:
        w = get_worker(project_id)
        w.on_chapter_committed(chapter_id)
    except Exception as e:
        _logger.warning("notify_chapter_committed 失败: %s", e)


# ── L5 prompt 注入 (供 prompt_assembler 调用) ──

def build_prompt_segment(project_id, chapter: dict) -> str:
    """给 chapter 生成 [📚 项目内参考] 段 (供 prompt_assembler 注入).

    默认关闭, 由 config.signal_inject_to_prompt 控制.
    """
    if not config.get("signal_inject_to_prompt", False):
        return ""
    if not config.get("signal_enabled", True):
        return ""
    try:
        injector = get_injector(project_id)
        return injector.build_prompt_segment(chapter)
    except Exception as e:
        _logger.debug("build_prompt_segment 失败: %s", e)
        return ""


def is_signal_enabled() -> bool:
    return bool(config.get("signal_enabled", True))


def is_signal_popup_muted() -> bool:
    return bool(config.get("signal_popup_muted", False))


def get_signal_inject_max_skills() -> int:
    return int(config.get("signal_inject_max_skills", 3))


def get_signal_inject_max_tokens() -> int:
    return int(config.get("signal_inject_max_tokens", 500))


def get_signal_debounce_ms() -> int:
    return int(config.get("signal_debounce_ms", 30_000))
