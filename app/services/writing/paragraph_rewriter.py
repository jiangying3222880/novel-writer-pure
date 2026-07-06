"""
段落重写器 (Phase 3 M3).

调 LLM 重写一个段落, 保留上下文 (前一后一). 解析失败时回退原段.

输入:  chapter_id, paragraph_index, instruction (可选: "更紧凑" / "更口语" / ""=通用重写)
输出:  rewrite_dict {new_paragraph, summary, diff_hint}

约束:
  - 段落序号基于 \n\n 切分
  - 重写长度 = 原文长度的 0.7x - 1.5x
  - 解析失败 -> 返回原文 + warning

M3-B: 搬到 app/services/writing/ 下, 原 app.core 留 re-export shim.
"""
from __future__ import annotations
import json
import logging
import re
from typing import Optional

from app.core.llm import LLMClient, ChatMessage
from app.services import chapter_service

log = logging.getLogger(__name__)

PARAGRAPH_SYSTEM_PROMPT = """你是小说润色编辑. 任务: 重写一个段落, 保持原意但更凝练.

约束:
- 长度: 原段落的 0.7x ~ 1.5x 字符
- 保持原意, 不改情节
- 保持人物声音一致
- 绝不写"我重写的是..."等元说明
- 如果原段有"AI 味" (句式整齐/模板化/全用抽象心理词), 主动改写打破
- 只输出 JSON:
{
  "new_paragraph": "重写后的段落",
  "summary": "改了什么 (一句话)",
  "diff_hint": "比原文 [短/长/同长] ~x%"
}"""


def split_paragraphs(content: str) -> list[str]:
    """按 \\n\\n 切分段落. 末尾空段忽略."""
    if not content:
        return []
    return [p.strip() for p in content.split("\n\n") if p.strip()]


def join_paragraphs(paragraphs: list[str]) -> str:
    return "\n\n".join(paragraphs)


def _parse_rewrite(text: str) -> Optional[dict]:
    """从 LLM 输出抠 JSON. 容错 markdown 围栏 + <think>/<think> 标签."""
    text = text.strip()
    # 去除 <think>...</think> 和 <think>...</think> 标签 (推理模型)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    # 去除 markdown 围栏
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # 找到第一个 { 开始的位置, 然后匹配括号深度
    first_brace = text.find("{")
    if first_brace < 0:
        return None
    depth = 0
    end = -1
    for i in range(first_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return None
    json_str = text[first_brace:end]
    try:
        d = json.loads(json_str)
    except json.JSONDecodeError:
        return None
    np = d.get("new_paragraph")
    if not isinstance(np, str) or not np.strip():
        return None
    return {
        "new_paragraph": np.strip(),
        "summary": str(d.get("summary", "")).strip(),
        "diff_hint": str(d.get("diff_hint", "")).strip(),
    }


class LLMScopedRewriter:
    """单段落重写 agent."""

    def __init__(self, llm_client: LLMClient, temperature: float = 0.7) -> None:
        self.client = llm_client
        self.temperature = temperature
        self.max_tokens = 2048

    def run(self, *, chapter: dict, paragraph_index: int,
            instruction: str = "") -> dict:
        """返回 {new_paragraph, summary, diff_hint, success}."""
        # ---- 准备上下文 ----
        try:
            draft = chapter_service.get_current_draft(chapter["id"])
            content = draft["content"] if draft else chapter.get("draft") or ""
        except Exception:
            content = chapter.get("draft") or ""
        paragraphs = split_paragraphs(content)
        if paragraph_index < 0 or paragraph_index >= len(paragraphs):
            return {
                "new_paragraph": "",
                "summary": f"段落序号越界 (0..{len(paragraphs)-1})",
                "diff_hint": "",
                "success": False,
            }
        target = paragraphs[paragraph_index]
        prev_p = paragraphs[paragraph_index - 1] if paragraph_index > 0 else ""
        next_p = paragraphs[paragraph_index + 1] if paragraph_index < len(paragraphs) - 1 else ""

        # ---- 拼 prompt ----
        user_prompt = (
            f"章节: 第{chapter.get('chapter_no', '?')}章 {chapter.get('title') or ''}\n"
            f"目标段落 ({len(target)} 字):\n{target}\n\n"
        )
        if prev_p:
            user_prompt += f"前一段 (承接):\n{prev_p[-200:]}\n\n"
        if next_p:
            user_prompt += f"后一段 (接续):\n{next_p[:200]}\n\n"
        if instruction:
            user_prompt += f"用户要求: {instruction}\n\n"
        user_prompt += "请按 JSON 输出重写结果."

        # ---- LLM 调用 ----
        try:
            resp = self.client.chat(
                messages=[
                    ChatMessage(role="system", content=PARAGRAPH_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=user_prompt),
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                step="paragraph_rewrite",
            )
        except Exception as e:
            log.warning(f"[paragraph_rewrite] LLM failed: {e}")
            return {
                "new_paragraph": target,
                "summary": f"LLM 失败, 保留原文: {e}",
                "diff_hint": "未改",
                "success": False,
            }
        parsed = _parse_rewrite(resp.content)
        if not parsed:
            log.warning(f"[paragraph_rewrite] JSON parse failed, raw: {resp.content[:200]!r}")
            return {
                "new_paragraph": target,
                "summary": "JSON 解析失败, 保留原文",
                "diff_hint": "未改",
                "success": False,
            }
        parsed["success"] = True
        return parsed


# --------------------------------------------------------------------- #
# Mock (测试 / 离线用)
# --------------------------------------------------------------------- #

class MockScopedRewriter:
    """Mock: 简单把段落加个 '改写: ' 前缀 (用于测试)."""
    def run(self, *, chapter: dict, paragraph_index: int, instruction: str = "") -> dict:
        try:
            draft = chapter_service.get_current_draft(chapter["id"])
            content = draft["content"] if draft else ""
        except Exception:
            content = ""
        paragraphs = split_paragraphs(content)
        if paragraph_index < 0 or paragraph_index >= len(paragraphs):
            return {
                "new_paragraph": "", "summary": "越界",
                "diff_hint": "", "success": False,
            }
        target = paragraphs[paragraph_index]
        new = f"改写: {target}"
        return {
            "new_paragraph": new,
            "summary": f"mock 重写 ({len(target)} -> {len(new)} 字)",
            "diff_hint": f"长 {len(new) / max(1, len(target)):.1f}x",
            "success": True,
        }
