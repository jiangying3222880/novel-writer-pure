"""
StoryTeller (写手 / 士兵)
业务场景: 拿到 Orchestrator 精炼过的提示 → 写章节正文.
士兵定位: 只看精炼版, 不知道其他 Agent 在干啥.

AI 调用: 默认使用 app.ai.engine.AIEngine 调用真实模型.
无网络/无配置时降级为 mock 段落.
"""
from __future__ import annotations
import logging
from typing import Any, Optional

from app.agents.base import AgentBase, AgentRole
from app.agents.report import Report, ReportKind

_logger = logging.getLogger("NovelWriter.agents.storyteller")

WRITER_SYSTEM = """你是一位追求"真人感"的小说作者。拿到精炼的写作提示后，在心里钉死后动笔。

## 写作铁律 (违反任何一条都不合格)
1. **写了画面就不用写结论** — 读者能推断的信息不写出来
2. **本场情绪基调要一致** — 不在中途突然拐弯
3. **做出来了就不必再说"我在做这个"** — 已发生的动作不重复标注
4. **事件的冲击力要体现在角色反应上** — 恐怖情节后必须跟上对应的情绪/身体反应
5. **不解释** — 不为角色的情绪/动作提供心理注解
6. **不凑数** — 该空就空, 该沉默就沉默

## 篇幅
2500-3500 字。一个完整故事片段。

## 输出
只输出章节正文。不要章节号、不要标题、不要"作者按"、不要 markdown 围栏。"""


class StoryTeller(AgentBase):
    """写手 (士兵)."""

    DEFAULT_KIND = ReportKind.WRITE

    def __init__(self, *, name: str = "StoryTeller", ai_engine: Any = None) -> None:
        super().__init__(name=name, role=AgentRole.WRITER)
        self.ai_engine = ai_engine

    def _get_ai(self):
        if self.ai_engine is not None:
            return self.ai_engine
        try:
            from app.ai.engine import AIEngine
            return AIEngine()
        except Exception:
            return None

    def _build_writer_kb(self, query: str) -> str:
        """
        M1 分层知识库: 给写作 Agent 拼装专属知识块 (指导手册 + 专属技巧/范本/对话 + 共享库)。
        失败时返回空串 (降级为纯 WRITER_SYSTEM)。
        """
        try:
            from app.knowledge.finder import extract_for_agent, extract_by_capability
            # 基础写作知识
            kb = extract_for_agent("writing", query)
            # v4.2新增: Capability知识注入 (Narrative + Dialogue + Language + Emotion)
            cap_kb = extract_by_capability(["narrative", "dialogue", "language", "emotion"], query)
            if cap_kb:
                kb = kb + "\n\n[能力知识库: 叙事/对话/语言/情绪]\n" + cap_kb[:500]
            return kb
        except Exception as e:
            _logger.warning("[writer] 写作知识库检索失败, 跳过: %s", e)
            return ""

    def _do_execute(self, task: dict) -> Report:
        ctx = task.get("context", {})
        project_id = ctx.get("project_id", "")
        chapter_id = ctx.get("chapter_id", "")
        refined = ctx.get("refined_prompt", "")
        is_initial = ctx.get("is_initial", True)
        prev_content = ctx.get("prev_content", "")

        # 1) 优先: 真实 AI 调用
        ai = self._get_ai()
        if ai is not None and refined:
            try:
                # system 段注入写作知识库 (0 污染: user 段 refined 保持纯净)
                kb_block = self._build_writer_kb(refined)
                system = (kb_block + "\n\n" + WRITER_SYSTEM) if kb_block else WRITER_SYSTEM
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": refined},
                ]
                result = ai.chat(
                    messages,
                    task="write",
                    project_id=project_id,
                    chapter_id=chapter_id,
                    temperature=0.7,
                    max_tokens=4096,
                )
                if result and result.content:
                    return self._build_report(task, {
                        "content": result.content,
                        "char_count": len(result.content),
                        "is_initial": is_initial,
                    }, suggestions=["精炼 prompt 已使用 (AI)"])
            except Exception as e:
                _logger.warning("[writer] AI 调用失败, 降级 mock: %s", e)

        # 2) 降级: 本地 mock 章节
        return self._mock_write(task, refined, is_initial, prev_content)

    def _mock_write(self, task: dict, refined: str, is_initial: bool, prev: str) -> Report:
        """本地 mock 写: 不调 AI, 拼几段占位正文."""
        if is_initial:
            paragraphs = [
                "门开了。\n\n",
                "他没回头，但能感觉到身后的空气在动。\n\n",
                "那脚步声很轻，但每一下都像踩在他脊椎上。\n\n",
                "灯还亮着。\n\n",
            ]
        else:
            paragraphs = [
                prev[: max(0, len(prev) - 50)] if prev else "",
                "\n\n窗外的雨更大了。\n\n",
            ]
        content = "".join(paragraphs)
        return self._build_report(task, {
            "content": content,
            "char_count": len(content),
            "is_initial": is_initial,
            "refined_prompt_chars": len(refined),
        })
