# Novel Writer v4.0 — Complete Implementation Plan

> Target: `D:\novel-writer-pure-v4.0`
> Source: `D:\novel-writer-pure-v3.4`
> Architecture: Story OS 10-Layer Design
> Date: 2026-07-06

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Reuse vs Rewrite Matrix](#2-reuse-vs-rewrite-matrix)
3. [Implementation Phases](#3-implementation-phases)
4. [File-by-File Plan](#4-file-by-file-plan)
5. [Dependencies & Integration](#5-dependencies--integration)
6. [Testing Strategy](#6-testing-strategy)
7. [Migration Path](#7-migration-path)

---

## 1. Project Structure

```
D:\novel-writer-pure-v4.0\
├── pyproject.toml
├── requirements.txt
├── requirements-pyside6.txt
├── README.md
├── CLAUDE.md
├── .env.example
├── .gitignore
│
├── app/                          # Application layer
│   ├── __init__.py
│   ├── __main__.py
│   ├── main.py
│   ├── cli.py
│   ├── app_paths.py
│   │
│   ├── core/                     # L1: Core infrastructure (KEEP)
│   │   ├── __init__.py
│   │   ├── config.py             # KEEP — app config
│   │   ├── container.py          # KEEP — DI container
│   │   ├── event_bus.py          # KEEP — internal pub/sub
│   │   ├── interfaces.py         # KEEP — abstract interfaces
│   │   ├── types.py              # KEEP — Guide dataclass + core types
│   │   ├── constants.py          # KEEP — constants
│   │   ├── logger.py             # KEEP — logging setup
│   │   ├── exceptions.py         # KEEP — exception hierarchy
│   │   └── version.py            # REWRITE → v4.0.0
│   │
│   ├── db/                       # L7: Event & State persistence (KEEP)
│   │   ├── __init__.py
│   │   ├── _impl.py              # KEEP — DB implementation
│   │   ├── db_utils.py           # KEEP — utilities
│   │   ├── schema.sql            # KEEP + EXTEND — add events table
│   │   ├── models.py             # KEEP — ORM models
│   │   ├── migrator.py           # KEEP — migration runner
│   │   └── migrations/           # KEEP — existing + new v4 migrations
│   │
│   ├── ai/                       # L6: Generation Layer providers (KEEP)
│   │   ├── engine.py             # KEEP — LLM engine
│   │   ├── providers.py          # KEEP — provider registry
│   │   ├── router.py             # KEEP — model router
│   │   ├── cache.py              # KEEP — response cache
│   │   ├── fallback.py           # KEEP — fallback chains
│   │   ├── parallel.py           # KEEP — parallel inference
│   │   ├── mock.py               # KEEP — mock for testing
│   │   └── utils.py              # KEEP — token estimation
│   │
│   ├── knowledge/                # KEEP — RAG subsystem
│   │   ├── bm25.py
│   │   ├── vector_db.py
│   │   ├── finder.py
│   │   ├── importer.py
│   │   ├── builtin/
│   │   └── index/
│   │
│   ├── validators/               # KEEP — content validators
│   │   ├── base.py
│   │   ├── pov.py
│   │   ├── props.py
│   │   ├── repetition.py
│   │   ├── setting.py
│   │   ├── space.py
│   │   └── voice.py
│   │
│   ├── adapters/                 # KEEP — platform adapters
│   │   ├── headless/
│   │   └── pyside6/
│   │
│   ├── agents/                   # L4: Agent Simulation (REWRITE)
│   │   ├── __init__.py
│   │   ├── base.py               # REWRITE — AgentBase v4 isolation kernel
│   │   ├── writer.py             # NEW — Writer agent
│   │   ├── reader.py             # NEW — Reader agent
│   │   ├── critic.py             # NEW — Critic agent
│   │   ├── memory_agent.py       # NEW — Memory agent
│   │   ├── orchestrator.py       # REWRITE — v4 orchestrator
│   │   ├── report.py             # KEEP + EXTEND
│   │   └── isolation.py          # NEW — isolation kernel
│   │
│   ├── services/                 # Cherry-pick clean ones, rewrite messy ones
│   │   ├── __init__.py
│   │   ├── project_service.py    # KEEP
│   │   ├── app_setting_service.py # KEEP
│   │   ├── book_service.py       # KEEP
│   │   ├── chapter_service.py    # KEEP
│   │   ├── story_unit_service_v2.py # KEEP
│   │   ├── unit_writing_service.py  # KEEP
│   │   ├── knowledge_service.py  # KEEP
│   │   ├── usage_analytics.py    # KEEP
│   │   ├── decision_service.py   # REWRITE — integrate v4 Decision Layer
│   │   ├── guide_graph.py        # REWRITE — integrate v4 Guide Engine
│   │   ├── memory_manager.py     # KEEP + EXTEND — L4 memory
│   │   ├── pressure.py           # KEEP — pressure signals
│   │   ├── consistency.py        # KEEP — consistency checks
│   │   ├── voice_profile.py      # KEEP — voice fingerprinting
│   │   ├── voice_inferrer.py     # KEEP
│   │   ├── style_fingerprint.py  # KEEP
│   │   ├── db.py                 # KEEP — DB helper
│   │   ├── exporter.py           # KEEP
│   │   └── ...                   # others: evaluate necessity
│   │
│   ├── ui/                       # L1: UI Layer (FULL REWRITE)
│   │   ├── __init__.py
│   │   ├── main_window.py        # REWRITE — v4 module nav
│   │   ├── pages.py              # REWRITE — page registry
│   │   ├── theme.py              # REWRITE — v4 design tokens
│   │   ├── theme_observer.py     # REWRITE — v4 theme binding
│   │   ├── screen_adapter.py     # KEEP — DPI scaling
│   │   ├── welcome.py            # REWRITE
│   │   │
│   │   ├── tabs/                 # REWRITE — all tabs
│   │   │   ├── __init__.py
│   │   │   ├── hud_tab.py        # NEW — Story HUD (overview dashboard)
│   │   │   ├── unit_editor_tab.py # REWRITE — unit editor
│   │   │   ├── graph_tab.py      # NEW — Story Graph visualization
│   │   │   ├── inspector_tab.py  # NEW — Character Inspector
│   │   │   ├── timeline_tab.py   # NEW — Timeline view
│   │   │   ├── outline_tab.py    # REWRITE
│   │   │   ├── worldview_tab.py  # REWRITE
│   │   │   ├── character_mgmt_tab.py # REWRITE
│   │   │   ├── generate_tab.py   # REWRITE
│   │   │   ├── settings_tab.py   # REWRITE
│   │   │   └── publish_tab.py    # NEW — unified publish view
│   │   │
│   │   ├── widgets/              # REWRITE — all widgets
│   │   │   ├── __init__.py
│   │   │   ├── module_nav.py     # REWRITE — v4 4-module nav
│   │   │   ├── story_hud.py      # REWRITE — HUD widget
│   │   │   ├── unit_editor.py    # REWRITE
│   │   │   ├── unit_tree.py      # REWRITE
│   │   │   ├── guide_panel.py    # REWRITE — v4 Guide signals panel
│   │   │   ├── decision_panel.py # NEW — Decision result display
│   │   │   ├── pressure_chart.py # NEW — Pressure curve chart
│   │   │   ├── settings_popup.py # REWRITE
│   │   │   ├── dialogs.py        # REWRITE
│   │   │   └── ...               # other widgets as needed
│   │   │
│   │   ├── observe/              # REWRITE — observation pages
│   │   │   ├── __init__.py
│   │   │   ├── story_health.py
│   │   │   ├── analytics.py
│   │   │   └── knowledge_page.py
│   │   │
│   │   └── workers/              # REWRITE — background workers
│   │       ├── __init__.py
│   │       └── generation_worker.py
│   │
│   ├── export/                   # L9: Publish Layer (KEEP + EXTEND)
│   │   ├── __init__.py
│   │   ├── exporters.py
│   │   └── platform_adapters/
│   │
│   └── resources/                # KEEP
│       ├── *.json
│       └── *.qss
│
├── story/                        # Story OS Core (L2-L8) — build around this
│   ├── __init__.py
│   │
│   ├── state/                    # L2: Story State (SSOT) — KEEP + EXTEND
│   │   ├── __init__.py
│   │   ├── story_state.py        # KEEP — frozen dataclass, immutable
│   │   ├── state_bridge.py       # KEEP — DB ↔ StoryState conversion
│   │   ├── apply_event.py        # KEEP — pure reducer
│   │   └── event_store.py        # NEW — EventStore persistence
│   │
│   ├── engine/                   # L10: Runtime Loop — KEEP + REWRITE
│   │   ├── __init__.py
│   │   ├── story_engine.py       # REWRITE — v4 StoryEngine facade
│   │   └── unit_runner.py        # REWRITE — v4 UnitRunner
│   │
│   ├── guide/                    # L3: Guide Engine — KEEP + REWRITE
│   │   ├── __init__.py
│   │   ├── collector.py          # REWRITE — v4 5-source signal collection
│   │   ├── pressure_source.py    # NEW — pressure guide source
│   │   ├── memory_source.py      # NEW — memory guide source
│   │   ├── consistency_source.py # NEW — consistency guide source
│   │   ├── voice_source.py       # NEW — voice guide source
│   │   ├── hook_source.py        # NEW — hook guide source
│   │   └── sources.py            # NEW — source registry
│   │
│   ├── decision/                 # L5: Decision Layer — KEEP + EXTEND
│   │   ├── __init__.py
│   │   ├── engine.py             # KEEP + EXTEND — conflict detection
│   │   ├── dimension_matrix.py   # KEEP — weight matrix
│   │   ├── strategy.py           # KEEP — 4 strategies
│   │   └── conflict.py           # NEW — conflict resolution
│   │
│   ├── prompt/                   # L6: Prompt OS — KEEP + REWRITE
│   │   ├── __init__.py
│   │   ├── compiler.py           # KEEP + EXTEND — SUC compiler
│   │   ├── suc_builder.py        # KEEP — SUC segments
│   │   ├── suc_template.py       # NEW — template engine
│   │   └── token_budget.py       # NEW — token budget optimizer
│   │
│   ├── events/                   # L7: Event System — NEW
│   │   ├── __init__.py
│   │   ├── types.py              # NEW — event type definitions
│   │   ├── store.py              # NEW — event store interface
│   │   └── reducer.py            # NEW — event reducer
│   │
│   ├── publish/                  # L9: Publish Layer — NEW
│   │   ├── __init__.py
│   │   ├── assembler.py          # NEW — unit → chapter assembly
│   │   ├── platform_adapter.py   # NEW — platform export interface
│   │   └── exporters/            # NEW — platform-specific exporters
│   │
│   └── ui/                       # L8: Observability UI — NEW
│       ├── __init__.py
│       ├── story_graph.py        # NEW — graph data model
│       ├── pressure_curve.py     # NEW — pressure curve data
│       └── inspector.py          # NEW — inspector data model
│
├── smoke/                        # Tests (KEEP + EXTEND)
│   ├── smoke_v4_guide_decision.py  # KEEP
│   ├── smoke_v4_prompt.py          # KEEP
│   ├── smoke_v4_runtime.py         # KEEP
│   ├── smoke_v4_state.py           # KEEP
│   ├── smoke_v4_isolation.py       # NEW
│   ├── smoke_v4_event_store.py     # NEW
│   ├── smoke_v4_publish.py         # NEW
│   └── ...                         # other smoke tests
│
├── docs/                         # Documentation
│   ├── ARCHITECTURE.md
│   ├── MIGRATION.md
│   └── CHANGELOG.md
│
└── tests/                        # Unit tests (NEW)
    ├── test_state.py
    ├── test_guide.py
    ├── test_decision.py
    ├── test_prompt.py
    ├── test_agents.py
    └── test_integration.py
```

---

## 2. Reuse vs Rewrite Matrix

### KEEP (solid, reusable) — Copy as-is

| Module | Source | Lines | Why Keep |
|--------|--------|-------|----------|
| `app/ai/*` | v3.4 | ~1200 | Clean provider abstraction, no changes needed |
| `app/core/*` | v3.4 | ~1800 | DI container, event bus, types — stable foundation |
| `app/db/*` | v3.4 | ~2000+ | Schema + migrations — backward compatible |
| `app/knowledge/*` | v3.4 | ~1000 | BM25 + vector DB — isolated, clean |
| `app/validators/*` | v3.4 | ~800 | Content validators — standalone |
| `app/adapters/*` | v3.4 | ~200 | Platform adapters — minimal |
| `app/services/project_service.py` | v3.4 | ~400 | Project CRUD — stable |
| `app/services/app_setting_service.py` | v3.4 | ~300 | Settings persistence — stable |
| `app/services/book_service.py` | v3.4 | ~200 | Book CRUD — stable |
| `app/services/chapter_service.py` | v3.4 | ~200 | Chapter CRUD — stable |
| `app/services/story_unit_service_v2.py` | v3.4 | ~300 | Unit CRUD — stable |
| `app/services/usage_analytics.py` | v3.4 | ~200 | Usage tracking — stable |
| `app/services/memory_manager.py` | v3.4 | ~500 | L1-L4 memory — keep, extend later |
| `app/services/pressure.py` | v3.4 | ~300 | Pressure signals — keep |
| `app/services/consistency.py` | v3.4 | ~400 | Consistency checks — keep |
| `app/services/voice_profile.py` | v3.4 | ~200 | Voice fingerprinting — keep |
| `app/services/voice_inferrer.py` | v3.4 | ~200 | Voice inference — keep |
| `app/services/style_fingerprint.py` | v3.4 | ~200 | Style fingerprinting — keep |
| `app/services/db.py` | v3.4 | ~100 | DB helper — keep |
| `app/services/exporter.py` | v3.4 | ~200 | Export — keep |
| `story/state/*` | v3.4 | ~600 | Core SSOT — immutable, event-sourced |
| `story/decision/strategy.py` | v3.4 | ~107 | 4 strategies — complete |
| `story/decision/dimension_matrix.py` | v3.4 | ~200 | Weight matrix — complete |
| `story/prompt/suc_builder.py` | v3.4 | ~268 | SUC segments — complete |
| `story/prompt/compiler.py` | v3.4 | ~130 | Prompt compilation — extend |
| `smoke/*` | v3.4 | ~70 files | Existing smoke tests — keep + add new |

### REWRITE (needs fresh design)

| Module | Source | Lines | Why Rewrite |
|--------|--------|-------|-------------|
| `app/ui/*` | v3.4 | ~5000+ | Full PySide6 UI rewrite — 133+ inline styles, no theme binding |
| `app/agents/*` | v3.4 | ~500 | Simplify to v4 Agent Simulation (4 agents) |
| `app/services/decision_service.py` | v3.4 | ~300 | Integrate v4 Decision Layer properly |
| `app/services/guide_graph.py` | v3.4 | ~200 | Integrate v4 Guide Engine |
| `story/guide/collector.py` | v3.4 | ~168 | Rewrite for 5-source architecture |
| `story/engine/story_engine.py` | v3.4 | ~92 | Rewrite as v4 facade |
| `story/engine/unit_runner.py` | v3.4 | ~172 | Rewrite as v4 UnitRunner |

### NEW (not in v3.4)

| Module | Purpose | Lines Est. |
|--------|---------|------------|
| `story/state/event_store.py` | EventStore persistence layer | ~150 |
| `story/events/*` | Event type definitions + store + reducer | ~300 |
| `story/guide/pressure_source.py` | Pressure guide source | ~80 |
| `story/guide/memory_source.py` | Memory guide source | ~80 |
| `story/guide/consistency_source.py` | Consistency guide source | ~80 |
| `story/guide/voice_source.py` | Voice guide source | ~80 |
| `story/guide/hook_source.py` | Hook guide source | ~80 |
| `story/guide/sources.py` | Source registry | ~50 |
| `story/decision/conflict.py` | Conflict resolution | ~100 |
| `story/prompt/suc_template.py` | Template engine | ~100 |
| `story/prompt/token_budget.py` | Token budget optimizer | ~80 |
| `story/publish/*` | Publish layer | ~300 |
| `story/ui/*` | Observability data models | ~200 |
| `app/agents/writer.py` | Writer agent | ~100 |
| `app/agents/reader.py` | Reader agent | ~100 |
| `app/agents/critic.py` | Critic agent | ~100 |
| `app/agents/memory_agent.py` | Memory agent | ~100 |
| `app/agents/isolation.py` | Isolation kernel | ~150 |
| `app/ui/tabs/hud_tab.py` | Story HUD | ~200 |
| `app/ui/tabs/graph_tab.py` | Story Graph | ~200 |
| `app/ui/tabs/inspector_tab.py` | Character Inspector | ~200 |
| `app/ui/tabs/timeline_tab.py` | Timeline view | ~200 |
| `app/ui/tabs/publish_tab.py` | Publish view | ~150 |
| `app/ui/widgets/decision_panel.py` | Decision display | ~100 |
| `app/ui/widgets/pressure_chart.py` | Pressure chart | ~150 |

---

## 3. Implementation Phases

### Phase 0: Project Bootstrap (Day 1)
**Goal**: Empty project that runs and passes basic smoke tests.

1. Create `D:\novel-writer-pure-v4.0` directory
2. Copy `pyproject.toml` → update version to `4.0.0`
3. Copy `app/core/` (all files) → no changes
4. Copy `app/db/` (all files) → no changes
5. Copy `app/ai/` (all files) → no changes
6. Create `app/__init__.py`, `app/__main__.py`, `app/main.py` (minimal)
7. Create `story/__init__.py`
8. Verify: `python -c "from app.core.config import AppConfig; print('OK')"`

### Phase 1: Story State Foundation (Days 2-3)
**Goal**: Immutable SSOT with event sourcing.

1. Copy `story/state/story_state.py` → keep as-is
2. Copy `story/state/apply_event.py` → keep as-is
3. Copy `story/state/state_bridge.py` → keep as-is
4. **NEW**: Create `story/state/event_store.py` — EventStore interface + SQLite implementation
5. **NEW**: Create `story/events/types.py` — event type definitions
6. **NEW**: Create `story/events/store.py` — event store interface
7. **NEW**: Create `story/events/reducer.py` — event reducer
8. Verify: smoke test passes with new EventStore

### Phase 2: Guide Engine (Days 4-5)
**Goal**: 5-source signal collection with proper isolation.

1. Copy `story/guide/collector.py` → REWRITE for v4 5-source architecture
2. **NEW**: Create `story/guide/pressure_source.py`
3. **NEW**: Create `story/guide/memory_source.py`
4. **NEW**: Create `story/guide/consistency_source.py`
5. **NEW**: Create `story/guide/voice_source.py`
6. **NEW**: Create `story/guide/hook_source.py`
7. **NEW**: Create `story/guide/sources.py` — source registry
8. Copy `app/services/pressure.py` → keep
9. Copy `app/services/consistency.py` → keep
10. Copy `app/services/memory_manager.py` → keep
11. Copy `app/services/voice_profile.py` → keep
12. Verify: guide collector produces signals from all 5 sources

### Phase 3: Decision Layer (Days 6-7)
**Goal**: Conflict detection + strategy selection.

1. Copy `story/decision/engine.py` → keep + extend
2. Copy `story/decision/dimension_matrix.py` → keep
3. Copy `story/decision/strategy.py` → keep
4. **NEW**: Create `story/decision/conflict.py` — conflict resolution
5. Verify: decision engine produces StrategyResult from signals

### Phase 4: Prompt OS (Days 8-9)
**Goal**: SUC compiler with token budget optimization.

1. Copy `story/prompt/compiler.py` → keep + extend
2. Copy `story/prompt/suc_builder.py` → keep
3. **NEW**: Create `story/prompt/suc_template.py` — template engine
4. **NEW**: Create `story/prompt/token_budget.py` — token budget optimizer
5. Verify: prompt compilation produces valid CompiledPrompt

### Phase 5: Agent Simulation (Days 10-12)
**Goal**: 4 agents with isolation kernel.

1. Rewrite `app/agents/base.py` → v4 AgentBase with isolation
2. **NEW**: Create `app/agents/writer.py`
3. **NEW**: Create `app/agents/reader.py`
4. **NEW**: Create `app/agents/critic.py`
5. **NEW**: Create `app/agents/memory_agent.py`
6. Rewrite `app/agents/orchestrator.py` → v4 orchestrator
7. Copy `app/agents/report.py` → keep + extend
8. **NEW**: Create `app/agents/isolation.py` — isolation kernel
9. Verify: agents execute in isolation, produce reports

### Phase 6: Runtime Loop (Days 13-14)
**Goal**: UnitRunner complete chain.

1. Rewrite `story/engine/story_engine.py` → v4 facade
2. Rewrite `story/engine/unit_runner.py` → v4 UnitRunner
3. Verify: full chain works end-to-end

### Phase 7: UI Foundation (Days 15-20)
**Goal**: Working UI shell with navigation.

1. Rewrite `app/ui/theme.py` → v4 design tokens
2. Rewrite `app/ui/theme_observer.py` → v4 theme binding
3. Rewrite `app/ui/main_window.py` → v4 module nav
4. Rewrite `app/ui/pages.py` → v4 page registry
5. Rewrite `app/ui/widgets/module_nav.py` → v4 nav
6. Rewrite `app/ui/welcome.py` → v4 welcome
7. Verify: app launches, navigation works

### Phase 8: UI Pages (Days 21-28)
**Goal**: All functional pages.

1. Rewrite `app/ui/tabs/generate_tab.py` → v4
2. Rewrite `app/ui/tabs/outline_tab.py` → v4
3. Rewrite `app/ui/tabs/worldview_tab.py` → v4
4. Rewrite `app/ui/tabs/character_mgmt_tab.py` → v4
5. **NEW**: Create `app/ui/tabs/hud_tab.py` → Story HUD
6. **NEW**: Create `app/ui/tabs/graph_tab.py` → Story Graph
7. **NEW**: Create `app/ui/tabs/inspector_tab.py` → Character Inspector
8. **NEW**: Create `app/ui/tabs/timeline_tab.py` → Timeline
9. **NEW**: Create `app/ui/tabs/publish_tab.py` → Publish
10. Rewrite `app/ui/tabs/settings_tab.py` → v4
11. Verify: all pages render and navigate

### Phase 9: Integration & Testing (Days 29-31)
**Goal**: Full integration + comprehensive testing.

1. Copy all existing `smoke/` tests → adapt to v4
2. **NEW**: Add `smoke_v4_isolation.py`
3. **NEW**: Add `smoke_v4_event_store.py`
4. **NEW**: Add `smoke_v4_publish.py`
5. Run full test suite
6. Manual UI testing
7. Performance profiling

---

## 4. File-by-File Plan

### 4.1 Core Infrastructure (KEEP as-is)

#### `app/core/config.py`
- **Action**: COPY from v3.4
- **Changes**: None
- **Dependencies**: None
- **Lines**: ~200

#### `app/core/container.py`
- **Action**: COPY from v3.4
- **Changes**: None
- **Dependencies**: None
- **Lines**: ~150

#### `app/core/event_bus.py`
- **Action**: COPY from v3.4
- **Changes**: None
- **Dependencies**: None
- **Lines**: ~100

#### `app/core/types.py`
- **Action**: COPY from v3.4
- **Changes**: None — Guide dataclass is already v4-compatible
- **Dependencies**: None
- **Lines**: ~331

### 4.2 Story State (KEEP + EXTEND)

#### `story/state/story_state.py`
- **Action**: COPY from v3.4
- **Changes**: None
- **Rationale**: Immutable frozen dataclass, perfect SSOT
- **Lines**: 295

#### `story/state/apply_event.py`
- **Action**: COPY from v3.4
- **Changes**: None
- **Rationale**: Pure reducer, no side effects
- **Lines**: 222

#### `story/state/state_bridge.py`
- **Action**: COPY from v3.4
- **Changes**: None
- **Lines**: ~100

#### `story/state/event_store.py` (NEW)
- **Action**: CREATE
- **Purpose**: Persist events to DB, enable replay
- **Interface**:
  ```python
  class EventStore:
      def append(self, unit_id: str, event: dict) -> None: ...
      def get_events(self, unit_id: str) -> list[dict]: ...
      def get_events_since(self, unit_id: str, since: float) -> list[dict]: ...
      def clear(self, unit_id: str) -> None: ...
  ```
- **Implementation**: SQLite-backed, uses existing DB schema
- **Lines**: ~150
- **Dependencies**: `app/db/`, `story/events/types.py`

### 4.3 Guide Engine (REWRITE)

#### `story/guide/collector.py` (REWRITE)
- **Action**: REWRITE
- **Purpose**: Collect signals from 5 sources
- **Current**: Single `collect_signals()` function
- **New**: 
  ```python
  class GuideCollector:
      def __init__(self, sources: list[GuideSource]): ...
      def collect(self, unit_id: str, *, state: StoryState = None) -> list[DecisionSignal]: ...
  ```
- **Sources**: pressure, memory, consistency, voice, hook
- **Lines**: ~200
- **Dependencies**: all 5 source modules

#### `story/guide/pressure_source.py` (NEW)
- **Action**: CREATE
- **Purpose**: Pressure signals from pacing analysis
- **Interface**: Implements `GuideSource` protocol
- **Lines**: ~80
- **Dependencies**: `app/services/pressure.py`

#### `story/guide/memory_source.py` (NEW)
- **Action**: CREATE
- **Purpose**: Memory signals from agent memory
- **Interface**: Implements `GuideSource` protocol
- **Lines**: ~80
- **Dependencies**: `app/services/memory_manager.py`

#### `story/guide/consistency_source.py` (NEW)
- **Action**: CREATE
- **Purpose**: Consistency signals from validators
- **Interface**: Implements `GuideSource` protocol
- **Lines**: ~80
- **Dependencies**: `app/validators/`, `app/services/consistency.py`

#### `story/guide/voice_source.py` (NEW)
- **Action**: CREATE
- **Purpose**: Voice signals from voice profiling
- **Interface**: Implements `GuideSource` protocol
- **Lines**: ~80
- **Dependencies**: `app/services/voice_profile.py`

#### `story/guide/hook_source.py` (NEW)
- **Action**: CREATE
- **Purpose**: Hook signals from hook tracking
- **Interface**: Implements `GuideSource` protocol
- **Lines**: ~80
- **Dependencies**: `story/state/story_state.py`

#### `story/guide/sources.py` (NEW)
- **Action**: CREATE
- **Purpose**: Source registry + protocol definition
- **Interface**:
  ```python
  class GuideSource(Protocol):
      source_id: str
      def collect(self, unit_id: str, *, state: StoryState = None) -> list[DecisionSignal]: ...
  ```
- **Lines**: ~50

### 4.4 Decision Layer (KEEP + EXTEND)

#### `story/decision/engine.py`
- **Action**: KEEP + extend
- **Changes**: Add conflict resolution integration
- **Lines**: 256

#### `story/decision/dimension_matrix.py`
- **Action**: KEEP
- **Changes**: None
- **Lines**: ~200

#### `story/decision/strategy.py`
- **Action**: KEEP
- **Changes**: None
- **Lines**: 107

#### `story/decision/conflict.py` (NEW)
- **Action**: CREATE
- **Purpose**: Detect and resolve conflicts between guides
- **Interface**:
  ```python
  def detect_conflicts(signals: list[DecisionSignal]) -> list[Conflict]: ...
  def resolve_conflicts(conflicts: list[Conflict], signals: list[DecisionSignal]) -> list[DecisionSignal]: ...
  ```
- **Lines**: ~100

### 4.5 Prompt OS (KEEP + EXTEND)

#### `story/prompt/compiler.py`
- **Action**: KEEP + extend
- **Changes**: Add template support, token budget
- **Lines**: 130

#### `story/prompt/suc_builder.py`
- **Action**: KEEP
- **Changes**: None
- **Lines**: 268

#### `story/prompt/suc_template.py` (NEW)
- **Action**: CREATE
- **Purpose**: Template engine for SUC segments
- **Lines**: ~100

#### `story/prompt/token_budget.py` (NEW)
- **Action**: CREATE
- **Purpose**: Optimize token usage across segments
- **Lines**: ~80

### 4.6 Agent Simulation (REWRITE)

#### `app/agents/base.py` (REWRITE)
- **Action**: REWRITE
- **Purpose**: v4 AgentBase with isolation kernel
- **Current**: 231 lines, complex state machine
- **New**: Simplified, isolation-focused
  ```python
  class AgentBase(ABC):
      role: AgentRole
      def execute(self, task: AgentTask) -> AgentReport: ...
      def _do_execute(self, task: AgentTask) -> AgentReport: ...
  ```
- **Lines**: ~200

#### `app/agents/isolation.py` (NEW)
- **Action**: CREATE
- **Purpose**: Isolation kernel for agents
- **Interface**:
  ```python
  class IsolationKernel:
      def __init__(self, agent: AgentBase): ...
      def run(self, task: AgentTask) -> AgentReport: ...
      def get_history(self) -> list[AgentReport]: ...
      def get_metrics(self) -> AgentMetrics: ...
  ```
- **Lines**: ~150

#### `app/agents/writer.py` (NEW)
- **Action**: CREATE
- **Purpose**: Writer agent — generates text
- **Lines**: ~100

#### `app/agents/reader.py` (NEW)
- **Action**: CREATE
- **Purpose**: Reader agent — evaluates quality
- **Lines**: ~100

#### `app/agents/critic.py` (NEW)
- **Action**: CREATE
- **Purpose**: Critic agent — style consistency
- **Lines**: ~100

#### `app/agents/memory_agent.py` (NEW)
- **Action**: CREATE
- **Purpose**: Memory agent — L1-L4 memory management
- **Lines**: ~100

#### `app/agents/orchestrator.py` (REWRITE)
- **Action**: REWRITE
- **Purpose**: v4 orchestrator with agent coordination
- **Current**: Complex, many responsibilities
- **New**: Simplified, focused on coordination
- **Lines**: ~300

### 4.7 Runtime Loop (REWRITE)

#### `story/engine/story_engine.py` (REWRITE)
- **Action**: REWRITE
- **Purpose**: v4 StoryEngine facade
- **Current**: 92 lines, basic facade
- **New**: Full v4 integration
  ```python
  class StoryEngine:
      def __init__(self, config: AppConfig): ...
      def run_unit(self, project_id: str, unit_id: str) -> RunResult: ...
      def apply_events(self, state: StoryState, events: list[dict]) -> StoryState: ...
  ```
- **Lines**: ~150

#### `story/engine/unit_runner.py` (REWRITE)
- **Action**: REWRITE
- **Purpose**: v4 UnitRunner — complete chain
- **Current**: 172 lines
- **New**: Full v4 chain with all integrations
  ```python
  class UnitRunner:
      def __init__(self, engine: StoryEngine): ...
      def run(self, project_id: str, unit_id: str) -> RunResult: ...
  ```
- **Lines**: ~200

### 4.8 UI Layer (FULL REWRITE)

#### `app/ui/theme.py` (REWRITE)
- **Action**: REWRITE
- **Purpose**: v4 design tokens
- **Current**: Hardcoded colors, no design system
- **New**: Token-based design system
  ```python
  # Color tokens
  class Theme:
      primary: str
      secondary: str
      background: str
      surface: str
      text: str
      text_secondary: str
      border: str
      error: str
      warning: str
      success: str
  
  # Spacing tokens
  SPACING = {4: 4, 8: 8, 12: 12, 16: 16, 24: 24, 32: 32}
  
  # Typography tokens
  FONT_SIZES = {"caption": 11, "body": 13, "heading": 16, "title": 20}
  ```
- **Lines**: ~200

#### `app/ui/theme_observer.py` (REWRITE)
- **Action**: REWRITE
- **Purpose**: Automatic theme binding
- **Current**: `bind_theme()` exists but unused (133+ inline styles)
- **New**: Comprehensive theme binding system
  ```python
  class ThemeObserver:
      def bind(self, widget: QWidget, property: str, token: str): ...
      def update_all(self): ...
  ```
- **Lines**: ~150

#### `app/ui/main_window.py` (REWRITE)
- **Action**: REWRITE
- **Purpose**: v4 module navigation
- **Current**: 662 lines, complex
- **New**: Simplified, 4-module layout
- **Lines**: ~400

#### `app/ui/pages.py` (REWRITE)
- **Action**: REWRITE
- **Purpose**: v4 page registry
- **Current**: 2677 lines, monolithic
- **New**: Clean registry, each page in its own file
- **Lines**: ~200

#### `app/ui/tabs/hud_tab.py` (NEW)
- **Action**: CREATE
- **Purpose**: Story HUD — overview dashboard
- **Lines**: ~200

#### `app/ui/tabs/graph_tab.py` (NEW)
- **Action**: CREATE
- **Purpose**: Story Graph visualization
- **Lines**: ~200

#### `app/ui/tabs/inspector_tab.py` (NEW)
- **Action**: CREATE
- **Purpose**: Character Inspector
- **Lines**: ~200

#### `app/ui/tabs/timeline_tab.py` (NEW)
- **Action**: CREATE
- **Purpose**: Timeline view
- **Lines**: ~200

#### `app/ui/tabs/publish_tab.py` (NEW)
- **Action**: CREATE
- **Purpose**: Unified publish view
- **Lines**: ~150

---

## 5. Dependencies & Integration

### 5.1 Dependency Graph

```
                    ┌─────────────┐
                    │  app/ui/    │  L1: UI Layer
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ app/agents/ │  L4: Agent Simulation
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──────┐ ┌──▼─────┐ ┌───▼────┐
       │ story/guide │ │ story/ │ │ story/ │
       │   (L3)      │ │decision│ │ prompt │
       └──────┬──────┘ │  (L5)  │ │  (L6)  │
              │         └───┬────┘ └───┬────┘
              │             │          │
       ┌──────▼─────────────▼──────────▼──────┐
       │           story/state (L2)            │
       │          StoryState (SSOT)            │
       └──────────────────┬───────────────────┘
                          │
              ┌───────────▼───────────┐
              │     app/db/ (L7)      │
              │   EventStore + SQL    │
              └───────────────────────┘
```

### 5.2 Integration Points

1. **UI → Agents**: UI calls `Orchestrator.execute(task)` via workers
2. **Agents → Guide**: Agents call `GuideCollector.collect()`
3. **Guide → Decision**: Collector produces `DecisionSignal` → Decision engine
4. **Decision → Prompt**: `StrategyResult` → Prompt compiler
5. **Prompt → AI**: `CompiledPrompt` → `app/ai/engine.py`
6. **AI → State**: LLM output → events → `apply_event()` → new `StoryState`
7. **State → DB**: `EventStore.append()` persists events
8. **DB → UI**: UI reads from DB via services

### 5.3 External Dependencies

```toml
# pyproject.toml
dependencies = [
    "PySide6>=6.5",
    "numpy",
    "scikit-learn",
    "jieba",
    "requests",
]
```

No new external dependencies required. v4 is built entirely on existing deps.

---

## 6. Testing Strategy

### 6.1 Unit Tests (NEW)

| Test File | Coverage |
|-----------|----------|
| `tests/test_state.py` | StoryState creation, mutation, event application |
| `tests/test_guide.py` | 5-source signal collection, conflict detection |
| `tests/test_decision.py` | Strategy selection, weight matrix |
| `tests/test_prompt.py` | SUC building, prompt compilation |
| `tests/test_agents.py` | Agent isolation, report generation |
| `tests/test_integration.py` | End-to-end chain |

### 6.2 Smoke Tests (KEEP + EXTEND)

| Test File | Status |
|-----------|--------|
| `smoke_v4_state.py` | KEEP — test StoryState |
| `smoke_v4_guide_decision.py` | KEEP — test guide → decision |
| `smoke_v4_prompt.py` | KEEP — test prompt compilation |
| `smoke_v4_runtime.py` | KEEP — test runtime loop |
| `smoke_v4_isolation.py` | NEW — test agent isolation |
| `smoke_v4_event_store.py` | NEW — test event persistence |
| `smoke_v4_publish.py` | NEW — test publish layer |

### 6.3 Manual Testing

1. **App launch**: Verify app starts without errors
2. **Navigation**: All 4 modules navigate correctly
3. **Theme**: Dark/light mode switch works
4. **Generation**: Full generation pipeline works
5. **Settings**: All settings save/load correctly
6. **Export**: Export to TXT/DOCX works

### 6.4 Performance Testing

1. **Startup time**: < 3 seconds
2. **Generation**: < 30 seconds for a chapter
3. **Memory**: < 500MB for a full project
4. **DB queries**: < 100ms for common operations

---

## 7. Migration Path

### 7.1 Database Compatibility

v4.0 maintains **full backward compatibility** with v3.4 databases:

- Same `schema.sql` tables
- Same column names and types
- Same JSON blob formats
- New `events` table for EventStore (additive, not breaking)

### 7.2 Migration Steps

1. **Backup**: User backs up v3.4 DB
2. **Copy DB**: Copy `data/*.db` to v4.0 project
3. **Run v4.0**: App detects v3.4 DB, runs any pending migrations
4. **Verify**: All existing data accessible

### 7.3 Code Migration

1. **Copy KEEP modules**: Direct copy, no changes
2. **Copy REWRITE modules**: Copy as reference, rewrite fresh
3. **Copy tests**: Adapt to v4 imports

### 7.4 Rollback Plan

- v3.4 project remains untouched
- v4.0 is a separate directory
- User can switch between versions by changing working directory

---

## Appendix: Key Design Decisions

### A.1 Why Keep `story/state/*` as-is?

The `StoryState` frozen dataclass is already a perfect SSOT implementation:
- Immutable (frozen=True)
- Event-sourced (apply_event returns new instance)
- Queryable (to_dict(), active_hooks(), etc.)
- Bridge pattern (StateBridge for DB ↔ runtime)

No changes needed. Build around it.

### A.2 Why Rewrite `story/guide/collector.py`?

Current implementation has issues:
- Single function, not extensible
- Hardcoded source mapping
- No proper source isolation

New design:
- `GuideSource` protocol for extensibility
- `GuideCollector` class with injectable sources
- Each source is independent and testable

### A.3 Why Full UI Rewrite?

v3.4 UI has systemic issues:
- 133+ inline `setStyleSheet` calls
- No theme binding (bind_theme exists but unused)
- Monolithic `pages.py` (2677 lines)
- Complex navigation with mapping inconsistencies

v4.0 UI:
- Token-based design system
- Automatic theme binding
- Each page in its own file
- Simplified 4-module navigation

### A.4 Why Agent Isolation?

v3.4 agents share context and can interfere:
- No context isolation
- No metric tracking per agent
- Complex state machine

v4.0 agents:
- Each agent runs in isolation
- Per-agent metrics and history
- Simple state machine (idle → working → done/error)
- Reports as only communication channel

---

## Summary

| Metric | v3.4 | v4.0 Target |
|--------|------|-------------|
| Total files | ~200 | ~180 (fewer, cleaner) |
| UI files | 50+ | 30 (simplified) |
| Agent files | 6 | 8 (more, but cleaner) |
| Story files | 15 | 25 (more, but modular) |
| Test files | 70 | 80 (more coverage) |
| Lines of code | ~15,000 | ~12,000 (less, better) |
| External deps | 5 | 5 (no new deps) |
| DB compatibility | - | 100% backward compatible |
