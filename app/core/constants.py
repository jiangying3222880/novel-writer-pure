"""
4.0 全局常量
- 所有枚举/状态/符号 集中在这里
- 不允许在业务代码里写 magic string / number
"""
from __future__ import annotations


# ────────────────────── 章节状态符号 (I8 拍板 8 个) ──────────────────────

class ChapterStatus:
    """章节状态 (用于章节管理 Tab 树状结构)。"""
    AI_GENERATED = "ai_generated"     # ✏️ AI 生成完
    EDITED = "edited"                 # ✓ 已编辑保存
    EDITING = "editing"               # ⏳ 编辑中未保存
    WITH_MINDSET = "with_mindset"     # 🧠 用了 6 问
    REWRITING = "rewriting"           # 🔄 重写中
    ERROR = "error"                   # ❌ 报错
    NEEDS_CONFIRM = "needs_confirm"   # ⚠️ 评分<阈值待确认
    PENDING = "pending"               # 待开始


# 符号 → 状态映射
CHAPTER_STATUS_SYMBOLS = {
    ChapterStatus.AI_GENERATED: "✏️",
    ChapterStatus.EDITED: "✓",
    ChapterStatus.EDITING: "⏳",
    ChapterStatus.WITH_MINDSET: "🧠",
    ChapterStatus.REWRITING: "🔄",
    ChapterStatus.ERROR: "❌",
    ChapterStatus.NEEDS_CONFIRM: "⚠️",
    ChapterStatus.PENDING: "○",
}


# ────────────────────── Subtext 模式 (G3 拍板 3 模式) ──────────────────────

class SubtextMode:
    AI_AUTO = "ai_auto"               # 默认, AI 自动生成卡
    MANUAL = "manual"                  # 手动 (模板选 + 改)
    CLOSED = "closed"                  # 不用


# 6 预置 subtext 模板 (G3 拍板)
SUBTEXT_TEMPLATE_PRESETS = [
    ("对峙", "对质/冲突/压抑的对话场景"),
    ("离别", "分离/告别/不舍的瞬间"),
    ("暧昧", "半推半就/情愫未明的对话"),
    ("反转", "揭示真相/身份大转变"),
    ("重逢", "多年后/不同立场再见面"),
    ("隐瞒", "藏秘密/嘴心分离/话里有话"),
]


# ────────────────────── Subtext 字段 (G3 拍板 13 字段) ──────────────────────

class SubtextField:
    """subtext card 13 字段名 (避免拼写错误)。"""
    SURFACE_EVENT = "surface_event"
    TRUE_INTENT = "true_intent"
    LIE = "lie"
    TRUTH = "truth"
    PHYSICAL_ANCHOR = "physical_anchor"
    REAL_INTENT_OTHERS = "real_intent_others"
    EMOTIONAL = "emotional"
    PACING = "pacing"
    VIEWPOINT = "viewpoint"
    ANTI_RULES = "anti_rules"
    CALLBACK_TO = "callback_to"
    SCENE_MAP = "scene_map"
    ENDING_SCENE_STATE = "ending_scene_state"


SUBTEXT_FIELD_COUNT = 13


# ────────────────────── 记忆层级 (E2 拍板 L1-L4) ──────────────────────

class MemoryLevel:
    L1_ARC = "L1"                      # 故事弧 (always available)
    L2_COMMITMENT = "L2"               # 承诺 (must fulfill)
    L2_WORLD_RULE = "L2"               # 世界规则 (immutable)
    L3_RAG = "L3"                      # 细节检索 (RAG)
    L4_FADE = "L4"                     # 优雅遗忘


# ────────────────────── 叙事压力 (E2 拍板 4 zone) ──────────────────────

class PressureZone:
    GREEN = "green"                    # 0-30 自由
    YELLOW = "yellow"                  # 30-70 谨慎
    ORANGE = "orange"                  # 70-95 必关
    RED = "red"                        # 95+ 阻止


PRESSURE_THRESHOLDS = {
    PressureZone.GREEN: 30,
    PressureZone.YELLOW: 70,
    PressureZone.ORANGE: 95,
}


# ────────────────────── 一致性维度 (G5 拍板 4 维) ──────────────────────

class ConsistencyDimension:
    CHARACTER = "character"
    LOCATION = "location"
    TIME = "time"
    ITEM = "item"


# ────────────────────── 模型角色 (A3 拍板) ──────────────────────

class ModelRole:
    PRIMARY = "primary"
    FALLBACK = "fallback"


# ────────────────────── 主题材 + 辅题材 (A1 拍板) ──────────────────────

class GenreTier:
    PRIMARY = "primary"                # 1 个
    AUX = "aux"                        # X 个


# ────────────────────── Task 类型 (A2 拍板 用量统计) ──────────────────────

class TaskType:
    WRITE = "write"                    # 写正文
    SUBTEXT = "subtext"                # subtext 卡
    CRITIC = "critic"                  # critic 评估
    HOOK = "hook"                      # hook 评估
    OUTLINE = "outline"                # 大纲
    IMPORT = "import"                  # 导入解析
    MINDSET = "mindset"                # 6 问
    CONSISTENCY = "consistency"        # 一致性检测
    STYLE_LEARN = "style_learn"        # 风格学习
    VOICE_INFER = "voice_infer"        # 声音推断
    DISTILL = "distill"                # 蒸馏


