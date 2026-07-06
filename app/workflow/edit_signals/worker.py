"""
app/workflow/edit_signals/worker.py

EditSignalWorker - 后台 daemon thread (§3 Layer 3 + Layer 4).

- 监听 chapter_committed 事件 (EventBus)
- 后台跑 curator (5 章/50 信号/24h)
- 后台跑 evolver (3 候选/5 patch/24h)
- 1 周 1 次 LLM 泛化 (可选, dry-run preview 默认)

写手感知的代价 = 0.
"""
from __future__ import annotations
import logging
import threading
import time
from typing import Optional

from .collector import EditSignalCollector
from .analytics import Curator, Evolver
from .jsonl_store import get_project_dir

_logger = logging.getLogger("NovelWriter.edit_signals.worker")


class EditSignalWorker:
    """后台 daemon, 跑 Layer 3 聚类 + Layer 4 进化.

    设计:
      - 单 daemon thread, 不阻塞主线程
      - 监听 EventBus 的 chapter_committed 事件 (editor_tab 触发)
      - 触发条件满足时跑 curator / evolver
      - LLM 泛化 1 周 1 次 (后台, dry-run 默认)
    """

    def __init__(
        self,
        project_id,
        *,
        llm_client=None,
        llm_enabled: bool = False,
        event_bus=None,
    ):
        self.project_id = project_id
        self.project_dir = get_project_dir(project_id)
        self.collector = EditSignalCollector(project_id)
        self.curator = Curator(project_id)
        self.evolver = Evolver(project_id)
        self.llm_client = llm_client
        self.llm_enabled = llm_enabled
        self._event_bus = event_bus
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._pending_event = threading.Event()  # 新事件触发
        self._last_run_lock = threading.Lock()
        self._last_curator_at: float = 0.0
        self._last_evolve_at: float = 0.0

    # ── 启停 ──

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"EditSignalWorker-p{self.project_id}",
            daemon=True,
        )
        self._thread.start()
        _logger.info("EditSignalWorker 启动: project=%s", self.project_id)

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._pending_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        _logger.info("EditSignalWorker 停止: project=%s", self.project_id)

    # ── 事件触发 ──

    def on_chapter_committed(self, chapter_id) -> None:
        """editor_tab 在保存章节后调这个 (替代事件总线, 更直接)."""
        try:
            count = self.collector.on_chapter_save(chapter_id)
            _logger.debug("chapter %d 封存: %d 条信号", chapter_id, count)
        except Exception as e:
            _logger.warning("chapter_committed 处理失败: %s", e)
        self._pending_event.set()

    # ── 主循环 ──

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            # 阻塞等事件, 超时 30s 退出
            triggered = self._pending_event.wait(timeout=30.0)
            self._pending_event.clear()
            if self._stop.is_set():
                break
            try:
                if triggered:
                    self._tick()
                # 周期性检查 LLM 泛化 (1 周 1 次)
                self._maybe_generalize()
            except Exception as e:
                _logger.exception("worker tick 失败: %s", e)

    def _tick(self) -> None:
        """1 次 tick: 跑 curator (如触发) + evolver (如触发)."""
        with self._last_run_lock:
            # 强制 cooldown 60s (避免章节连续保存频繁跑)
            now = time.time()
            if (now - self._last_curator_at) < 60 and (now - self._last_evolve_at) < 60:
                return
        # 1. Curator
        try:
            if self.curator.should_run():
                stats = self.curator.run()
                self._last_curator_at = time.time()
                _logger.info("curator tick: %s", stats.get("new_candidates"))
        except Exception as e:
            _logger.warning("curator tick 失败: %s", e)
        # 2. Evolver
        try:
            if self.evolver.should_run():
                stats = self.evolver.run(llm_client=self.llm_client, llm_enabled=False)
                self._last_evolve_at = time.time()
                _logger.info("evolver tick: merged=%d promoted=%d anti=%d",
                             len(stats.get("merged", [])),
                             len(stats.get("promoted", [])),
                             len(stats.get("anti_patterns", [])))
        except Exception as e:
            _logger.warning("evolver tick 失败: %s", e)

    def _maybe_generalize(self) -> None:
        """1 周 1 次 LLM 泛化 (后台, 默认 disabled, 由 settings 开关)."""
        if not self.llm_enabled or not self.llm_client:
            return
        try:
            self.evolver.maybe_generalize(llm_client=self.llm_client, llm_enabled=True)
        except Exception as e:
            _logger.warning("LLM 泛化失败: %s", e)

    # ── 强制入口 (UI 按钮) ──

    def force_curate(self, *, dry_run: bool = False) -> dict:
        """手动 [立即聚类]."""
        return self.curator.run(force=True, dry_run=dry_run)

    def force_evolve(self, *, dry_run: bool = False) -> dict:
        """手动 [立即进化]."""
        return self.evolver.run(force=True, dry_run=dry_run)

    def force_generalize(self) -> dict:
        """手动 [立即泛化] (LLM 泛化)."""
        return self.evolver.maybe_generalize(llm_client=self.llm_client, llm_enabled=self.llm_enabled)
