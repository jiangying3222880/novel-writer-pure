"""
Critic (批评家)
业务场景: 检查章节正文的风格一致性 (L1 作者指纹 6 维).
       与 Editor 评估 6 维不同: Critic 关注"风格是否跑偏".

默认实现: 拿作者指纹做比对, 跑偏返 style_notes.
"""
from __future__ import annotations
import logging
from typing import Any

from app.agents.base import AgentBase, AgentRole
from app.agents.report import Report, ReportKind

_logger = logging.getLogger("NovelWriter.agents.critic")


class Critic(AgentBase):
    """批评家 (风格一致性)."""

    DEFAULT_KIND = ReportKind.CRITIC

    def __init__(self, *, name: str = "Critic") -> None:
        super().__init__(name=name, role=AgentRole.CRITIC)

    def _do_execute(self, task: dict) -> Report:
        ctx = task.get("context", {})
        content = ctx.get("content", "")
        project_id = ctx.get("project_id", "")

        if not content:
            return self._build_fail(task, "content 为空")

        # 1) 取作者风格指纹 (L1)
        try:
            from app.services import style_fingerprint
            fp = style_fingerprint.get_author_fp()
        except Exception as e:
            _logger.debug("[critic] 作者指纹加载失败: %s", e)
            fp = None

        style_notes: list[str] = []
        score = 70  # 默认

        if fp:
            # 句长节奏检查
            sentences = [s for s in content.replace("。", "。|").replace("！", "！|").replace("？", "？|").split("|") if s.strip()]
            if sentences:
                avg_len = sum(len(s) for s in sentences) / len(sentences)
                # 作者偏好流水长句 (8-10) 但实际写的很短 → 跑偏
                if fp.sentence_rhythm >= 7 and avg_len < 20:
                    style_notes.append(f"句子节奏跑偏: 作者偏好流水长句({fp.sentence_rhythm}/10), 但当前均{avg_len:.0f}字偏短")
                    score -= 10
                # 作者偏好短促 (1-3) 但实际写的很长 → 跑偏
                elif fp.sentence_rhythm <= 3 and avg_len > 35:
                    style_notes.append(f"句子节奏跑偏: 作者偏好短促快节奏({fp.sentence_rhythm}/10), 但当前均{avg_len:.0f}字偏长")
                    score -= 10

            # 段落密度检查
            paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
            if paragraphs:
                para_per_1k = len(paragraphs) / (len(content) / 1000)
                if fp.paragraph_density >= 7 and para_per_1k < 8:
                    style_notes.append(f"段落密度跑偏: 偏好舒朗短段({fp.paragraph_density}/10), 但当前{para_per_1k:.0f}段/千字偏密")
                    score -= 5
                elif fp.paragraph_density <= 3 and para_per_1k > 15:
                    style_notes.append(f"段落密度跑偏: 偏好密集长段({fp.paragraph_density}/10), 但当前{para_per_1k:.0f}段/千字偏碎")
                    score -= 5

            # 情绪表达检查
            direct_words = ["愤怒", "悲伤", "高兴", "恐惧", "焦虑", "激动"]
            body_words = ["攥紧拳头", "手心出汗", "心跳加速", "脸色发白", "眉头紧锁"]
            direct_cnt = sum(1 for w in direct_words if w in content)
            body_cnt = sum(1 for w in body_words if w in content)
            if fp.emotion_expression <= 3 and body_cnt > direct_cnt * 2:
                style_notes.append(f"情绪表达跑偏: 偏好直说({fp.emotion_expression}/10), 但身体暗示过多")
                score -= 5
            elif fp.emotion_expression >= 7 and direct_cnt > body_cnt * 2:
                style_notes.append(f"情绪表达跑偏: 偏好暗示({fp.emotion_expression}/10), 但直接情绪词过多")
                score -= 5

        score = max(0, min(100, score))
        avg_len = sum(len(s) for s in sentences) / len(sentences) if (fp and sentences) else 0

        return self._build_report(task, {
            "score": score,
            "style_notes": "; ".join(style_notes) if style_notes else "风格一致",
            "avg_sentence_len": avg_len,
            "sentence_count": len(sentences) if (fp and sentences) else 0,
        }, suggestions=style_notes[:3])
