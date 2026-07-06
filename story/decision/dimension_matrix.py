"""
Dimension Matrix — converts heterogeneous Guide signals into a unified decision input.

Each Guide source maps to 6 narrative dimensions with configurable weights.
The matrix output is a ranked vector: which dimension is most activated, by how much,
and which specific Guides contributed.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

NARRATIVE_DIMENSIONS = ["pacing", "tension", "character", "hook", "world", "style"]

DIMENSION_LABELS: dict[str, str] = {
    "pacing": "叙事节奏",
    "tension": "张力水平",
    "character": "角色状态",
    "hook": "伏笔管理",
    "world": "世界一致性",
    "style": "风格保持",
}

SOURCE_DIMENSION_WEIGHTS: dict[str, dict[str, float]] = {
    "pressure": {
        "pacing": 0.9,
        "tension": 0.8,
        "hook": 0.5,
        "character": 0.2,
        "world": 0.1,
        "style": 0.0,
    },
    "reader_signal": {
        "pacing": 0.8,
        "tension": 0.7,
        "hook": 0.4,
        "character": 0.3,
        "world": 0.1,
        "style": 0.1,
    },
    "hook": {
        "hook": 0.95,
        "tension": 0.6,
        "pacing": 0.5,
        "character": 0.2,
        "world": 0.2,
        "style": 0.0,
    },
    "character_state": {
        "character": 0.9,
        "tension": 0.3,
        "hook": 0.2,
        "pacing": 0.1,
        "world": 0.1,
        "style": 0.0,
    },
    "voice": {
        "character": 0.7,
        "style": 0.6,
        "tension": 0.2,
        "pacing": 0.1,
        "hook": 0.1,
        "world": 0.1,
    },
    "style": {
        "style": 0.9,
        "character": 0.2,
        "pacing": 0.1,
        "tension": 0.1,
        "hook": 0.0,
        "world": 0.0,
    },
    "consistency": {
        "world": 0.8,
        "character": 0.5,
        "hook": 0.3,
        "pacing": 0.1,
        "tension": 0.1,
        "style": 0.0,
    },
    "memory": {
        "hook": 0.6,
        "character": 0.5,
        "world": 0.4,
        "tension": 0.3,
        "pacing": 0.3,
        "style": 0.1,
    },
    "event": {
        "hook": 0.5,
        "character": 0.5,
        "world": 0.5,
        "tension": 0.4,
        "pacing": 0.2,
        "style": 0.0,
    },
    "unit_event": {
        "hook": 0.5,
        "character": 0.5,
        "world": 0.5,
        "tension": 0.4,
        "pacing": 0.2,
        "style": 0.0,
    },
}


@dataclass
class DimensionScore:
    dimension: str
    label: str = ""
    score: float = 0.0
    guide_count: int = 0
    top_guides: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.label:
            self.label = DIMENSION_LABELS.get(self.dimension, self.dimension)

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "label": self.label,
            "score": self.score,
            "guide_count": self.guide_count,
            "top_guides": list(self.top_guides),
        }


@dataclass
class DimensionVector:
    scores: list[DimensionScore] = field(default_factory=list)
    dominant: str = ""
    dominant_score: float = 0.0
    guide_count: int = 0

    @property
    def has_signals(self) -> bool:
        return self.guide_count > 0

    def get_score(self, dimension: str) -> float:
        for s in self.scores:
            if s.dimension == dimension:
                return s.score
        return 0.0

    def sorted_scores(self) -> list[DimensionScore]:
        return sorted(self.scores, key=lambda s: -s.score)

    def to_dict(self) -> dict:
        return {
            "scores": [s.to_dict() for s in self.sorted_scores()],
            "dominant": self.dominant,
            "dominant_score": self.dominant_score,
            "guide_count": self.guide_count,
        }


def compute_dimension_vector(
    guides: list,
    *,
    min_confidence: float = 0.3,
) -> DimensionVector:
    dim_scores: dict[str, float] = {d: 0.0 for d in NARRATIVE_DIMENSIONS}
    dim_guides: dict[str, list[str]] = {d: [] for d in NARRATIVE_DIMENSIONS}
    total_guides = 0

    for g in guides:
        source = g.source if hasattr(g, "source") else g.get("source", "")
        confidence = g.confidence if hasattr(g, "confidence") else g.get("confidence", 0.7)
        priority = g.priority if hasattr(g, "priority") else g.get("priority", 0.5)
        guide_id = g.guide_id if hasattr(g, "guide_id") else g.get("guide_id", "")

        if confidence < min_confidence:
            continue

        weights = SOURCE_DIMENSION_WEIGHTS.get(source)
        if weights is None:
            continue

        total_guides += 1
        signal_strength = confidence * priority

        for dim, weight in weights.items():
            if weight > 0:
                contribution = signal_strength * weight
                dim_scores[dim] += contribution
                if guide_id:
                    dim_guides[dim].append(guide_id)

    scores: list[DimensionScore] = []
    dominant = ""
    dominant_score = 0.0

    for dim in NARRATIVE_DIMENSIONS:
        s = dim_scores[dim]
        top_ids = sorted(dim_guides[dim])[:3]
        scores.append(DimensionScore(
            dimension=dim,
            score=round(s, 4),
            guide_count=len(dim_guides[dim]),
            top_guides=top_ids,
        ))
        if s > dominant_score:
            dominant_score = s
            dominant = dim

    return DimensionVector(
        scores=scores,
        dominant=dominant,
        dominant_score=round(dominant_score, 4),
        guide_count=total_guides,
    )
