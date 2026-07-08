"""
D1 拍板: 知识包目录初始化 (明文 MD)
- 启动时 init_knowledge_dirs() 确保 builtin/local/index 三层目录齐全
- 5 个分类 × 2 个来源 = 10 个分类目录
- 提供 scan_category / read_doc 供 F1 (BM25) / F2 (向量) / D2 (finder) 调用

A1 拍板: 检索只取 文风语料 + 桥段 (for_retrieval=True)
A1.7 拍板: 题材感知 (从 frontmatter 解析 genre)
A1.8 拍板: 每类抽 1-2 段 (总 ~200 字)
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_logger = logging.getLogger("NovelWriter.knowledge")

# ────────────────────── 路径常量 ──────────────────────

# knowledge/ 根目录 = app/knowledge/
KNOWLEDGE_ROOT = Path(__file__).resolve().parent

BUILTIN_DIR = KNOWLEDGE_ROOT / "builtin"
LOCAL_DIR = KNOWLEDGE_ROOT / "local"
INDEX_DIR = KNOWLEDGE_ROOT / "index"

# 5 个预置分类 (与 app.core.constants.PRESET_KNOWLEDGE_CATEGORIES 一致)
PRESET_CATEGORIES = (
    "文风语料",
    "桥段",
    "人物人设",
    "场景描写",
    "框架模板",
    # ── 新增: Agent 专属知识分类 (分层知识库 M1) ──
    "编排技巧",
    "编排范本",
    "写作技巧",
    "写作范本",
    "人物对话",
    "指导手册",
)

# A1.7 拍板: 旧检索只取 文风 + 桥段 (喂给写作 RAG 的默认范围)
RETRIEVAL_CATEGORIES = frozenset({"文风语料", "桥段"})

# 新增: Agent 分区专属分类 (编排/写作 Agent 各自的知识库)
AGENT_CATEGORIES = (
    "编排技巧",
    "编排范本",
    "写作技巧",
    "写作范本",
    "人物对话",
    "指导手册",
)

# 索引构建时纳入检索的分类 = 旧检索类 ∪ Agent 类
# (旧 RAG 行为通过 finder.search 的 category 门控保持, 不会把 Agent 类混入旧 prompt)
INDEX_RETRIEVAL_CATEGORIES = frozenset(RETRIEVAL_CATEGORIES).union(AGENT_CATEGORIES)

# ── Agent 分区标识 (frontmatter `agent` 字段取值, 支持逗号分隔多归属) ──
AGENT_ORCHESTRATION = "orchestration"   # 编排 Agent
AGENT_WRITING = "writing"               # 写作 Agent
AGENT_GENERAL = "general"               # 共享能用库 (所有 Agent 可取)
AGENT_VALUES = (AGENT_ORCHESTRATION, AGENT_WRITING, AGENT_GENERAL)

# ── 文档类型 (frontmatter `doc_type` 字段取值) ──
DOC_MANUAL = "manual"           # 指导手册 (固定注入 system, 不占检索预算)
DOC_TECHNIQUE = "technique"     # 写作/编排技巧
DOC_TEMPLATE = "template"       # 编排/写作范本
DOC_DIALOGUE = "dialogue"       # 人物对话
DOC_REFERENCE = "reference"     # 参考资料
DOC_TYPES = (DOC_MANUAL, DOC_TECHNIQUE, DOC_TEMPLATE, DOC_DIALOGUE, DOC_REFERENCE)

# ── Agent 分区预算 (字符上限, 防 prompt 膨胀) ──
KB_BUDGET_MANUAL = 800          # 指导手册固定注入上限
KB_BUDGET_RETRIEVE = 600        # 专属分区检索上限
KB_BUDGET_SHARED = 600          # 共享库检索上限
KB_BUDGET_TOTAL_PER_AGENT = 1500  # 单 Agent 总字符上限

# 合法来源
SOURCE_BUILTIN = "builtin"
SOURCE_LOCAL = "local"
VALID_SOURCES = (SOURCE_BUILTIN, SOURCE_LOCAL)


# ────────────────────── Agent 分区工具 ──────────────────────

def split_agents(agent_field: str) -> set[str]:
    """把 frontmatter `agent` 字段 (逗号分隔) 解析成集合。"""
    if not agent_field:
        return set()
    return {a.strip() for a in str(agent_field).split(",") if a.strip()}


def agent_in_partition(doc_agent: str, partition_agent: str) -> bool:
    """
    判断文档是否属于某 Agent 分区。
    - doc_agent: 文档的 agent 字段 (可逗号多归属)
    - partition_agent: 目标分区 (orchestration/writing/general)
    规则: 文档 agent 含 partition_agent, 或含 general 且 partition 允许共享。
    共享库 (general) 文档对所有分区可见; 分区专属文档仅对该分区可见。
    """
    doc_agents = split_agents(doc_agent)
    if not doc_agents:
        return False
    if partition_agent in doc_agents:
        return True
    # 共享库对所有分区开放
    if AGENT_GENERAL in doc_agents and partition_agent != AGENT_GENERAL:
        return True
    return False


# ────────────────────── 数据类 ──────────────────────

@dataclass
class KnowledgeDoc:
    """一篇知识文档 (含解析后的 frontmatter)。"""
    path: Path
    name: str
    category: str
    source: str         # builtin / local
    genre: str = "通用"  # 从 frontmatter 解析, 默认 "通用"
    tags: list[str] = field(default_factory=list)
    agent: str = ""     # 从 frontmatter 解析, 逗号分隔 (orchestration/writing/general)
    doc_type: str = ""  # 从 frontmatter 解析 (manual/technique/template/dialogue/reference)
    content: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "name": self.name,
            "category": self.category,
            "source": self.source,
            "genre": self.genre,
            "tags": self.tags,
            "agent": self.agent,
            "doc_type": self.doc_type,
            "content_length": len(self.content),
        }


# ────────────────────── 目录管理 ──────────────────────

def get_source_dir(source: str) -> Path:
    """获取来源根目录。"""
    if source == SOURCE_BUILTIN:
        return BUILTIN_DIR
    if source == SOURCE_LOCAL:
        return LOCAL_DIR
    raise ValueError(f"未知来源: {source} (合法: {VALID_SOURCES})")


def get_category_dir(category: str, source: str = SOURCE_BUILTIN) -> Path:
    """获取某分类目录。"""
    if category not in PRESET_CATEGORIES:
        raise ValueError(f"未知分类: {category} (合法: {PRESET_CATEGORIES})")
    return get_source_dir(source) / category


def init_knowledge_dirs() -> dict:
    """
    启动时初始化所有知识目录。
    返回创建结果 (用于日志 / 首次启动提示)。
    """
    result = {
        "builtin": [],
        "local": [],
        "index": [],
    }
    for source in VALID_SOURCES:
        base = get_source_dir(source)
        if not base.exists():
            base.mkdir(parents=True, exist_ok=True)
            result[source].append(str(base))
        for cat in PRESET_CATEGORIES:
            cat_dir = base / cat
            if not cat_dir.exists():
                cat_dir.mkdir(parents=True, exist_ok=True)
                result[source].append(str(cat_dir))
    # 索引目录
    if not INDEX_DIR.exists():
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        result["index"].append(str(INDEX_DIR))
    # 内置 README (首次启动)
    readme = KNOWLEDGE_ROOT / "README.md"
    if not readme.exists():
        readme.write_text(_DEFAULT_README, encoding="utf-8")
        result["builtin"].append(str(readme))
    total = sum(len(v) for v in result.values())
    _logger.info("知识目录初始化: 共 %d 项", total)
    return result


# ────────────────────── 扫描 / 读取 ──────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    解析 frontmatter (--- 包裹的 YAML-ish 段)。
    极简实现: 只支持 key: value / key: [a, b, c]
    返回 (meta_dict, 剩余正文)。
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    block = m.group(1)
    rest = text[m.end():]
    meta = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            if not inner:
                meta[key] = []
                continue
            # 简单分隔: 逗号 或 空格
            parts = [p.strip().strip('"').strip("'") for p in re.split(r"[,\s]+", inner) if p.strip()]
            meta[key] = parts
        else:
            meta[key] = val.strip('"').strip("'")
    return meta, rest


def _read_text(path: Path) -> str:
    """读文本, 容错 (优先 utf-8, 失败再 gbk)。"""
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
        except Exception as e:
            _logger.warning("读文件失败 %s: %s", path, e)
            return ""
    return ""


def read_doc(path: str | Path) -> KnowledgeDoc:
    """
    读一个 MD 文件 → KnowledgeDoc。
    path 可以是绝对路径 / 相对于 knowledge/ 的路径。
    """
    p = Path(path)
    if not p.is_absolute():
        p = KNOWLEDGE_ROOT / p
    if not p.exists():
        raise FileNotFoundError(f"知识文件不存在: {p}")

    # 推断 category + source (从路径)
    rel = p.relative_to(KNOWLEDGE_ROOT) if p.is_relative_to(KNOWLEDGE_ROOT) else p
    parts = rel.parts
    source = SOURCE_BUILTIN
    category = "未分类"
    if len(parts) >= 2:
        if parts[0] == SOURCE_BUILTIN and parts[1] in PRESET_CATEGORIES:
            source = SOURCE_BUILTIN
            category = parts[1]
        elif parts[0] == SOURCE_LOCAL and parts[1] in PRESET_CATEGORIES:
            source = SOURCE_LOCAL
            category = parts[1]

    text = _read_text(p)
    meta, _ = _parse_frontmatter(text)
    return KnowledgeDoc(
        path=p,
        name=p.stem,
        category=category,
        source=source,
        genre=meta.get("genre", "通用"),
        tags=meta.get("tags", []) or [],
        agent=str(meta.get("agent", "")).strip(),
        doc_type=str(meta.get("doc_type", "")).strip(),
        content=text,
        metadata=meta,
    )


def scan_category(
    category: str,
    source: str = SOURCE_BUILTIN,
    *,
    for_retrieval: bool = False,
) -> list[KnowledgeDoc]:
    """
    扫描某分类下所有 MD 文件。
    for_retrieval=True → 只返回纳入检索的分类 (旧 文风+桥段 ∪ Agent 类)。
    """
    if for_retrieval and category not in INDEX_RETRIEVAL_CATEGORIES:
        return []
    cat_dir = get_category_dir(category, source)
    if not cat_dir.exists():
        return []
    docs: list[KnowledgeDoc] = []
    for p in sorted(cat_dir.glob("*.md")):
        if p.name.lower() == "readme.md":
            continue
        try:
            docs.append(read_doc(p))
        except Exception as e:
            _logger.warning("扫描文件失败 %s: %s", p, e)
    return docs


def list_all() -> dict[str, dict[str, list[KnowledgeDoc]]]:
    """
    列出所有知识 (按 source → category 分组)。
    返回: {source: {category: [docs]}}
    """
    out: dict[str, dict[str, list[KnowledgeDoc]]] = {}
    for source in VALID_SOURCES:
        out[source] = {}
        for cat in PRESET_CATEGORIES:
            out[source][cat] = scan_category(cat, source)
    return out


def count_all() -> dict:
    """统计 (用于启动时打日志 / UI 仪表盘)。"""
    counts = {"total": 0, "by_source": {}, "by_category": {}}
    for source in VALID_SOURCES:
        cnt = 0
        for cat in PRESET_CATEGORIES:
            docs = scan_category(cat, source)
            cnt += len(docs)
            counts["by_category"].setdefault(cat, 0)
            counts["by_category"][cat] += len(docs)
        counts["by_source"][source] = cnt
        counts["total"] += cnt
    return counts


# ────────────────────── 检索 (占位, F1/F2/D2 会覆盖) ──────────────────────

def search_text(query: str, category: str = "文风语料", source: str = SOURCE_BUILTIN, top_k: int = 3) -> list[KnowledgeDoc]:
    """
    极简关键词检索 (F1 BM25 上线前的占位)。
    - 命中规则: 文档内容包含 query 任一关键词
    - 排序: 命中次数降序
    """
    keywords = [k for k in re.split(r"[\s,，]+", query) if k]
    if not keywords:
        return []
    docs = scan_category(category, source, for_retrieval=True)
    scored: list[tuple[int, KnowledgeDoc]] = []
    for d in docs:
        text = d.content
        score = sum(text.count(k) for k in keywords)
        if score > 0:
            scored.append((score, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored[:top_k]]


def extract_for_prompt(docs: list[KnowledgeDoc], max_total_chars: int = 200) -> str:
    """
    A1.8 拍板: 每类抽 1-2 段, 总 ~200 字。
    把多个 doc 的内容拼成 1 段, 不超 max_total_chars。
    """
    if not docs:
        return ""
    chunks: list[str] = []
    used = 0
    for d in docs[:2]:                # 每类最多 2 篇
        # 取前 max(200, max_total_chars) 字
        head = d.content.strip()
        if used + len(head) > max_total_chars:
            head = head[:max_total_chars - used]
        if head:
            chunks.append(f"【{d.category}/{d.name}】\n{head}")
            used += len(head)
        if used >= max_total_chars:
            break
    return "\n\n".join(chunks)


# ────────────────────── 默认 README (兜底) ──────────────────────

_DEFAULT_README = """# 知识库 (Knowledge)