# ────────────────────── 写作步骤 (G1 拍板 v3_engine 7 步) ──────────────────────

class WriteStep:
    LOAD_MEMORY = "load_memory"        # 1. 读 L1-L4
    ANTI_AI = "anti_ai"                # 2. 检查 6 大去 AI 味
    PRESSURE = "pressure"              # 3. 检查叙事压力
    RETRIEVE = "retrieve"              # 4. 检索知识库
    GENERATE = "generate"              # 5. 调 AI 写
    EVALUATE = "evaluate"              # 6. critic/hook 评估
    SYNC = "sync"                      # 7. 触发同步


WRITE_STEP_ORDER = [
    WriteStep.LOAD_MEMORY,
    WriteStep.ANTI_AI,
    WriteStep.PRESSURE,
    WriteStep.RETRIEVE,
    WriteStep.GENERATE,
    WriteStep.EVALUATE,
    WriteStep.SYNC,
]


# ────────────────────── 评估器 (G11-G16) ──────────────────────

class EvaluatorKind:
    POV = "pov"                        # 视角
    SPATIAL = "spatial"                # 空间
    REPETITION = "repetition"          # 重复
    SETTING = "setting"                # 设定
    ITEM = "item"                      # 物品
    VOICE = "voice"                    # 声音


# ────────────────────── 双层风格指纹 (G6 rev2) ──────────────────────

class AuthorDim:
    """L1 作者指纹 6 维: 描述"这个人怎么写" — 跨书迁移."""
    SENTENCE_RHYTHM = "sentence_rhythm"          # 句子节奏 (1=短促 10=流水)
    DIALOGUE_DENSITY = "dialogue_density"         # 对话密度 (1=叙述 10=对话)
    DESCRIPTION_STYLE = "description_style"       # 描写风格 (1=动作 10=氛围)
    EMOTION_EXPRESSION = "emotion_expression"     # 情绪表达 (1=直说 10=暗示)
    PARAGRAPH_DENSITY = "paragraph_density"       # 段落密度 (1=密集 10=舒朗)
    LANGUAGE_LEVEL = "language_level"             # 语言层级 (1=口语 10=文学)


class BookDim:
    """L2 作品指纹 4 维: 描述"这本小说的调性" — 随书而定."""
    GENRE_TONE = "genre_tone"                    # 题材基调 (1=轻快 10=厚重)
    ATMOSPHERE_TENDENCY = "atmosphere_tendency"   # 氛围取向 (1=温情 10=紧张)
    NARRATIVE_COMPLEXITY = "narrative_complexity" # 叙事复杂度 (1=简单 10=复杂)
    PACING_PREFERENCE = "pacing_preference"       # 节奏偏好 (1=快节奏 10=慢热)


# [DEPRECATED] 旧 5 维 — 保留向后兼容, 新代码使用 AuthorDim/BookDim
class StyleDim:
    CULTIVATION = "cultivation_level"  # 修真度 (已废弃)
    INTRIGUE = "intrigue_level"        # 阴谋度 (已废弃)
    TONE = "tone"                      # 色调 (已废弃)
    SENTENCE_LENGTH = "sentence_length"
    VOCABULARY = "vocabulary"


# ────────────────────── 声音档案 5 维 (G9 拍板) ──────────────────────

class VoiceDim:
    PERSONALITY = "personality"
    SENTENCE_LENGTH = "sentence_length"
    TONE_WORDS = "tone_words"
    CATCHPHRASES = "catchphrases"
    METAPHOR_PREF = "metaphor_pref"


# ────────────────────── 角色追踪 5 维 (E1 拍板) ──────────────────────

class TrackerDim:
    LOCATION = "location"
    STATE = "state"
    POWER_LEVEL = "power_level"
    EQUIPMENT = "equipment"
    RELATIONSHIP = "relationship"


# ────────────────────── 世界观 5 表类型 (D3 拍板) ──────────────────────

class WorldTable:
    POWER_SYSTEM = "power_system"
    LOCATION = "location"
    ITEM = "item"
    CHARACTER = "character"
    FACTION = "faction"


# ────────────────────── 5 文件 store 类型 (D3 拍板) ──────────────────────

class StoreFile:
    """每个项目下的 5 个 JSON 文件 (静态 MD 之外的动态 store)。"""
    METADATA = "01_metadata.json"
    CHARACTERS = "02_characters.json"
    LOCATIONS = "03_locations.json"
    ITEMS = "04_items.json"
    RELATIONSHIPS = "05_relationships.json"


# ────────────────────── 文件路径 / 目录名 ──────────────────────

class DirName:
    LOGS = "logs"
    KNOWLEDGE = "knowledge"
    DATA = "data"
    BACKUPS = "backups"


# ────────────────────── 题材清单 (内置预置, A1 拍板) ──────────────────────

