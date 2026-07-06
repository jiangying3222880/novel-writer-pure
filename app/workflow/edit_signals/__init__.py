"""
app/workflow/edit_signals - 用户改稿信号 → Skill 沉淀 & 进化 (v3.4 精简版)

外部只需:
  - notify_chapter_committed()     # editor_tab 保存后调用
  - build_prompt_segment()          # prompt_assembler 注入
  - start_worker() / stop_worker()  # worker 生命周期
  - get_collector()                 # 采集信号
  - is_signal_enabled() 等配置查询
  - stop_all_workers()              # app 退出

内部结构 (不对外暴露):
  Layer 1: 30s 防抖 (collector)
  Layer 2: 章节封存 (jsonl_store)
  Layer 3: 聚类沉淀 (analytics.Curator)
  Layer 4: 进化合并 (analytics.Evolver)
  Layer 5: BM25 注入 (injection)
"""
from __future__ import annotations

# 只导出外部实际用到的符号 (15 个)
from .models import (
    EditSignal, SignalKind, CandidateSkill,
    SKILL_CANDIDATE_STATE, SKILL_PROVEN_STATE, SKILL_BUILTIN_STATE,
    SKILL_UNCERTAIN_STATE,
)
from .jsonl_store import (
    JSONLStore, CandidateStore, SidecarStore,
    get_project_dir, SIGNALS_DIR, PROJECTS_DIR,
)
from .lock import ProjectLock, LockGuard
from .state_machine import StateMachine, evaluate_state_static
from .collector import EditSignalCollector
from .worker import EditSignalWorker
from .analytics import CursorLog  # backup 已内联
from .service import (
    get_collector, get_curator, get_evolver, get_injector, get_worker,
    start_worker, stop_worker, stop_all_workers,
    notify_chapter_committed, build_prompt_segment,
    is_signal_enabled, is_signal_popup_muted,
    get_signal_inject_max_skills, get_signal_inject_max_tokens,
    get_signal_debounce_ms,
)

__all__ = [
    # models (外部用)
    "EditSignal", "SignalKind", "CandidateSkill",
    "SKILL_CANDIDATE_STATE", "SKILL_PROVEN_STATE",
    "SKILL_BUILTIN_STATE", "SKILL_UNCERTAIN_STATE",
    # store
    "JSONLStore", "CandidateStore", "SidecarStore",
    "get_project_dir", "SIGNALS_DIR", "PROJECTS_DIR",
    # lock
    "ProjectLock", "LockGuard",
    # state
    "StateMachine", "evaluate_state_static",
    # collector + worker
    "EditSignalCollector", "EditSignalWorker",
    # cursor
    "CursorLog",
    # service (外部用)
    "get_collector", "get_curator", "get_evolver",
    "get_injector", "get_worker",
    "start_worker", "stop_worker", "stop_all_workers",
    "notify_chapter_committed", "build_prompt_segment",
    "is_signal_enabled", "is_signal_popup_muted",
    "get_signal_inject_max_skills", "get_signal_inject_max_tokens",
    "get_signal_debounce_ms",
]
