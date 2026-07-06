"""
Prompt 资产组装器 (Phase 3 M3).

把项目级 setting (worldbuilding / characters / voice_profiles / anti_rules / style_fingerprint / hooks)
+ 当前 chapter brief 拼成给 Writer 用的 system + user prompt.

预算管理: 各项有 token 预算, 总 prompt 不超过 max_total.
超长部分截断并标注 "(truncated)".

数据来源 (M3-A 解耦后, 走 Protocol 注入):
  - setting_reader.get_setting(project_id, key)
  - project_reader.get(project_id)
  - chapter_reader.get(chapter_id) + chapter_briefs

M3-B: 搬到 app/services/writing/ 下, 原 app.core 留 re-export shim.
"""
from __future__ import annotations
import logging
from typing import Optional

from app.services import chapter_service, project_service, setting_service

log = logging.getLogger(__name__)

# 字符预算 (粗略按 1 token ≈ 1.5 char 中文算, 实际中文 1 字 ≈ 1.5 token)
BUDGET_WORLD    = 600
BUDGET_STYLE    = 300
BUDGET_VOICE    = 400
BUDGET_ANTI     = 300
BUDGET_HOOKS    = 300
BUDGET_BRIEF    = 500
BUDGET_SUBTEXT  = 200
BUDGET_WORLD_GRAPH = 400


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "…(truncated)"


def _format_worldbuilding(data) -> str:
    if not data:
        return ""
    parts: list[str] = []
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
        parts.append(str(data)[:BUDGET_WORLD])
    return _truncate("\n\n".join(parts), BUDGET_WORLD)


def _format_characters(data) -> str:
    if not data:
        return ""
    parts: list[str] = []
    if isinstance(data, list):
        for c in data[:10]:
            if isinstance(c, dict):
                name = c.get("name", "?")
                traits = c.get("traits", c.get("personality", ""))
                parts.append(f"【{name}】{traits}")
            else:
                parts.append(str(c))
    elif isinstance(data, dict):
        for name, info in list(data.items())[:10]:
            if isinstance(info, dict):
                traits = info.get("traits", info.get("personality", ""))
                parts.append(f"【{name}】{traits}")
            else:
                parts.append(f"【{name}】{info}")
    else:
        parts.append(str(data)[:BUDGET_VOICE])
    return _truncate("\n".join(parts), BUDGET_VOICE)


def _format_anti_rules(data) -> str:
    if not data:
        return ""
    if isinstance(data, list):
        lines = [f"- {x}" for x in data[:20] if str(x).strip()]
    elif isinstance(data, dict):
        lines = [f"- {k}: {v}" for k, v in list(data.items())[:20]]
    else:
        lines = [str(data)]
    return _truncate("\n".join(lines), BUDGET_ANTI)


def _format_hooks(data) -> str:
    if not data:
        return ""
    if isinstance(data, list):
        lines = []
        for h in data[:15]:
            if isinstance(h, dict):
                lines.append(f"- {h.get('desc', h.get('name', str(h)))}")
            else:
                lines.append(f"- {h}")
    else:
        lines = [str(data)]
    return _truncate("\n".join(lines), BUDGET_HOOKS)


def _format_world_graph(project_id: str, chapter_no: int = 0) -> str:
    """格式化实体关系图谱, 让 AI 知道当前章节牵涉的实体关系.

    取当前 chapter 之前的所有 world_state_snapshots 共现数据,
    摘 top 10 节点 + top 8 边, 拼成紧凑文本注入 prompt.
    """
    try:
        from app.services.world_observer import get_relations_graph

        g = get_relations_graph(project_id, chapter_no=chapter_no if chapter_no else None)
    except Exception as e:
        logging.getLogger(__name__).debug("world_graph fetch failed: %s", e)
        return ""

    if not g or not g.nodes:
        return ""

    # top 10 实体
    top_nodes = g.nodes[:10]
    entity_lines = []
    for n in top_nodes:
        kind_tag = {"character": "👤", "location": "📍", "item": "📦", "concept": "💡"}.get(n.get("kind", ""), "▪")
        entity_lines.append(f"{kind_tag} {n['label']}(×{n['size']})")

    # top 8 关系边
    top_edges = sorted(g.edges, key=lambda e: -e.get("weight", 0))[:8]
    edge_lines = []
    for e in top_edges:
        edge_lines.append(f"{e['source']} ↔ {e['target']} (共{e['weight']}章)")

    lines = [", ".join(entity_lines)]
    if edge_lines:
        lines.append(" | ".join(edge_lines))
    return _truncate("\n".join(lines), BUDGET_WORLD_GRAPH)