4.0 自带知识库。明文 MD 文件存放在本目录。

```
app/knowledge/
├── builtin/   ← 内置知识 (用户可读 / 可改)
├── local/     ← 用户本地知识 (可增 / 减 / 改)
└── index/     ← 索引缓存 (运行时生成)
```

## 分类 (11 个)
旧 5 类: 文风语料 / 桥段 / 人物人设 / 场景描写 / 框架模板
Agent 专属 6 类: 编排技巧 / 编排范本 / 写作技巧 / 写作范本 / 人物对话 / 指导手册

## 分层知识库 (M1)
每篇文档 frontmatter 可带:
- `agent`: orchestration | writing | general (可逗号多归属; general=共享能用库)
- `doc_type`: manual | technique | template | dialogue | reference
- `genre` / `tags` / `category`

Agent 调用: `from app.knowledge.finder import extract_for_agent`
`extract_for_agent("writing", query)` → 【指导手册】+【专属知识-writing】+【共享库】
`extract_for_agent("orchestration", query)` → 编排分区专属
改/加文档后务必 `rebuild_index()` 重建索引。
"""


# ────────────────────── 启动入口 (main 调一次) ──────────────────────

def bootstrap() -> dict:
    """main 启动时调一次, 确保目录齐全 + 返回统计。"""
    init_knowledge_dirs()
    counts = count_all()
    _logger.info("知识库就绪: %d 篇 (内置 %d / 本地 %d)",
                 counts["total"],
                 counts["by_source"].get(SOURCE_BUILTIN, 0),
                 counts["by_source"].get(SOURCE_LOCAL, 0))
    return counts


if __name__ == "__main__":
    # 单独跑: python -m app.knowledge
    import json as _json
    c = bootstrap()
    print(_json.dumps(c, ensure_ascii=False, indent=2))
