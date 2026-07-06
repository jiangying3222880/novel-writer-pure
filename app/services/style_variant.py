"""
风格变体生成器 - 多版本正文生成的"发散->收敛"算法.

核心思路:
  - 第 1 轮: 3 个版本的风格指纹差异大 (spread=4), 让用户感受截然不同的文字风格
  - 第 2 轮: 基于用户选定的版本, 缩小差异 (spread=2)
  - 第 3+ 轮: 继续收敛, 最终稳定在 +-1 的波动区间 (不固定死, 保留创作弹性)

6 维作者风格指纹 (L1, 1-10):
  sentence_rhythm    句子节奏 (1=短促 10=流水)
  dialogue_density   对话密度 (1=叙述 10=对话)
  description_style  描写风格 (1=动作 10=氛围)
  emotion_expression 情绪表达 (1=直说 10=暗示)
  paragraph_density  段落密度 (1=密集 10=舒朗)
  language_level     语言层级 (1=口语 10=文学)
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

# 收敛参数
INITIAL_SPREAD = 4   # 第 1 轮: +-4, 差异最大
MIN_SPREAD = 1       # 最小波动: +-1, 不固定死
SPREAD_DECAY = 0.5   # 每轮衰减系数

# L1 作者指纹 6 维
VARIANT_DIMS = [
    "sentence_rhythm",
    "dialogue_density",
    "description_style",
    "emotion_expression",
    "paragraph_density",
    "language_level",
]

VARIANT_DIM_LABELS = {
    "sentence_rhythm": "句子节奏",
    "dialogue_density": "对话密度",
    "description_style": "描写风格",
    "emotion_expression": "情绪表达",
    "paragraph_density": "段落密度",
    "language_level": "语言层级",
}


@dataclass
class StyleVariant:
    """单个版本的风格变体 (L1 作者指纹 6 维)."""
    label: str  # "A" / "B" / "C"
    sentence_rhythm: int = 5
    dialogue_density: int = 5
    description_style: int = 5
    emotion_expression: int = 5
    paragraph_density: int = 5
    language_level: int = 5

    def to_dict(self) -> dict:
        return {d: getattr(self, d) for d in VARIANT_DIMS}

    def to_prompt_block(self) -> str:
        """转成注入 prompt 的文本块."""
        label_map = VARIANT_DIM_LABELS
        parts = [f"[版本 {self.label} 风格指纹]"]
        for d in VARIANT_DIMS:
            v = getattr(self, d)
            parts.append(f"  {label_map[d]}: {v}/10")
        return "\n".join(parts)

    def distance_to(self, other: "StyleVariant") -> float:
        """计算与另一个变体的欧氏距离 (用于 UI 展示差异度)."""
        total = 0
        for d in VARIANT_DIMS:
            diff = getattr(self, d) - getattr(other, d)
            total += diff * diff
        return (total ** 0.5)


def _clamp(v: int, lo: int = 1, hi: int = 10) -> int:
    return max(lo, min(hi, v))


def generate_variants(
    base: dict,
    *,
    spread: int = INITIAL_SPREAD,
    selected_label: Optional[str] = None,
    seed: Optional[int] = None,
) -> list[StyleVariant]:
    """基于基准作者指纹生成 3 个风格变体.

    Args:
        base: 基准风格指纹 dict (L1 6 维, 值 1-10)
        spread: 每维最大偏移量 (+-spread). 第 1 轮=4, 后续递减.
        selected_label: 上一轮用户选定的版本标签 ("A"/"B"/"C").
                        非 None 时, 该版本以 base 为基准 (偏移更小),
                        其他版本以 base+-spread 为基准.
        seed: 随机种子 (测试用).

    Returns:
        [variant_A, variant_B, variant_C]
    """
    if seed is not None:
        random.seed(seed)

    labels = ["A", "B", "C"]
    variants = []

    for label in labels:
        variant = {}
        for d in VARIANT_DIMS:
            base_val = base.get(d, 5)

            if selected_label is not None:
                if label == selected_label:
                    # 用户选定的版本: 小波动 (+-1), 作为"锚点"
                    offset = random.randint(-1, 1)
                else:
                    # 其他版本: 在锚点基础上再偏移 +-spread
                    offset = random.randint(-spread, spread)
            else:
                # 第 1 轮: 每个版本独立随机偏移 +-spread
                offset = random.randint(-spread, spread)

            variant[d] = _clamp(base_val + offset)

        variants.append(StyleVariant(label=label, **variant))

    return variants


def next_spread(current_spread: int) -> int:
    """计算下一轮的 spread (收敛)."""
    new_spread = max(MIN_SPREAD, int(current_spread * SPREAD_DECAY))
    return new_spread


def format_variant_summary(variants: list[StyleVariant], round_num: int) -> str:
    """生成变体摘要文本 (用于 UI 展示)."""
    lines = [f" 第 {round_num} 轮风格变体:"]
    for v in variants:
        dim_parts = []
        for d in VARIANT_DIMS:
            dim_parts.append(f"{VARIANT_DIM_LABELS[d]}{getattr(v, d)}")
        lines.append(f"  {v.label}: {' '.join(dim_parts)}")
    # 计算两两距离
    if len(variants) >= 2:
        d_ab = variants[0].distance_to(variants[1])
        d_bc = variants[1].distance_to(variants[2])
        d_ac = variants[0].distance_to(variants[2])
        avg_dist = (d_ab + d_bc + d_ac) / 3
        lines.append(f"  平均差异度: {avg_dist:.1f}")
    return "\n".join(lines)