def _format_project_skill_hints(project_id: str, chapter: dict) -> str:
    """v3.0 Layer 5: 注入候选 Skill 作为 [📚 项目内参考] 段."""
    try:
        from app.workflow import edit_signals as _es
        return _es.build_prompt_segment(project_id, chapter)
    except Exception:
        return ""


def _format_style_fingerprint(data) -> str:
    """格式化风格指纹文本 (兼容旧版 JSON + 新版双层)."""
    if not data:
        return ""
    if isinstance(data, dict):
        # 新版 L1 作者指纹 6 维 key
        new_keys = ["sentence_rhythm", "dialogue_density", "description_style",
                    "emotion_expression", "paragraph_density", "language_level"]
        label_map = {
            "sentence_rhythm": "句子节奏", "dialogue_density": "对话密度",
            "description_style": "描写风格", "emotion_expression": "情绪表达",
            "paragraph_density": "段落密度", "language_level": "语言层级",
        }
        parts = []
        for k in new_keys:
            if k in data:
                parts.append(f"{label_map[k]}: {data[k]}/10")
        if not parts:
            # 旧版 key 兼容
            old_keys = ["sentence_rhythm", "vocabulary", "view_point", "tone", "pacing"]
            parts = [f"{k}: {data[k]}" for k in old_keys if k in data]
        if not parts:
            parts = [str(data)[:BUDGET_STYLE]]
    else:
        parts = [str(data)]
    return _truncate("\n".join(parts), BUDGET_STYLE)


def _format_genre_writing_guide(genre_str: str) -> str:
    """v3.4 新增: 格式化题材写法指导 (AI病句正反例 + 写法要点 + 禁忌)."""
    from app.core.genre_presets import GENRE_WRITING_GUIDES
    
    if not genre_str:
        return ""
    
    # 解析主题材 (取第一个)
    from app.core.genre_presets import parse_genre_string
    genres = parse_genre_string(genre_str)
    if not genres:
        return ""
    
    main_genre = genres[0]
    guide = GENRE_WRITING_GUIDES.get(main_genre)
    if not guide:
        return ""
    
    parts = []
    
    # AI病句正反例
    sick = guide.get("ai_sick_sentences", {})
    if sick:
        parts.append("❌ 病句示例:")
        parts.append(f"  反例: {sick.get('bad', '')}")
        parts.append(f"  正例: {sick.get('good', '')}")
        reason = sick.get("reason", "")
        if reason:
            parts.append(f"  原因: {reason}")
    
    # 写法要点
    tips = guide.get("writing_tips", [])
    if tips:
        parts.append("\n✅ 写法要点:")
        for tip in tips[:4]:  # 限制最多4条
            parts.append(f"  • {tip}")
    
    # 禁忌
    taboos = guide.get("taboos", [])
    if taboos:
        parts.append("\n⚠️ 禁忌:")
        for taboo in taboos[:4]:  # 限制最多4条
            parts.append(f"  • {taboo}")
    
    return "\n".join(parts) if parts else ""


# --------------------------------------------------------------------- #
# 公开 API
# --------------------------------------------------------------------- #

