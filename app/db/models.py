"""
数据模型（C4: dataclass）
- 对齐 4.0 现状 schema (app/db/schema.sql)
- 字段名一一对应
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional
import json


def to_dict(obj) -> dict:
    return asdict(obj)


def from_row(cls, row):
    if row is None:
        return None
    field_names = {f.name for f in cls.__dataclass_fields__.values()}
    data = {k: row[k] for k in row.keys() if k in field_names}
    return cls(**data)


def from_rows(cls, rows) -> list:
    return [from_row(cls, r) for r in rows]


# ────────────────────── Project ──────────────────────

@dataclass
class Project:
    id: str
    name: str
    book_title: str = ""
    genre: str = ""                     # 主题材 (A1.1 兼容旧字段)
    platform: str = ""
    word_target: int = 200000
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Book (卷) ──────────────────────

@dataclass
class Book:
    id: str
    project_id: str
    volume_no: int
    title: str = ""
    synopsis: str = ""
    target_chapters: int = 100
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Chapter ──────────────────────

@dataclass
class Chapter:
    id: str
    book_id: str
    chapter_no: int
    status: str = "draft"               # draft / generated / critiqued / persisted / reviewed
    title: str = ""
    scene_context: str = ""
    draft: str = ""
    final: str = ""
    critique: str = ""
    checkpoint: str = ""
    word_count: int = 0
    review_flag: str = "pending"        # pending / accepted / problem
    source_unit_id: str = ""            # 来源单元 ID (单元驱动)
    split_version: int = 0              # 同一单元拆出的版本号
    is_current_version: int = 1         # 1=当前有效, 0=被重拆覆盖的旧章节
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Chapter Brief (6 问基础) ──────────────────────

@dataclass
class ChapterBrief:
    id: str
    chapter_id: str
    brief: str = ""                     # 完整 brief
    core_events: str = ""               # 核心事件
    emotion_arc: str = ""               # 情绪曲线
    volume_no: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Subtext Card (基础 5 字段 + 9.0 扩展字段) ──────────────────────
# 4.0 现状: surface_event / true_intent / lie / truth / physical_anchor
# 9.0 加: real_intent_others / emotional / pacing / viewpoint / anti_rules / callback_to / scene_map / ending_scene_state / source / template_id / updated_at

@dataclass
class SubtextCard:
    id: str
    chapter_id: str
    surface_event: str = ""
    true_intent: str = ""
    lie: str = ""
    truth: str = ""
    physical_anchor: str = ""
    # 9.0 扩展
    real_intent_others: str = ""
    emotional: str = ""
    pacing: str = ""
    viewpoint: str = ""
    anti_rules: str = ""
    callback_to: str = ""
    scene_map: str = ""
    ending_scene_state: str = ""
    source: str = "manual"
    template_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Subtext Project Mode ──────────────────────

@dataclass
class SubtextProjectMode:
    project_id: str
    mode: str = "ai_auto"               # ai_auto / manual / closed
    template_id: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Subtext Template (6 预置) ──────────────────────

@dataclass
class SubtextTemplate:
    id: str
    name: str
    description: str = ""
    template_json: str = "{}"
    built_in: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def get_template(self) -> dict:
        return json.loads(self.template_json) if self.template_json else {}


# ────────────────────── Worldbuilding (5 表) ──────────────────────

@dataclass
class WorldPowerSystem:
    id: str
    project_id: str
    name: str
    level: int = 0
    description: str = ""
    metadata: str = "{}"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class WorldLocation:
    id: str
    project_id: str
    name: str
    region: str = ""
    description: str = ""
    metadata: str = "{}"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class WorldItem:
    id: str
    project_id: str
    name: str
    owner: str = ""
    tier: str = ""
    description: str = ""
    metadata: str = "{}"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class WorldFaction:
    id: str
    project_id: str
    name: str
    description: str = ""
    metadata: str = "{}"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class WorldRelation:
    id: str
    project_id: str
    src_id: str
    src_type: str
    dst_id: str
    dst_type: str
    relation: str
    valid_from_chapter: Optional[int] = None
    valid_to_chapter: Optional[int] = None
    metadata: str = "{}"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Character Tracker (5 维度) ──────────────────────

@dataclass
class CharacterTracker:
    id: str
    project_id: str
    chapter_id: str
    character_name: str
    location: str = ""
    state: str = ""
    power_level: str = ""
    equipment: str = ""
    relationship: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── World State Snapshot (4.0 现状 schema 字段) ──────────────────────

@dataclass
class WorldStateSnapshot:
    id: str
    project_id: str
    chapter_no: int
    entity_name: str
    entity_kind: str = ""
    state_value: str = ""
    changes_delta: str = ""
    source: str = "observer"             # observer / manual / imported
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Agent Memory (4.0 现状 schema: tier/entity_type/entity_name) ──────────────────────

@dataclass
class AgentMemory:
    id: str
    chapter_id: Optional[str]
    tier: str                           # L1 / L2 / L3 / L4
    entity_type: str = ""               # character / location / item / faction / hook / promise
    entity_name: str = ""
    content: str = ""
    token_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Narrative Pressure ──────────────────────

@dataclass
class NarrativePressure:
    id: str
    project_id: str
    chapter_id: str
    pressure: int = 0
    active_hooks: int = 0
    open_promises: int = 0
    unresolved_subplots: int = 0
    zone: str = "green"
    deadline_chapter: Optional[int] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Knowledge (3 张表) ──────────────────────

@dataclass
class KnowledgeBuiltin:
    id: str
    category: str
    genre: str
    name: str
    content: str = ""
    metadata: str = "{}"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class KnowledgeLocal:
    id: str
    project_id: str
    name: str
    file_path: str
    content: str = ""
    file_type: str = "txt"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class KnowledgeIndex:
    id: str
    source_type: str                    # builtin / local / chapter / entity
    source_id: str
    chunk_index: int = 0
    content: str = ""
    bm25_tokens: str = ""
    vector_blob: bytes = b""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Style / Voice ──────────────────────

@dataclass
class AuthorFingerprint:
    """L1 作者指纹 (6 维): 描述笔法, 跨书迁移."""
    id: str = ""
    user_id: str = "default"
    sentence_rhythm: int = 5
    dialogue_density: int = 5
    description_style: int = 5
    emotion_expression: int = 5
    paragraph_density: int = 5
    language_level: int = 5
    source: str = "manual"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class BookFingerprint:
    """L2 作品指纹 (4 维): 描述调性, 随书而定."""
    id: str = ""
    project_id: str = ""
    genre_tone: int = 5
    atmosphere_tendency: int = 5
    narrative_complexity: int = 5
    pacing_preference: int = 5
    source: str = "manual"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class StyleFingerprint:
    """[DEPRECATED] 旧版风格指纹模型, 保留向后兼容."""
    id: str = ""
    project_id: str = ""
    cultivation_level: int = 5
    intrigue_level: int = 5
    tone: int = 5
    sentence_length: int = 5
    vocabulary: int = 5
    source: str = "manual"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class VoiceProfile:
    id: str
    project_id: str
    character_name: str
    personality: int = 5
    sentence_length: int = 5
    tone_words: str = ""
    catchphrases: str = ""
    metaphor_pref: int = 5
    source: str = "manual"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Consistency Log ──────────────────────

@dataclass
class ConsistencyLog:
    id: str
    project_id: str
    chapter_id: str
    dimension: str                      # character / location / time / item
    severity: str = "warning"
    description: str = ""
    chapter_a: Optional[int] = None
    chapter_b: Optional[int] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Model Config (A3 + A4) ──────────────────────

@dataclass
class ModelConfig:
    id: str
    provider: str                       # openai_compat / anthropic
    model_name: str
    base_url: str = ""
    api_key: str = ""
    role: str = "primary"
    rpm_limit: int = 60
    tpm_limit: int = 90000
    input_price: float = 0.0
    output_price: float = 0.0
    max_tokens: int = 4096
    supports_streaming: bool = True
    supports_thinking: bool = False
    built_in: bool = False
    price_updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Usage Record (4.0 现状 schema 字段) ──────────────────────

@dataclass
class UsageRecord:
    id: str
    project_id: Optional[str]
    chapter_id: Optional[str]
    provider: str = ""
    model: str = ""
    step: str = ""                      # write / subtext / critic / hook / outline / import
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    duration_ms: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UsageSummary:
    id: str
    project_id: str
    month: str                          # 'YYYY-MM'
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    task_breakdown: str = "{}"
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class StoryUnit:
    id: str
    project_id: str
    story_order: int = 0
    title: str = ""
    unit_type: str = ""                 # battle / romance / reveal / transition / ...
    status: str = "draft"               # draft / writing / completed / split
    synopsis: str = ""
    draft: str = ""
    word_count: int = 0
    emotion_basis: str = ""
    entry_characters: str = ""          # JSON
    entry_world: str = ""               # JSON
    entry_commitments: str = ""         # JSON
    exit_characters: str = ""           # JSON
    exit_world: str = ""                # JSON
    exit_commitments: str = ""          # JSON
    unit_memories: str = ""             # JSON array
    target_chapter_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UnitHookMap:
    id: str
    project_id: str
    hook_desc: str = ""
    hook_type: str = "promise"          # promise / active / fulfilled
    plant_unit_id: str = ""
    payoff_unit_id: str = ""
    plant_chapter_id: str = ""
    payoff_chapter_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ────────────────────── Unit v2 (Phase 0 新版) ──────────────────────

@dataclass
class StoryUnitV2:
    """故事单元 v2（双时间线 + 衔接类型 + 写作进度）"""
    id: str
    project_id: str
    book_id: str = ""
    unit_no: int = 0
    title: str = ""
    unit_type: str = "other"
    story_order: int = 0
    present_order: int = 0
    status: str = "draft"
    synopsis: str = ""
    draft: str = ""
    word_count: int = 0
    emotion_basis: str = ""
    transition_type: str = "direct"
    transition_text: str = ""
    pov_character: str = ""
    timeline_label: str = "现在"
    entry_characters: str = ""
    entry_world: str = ""
    entry_commitments: str = ""
    exit_characters: str = ""
    exit_world: str = ""
    exit_commitments: str = ""
    unit_memories: str = ""
    target_chars: int = 5000
    target_chapter_count: int = 2
    current_step: int = 0
    total_steps: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UnitBrief:
    """单元大纲"""
    id: str
    unit_id: str
    project_id: str
    brief: str = ""
    core_events: str = "[]"
    emotion_arc: str = ""
    cause_summary: str = ""
    effect_summary: str = ""
    hooks_planned_plant: str = "[]"
    hooks_planned_pay: str = "[]"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UnitWritingSnapshot:
    """写作断点快照"""
    id: str
    unit_id: str
    project_id: str
    step_no: int
    draft_text: str
    unit_summary: str = ""
    word_count: int = 0
    character_state: str = "{}"
    world_state: str = "{}"
    active_hooks: str = "[]"
    step_prompt: str = ""
    model_used: str = ""
    tokens_used: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UnitParagraph:
    """单元段落（段落 ID 锚点，单元与章节的桥梁）"""
    id: str
    unit_id: str
    project_id: str
    sort_order: int
    text: str
    char_start: int = -1
    char_end: int = -1
    paragraph_type: str = "normal"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UnitHookMapV2:
    """单元-钩子映射 v2（段落锚点版）"""
    id: str
    unit_id: str
    project_id: str
    hook_id: str = ""
    hook_type: str = "plant"
    paragraph_id: str = ""
    step_no: int = 0
    description: str = ""
    manual_locked: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UnitCausalEdge:
    """单元因果边"""
    id: str
    project_id: str
    from_unit_id: str
    to_unit_id: str
    edge_type: str = "direct"
    description: str = ""
    strength: float = 1.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UnitCausalGroup:
    """剧情线（单元组）"""
    id: str
    project_id: str
    name: str
    color: str = "#4A90D9"
    description: str = ""
    unit_ids: str = "[]"
    sort_order: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SplitConfig:
    """分章规则配置"""
    id: str
    project_id: str
    book_id: str = ""
    name: str = "默认"
    target_chars: int = 3000
    min_chars: int = 2000
    max_chars: int = 5000
    split_strategy: str = "auto"
    use_ai_analysis: int = 1
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
