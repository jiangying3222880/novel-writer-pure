"""
G11-G16 验证器框架
6 个独立模块, 每个专注一类内容质量检查:
  - G11 props     道具: 持有/位置/状态跨章一致, 凭空出现/消失
  - G12 pov       视角: 第一/第二/第三人称一致, 内心独白边界
  - G13 repetition 重复: 段落/短语/常用词 N-gram 过度重复
  - G14 setting   设定: 世界规则一致性 (修真不能用热武器, 古代无汽车等)
  - G15 space     空间: 场景/空间跳跃无解释, 同场景矛盾 (门朝东/朝西)
  - G16 voice     声音: 角色台词是否匹配 voice_profile

设计原则:
  - 独立模块, 可单独 import + 单独运行
  - 统一 API: validate_chapter(project_id, chapter_id) -> ValidatorResult
  - 统一 ValidationIssue (dim, severity, description, chapter_no, char_span, suggestion)
  - 不强制依赖 G5 consistency.py / G8 voice_inferrer (可注入)
  - 0 tokens, 纯本地规则
"""
from .base import (
    # 维度
    DIM_PROPS, DIM_POV, DIM_REPETITION, DIM_SETTING, DIM_SPACE, DIM_VOICE,
    ALL_DIMS, DIM_LABELS, DIM_CODES,
    # 严重度
    SEV_INFO, SEV_WARNING, SEV_ERROR, ALL_SEVS, SEV_LABELS,
    # 数据类
    ValidationIssue, ValidatorResult, BaseValidator,
    # 注册表
    ValidatorRegistry, get_default_registry,
)

__all__ = [
    "DIM_PROPS", "DIM_POV", "DIM_REPETITION", "DIM_SETTING", "DIM_SPACE", "DIM_VOICE",
    "ALL_DIMS", "DIM_LABELS", "DIM_CODES",
    "SEV_INFO", "SEV_WARNING", "SEV_ERROR", "ALL_SEVS", "SEV_LABELS",
    "ValidationIssue", "ValidatorResult", "BaseValidator",
    "ValidatorRegistry", "get_default_registry",
]
