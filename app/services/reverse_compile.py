"""
反向编译服务 - 将文本反向解析为结构化数据

闭环：AI生成 → 人类润色 → 知识库固化
下次编译时，已经被作者认可的表达会优先出现。

用途：
- 作者修改了AI生成的内容后，反向提取被认可的表达
- 更新知识库权重，让好的表达优先复用
- 提取新的角色/事件/设定信息
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.db._impl import get_conn

_logger = logging.getLogger("NovelWriter.services.reverse_compile")


@dataclass
class ParsedCharacter:
    """解析出的角色信息"""
    name: str
    aliases: list[str] = field(default_factory=list)
    traits: list[str] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)


@dataclass
class ParsedEvent:
    """解析出的事件信息"""
    description: str
    chapter: int = 0
    characters_involved: list[str] = field(default_factory=list)
    location: str = ""
    time_ref: str = ""


@dataclass
class ParsedOutline:
    """解析出的大纲结构"""
    title: str = ""
    synopsis: str = ""
    chapters: list[dict] = field(default_factory=list)
    characters: list[ParsedCharacter] = field(default_factory=list)
    events: list[ParsedEvent] = field(default_factory=list)
    worldbuilding: dict = field(default_factory=dict)


@dataclass
class ReverseCompileResult:
    """反向编译结果"""
    id: str
    project_id: str
    source_chapter_id: str
    ai_version_hash: str  # AI生成版本的hash
    author_version_hash: str  # 作者版本的hash
    parsed_outline: ParsedOutline
    extracted_patterns: list[dict]  # 提取的写作模式
    weight_updates: list[dict]  # 知识权重更新建议
    created_at: str


def reverse_compile(
    project_id: str,
    chapter_id: str,
    ai_content: str,
    author_content: str,
) -> ReverseCompileResult:
    """
    反向编译：对比AI版本和作者版本，提取被认可的表达

    Args:
        project_id: 项目ID
        chapter_id: 章节ID
        ai_content: AI生成的内容
        author_content: 作者修改后的内容

    Returns:
        ReverseCompileResult: 反向编译结果
    """
    import hashlib

    # 1. 计算hash
    ai_hash = hashlib.md5(ai_content.encode()).hexdigest()[:8]
    author_hash = hashlib.md5(author_content.encode()).hexdigest()[:8]

    # 2. 解析作者版本
    parsed = parse_text(author_content)

    # 3. 提取被认可的模式
    patterns = _extract_patterns(ai_content, author_content)

    # 4. 计算权重更新
    weight_updates = _calculate_weight_updates(patterns)

    result = ReverseCompileResult(
        id=str(uuid.uuid4()),
        project_id=project_id,
        source_chapter_id=chapter_id,
        ai_version_hash=ai_hash,
        author_version_hash=author_hash,
        parsed_outline=parsed,
        extracted_patterns=patterns,
        weight_updates=weight_updates,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )

    _save_to_db(result)
    _logger.info(f"Reverse compile done: {result.id}, {len(patterns)} patterns extracted")
    return result


def parse_text(text: str) -> ParsedOutline:
    """
    解析文本为大纲结构

    Args:
        text: 文本内容

    Returns:
        ParsedOutline: 解析出的大纲结构
    """
    outline = ParsedOutline()

    # 提取标题（如果有）
    title_match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
    if title_match:
        outline.title = title_match.group(1).strip()

    # 提取章节
    chapter_pattern = r'(?:^|\n)第?(\d+)[章节回]\s*[:：]?\s*(.+?)(?:\n|$)'
    for match in re.finditer(chapter_pattern, text):
        outline.chapters.append({
            "number": int(match.group(1)),
            "title": match.group(2).strip(),
        })

    # 提取角色
    outline.characters = _extract_characters(text)

    # 提取事件
    outline.events = _extract_events(text)

    # 提取世界观设定
    outline.worldbuilding = _extract_worldbuilding(text)

    return outline


def parse_characters(text: str) -> list[ParsedCharacter]:
    """
    解析文本中的角色信息

    Args:
        text: 文本内容

    Returns:
        list[ParsedCharacter]: 角色列表
    """
    return _extract_characters(text)


def parse_events(text: str) -> list[ParsedEvent]:
    """
    解析文本中的事件信息

    Args:
        text: 文本内容

    Returns:
        list[ParsedEvent]: 事件列表
    """
    return _extract_events(text)


def apply_weight_updates(result_id: str) -> int:
    """
    应用权重更新到知识库

    Args:
        result_id: 反向编译结果ID

    Returns:
        int: 更新的知识条目数
    """
    result = _get_result(result_id)
    if not result:
        return 0

    conn = get_conn()
    updated = 0

    for update in result.weight_updates:
        evidence_id = update.get("evidence_id")
        delta = update.get("delta", 0.1)

        if evidence_id:
            # 更新知识条目权重
            conn.execute(
                """UPDATE knowledge_entries
                   SET weight = MIN(1.0, weight + ?)
                   WHERE id = ?""",
                (delta, evidence_id),
            )
            updated += 1

    conn.commit()
    _logger.info(f"Applied {updated} weight updates from result {result_id}")
    return updated


def get_reverse_compile_results(
    project_id: str,
    chapter_id: str | None = None,
) -> list[ReverseCompileResult]:
    """
    获取反向编译结果列表

    Args:
        project_id: 项目ID
        chapter_id: 可选，按章节ID过滤

    Returns:
        list[ReverseCompileResult]: 结果列表
    """
    conn = get_conn()
    query = "SELECT * FROM reverse_compile_results WHERE project_id = ?"
    params: list = [project_id]

    if chapter_id:
        query += " AND source_chapter_id = ?"
        params.append(chapter_id)

    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()

    return [_row_to_result(row) for row in rows]


# --- 内部函数 ---

def _extract_characters(text: str) -> list[ParsedCharacter]:
    """从文本中提取角色"""
    characters = []

    # 简单的中文人名提取（2-4个字的名字）
    name_pattern = r'(?<![a-zA-Z])([^\s,，。！？""''（）\(\)]{2,4}?)(?:说|道|想|看|走|跑|笑|哭|站|坐|听|问|答|叫|喊|哼|点头|摇头|转身|回头)'
    found_names = set()

    for match in re.finditer(name_pattern, text):
        name = match.group(1)
        if len(name) >= 2 and name not in found_names:
            found_names.add(name)
            characters.append(ParsedCharacter(name=name))

    return characters


def _extract_events(text: str) -> list[ParsedEvent]:
    """从文本中提取事件"""
    events = []

    # 简单的事件提取（基于动词和时间词）
    event_indicators = ['突然', '忽然', '只见', '只听', '这时', '此时', '忽然间', '猛然']

    for indicator in event_indicators:
        pattern = f'{indicator}[，,](.+?)[。！？]'
        for match in re.finditer(pattern, text):
            events.append(ParsedEvent(description=match.group(1).strip()))

    return events


def _extract_worldbuilding(text: str) -> dict:
    """从文本中提取世界观设定"""
    worldbuilding = {}

    # 提取修仙等级
    realm_patterns = [
        r'(炼气|筑基|金丹|元婴|化神|合体|大乘|渡劫)',
        r'(后天|先天|宗师|大宗师)',
    ]
    for pattern in realm_patterns:
        matches = re.findall(pattern, text)
        if matches:
            worldbuilding['realms'] = list(set(matches))

    # 提取地名
    location_pattern = r'[\u4e00-\u9fa5]{2,6}(?:山|谷|洞|城|镇|村|峰|岛|海|湖|河|寺|庙|宫|殿|阁)'
    locations = re.findall(location_pattern, text)
    if locations:
        worldbuilding['locations'] = list(set(locations))

    return worldbuilding


def _extract_patterns(ai_content: str, author_content: str) -> list[dict]:
    """提取被作者认可的写作模式"""
    patterns = []

    # 1. 提取作者保留的句子（AI有但作者没删的）
    ai_sentences = set(re.split(r'[。！？]', ai_content))
    author_sentences = set(re.split(r'[。！？]', author_content))

    kept_sentences = ai_sentences & author_sentences
    for sentence in kept_sentences:
        if len(sentence.strip()) > 10:  # 忽略太短的
            patterns.append({
                "type": "kept_sentence",
                "content": sentence.strip(),
                "weight_delta": 0.05,
            })

    # 2. 提取作者新增的表达
    added_sentences = author_sentences - ai_sentences
    for sentence in added_sentences:
        if len(sentence.strip()) > 10:
            patterns.append({
                "type": "author_added",
                "content": sentence.strip(),
                "weight_delta": 0.1,
            })

    # 3. 提取作者删除的表达（可能是AI味）
    deleted_sentences = ai_sentences - author_sentences
    for sentence in deleted_sentences:
        if len(sentence.strip()) > 10:
            patterns.append({
                "type": "author_deleted",
                "content": sentence.strip(),
                "weight_delta": -0.1,
            })

    return patterns


def _calculate_weight_updates(patterns: list[dict]) -> list[dict]:
    """计算权重更新建议"""
    updates = []

    for pattern in patterns:
        # TODO: 匹配到知识库中的具体条目
        # 这里简化处理，实际应该用语义匹配
        updates.append({
            "pattern_type": pattern["type"],
            "content_preview": pattern["content"][:50],
            "delta": pattern["weight_delta"],
            "evidence_id": None,  # 需要实际匹配
        })

    return updates


def _save_to_db(result: ReverseCompileResult) -> None:
    """保存反向编译结果到数据库"""
    conn = get_conn()
    conn.execute(
        """INSERT INTO reverse_compile_results
           (id, project_id, source_chapter_id, ai_version_hash,
            author_version_hash, parsed_outline, extracted_patterns,
            weight_updates, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            result.id,
            result.project_id,
            result.source_chapter_id,
            result.ai_version_hash,
            result.author_version_hash,
            json.dumps({
                "title": result.parsed_outline.title,
                "synopsis": result.parsed_outline.synopsis,
                "chapters": result.parsed_outline.chapters,
                "worldbuilding": result.parsed_outline.worldbuilding,
            }, ensure_ascii=False),
            json.dumps(result.extracted_patterns, ensure_ascii=False),
            json.dumps(result.weight_updates, ensure_ascii=False),
            result.created_at,
        ),
    )
    conn.commit()


def _get_result(result_id: str) -> ReverseCompileResult | None:
    """获取反向编译结果"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM reverse_compile_results WHERE id = ?",
        (result_id,),
    ).fetchone()

    return _row_to_result(row) if row else None


def _row_to_result(row) -> ReverseCompileResult:
    """将数据库行转换为ReverseCompileResult"""
    outline_data = json.loads(row[5]) if row[5] else {}
    return ReverseCompileResult(
        id=row[0],
        project_id=row[1],
        source_chapter_id=row[2],
        ai_version_hash=row[3],
        author_version_hash=row[4],
        parsed_outline=ParsedOutline(
            title=outline_data.get("title", ""),
            synopsis=outline_data.get("synopsis", ""),
            chapters=outline_data.get("chapters", []),
            worldbuilding=outline_data.get("worldbuilding", {}),
        ),
        extracted_patterns=json.loads(row[6]) if row[6] else [],
        weight_updates=json.loads(row[7]) if row[7] else [],
        created_at=row[8],
    )
