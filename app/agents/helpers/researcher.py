"""
Researcher (资料研究员 Agent)
业务场景: 为章节写作查找历史/题材相关资料，补充知识库不足。

职责:
  1. 分析章节任务，拆解需要查什么资料
  2. 查本地知识库（BM25 + 向量）
  3. 整理输出精炼资料给写手

设计原则:
  - P0: 只查本地知识库，不接联网搜索
  - 资料注入 _refine() 的"写作指导"section
  - 不污染写手上下文，只给精炼后的资料摘要
"""
from __future__ import annotations
import logging
from typing import Any

from app.agents.base import AgentBase, AgentRole
from app.agents.report import Report, ReportKind

_logger = logging.getLogger("NovelWriter.agents.researcher")


class Researcher(AgentBase):
    """
    资料研究员 Agent。

    工作流程:
      1. 加载章节上下文（标题、场景、人物、朝代等）
      2. 分析需要什么资料（典章制度/地理风物/礼仪称谓/历史事件等）
      3. 查本地知识库（按题材+标签检索）
      4. 整理输出精炼资料摘要
    """

    DEFAULT_KIND = ReportKind.RESEARCH

    def __init__(
        self,
        *,
        name: str = "Researcher",
        max_chars: int = 400,
    ) -> None:
        super().__init__(name=name, role=AgentRole.RESEARCHER)
        self.max_chars = max_chars  # 精炼后资料上限

    def _do_execute(self, task: dict) -> Report:
        ctx = task.get("context", {})
        project_id = ctx.get("project_id", "")
        chapter_id = ctx.get("chapter_id", "")

        # ---- Step 1: 加载章节上下文 ----
        chapter_info = self._load_chapter_context(chapter_id)
        if not chapter_info:
            return self._build_report(task, {
                "needs_research": False,
                "snippets": "",
                "topics": [],
                "query": "",
            })

        # ---- Step 2: 分析需要什么资料 ----
        research_topics = self._analyze_research_needs(chapter_info)
        if not research_topics:
            return self._build_report(task, {
                "needs_research": False,
                "snippets": "",
                "topics": [],
                "query": "",
            })

        # ---- Step 3: 查本地知识库 ----
        snippets = self._search_knowledge_base(research_topics, chapter_info)

        # ---- Step 4: 整理输出 ----
        data = {
            "needs_research": bool(snippets),
            "snippets": snippets,
            "topics": research_topics,
            "query": " ".join(research_topics),
        }
        return self._build_report(task, data)

    def _load_chapter_context(self, chapter_id: str) -> dict:
        """加载章节相关信息，供资料分析用."""
        try:
            from app.services import chapter_service, project_service

            chapter = chapter_service.get(chapter_id) or {}
            project = project_service.get(chapter.get("project_id", "")) or {}

            return {
                "title": chapter.get("title", ""),
                "scene_context": chapter.get("scene_context", ""),
                "genre": project.get("genre", ""),
                "dynasty": project.get("dynasty", ""),  # 朝代标签
                "tags": project.get("tags", []),
                "chapter_no": chapter.get("chapter_no", 0),
            }
        except Exception as e:
            _logger.debug("[researcher] 加载上下文失败: %s", e)
            return {}

    def _analyze_research_needs(self, chapter_info: dict) -> list[str]:
        """
        分析本章需要什么资料。
        P0 版本：基于题材和标签做简单匹配。

        返回: 需要检索的关键词列表
        """
        topics: list[str] = []
        genre = chapter_info.get("genre", "")
        dynasty = chapter_info.get("dynasty", "")
        tags = chapter_info.get("tags", []) or []
        scene = chapter_info.get("scene_context", "")
        title = chapter_info.get("title", "")

        # 朝代优先
        if dynasty:
            topics.append(dynasty)

        # 题材关键词映射
        genre_keyword_map = {
            "历史": ["古代", "典章", "官职", "礼仪"],
            "古言": ["古代", "闺阁", "宅斗", "宫斗"],
            "仙侠": ["修仙", "宗门", "法宝", "灵草"],
            "都市": ["现代", "职场", "商战"],
            "悬疑": ["推理", "犯罪", "刑侦"],
            "科幻": ["未来", "科技", "星际"],
        }
        if genre in genre_keyword_map:
            topics.extend(genre_keyword_map[genre])

        # 从场景描述中提关键词（简单分词）
        for keyword in ["市集", "宫殿", "战场", "酒楼", "茶馆", "书院",
                        "婚姻", "丧礼", "宴会", "祭祀", "科举", "狩猎"]:
            if keyword in scene or keyword in title:
                topics.append(keyword)

        # 去重，保持顺序
        seen = set()
        unique_topics = []
        for t in topics:
            if t not in seen:
                seen.add(t)
                unique_topics.append(t)

        return unique_topics[:5]  # 最多 5 个主题

    def _search_knowledge_base(self, topics: list[str], chapter_info: dict) -> str:
        """
        查本地知识库，返回精炼后的资料摘要。

        P0 版本：走 app.knowledge.finder.extract_for_prompt
        """
        if not topics:
            return ""

        try:
            from app.knowledge import finder as _finder

            # 构造查询：题材 + 朝代 + 主题
            query_parts = [chapter_info.get("genre", ""), chapter_info.get("dynasty", "")]
            query_parts.extend(topics)
            query = " ".join(filter(None, query_parts))

            if not query.strip():
                return ""

            # 查本地知识库（文风+桥段+场景描写）
            snippet = _finder.extract_for_prompt(
                query,
                top_k=3,
                max_total_chars=self.max_chars,
            )
            return snippet

        except Exception as e:
            _logger.warning("[researcher] 检索知识库失败: %s", e)
            return ""
