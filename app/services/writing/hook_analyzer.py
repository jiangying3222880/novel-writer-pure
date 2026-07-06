"""
HookAnalyzer (Phase 3 M3).

评估章节的"追读潜力" (读者读完想不想继续读下一章).

5 维 (权重):
  - last_paragraph_hook (0-25): 末段是否"未完成"
  - next_chapter_setup  (0-25): 是否给下章留必须读的问题
  - mid_micro_hooks     (0-20): 中段密度 (每 500-800 字一小钩)
  - promise_fulfillment (0-15): 是否兑现上章期待
  - info_density_curve  (0-15): 密度是否递增

输入: content (str), chapter_meta (dict)
输出: HookReport {score 0-100, axes dict, summary str, issues list}

M3-B: 搬到 app/services/writing/ 下, 原 app.core 留 re-export shim.
"""
from __future__ import annotations
import json
import logging
import re
from typing import Optional

from app.core.llm import LLMClient, ChatMessage

log = logging.getLogger(__name__)

HOOK_SYSTEM_PROMPT = """你是追读力诊断师. 拿到一章小说正文, 评估"读者读完这一章, 想不想继续读下一章".

严格按 JSON 输出:
{
  "score": 0,                                  // 总分 0-100
  "axes": {
    "last_paragraph_hook": 0,                  // 末段钩子 0-25
    "next_chapter_setup": 0,                   // 下章衔接 0-25
    "mid_micro_hooks": 0,                      // 中段微钩 0-20
    "promise_fulfillment": 0,                  // 承诺兑现 0-15
    "info_density_curve": 0                    // 密度曲线 0-15
  },
  "summary": "一句话评语",
  "issues": [                                  // 可选, 列具体问题
    {"axis": "last_paragraph_hook", "desc": "末段是总结, 没有未完成画面"}
  ]
}

评分标准:
- 末段钩子 (25): 末段是画面/动作/对话/沉默, 不是总结. 25 = 完美未完成; 0 = 总结收束.
- 下章衔接 (25): 末段抛出了问题/期待/缺口. 25 = 必读; 0 = 与下章无关.
- 中段微钩 (20): 每 500-800 字有悬念/反常/暗示/未说出口. 20 = 每段都有; 0 = 全平.
- 承诺兑现 (15): 对照「当前承诺清单」, 检查本章是否兑现/推进已触发承诺. 15 = 兑现/推进; 0 = 完全忽略承诺.
- 密度曲线 (15): 开头低 → 中段升 → 末段峰值. 15 = 标准曲线; 0 = 平线.

只输出 JSON, 不要解释, 不要 markdown 围栏."""


_FALLBACK = {
    "score": 50,
    "axes": {
        "last_paragraph_hook": 12,
        "next_chapter_setup": 12,
        "mid_micro_hooks": 10,
        "promise_fulfillment": 8,
        "info_density_curve": 8,
    },
    "summary": "HookAnalyzer LLM 失败, 给出默认分 50",
    "issues": [],
}


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def _parse_hook_report(d: Optional[dict]) -> Optional[dict]:
    if not d or not isinstance(d, dict):
        return None
    axes_raw = d.get("axes", {})
    if not isinstance(axes_raw, dict):
        return None
    # 容错: 各项可能在 / 不在
    axes = {
        "last_paragraph_hook": int(axes_raw.get("last_paragraph_hook", 0)),
        "next_chapter_setup":  int(axes_raw.get("next_chapter_setup", 0)),
        "mid_micro_hooks":     int(axes_raw.get("mid_micro_hooks", 0)),
        "promise_fulfillment": int(axes_raw.get("promise_fulfillment", 0)),
        "info_density_curve":  int(axes_raw.get("info_density_curve", 0)),
    }
    # clamp
    caps = {
        "last_paragraph_hook": 25, "next_chapter_setup": 25,
        "mid_micro_hooks": 20, "promise_fulfillment": 15, "info_density_curve": 15,
    }
    for k, v in axes.items():
        axes[k] = max(0, min(caps[k], v))
    score = d.get("score", 0)
    try:
        score = int(score)
    except (ValueError, TypeError):
        score = 0
    score = max(0, min(100, score))
    return {
        "score": score,
        "axes": axes,
        "summary": str(d.get("summary", "")).strip(),
        "issues": d.get("issues", []) if isinstance(d.get("issues"), list) else [],
    }


class LLMHookAnalyzer:
    def __init__(self, llm_client: LLMClient, temperature: float = 0.2) -> None:
        self.client = llm_client
        self.temperature = temperature
        self.max_tokens = 1024

    def _fetch_commitment_context(self, project_id: str) -> str:
        """从 memory 系统读取当前项目的活跃承诺, 供 AI 评分用."""
        try:
            from app.services.memory import get_l1_l2
            memories = get_l1_l2(project_id)
        except Exception as e:
            log.debug("[hook_analyzer] memory fetch failed: %s", e)
            return ""

        active = [m for m in memories if m.category == "commitment_active"]
        promised = [m for m in memories if m.category == "commitment_promise"]
        lines = []
        if active:
            lines.append("### 已触发承诺 (必兑现)")
            for m in active[:5]:
                lines.append(f"- {m.content[:120]}")
        if promised:
            lines.append("### 待履行承诺 (读者期待)")
            for m in promised[:5]:
                lines.append(f"- {m.content[:120]}")
        return "\n".join(lines) if lines else ""

    def run(self, *, content: str, chapter: dict) -> dict:
        title = chapter.get("title") or "(无题)"
        chapter_no = chapter.get("chapter_no", "?")
        project_id = chapter.get("project_id") or chapter.get("_project_id", "")
        # 截断长文, 末段 600 字
        last_para_hint = content[-600:] if len(content) > 600 else content
        # 承诺上下文: 从 memory 系统读取, 注入给 AI
        commit_ctx = ""
        if project_id:
            commit_ctx = self._fetch_commitment_context(str(project_id))
        user_prompt = (
            f"## 章节信息\n第 {chapter_no} 章: {title}\n"
            f"## 末段 ({len(last_para_hint)} 字, 完整呈现)\n"
            f"{last_para_hint}\n\n"
            f"## 全文 ({len(content)} 字, 节选首段+中段)\n"
            f"{content[:2500]}\n"
            f"{'…(省略)' if len(content) > 2500 else ''}\n\n"
            + (f"## 当前承诺清单\n{commit_ctx}\n\n" if commit_ctx else "")
            + "请按 JSON 给出追读力诊断."
        )
        try:
            resp = self.client.chat(
                messages=[
                    ChatMessage(role="system", content=HOOK_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=user_prompt),
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                step="hook_analyze",
            )
        except Exception as e:
            log.warning(f"[hook_analyzer] LLM failed: {e}, fallback")
            return _FALLBACK
        parsed = _parse_hook_report(_extract_json(resp.content))
        if not parsed:
            log.warning(f"[hook_analyzer] parse failed, raw: {resp.content[:200]!r}")
            return _FALLBACK
        return parsed


class MockHookAnalyzer:
    """Mock: 固定分数, 用于离线/测试."""
    def run(self, *, content: str, chapter: dict) -> dict:
        # 长度相关, 内容越多分越高 (粗略)
        score = 60 + min(20, len(content) // 200)
        return {
            "score": score,
            "axes": {
                "last_paragraph_hook": 12,
                "next_chapter_setup": 12,
                "mid_micro_hooks": 10,
                "promise_fulfillment": 8,
                "info_density_curve": 8,
            },
            "summary": f"Mock: {len(content)} 字, 估 {score} 分",
            "issues": [],
        }