PRESET_GENRES = [
    "仙侠", "修真", "玄幻", "奇幻",
    "古言", "宫斗", "宅斗", "穿越",
    "都市", "职场", "校园", "商战",
    "悬疑", "推理", "犯罪", "灵异",
    "科幻", "末世", "机甲", "星际",
    "军事", "历史", "武侠", "同人",
]


# ────────────────────── 内置预置题材库 (H2 拍板) ──────────────────────

PRESET_KNOWLEDGE_CATEGORIES = [
    "文风语料",
    "桥段",
    "人物人设",
    "场景描写",
    "框架模板",
]


# ────────────────────── 4 大问题 (subtext 11 条拍板) ──────────────────────

class FourBigProblems:
    """AI vs 真人 4 大差距 (去 AI 味优先级)。"""
    EMOTION_FADE = "E7"               # 情感衰减曲线
    PACING_BREATH = "E8"              # 节奏呼吸
    READER_INFO = "E9"                # 读者信息差
    PATTERN_DEDUPE = "E10"            # 跨章叙事去重


# ────────────────────── 默认 4 大题材选择限制 (A1 拍板 1+X) ──────────────────────

MAX_PRIMARY_GENRES = 1
MAX_AUX_GENRES = 3   # 默认 3, 可在设置里改


# ────────────────────── 默认设置 (B7 + J2 等可改) ──────────────────────

DEFAULT_SETTINGS = {
    # ─────────── 引擎 (P2: 不再硬编码) ───────────
    "engine.max_retries": 3,
    "engine.retry_delays": [2, 4, 8],
    "engine.use_fallback": True,
    # ─────────── 日志 (P3: 不再硬编码) ───────────
    "log.retention_days": 7,
    "log.max_bytes": 10 * 1024 * 1024,         # 10 MB
    # ─────────── 备份 (4.0 修复: 原 UI 改完不保存, 现在存到 app_settings) ───────────
    "backup.auto": True,                        # 自动备份开关
    "backup.interval_hours": 24,                # 备份间隔 (1-168)
    "backup.keep_count": 7,                     # 保留份数 (1-100)
    # ─────────── DB (P5: 不再硬编码) ───────────
    "db.journal_mode": "WAL",
    "db.isolation_level": None,                # None = autocommit
    # ─────────── 模型 (P1: 价格从 seed 读) ───────────
    "model.price_updated_at": "2026-01-01",    # seed_models.json 里的价格基准日
    # ─────────── 业务 (其他) ───────────
    "subtext.default_mode": SubtextMode.AI_AUTO,
    "genre.max_primary": MAX_PRIMARY_GENRES,
    "genre.max_aux": MAX_AUX_GENRES,
    "ui.theme": "light",                       # light / dark
    "ui.scale": 1.0,                           # 0.8 - 1.5 (I7 实时缩放)
    "ui.font_size": 14,
    "ui.line_spacing": 1.5,
    "auth.standard_features": True,
    "auth.advanced_features": False,           # 高级版开关
    # ─────────── v3.0 Edit Signals 开关 (改稿信号 → Skill 沉淀) ───────────
    "signal_enabled": True,                    # L1: 全功能
    "signal_popup_muted": False,               # L2: 静默不弹窗
    "signal_llm_generalize_enabled": False,    # LLM 异步泛化 (opt-in, 默认关)
    "signal_inject_to_prompt": True,           # 注入到 writer prompt (默认开, 修订闭环通电)
    "signal_anti_aggregate_enabled": True,     # 反例聚合开关
    "signal_debounce_ms": 30000,               # Layer 1 30s 防抖
    "signal_curator_chapter_threshold": 5,     # Layer 3 5 章触发
    "signal_curator_signal_threshold": 50,     # Layer 3 50 信号触发
    "signal_curator_cooldown_hours": 24,       # Layer 3 24h 冷却
    "signal_evolve_candidate_threshold": 3,    # Layer 4 3 候选触发
    "signal_evolve_patch_threshold": 5,        # Layer 4 5 patch 触发
    "signal_evolve_cooldown_hours": 24,        # Layer 4 24h 冷却
    "signal_inject_max_skills": 3,             # Layer 5 hard cap
    "signal_inject_max_tokens": 500,           # Layer 5 hard cap
    "signal_inject_fresh_days": 30,            # Layer 5 30 天新鲜度
    "signal_stale_days": 30,                   # 状态机 stale 阈值
    "signal_archive_days": 90,                 # 状态机 archive 阈值
    "signal_promote_proven_use": 5,            # use >= 5 → proven
    "signal_promote_builtin_use": 20,          # use >= 20 + patch==0 → builtin
    "signal_uncertain_patch_ratio": 0.5,       # patch/(patch+use) >= 0.5 → uncertain
    "signal_max_candidates": 30,               # 单项目最大候选数
}


# ────────────────────── 工具: 获取常量名 ──────────────────────

def all_chapter_statuses() -> list[str]:
    return [s for s in dir(ChapterStatus) if not s.startswith("_") and s.isupper()]


def all_task_types() -> list[str]:
    return [s for s in dir(TaskType) if not s.startswith("_") and s.isupper()]
