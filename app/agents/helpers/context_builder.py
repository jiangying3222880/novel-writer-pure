"""
ContextBuilder (上下文构建 Agent)
业务场景: 把项目设定（世界观/角色/伏笔/风格指纹/心智6问/题材写法）格式化成
          写手可读的精炼上下文，注入 _refine()。

职责:
  1. 世界观格式化（~600字）
  2. 角色列表格式化（~400字）
  3. 伏笔列表格式化（~300字）
  4. 声音档案格式化（~200字）
  5. 心智6问（从 subtext card 加载）
  6. 风格指纹（author + book 双层）
  7. 题材写法指南 + 风格关键词

设计原则:
  - 只格式化，不做 AI 调用（0 tokens）
  - 写手看不到原始业务数据，只看到格式化后的写作指导
  - 与 WritingEngine._build_user_prompt() 对齐，确保迁移后效果一致
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any

from app.agents.base import AgentBase, AgentRole
from app.agents.report import Report, ReportKind

_logger = logging.getLogger("NovelWriter.agents.context_builder")


@dataclass
class Mindset:
    """心智6问."""
    q1_atmosphere: str = ""
    q2_body_anchor: str = ""
    q3_body_react: str = ""
    q4_dont_write: str = ""
    q5_open_close: str = ""
    q6_dialogue_gap: str = ""

    def to_text(self) -> str:
        lines = []
        if self.q1_atmosphere:
            lines.append(f"1. 氛围: {self.q1_atmosphere}")
        if self.q2_body_anchor:
            lines.append(f"2. 身体锚点: {self.q2_body_anchor}")
        if self.q3_body_react:
            lines.append(f"3. 身体先反应: {self.q3_body_react}")
        if self.q4_dont_write:
            lines.append(f"4. 不写什么: {self.q4_dont_write}")
        if self.q5_open_close:
            lines.append(f"5. 开/收: {self.q5_open_close}")
        if self.q6_dialogue_gap:
            lines.append(f"6. 嘴/心差距: {self.q6_dialogue_gap}")
        return "\n".join(lines)


class ContextBuilder(AgentBase):
    """
    上下文构建 Agent。

    输出 Report.data 字段:
      - world_text: 世界观格式化
      - chars_text: 角色列表格式化
      - hooks_text: 伏笔列表格式化
      - voice_text: 声音档案格式化
      - mindset_text: 心智6问
      - fingerprint_text: 风格指纹指令
      - genre_guide_text: 题材写法指南
      - genre_keywords_text: 风格关键词
      - ctx_formatted: 合并后的完整格式化文本（直接给 _refine() 用）
    """

    DEFAULT_KIND = ReportKind.CONTEXT

    def __init__(
        self,
        *,
        name: str = "ContextBuilder",
        max_total_chars: int = 2400,
    ) -> None:
        super().__init__(name=name, role=AgentRole.CONTEXT_BUILDER)
        self.max_total_chars = max_total_chars

    def _do_execute(self, task: dict) -> Report:
        ctx = task.get("context", {})
        project_id = ctx.get("project_id", "")
        chapter_id = ctx.get("chapter_id", "")

        if not project_id:
            return self._build_fail(task, "缺少 project_id")

        data: dict = {}

        try:
            # 1. 世界观
            world = self._load_setting(project_id, "worldbuilding")
            world_text = self._fmt_worldbuilding(world)
            data["world_text"] = world_text

            # 2. 角色
            chars = self._load_setting(project_id, "characters")
            chars_text = self._fmt_characters(chars)
            data["chars_text"] = chars_text

            # 3. 声音档案
            voice = self._load_setting(project_id, "voice_profiles")
            voice_text = self._fmt_characters(voice)
            if voice_text == chars_text:
                voice_text = ""
            data["voice_text"] = voice_text

            # 4. 伏笔
            hooks = self._load_setting(project_id, "hooks")
            hooks_text = self._fmt_hooks(hooks)
            data["hooks_text"] = hooks_text

            # 5. 心智6问（从 subtext card）
            mindset = self._load_mindset_from_subtext(chapter_id)
            mindset_text = mindset.to_text()
            data["mindset_text"] = mindset_text

            # 6. 风格指纹
            fp_text = self._load_fingerprint(project_id)
            data["fingerprint_text"] = fp_text

            # 7. 题材写法 + 关键词
            genre_guide, genre_keywords = self._load_genre_guide(project_id)
            data["genre_guide_text"] = genre_guide
            data["genre_keywords_text"] = genre_keywords

            # 8. 合并成格式化文本
            ctx_formatted = self._merge_formatted(data)
            data["ctx_formatted"] = ctx_formatted

            return self._build_report(task, data)

        except Exception as e:
            _logger.exception("[context_builder] 构建失败")
            return self._build_fail(task, f"{type(e).__name__}: {e}")

    # ----------------- 设定加载 ----------------- #

    def _load_setting(self, project_id: str, key: str):
        """安全读取一个 setting key."""
        try:
            from app.services import setting_service
            result = setting_service.get_setting(project_id, key)
            return result.get("data") if isinstance(result, dict) else None
        except Exception as e:
            _logger.debug("[context_builder] 加载 setting %s 失败: %s", key, e)
            return None

    def _load_mindset_from_subtext(self, chapter_id: str) -> Mindset:
        """从 subtext card 加载 6 问答案当 Mindset. 无则用默认."""
        try:
            from app.services import subtext
            card = subtext.get_card_for_chapter(chapter_id)
            if card:
                f = card
                return Mindset(
                    q1_atmosphere=f.emotional or f.scene_map or "",
                    q2_body_anchor=f.physical_anchor or "",
                    q3_body_react=f.physical_anchor or "",
                    q4_dont_write=f.anti_rules or "",
                    q5_open_close=f"{f.pacing or ''} / 收尾: {f.ending_scene_state or ''}".strip(" /"),
                    q6_dialogue_gap=f"嘴上说: {f.lie or ''} / 心里想: {f.truth or ''}",
                )
        except Exception as e:
            _logger.debug("[context_builder] 加载 subtext 失败, 用默认: %s", e)
        return Mindset(
            q1_atmosphere="不安",
            q2_body_anchor="肩胛骨之间那根筋在跳",
            q3_body_react="胃缩了一下",
            q4_dont_write="不解释恐惧、不注解动作",
            q5_open_close="开场: 开门声 / 收尾: 未关的灯",
            q6_dialogue_gap="嘴上说'没事', 心里想'完了'",
        )

    def _load_fingerprint(self, project_id: str) -> str:
        """加载风格指纹（author + book）."""
        try:
            from app.services.style_fingerprint import (
                get_author_fp, get_book_fp,
                to_author_prompt_block, to_book_prompt_block,
            )
            af = get_author_fp()
            bf = get_book_fp(project_id)
            fp_parts = [to_author_prompt_block(af), to_book_prompt_block(bf)]
            return "\n\n".join(fp_parts)
        except Exception as e:
            _logger.debug("[context_builder] 加载风格指纹失败: %s", e)
            return ""

    def _load_genre_guide(self, project_id: str) -> tuple[str, str]:
        """加载题材写法指南 + 风格关键词."""
        try:
            from app.services import project_service
            proj = project_service.get(project_id) or {}
            genre_str = proj.get("genre") or ""
            sub_genres = proj.get("sub_genres") or []
            if isinstance(sub_genres, str):
                sub_genres = [g.strip() for g in sub_genres.split(",") if g.strip()]

            guide_text = ""
            keywords_text = ""

            try:
                from app.core.genre_presets import GENRE_WRITING_GUIDES, parse_genre_string, genre_to_keywords
                # 写法指南
                genres_parsed = parse_genre_string(genre_str)
                guide_parts = []
                for g in genres_parsed:
                    if g in GENRE_WRITING_GUIDES:
                        guide_parts.append(GENRE_WRITING_GUIDES[g])
                if guide_parts:
                    guide_text = "\n\n".join(guide_parts)[:600]

                # 风格关键词
                kws_main = genre_to_keywords(genre_str) if genre_str else []
                kws_sub = list(sub_genres)
                seen = set()
                kws_all = []
                for kw in (kws_main + kws_sub):
                    if kw and kw not in seen:
                        seen.add(kw)
                        kws_all.append(kw)
                if kws_all:
                    keywords_text = "、".join(kws_all[:10])
            except Exception as e:
                _logger.debug("[context_builder] 加载题材指南失败: %s", e)

            return guide_text, keywords_text

        except Exception as e:
            _logger.debug("[context_builder] 加载项目信息失败: %s", e)
            return "", ""

    # ----------------- 格式化函数 ----------------- #

    def _fmt_worldbuilding(self, data) -> str:
        """格式化世界观设定, 预算 ~600 字."""
        if not data:
            return ""
        parts = []
        if isinstance(data, dict):
            for k, v in list(data.items())[:8]:
                parts.append(f"## {k}\n{str(v)[:200]}")
        elif isinstance(data, list):
            for item in data[:8]:
                if isinstance(item, dict):
                    parts.append("## " + str(item.get("name", "?")) + "\n" + str(item.get("desc", ""))[:200])
                else:
                    parts.append(str(item)[:200])
        else:
            parts.append(str(data)[:600])
        return "\n\n".join(parts)[:600]

    def _fmt_characters(self, data) -> str:
        """格式化角色列表, 预算 ~400 字."""
        if not data:
            return ""
        parts = []
        if isinstance(data, list):
            for c in data[:8]:
                if isinstance(c, dict):
                    name = c.get("name", "?")
                    traits = c.get("traits", c.get("personality", ""))
                    parts.append(f"【{name}】{traits}")
                else:
                    parts.append(str(c))
        elif isinstance(data, dict):
            for name, info in list(data.items())[:8]:
                if isinstance(info, dict):
                    traits = info.get("traits", info.get("personality", ""))
                    parts.append(f"【{name}】{traits}")
                else:
                    parts.append(f"【{name}】{info}")
        else:
            parts.append(str(data)[:400])
        return "\n".join(parts)[:400]

    def _fmt_hooks(self, data) -> str:
        """格式化待回收伏笔, 预算 ~300 字."""
        if not data:
            return ""
        if isinstance(data, list):
            lines = []
            for h in data[:10]:
                if isinstance(h, dict):
                    lines.append(f"- {h.get('desc', h.get('name', str(h)))}")
                else:
                    lines.append(f"- {h}")
        else:
            lines = [str(data)]
        return "\n".join(lines)[:300]

    # ----------------- 合并输出 ----------------- #

    def _merge_formatted(self, data: dict) -> str:
        """把各段格式化文本合并成一个大 section."""
        parts: list[str] = []

        # 世界观
        if data.get("world_text"):
            parts.append("## 世界观\n" + data["world_text"])

        # 角色
        if data.get("chars_text"):
            parts.append("## 角色\n" + data["chars_text"])

        # 声音档案
        if data.get("voice_text"):
            parts.append("## 声音档案补充\n" + data["voice_text"])

        # 伏笔
        if data.get("hooks_text"):
            parts.append("## 待回收伏笔\n" + data["hooks_text"])

        # 风格指纹
        if data.get("fingerprint_text"):
            parts.append(data["fingerprint_text"])

        # 题材写法
        if data.get("genre_guide_text"):
            parts.append("## 题材写法指南\n" + data["genre_guide_text"])

        # 心智6问
        if data.get("mindset_text"):
            parts.append("## 心智清单 (6 问, 动笔前在心里钉死)\n" + data["mindset_text"])

        result = "\n\n".join(parts)
        if len(result) > self.max_total_chars:
            result = result[:self.max_total_chars]
        return result
