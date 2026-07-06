"""
app/workflow/edit_signals/models.py

数据模型 (4 字段 + 章节文件切分):
  - EditSignal: 一条用户改稿信号 (ts/kind/chapter_id/payload)
  - SignalKind: enum (regen / manual_edit / discard)
  - SkillState: enum (active / stale / archived) - Hermes v0.16.0 借鉴
  - CandidateSkill: 沉淀的候选 Skill (含 use_count/patch_count/last_activity_at/pinned)
  - AntiPattern: 反例 Skill (从 discard 信号聚合)
"""
from __future__ import annotations
import time
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


# ────────────────────── SignalKind ──────────────────────

class SignalKind(str, Enum):
    """3 种信号来源 (v3.0 §4.1)."""
    REGEN = "regen"                  # 重新生成 (接受/放弃)
    MANUAL_EDIT = "manual_edit"      # 手动编辑段落
    DISCARD = "discard"              # 删除整段


# ────────────────────── SkillState (3 状态机) ──────────────────────

class SkillState(str, Enum):
    """3 状态自动机 (Hermes v0.16.0 借鉴) - §8.1."""
    ACTIVE = "active"                # 默认: 注入候选
    STALE = "stale"                  # 30 天无活动 → 降级, 不注入
    ARCHIVED = "archived"            # 90 天无活动 → 归档, 不显示


# 候选状态 (v3.0 进化层, 4 状态)
SKILL_CANDIDATE_STATE = "candidate"      # 刚沉淀
SKILL_PROVEN_STATE = "proven"            # use_count >= 5
SKILL_BUILTIN_STATE = "builtin"          # use_count >= 20 + patch == 0
SKILL_UNCERTAIN_STATE = "uncertain"      # patch/use >= 0.5

# ────────────────────── EditSignal (顶层 4 字段) ──────────────────────

@dataclass
class EditSignal:
    """一条用户改稿信号 (§5.2)."""
    kind: SignalKind
    chapter_id: str
    payload: dict                                # 自由 JSON, 按 kind 选字段
    ts: float = field(default_factory=time.time)
    project_id: str = ""                         # 写入时注入

    def to_jsonl(self) -> str:
        """序列化为 1 行 JSONL (§5.3)."""
        d = asdict(self)
        d["kind"] = self.kind.value
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_jsonl(cls, line: str) -> "EditSignal":
        d = json.loads(line)
        return cls(
            kind=SignalKind(d["kind"]),
            chapter_id=str(d["chapter_id"]),
            payload=d.get("payload", {}),
            ts=float(d.get("ts", 0)),
            project_id=str(d.get("project_id", "")),
        )


# ────────────────────── CandidateSkill (沉淀的 Skill) ──────────────────────

@dataclass
class CandidateSkill:
    """沉淀的候选 Skill (Layer 3 产出, Layer 4 进化, Layer 5 注入)."""
    name: str                                    # pattern 名 (e.g. "polish", "anti_xxx")
    version: int = 1
    state: str = SKILL_CANDIDATE_STATE           # candidate/proven/builtin/uncertain
    created_at: float = field(default_factory=time.time)
    created_by: str = "user_edit"               # §7.1 Hermes 借鉴
    agent_created: bool = False                  # §7.1 兼容字段
    source_signals: int = 0                      # 沉淀时合并的信号数
    source_chapters: list[int] = field(default_factory=list)  # 来源章节 ID 列表
    pattern_hint: str = ""                       # 1 句话描述 (§9.2)
    before_examples: list[str] = field(default_factory=list)  # 最多 5 条
    after_examples: list[str] = field(default_factory=list)   # 最多 5 条
    # ── v3.0 Layer 4 进化新增字段 ──
    generalized_rule: str = ""                   # LLM 泛化产出 (§20.4.3)
    generalized_at: float = 0.0                  # 泛化时间戳
    generalize_failed: bool = False              # 泛化失败标记
    # ── 反例 Skill 专用 ──
    kind: str = "skill"                          # "skill" / "anti_pattern"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CandidateSkill":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "CandidateSkill":
        return cls.from_dict(json.loads(raw))


# ────────────────────── AntiPattern (反例 Skill) ──────────────────────

@dataclass
class AntiPattern:
    """反例 Skill (从 discard 信号聚合, §20.4.5).

    与 CandidateSkill 区别:
      - name 前缀 "anti_"
      - pattern_hint 写 "❌ 写手不喜欢的修法: xxx"
      - state 独立 (不参与 use_count 评分)
    """
    name: str
    version: int = 1
    state: str = SKILL_CANDIDATE_STATE
    created_at: float = field(default_factory=time.time)
    created_by: str = "user_edit"
    agent_created: bool = False
    source_signals: int = 0
    source_chapters: list[int] = field(default_factory=list)
    pattern_hint: str = ""
    discard_examples: list[str] = field(default_factory=list)
    kind: str = "anti_pattern"
    generalized_rule: str = ""
    generalized_at: float = 0.0
    generalize_failed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AntiPattern":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "AntiPattern":
        return cls.from_dict(json.loads(raw))

    def to_candidate(self) -> CandidateSkill:
        """转 CandidateSkill (统一存储, 用 prefix 区分)."""
        return CandidateSkill(
            name=self.name,
            version=self.version,
            state=self.state,
            created_at=self.created_at,
            created_by=self.created_by,
            agent_created=self.agent_created,
            source_signals=self.source_signals,
            source_chapters=self.source_chapters,
            pattern_hint=self.pattern_hint,
            before_examples=[],  # 反例无 before
            after_examples=self.discard_examples,
            generalized_rule=self.generalized_rule,
            generalized_at=self.generalized_at,
            generalize_failed=self.generalize_failed,
            kind=self.kind,
        )


# ────────────────────── SidecarEntry (candidate_usage.json 一行) ──────────────────────

@dataclass
class SidecarEntry:
    """candidate_usage.json 里一个 candidate 的 sidecar (§7.2)."""
    name: str
    version: int = 1
    use_count: int = 0                         # 被 prompt 引用次数
    patch_count: int = 0                       # §7.2 写手手动编辑 (永不归档)
    last_patched_at: float = 0.0
    last_activity_at: float = field(default_factory=time.time)
    activity_count: int = 0
    status: str = SKILL_CANDIDATE_STATE
    pinned: bool = False                       # §7.3 钉住 = 永久 active
    state: str = SKILL_CANDIDATE_STATE         # 同 status, alias

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SidecarEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ────────────────────── CursorLogEntry (cursor.log 一行) ──────────────────────

@dataclass
class CursorLogEntry:
    """cursor.log 一行 (§20.5) - 审计/回滚辅助."""
    step: str                                  # merge/promote/generalize/discard/...
    candidates_before: int = 0
    candidates_after: int = 0
    changed: list[str] = field(default_factory=list)
    duration_ms: int = 0
    ts: float = field(default_factory=time.time)
    note: str = ""

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
