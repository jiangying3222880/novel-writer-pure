"""
Editor (编辑)
业务场景: 拿到写手正文 → 按 6 维评估 (plot/character/writing/rhythm/style/foreshadow) + 返 issues.

AI 模式: 调用 AI 评估 6 维度 (需要 ai_engine 注入).
降级模式: 本地反 AI 味 + 字数打分 (离线可用).
"""
from __future__ import annotations
import json
import logging
from typing import Any

from app.agents.base import AgentBase, AgentRole
from app.agents.report import Report, ReportKind

_logger = logging.getLogger("NovelWriter.agents.editor")

EDITOR_SYSTEM = """你是一位资深小说编辑。请对以下章节正文按6个维度评分(0-20分)，并返回 JSON。

评分维度:
- plot: 情节推进，是否有实质进展
- character: 角色塑造，行为是否一致、有层次
- writing: 文字质量，是否自然流畅、无模板化表达
- rhythm: 节奏控制，张弛是否得当
- style: 风格统一，是否符合网文语境
- foreshadow: 伏笔管理，是否埋/收得当

同时给出2-3条具体改进建议。

返回纯 JSON，格式:
{"score": 75, "axes": {"plot": 15, "character": 14, "writing": 15, "rhythm": 14, "style": 15, "foreshadow": 14}, "issues": ["建议1", "建议2"], "summary": "总体评价一句话"}"""


class Editor(AgentBase):
    """编辑 (评估 6 维)."""

    DEFAULT_KIND = ReportKind.EDIT

    def __init__(self, *, name: str = "Editor", ai_engine: Any = None) -> None:
        super().__init__(name=name, role=AgentRole.EDITOR)
        self.ai_engine = ai_engine

    def _get_ai(self):
        if self.ai_engine is not None:
            return self.ai_engine
        try:
            from app.ai.engine import AIEngine
            return AIEngine()
        except Exception:
            return None

    def _do_execute(self, task: dict) -> Report:
        ctx = task.get("context", {})
        content = ctx.get("content", "")

        if not content:
            return self._build_fail(task, "content 为空")

        # 1) 本地评估 (反 AI 味 + 字数)
        try:
            from app.services import anti_ai
            issues = anti_ai.run_all(content)
        except Exception as e:
            _logger.warning("[editor] 本地评估失败: %s", e)
            issues = []

        # 2) 尝试 AI 评估
        ai_score = None
        ai_axes = None
        ai_issues = None
        ai_summary = ""
        ai = self._get_ai()
        if ai is not None and len(content) > 100:
            try:
                messages = [
                    {"role": "system", "content": EDITOR_SYSTEM},
                    {"role": "user", "content": content[:3000]},
                ]
                result = ai.chat(messages, task="evaluate", temperature=0.3, max_tokens=512)
                if result and result.content:
                    parsed = self._parse_ai_result(result.content)
                    ai_score = parsed.get("score")
                    ai_axes = parsed.get("axes")
                    ai_issues = parsed.get("issues")
                    ai_summary = parsed.get("summary", "")
            except Exception as e:
                _logger.warning("[editor] AI 评估失败, 降级本地: %s", e)

        # 3) 合并结果 (AI 优先, 降级本地)
        char_count = len(content)
        if ai_score is not None and ai_axes:
            score = min(100, max(0, int(ai_score)))
            axes = ai_axes
            summary = ai_summary or f"AI 评估: {char_count} 字"
            all_issues = (ai_issues or []) + [
                getattr(i, "message", str(i)) for i in issues[:3]
            ]
        else:
            if char_count < 200:
                writing = 5
            elif char_count < 1000:
                writing = 10
            elif char_count < 2500:
                writing = 14
            else:
                writing = 13
            axes = {
                "plot": 8, "character": 7, "writing": writing,
                "rhythm": 8, "style": 8, "foreshadow": 7,
            }
            axes_sum = sum(int(v) for v in axes.values() if isinstance(v, (int, float)))
            score = min(100, max(0, axes_sum * 3 - len(issues)))
            summary = f"本地评估: {char_count} 字, {len(issues)} 个反 AI 味问题"
            all_issues = [getattr(i, "message", str(i)) for i in issues[:10]]

        # 4) 转成建议
        suggestions: list[str] = []
        if all_issues:
            for i in all_issues[:3]:
                suggestions.append(f"修复: {str(i)[:80]}")

        return self._build_report(task, {
            "score": score,
            "axes": axes,
            "char_count": len(content),
            "issues": all_issues,
            "summary": summary,
        }, suggestions=suggestions)

    def _parse_ai_result(self, text: str) -> dict:
        """从 AI 返回文本中提取 JSON."""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 尝试提取 {...} 块
        import re
        m = re.search(r'\{[^{}]*"score"[^{}]*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        _logger.debug("[editor] 无法解析 AI 响应: %s", text[:200])
        return {}
