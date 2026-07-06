"""
G11-G16 验证器基础类
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# ============================================================
# 6 个维度
# ============================================================
DIM_PROPS = "props"
DIM_POV = "pov"
DIM_REPETITION = "repetition"
DIM_SETTING = "setting"
DIM_SPACE = "space"
DIM_VOICE = "voice"

ALL_DIMS = [DIM_PROPS, DIM_POV, DIM_REPETITION, DIM_SETTING, DIM_SPACE, DIM_VOICE]

DIM_LABELS = {
    DIM_PROPS: "道具",
    DIM_POV: "视角",
    DIM_REPETITION: "重复",
    DIM_SETTING: "设定",
    DIM_SPACE: "空间",
    DIM_VOICE: "声音",
}

DIM_CODES = {
    "G11": DIM_PROPS,
    "G12": DIM_POV,
    "G13": DIM_REPETITION,
    "G14": DIM_SETTING,
    "G15": DIM_SPACE,
    "G16": DIM_VOICE,
}


# ============================================================
# 严重度
# ============================================================
SEV_INFO = "info"
SEV_WARNING = "warning"
SEV_ERROR = "error"
ALL_SEVS = [SEV_INFO, SEV_WARNING, SEV_ERROR]

SEV_LABELS = {SEV_INFO: "提示", SEV_WARNING: "警告", SEV_ERROR: "严重"}


# ============================================================
# 问题数据类
# ============================================================
@dataclass
class ValidationIssue:
    """单个验证问题."""
    dimension: str  # 维度 (props/pov/...)
    severity: str  # info/warning/error
    description: str  # 问题描述 (中文)
    chapter_no: Optional[int] = None
    char_start: Optional[int] = None  # 文中位置 (字符)
    char_end: Optional[int] = None
    suggestion: str = ""  # 修复建议
    related: str = ""  # 关联 entity 名 (道具/角色/地点)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidatorResult:
    """单个验证器在单章的结果."""
    dimension: str
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == SEV_ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == SEV_WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == SEV_INFO)

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "issue_count": len(self.issues),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [i.to_dict() for i in self.issues],
        }


# ============================================================
# 验证器基类
# ============================================================
class BaseValidator:
    """验证器基类. 子类需重写 dimension, name, _do_validate."""

    dimension: str = ""  # 子类必填: DIM_PROPS 等
    name: str = ""  # 子类必填: 中文名

    def __init__(self, *, voice_profiles: Optional[dict] = None,
                  world_settings: Optional[dict] = None) -> None:
        """初始化.

        Args:
            voice_profiles: {角色名: voice_profile dict} (供 G16 注入, G8 推断结果)
            world_settings: {key: value} 世界设定 (供 G14 注入)
        """
        self._voice_profiles = voice_profiles or {}
        self._world_settings = world_settings or {}

    def validate_chapter(self, project_id: str, chapter_id: str,
                          *, content: str = "", chapter_no: int = 0,
                          context: Optional[dict] = None) -> ValidatorResult:
        """验证单章. 子类可重写此方法, 默认调 _do_validate.

        Args:
            project_id: 项目 ID
            chapter_id: 章节 ID
            content: 章节正文 (可选, 不传则从 DB 读)
            chapter_no: 章号 (可选)
            context: 上下文 dict (供 G11 传跨章道具状态等)

        Returns:
            ValidatorResult
        """
        if not content:
            content, chapter_no = self._load_chapter(project_id, chapter_id)
        return self._do_validate(project_id, chapter_id, content, chapter_no, context or {})

    # 子类重写:
    def _do_validate(self, project_id: str, chapter_id: str,
                      content: str, chapter_no: int,
                      context: dict) -> ValidatorResult:
        raise NotImplementedError

    # 工具: 加载章节正文
    def _load_chapter(self, project_id: str, chapter_id: str) -> tuple[str, int]:
        from app.services import chapter_service
        ch = chapter_service.get(chapter_id)
        draft = chapter_service.get_current_draft(chapter_id)
        content = draft.get("content", "") if draft else ""
        return content, ch.get("chapter_no", 0)

    # 工具: 加载跨章历史 (供 G11 道具状态追踪)
    def _load_chapter_history(self, project_id: str, up_to_chapter_no: int) -> list[tuple[int, str, str]]:
        """加载项目所有 ≤ up_to_chapter_no 的章 (chapter_no, chapter_id, content)."""
        from app.services import book_service, chapter_service
        books = book_service.list_for_project(project_id).get("books", [])
        out: list[tuple[int, str, str]] = []
        for b in books:
            chs = chapter_service.list_for_book(b["id"]).get("chapters", [])
            for ch in chs:
                if ch.get("chapter_no", 0) > up_to_chapter_no:
                    continue
                draft = chapter_service.get_current_draft(ch["id"])
                content = draft.get("content", "") if draft else ""
                out.append((ch.get("chapter_no", 0), ch["id"], content))
        out.sort(key=lambda x: x[0])
        return out

    # 工具: 加载世界设定 (供 G14)
    def _load_world_settings(self, project_id: str) -> dict:
        try:
            from app.services import worldbuilding
            items = worldbuilding.list_all(project_id, worldbuilding.KIND_SETTING)
            return {e.name: e.description for e in items} if items else {}
        except Exception:
            return {}

    # 工具: 加载世界物品 (供 G11 / G14)
    def _load_world_items(self, project_id: str) -> list[str]:
        try:
            from app.services import worldbuilding
            items = worldbuilding.list_all(project_id, worldbuilding.KIND_ITEM)
            return [e.name for e in items] if items else []
        except Exception:
            return []

    # 工具: 加载世界地点 (供 G15)
    def _load_world_locations(self, project_id: str) -> list[str]:
        try:
            from app.services import worldbuilding
            items = worldbuilding.list_all(project_id, worldbuilding.KIND_LOCATION)
            return [e.name for e in items] if items else []
        except Exception:
            return []


# ============================================================
# 验证器注册表
# ============================================================
class ValidatorRegistry:
    """验证器注册表 - 单例."""

    _validators: dict = {}

    @classmethod
    def register(cls, validator_id: str, validator: BaseValidator) -> None:
        cls._validators[validator_id] = validator

    @classmethod
    def get(cls, validator_id: str) -> Optional[BaseValidator]:
        return cls._validators.get(validator_id)

    @classmethod
    def all(cls) -> dict:
        return dict(cls._validators)

    @classmethod
    def all_ids(cls) -> list:
        return list(cls._validators.keys())

    @classmethod
    def clear(cls) -> None:
        cls._validators.clear()


def get_default_registry() -> ValidatorRegistry:
    """获取默认注册表 (含 G11-G16 全部 6 个)."""
    if not ValidatorRegistry._validators:
        from .props import PropsValidator
        from .pov import POVValidator
        from .repetition import RepetitionValidator
        from .setting import SettingValidator
        from .space import SpaceValidator
        from .voice import VoiceValidator
        ValidatorRegistry.register("G11", PropsValidator())
        ValidatorRegistry.register("G12", POVValidator())
        ValidatorRegistry.register("G13", RepetitionValidator())
        ValidatorRegistry.register("G14", SettingValidator())
        ValidatorRegistry.register("G15", SpaceValidator())
        ValidatorRegistry.register("G16", VoiceValidator())
    return ValidatorRegistry
