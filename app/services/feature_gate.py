"""
app/services/feature_gate.py - M9-C: 功能分级 / 付费门控 (Feature Gate)

设计:
- 3 个等级: free (永久) / standard (默认, 标准版) / pro (付费高级版)
- 功能 → 最低等级映射 (FEATURE_TIERS)
- 等级比较: 数字越大越高级 (free=0 < standard=1 < pro=2)
- 跟 license 集成: license.status==PREMIUM 视同 pro (永久/未过期)
- 跟插件解耦: is_plugin_unlocked() 也走这个 gate (统一规则)

公开 API:
    Tier, FeatureInfo, FEATURE_REGISTRY, FEATURE_TIERS
    get_tier()                       -> 当前等级 (基于 license)
    check_feature(feature_id)        -> bool (是否解锁)
    require_tier(feature_id)         -> decorator (HTTP/CLI 用)
    list_features()                  -> [(feature_id, info, unlocked)]
    format_tier_badge()              -> "🥉 免费版" 等 UI 文案
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Dict, List, Optional, Tuple

_logger = logging.getLogger("NovelWriter.services.feature_gate")


# ============================================================
# 等级
# ============================================================


class Tier(str, Enum):
    """用户等级 (3 档)."""
    FREE = "free"           # 永久免费层
    STANDARD = "standard"   # 标准版 (默认, 基础功能)
    PRO = "pro"            # 专业版 (付费解锁)


# 等级排序: 用于比较
_TIER_ORDER: Dict[Tier, int] = {
    Tier.FREE: 0,
    Tier.STANDARD: 1,
    Tier.PRO: 2,
}


def tier_rank(t: Tier) -> int:
    """等级 → 数字 (越大越高级)."""
    return _TIER_ORDER.get(t, 0)


def tier_meets(actual: Tier, required: Tier) -> bool:
    """actual 是否 >= required."""
    return tier_rank(actual) >= tier_rank(required)


# ============================================================
# 功能元数据
# ============================================================


@dataclass(frozen=True)
class FeatureInfo:
    """单个功能的信息."""
    feature_id: str
    name: str
    description: str
    tier: Tier                    # 最低要求等级
    category: str = "general"     # general / writing / export / ai / collab
    token_cost: str = ""          # 估算的 token 成本 (UI 展示, 留空 = 不计)
    extra: Dict[str, str] = field(default_factory=dict)


# ============================================================
# 功能注册表 (中央)
# ============================================================


# 注: tier 字段的含义是"最低需要 X 才能用"
FEATURE_TIERS: Dict[str, FeatureInfo] = {
    # ── 基础 (FREE) ──
    "core.editor": FeatureInfo(
        "core.editor", "章节编辑器", "基础的章节编辑 + 保存", Tier.FREE,
        category="general",
    ),
    "core.project": FeatureInfo(
        "core.project", "项目管理", "新建 / 删除 / 浏览项目", Tier.FREE,
        category="general",
    ),
    "core.chapter.create": FeatureInfo(
        "core.chapter.create", "新建章节", "手动新建空章节", Tier.FREE,
        category="writing",
    ),
    # ── 标准 (STANDARD) ──
    "writing.draft": FeatureInfo(
        "writing.draft", "AI 章节生成", "AI 根据潜文本卡生成章节草稿",
        Tier.STANDARD, category="writing", token_cost="~3000-8000 tokens/章",
    ),
    "writing.rewrite": FeatureInfo(
        "writing.rewrite", "段落重写", "AI 重写指定段落", Tier.STANDARD,
        category="writing", token_cost="~500-2000 tokens/次",
    ),
    "writing.expand": FeatureInfo(
        "writing.expand", "AI 扩写", "AI 把短段落扩成长段", Tier.STANDARD,
        category="writing", token_cost="~1000-3000 tokens/次",
    ),
    "subtext.basic": FeatureInfo(
        "subtext.basic", "潜文本卡 (手动)", "手动配置 6 种场景模板",
        Tier.STANDARD, category="writing",
    ),
    "tts.mock": FeatureInfo(
        "tts.mock", "TTS 章节朗读 (mock)", "生成占位 wav 文件", Tier.STANDARD,
        category="export",
    ),
    "export.md": FeatureInfo(
        "export.md", "导出 Markdown", "导出 .md 格式", Tier.STANDARD,
        category="export",
    ),
    "export.txt": FeatureInfo(
        "export.txt", "导出 TXT", "导出 .txt 纯文本", Tier.STANDARD,
        category="export",
    ),
    # ── 专业 (PRO) ──
    "ai.critic": FeatureInfo(
        "ai.critic", "AI Critic 评估", "AI 自动评分 + 反馈", Tier.PRO,
        category="ai", token_cost="~1000-3000 tokens/次",
    ),
    "ai.batch_regen": FeatureInfo(
        "ai.batch_regen", "批量重生成", "一键重写多章节", Tier.PRO,
        category="ai", token_cost="~3000 tokens × 章节数",
    ),
    "subtext.auto": FeatureInfo(
        "subtext.auto", "潜文本卡 (AI 自动)", "AI 自动生成潜文本卡", Tier.PRO,
        category="ai", token_cost="~500-1500 tokens/章",
    ),
    "tts.edge": FeatureInfo(
        "tts.edge", "TTS 章节朗读 (edge 在线)", "edge-tts 高质量在线合成",
        Tier.PRO, category="export", token_cost="免费 (edge-tts)",
    ),
    "export.epub": FeatureInfo(
        "export.epub", "导出 EPUB 电子书", "标准 EPUB 3.0 格式", Tier.PRO,
        category="export",
    ),
    "export.docx": FeatureInfo(
        "export.docx", "导出 Word (DOCX)", "Office Open XML 格式", Tier.PRO,
        category="export",
    ),
    "export.cover": FeatureInfo(
        "export.cover", "封面生成", "5 种模板自动生成封面", Tier.PRO,
        category="export",
    ),
    "ai.router.parallel": FeatureInfo(
        "ai.router.parallel", "AI 并行调度", "多模型并发投票", Tier.PRO,
        category="ai", token_cost="成本 × 模型数 (并行)",
    ),
    "ai.router.fallback": FeatureInfo(
        "ai.router.fallback", "AI 降级链", "主模型失败自动降级", Tier.PRO,
        category="ai",
    ),
    "ai.cache": FeatureInfo(
        "ai.cache", "AI 响应缓存", "重复 prompt 命中缓存省钱", Tier.PRO,
        category="ai",
    ),
    "plugin.marketplace": FeatureInfo(
        "plugin.marketplace", "插件市场", "安装第三方 .nwp 插件", Tier.PRO,
        category="general",
    ),
    "collab.cloud": FeatureInfo(
        "collab.cloud", "云同步 (未来)", "多设备同步项目", Tier.PRO,
        category="collab",
    ),
    "publish.oneclick": FeatureInfo(
        "publish.oneclick", "一键出版", "批量导出 + 封面 + 目录", Tier.PRO,
        category="export",
    ),
}


# ============================================================
# 当前等级判定
# ============================================================


def get_tier() -> Tier:
    """当前用户等级. 基于 license 状态.

    - 无 license / STANDARD → STANDARD
    - PREMIUM + 未过期 → PRO
    - EXPIRED / INVALID / MACHINE_MISMATCH → 降回 STANDARD (不锁死用户, 让 ta 重输)
    """
    try:
        from app.services.license import (
            get_license as _gl,
            LicenseStatus,
        )
        info = _gl()
        if info.status == LicenseStatus.PREMIUM and not info.error_msg:
            return Tier.PRO
        return Tier.STANDARD
    except Exception as e:
        _logger.debug("get_tier 降级到 STANDARD: %s", e)
        return Tier.STANDARD


# ============================================================
# 功能检查
# ============================================================


def check_feature(feature_id: str) -> bool:
    """某功能当前是否可用."""
    info = FEATURE_TIERS.get(feature_id)
    if info is None:
        _logger.warning("check_feature: 未知 feature_id=%s", feature_id)
        return False
    return tier_meets(get_tier(), info.tier)


def get_feature_info(feature_id: str) -> Optional[FeatureInfo]:
    """取一个功能的元数据."""
    return FEATURE_TIERS.get(feature_id)


def list_features() -> List[Tuple[str, FeatureInfo, bool]]:
    """列出所有功能 + 当前是否解锁. 用于 UI 面板 + CLI.

    Returns: [(feature_id, info, unlocked), ...] 按 tier 升序, 同 tier 按 feature_id 排.
    """
    actual = get_tier()
    out: List[Tuple[str, FeatureInfo, bool]] = []
    for fid, info in FEATURE_TIERS.items():
        out.append((fid, info, tier_meets(actual, info.tier)))
    out.sort(key=lambda t: (tier_rank(t[1].tier), t[0]))
    return out


def required_tier(feature_id: str) -> Tier:
    """某功能需要的最低等级 (UI 提示)."""
    info = FEATURE_TIERS.get(feature_id)
    return info.tier if info else Tier.FREE


# ============================================================
# 装饰器: 门控 AI 写作 / HTTP / CLI
# ============================================================


class FeatureLockedError(Exception):
    """功能未解锁, 抛此异常."""
    def __init__(self, feature_id: str, required: Tier, actual: Tier, *, unknown: bool = False):
        self.feature_id = feature_id
        self.required = required
        self.actual = actual
        self.unknown = unknown  # True = feature_id 不存在
        if unknown:
            super().__init__(
                f"功能 '{feature_id}' 不存在 (请检查 feature_id, 拼写错误? )"
            )
        else:
            super().__init__(
                f"功能 '{feature_id}' 需要 {required.value} 等级, 当前 {actual.value}。"
                f"升级请到设置 → 授权, 输入 license key。"
            )


def require_tier(feature_id: str):
    """装饰器: 调用函数前检查 tier. 不通过抛 FeatureLockedError.

    用法:
        @require_tier("ai.critic")
        def ai_critique(...): ...
    """
    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            actual = get_tier()
            info = FEATURE_TIERS.get(feature_id)
            if info is None:
                # 未知功能 → 抛 unknown=True 的错误 (拼错就立刻发现)
                raise FeatureLockedError(feature_id, Tier.PRO, actual, unknown=True)
            if not tier_meets(actual, info.tier):
                raise FeatureLockedError(feature_id, info.tier, actual)
            return fn(*args, **kwargs)
        return wrapped
    return deco


def assert_feature(feature_id: str) -> None:
    """检查功能, 不通过抛 FeatureLockedError."""
    actual = get_tier()
    info = FEATURE_TIERS.get(feature_id)
    if info is None:
        raise FeatureLockedError(feature_id, Tier.PRO, actual, unknown=True)
    if not tier_meets(actual, info.tier):
        raise FeatureLockedError(feature_id, info.tier, actual)


# ============================================================
# UI 文案
# ============================================================


_TIER_BADGE = {
    Tier.FREE: ("🥉", "免费版"),
    Tier.STANDARD: ("🥈", "标准版"),
    Tier.PRO: ("🥇", "专业版"),
}


_TIER_DESC = {
    Tier.FREE: "永久免费的基础功能",
    Tier.STANDARD: "默认开通, 含 AI 写作 / 草稿 / 段落重写",
    Tier.PRO: "付费高级版, 解锁全部 AI / 出版 / 插件功能",
}


def format_tier_badge(tier: Optional[Tier] = None) -> str:
    """UI 顶部徽章: '🥈 标准版'."""
    if tier is None:
        tier = get_tier()
    icon, label = _TIER_BADGE.get(tier, ("❓", tier.value))
    return f"{icon} {label}"


def format_tier_description(tier: Optional[Tier] = None) -> str:
    """tier 的描述 (1 句)."""
    if tier is None:
        tier = get_tier()
    return _TIER_DESC.get(tier, "")


def format_feature_line(feature_id: str, info: FeatureInfo, unlocked: bool) -> str:
    """UI/CLI 单行展示: '✅ ai.critic  AI Critic 评估    [PRO]'."""
    mark = "✅" if unlocked else "🔒"
    req = info.tier.value.upper()
    cost = f"  ({info.token_cost})" if info.token_cost else ""
    return f"  {mark} {feature_id:<24} {info.name}    [{req}]{cost}"


# ============================================================
# 兼容: 旧版 is_plugin_unlocked 重新走 feature gate
# ============================================================


def is_plugin_unlocked_v2(plugin_id: str, *, required_role: str = "user") -> bool:
    """新版插件解锁: 走 feature gate.

    - 内置插件 (required_role=builtin) 永远解锁
    - 其他插件 → 需要 PRO
    """
    if required_role == "builtin":
        return True
    if required_role == "standard":
        return tier_meets(get_tier(), Tier.STANDARD)
    # premium / pro / external / market
    return tier_meets(get_tier(), Tier.PRO)