def assemble_writer_prompt(
    project_id: str,
    chapter_id: str,
    *,
    mindset_dict: Optional[dict] = None,
) -> dict:
    """组装 Writer 用的 prompt. 返回 {"system": str, "user": str}.

    system: 全局约束 (世界观 / 风格指纹 / 声音档案 / 反规则)
    user:   本章上下文 (brief + 6 问 + 伏笔)
    """
    # ---- 系统提示 (风格指纹 / 反规则 / 题材) ----
    # genre_presets 是 L0 纯数据 (app.core.genre_presets), 跨层 OK
    from app.core import genre_presets  # noqa: E402  (L0, no layering issue)

    # 双层风格指纹: 优先从新 SQLite 体系读取
    style = None
    try:
        from app.services.style_fingerprint import (
            get_author_fp, get_book_fp,
            to_author_prompt_block, to_book_prompt_block,
        )
        af = get_author_fp()
        bf = get_book_fp(project_id)
        # 合并为新格式 dict (供 _format_style_fingerprint 使用)
        style = {}
        style.update(af.to_dict())
        style["book_genre_tone"] = bf.genre_tone
        style["book_atmosphere"] = bf.atmosphere_tendency
        style["book_complexity"] = bf.narrative_complexity
        style["book_pacing"] = bf.pacing_preference
    except Exception:
        # fallback: 旧 setting_service JSON 路径
        _style = setting_service.get_setting(project_id, "style_fingerprint") or {}
        style = _style.get("data")
    _anti = setting_service.get_setting(project_id, "anti_rules") or {}
    anti = _anti.get("data")
    system_parts: list[str] = [
        "你是一位专业的小说作者. 严格遵循以下风格指纹, 绝不违反反规则.",
    ]
    # 注入题材 (A1 题材 prompt) — genre_presets 是 L0 纯数据, 跨层 OK
    # V4.0-P2-新: 同时叠加 副题材 (sub_genres) 到题材行 + 扩展 keywords 集合
    try:
        proj = project_service.get(project_id) or {}
        genre_str = proj.get("genre") or ""
        sub_genres = proj.get("sub_genres") or []
        # 副题材可能是字符串 (老数据) 或 list (新数据)
        if isinstance(sub_genres, str):
            sub_genres = genre_presets.parse_subgenre_string(sub_genres)
    except Exception as e:
        logging.warning("project_service.get(%s) failed in prompt assembler: %s", project_id, e)
        genre_str = ""
        sub_genres = []

    # 字数控制: words_per_chapter / word_target 注入到 ## 字数控制
    words_per_chapter = int(proj.get("words_per_chapter") or 0)
    word_target = int(proj.get("total_words") or (proj.get("word_target") or 0))

    if genre_str or sub_genres:
        # 主 + 副 双轨显示
        if sub_genres:
            genre_line = f"题材: {genre_str or '未设'} + 元素标签: {'、'.join(sub_genres)}"
        else:
            genre_line = f"题材: {genre_str}"

        # 关键词扩: 主题材的 keywords + 副题材的名字本身 (副题材就是元素标签, 注入 prompt 等于点名)
        kws_main = genre_presets.genre_to_keywords(genre_str) if genre_str else []
        kws_sub = list(sub_genres)  # 副题材本身就是要的风格/元素提示
        seen: set = set()
        kws_all: list[str] = []
        for kw in (kws_main + kws_sub):
            if kw and kw not in seen:
                seen.add(kw)
                kws_all.append(kw)
        kw_line = "、".join(kws_all[:10]) if kws_all else ""
        if kw_line:
            genre_line += f"\n风格关键词: {kw_line}"
        system_parts.append("## 题材与元素标签\n" + genre_line)
        
        # v3.4 新增: 注入题材写法指导 (AI病句正反例 + 写法要点 + 禁忌)
        genre_guide_text = _format_genre_writing_guide(genre_str)
        if genre_guide_text:
            system_parts.append("## 题材写法指导\n" + genre_guide_text)

    # V4.0-P2-新: ## 字数控制 — 告诉 AI 写多少字, 避免一章写了 3 万字
    if words_per_chapter > 0 or word_target > 0:
        wc_parts = []
        if words_per_chapter > 0:
            wc_parts.append(f"本章目标字数: 约 {words_per_chapter:,} 字 (±20%)")
        if word_target > 0:
            wc_parts.append(f"全书总字数目标: {word_target:,} 字")
        wc_parts.append("请按场景切片, 不要把多章塞到一节里.")
        system_parts.append("## 字数控制\n" + "\n".join(wc_parts))
    style_text = _format_style_fingerprint(style)
    if style_text:
        system_parts.append("## 风格指纹\n" + style_text)
    anti_text = _format_anti_rules(anti)
    if anti_text:
        system_parts.append("## 反规则 (绝不写)\n" + anti_text)

    system_text = "\n\n".join(system_parts)

    # ---- 用户提示 (项目设定 + brief + 6 问 + 伏笔) ----
    # M11-A: get_setting 可能返回 None (新项目没存这些), 加 fallback {}
    def _s(key: str):
        v = setting_service.get_setting(project_id, key)
        return v.get("data") if isinstance(v, dict) else None
    world = _s("worldbuilding")
    chars = _s("characters")
    voice = _s("voice_profiles")
    hooks = _s("hooks")

    try:
        chapter = chapter_service.get(chapter_id)
    except Exception:
        chapter = {"chapter_no": "?", "title": "(无题)", "scene_context": ""}
    try:
        brief = chapter_service.get_brief(chapter_id)
    except Exception:
        brief = {"brief": None, "core_events": None, "emotion_arc": None}

    user_parts: list[str] = [
        f"第 {chapter.get('chapter_no', '?')} 章: {chapter.get('title') or '(无题)'}",
    ]
    scene = chapter.get("scene_context") or ""
    if scene:
        user_parts.append(f"场景: {scene[:300]}")

    brief_text = brief.get("brief") or ""
    if brief_text:
        user_parts.append("## 大纲\n" + _truncate(brief_text, BUDGET_BRIEF))
    if brief.get("core_events"):
        user_parts.append("## 核心事件\n" + _truncate(str(brief["core_events"]), 200))
    if brief.get("emotion_arc"):
        user_parts.append("## 情绪弧线\n" + _truncate(str(brief["emotion_arc"]), 150))

    world_text = _format_worldbuilding(world)
    if world_text:
        user_parts.append("## 世界观\n" + world_text)
    chars_text = _format_characters(chars)
    if chars_text:
        user_parts.append("## 角色 (声音档案)\n" + chars_text)
    voice_text = _format_characters(voice)
    if voice_text and voice_text != chars_text:
        user_parts.append("## 声音档案补充\n" + voice_text)
    # 实体关系图谱 (v3.4 G10, 让 AI 知道当前章节的实体关系网)
    try:
        chapter_no = chapter.get("chapter_no", 0)
        chapter_no_int = int(chapter_no) if chapter_no else 0
        graph_text = _format_world_graph(project_id, chapter_no_int)
        if graph_text:
            user_parts.append("## 当前实体关系\n" + graph_text)
    except Exception:
        pass
    hooks_text = _format_hooks(hooks)
    if hooks_text:
        user_parts.append("## 待回收伏笔\n" + hooks_text)

    # 6 问 (如果传入了)
    if mindset_dict:
        for k, v in mindset_dict.items():
            if v:
                user_parts.append(f"## 心智清单 {k}\n{_truncate(str(v), 100)}")

    # v3.0 Layer 5: 注入候选 Skill 作为 [📚 项目内参考] 段 (opt-in)
    try:
        chapter_dict = dict(chapter or {})
        chapter_dict["id"] = chapter_id if chapter_id else ""
        chapter_dict["content"] = (
            (brief_text or "")
            + "\n"
            + (chapter.get("scene_context") or "")
        )[:2000]
        skill_hints = _format_project_skill_hints(project_id, chapter_dict)
        if skill_hints:
            user_parts.append("## 📚 项目内参考 (候选 Skill)\n" + skill_hints)
    except Exception:
        pass

    user_parts.append("\n请写这一章, 2500-3500 字, 直接输出正文, 标题用第 N 章.")
    user_text = "\n\n".join(user_parts)

    return {"system": system_text, "user": user_text}
