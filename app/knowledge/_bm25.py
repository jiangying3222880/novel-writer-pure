"""
F1 拍板: BM25 检索 (含中文分词)
- 经典 BM25 (k1=1.5, b=0.75) + jieba 中文分词
- 支持增量添加 / 持久化 (pickle 到 app/knowledge/index/)
- 配套 A1.4 混合检索的第一零件 (与 F2 向量融合)
"""
from __future__ import annotations

import logging
import math
import pickle
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import jieba

# ────────────────────── 自定义词典 ──────────────────────
# jieba 默认词典对修真文常用词切分不够准, 这里加补充
# 用较高 freq 提高优先级 (默认 0 容易被默认词典覆盖)
_CUSTOM_WORDS = [
    "修真", "修仙", "修魔", "修佛", "境界", "炼气", "筑基", "金丹", "元婴", "化神",
    "渡劫", "飞升", "宗门", "长老", "掌门", "弟子", "剑修", "道侣", "洞府", "灵根",
    "秘笈", "法宝", "神识", "灵力", "丹田", "经脉", "前世", "今生", "来世",
    "师父", "徒弟", "师兄", "师弟", "师姐", "师妹", "魔尊", "妖王", "仙尊",
    "对峙", "离别", "暧昧", "反转", "重逢", "隐瞒", "回忆杀", "打脸", "反杀",
    "悬疑", "推理", "密室", "叙述性诡计", "童年阴影", "双重人格",
    "古言", "宫廷", "宅斗", "宫斗", "王爷", "侯爷", "夫人", "侯府",
    "都市", "职场", "总裁", "霸总", "灰姑娘", "老同学",
    "科幻", "末世", "机甲", "星际", "穿越", "重生",
]
for _w in _CUSTOM_WORDS:
    jieba.add_word(_w, freq=10000, tag="n")

# 关键短语 (jieba 容易把 "修真 + 的" 切成 "修 + 真的" 之类)
# suggest_freq 返回的 freq 用上, 强制合并
_KEY_PHRASES = [
    "修真的", "修真者", "修真人", "修真界", "修真小说",
    "仙侠文", "仙侠类", "古言文", "古言类", "都市文", "都市类", "悬疑文", "悬疑类",
    "宫廷剧", "宅斗剧", "宫斗剧",
]
for _p in _KEY_PHRASES:
    jieba.suggest_freq(_p, tune=True)

from app.knowledge import (
    BUILTIN_DIR,
    INDEX_DIR,
    LOCAL_DIR,
    PRESET_CATEGORIES,
    RETRIEVAL_CATEGORIES,
    INDEX_RETRIEVAL_CATEGORIES,
    SOURCE_BUILTIN,
    KnowledgeDoc,
    read_doc,
    scan_category,
)

_logger = logging.getLogger("NovelWriter.bm25")

# ────────────────────── 停用词 ──────────────────────
# ~120 个常用中文停用词 + 标点 + 英文 (节省内存, 不全)
STOPWORDS_ZH = frozenset("""
的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好
自己 这 那 但 还 把 里有 做 让 什么 只 没 出 给 从 当 跟 与 及 或 以 及 由 至 为 被
让 被 为 因 被 为 因 因 因 因 因
啊 吧 呢 嗯 哦 哈 呀 哎 嘿 哇 嘛 咯 啦 嘞
他 她 它 们 这 那 谁 什么 哪 怎么 怎样
把 被 给 让 叫 让
""".split())

STOPWORDS_PUNCT = frozenset("，。！？、；：\"\"''（）()【】《》…—·-——/\n\r\t .,!?;:\"'()[]{}<>\\") 

STOPWORDS_EN = frozenset("""
a an the is are was were be been being have has had do does did will would shall should
can could may might must need dare ought to of in on at by for with from as into about
and or but if then else when while until than this that these those it its they them
""".split())

STOPWORDS = STOPWORDS_ZH | STOPWORDS_PUNCT | STOPWORDS_EN


# ────────────────────── 数据类 ──────────────────────

@dataclass
class BM25Hit:
    """一次 BM25 检索命中。"""
    doc_id: int
    score: float
    snippet: str              # 命中文本片段 (前 80 字)


@dataclass
class BM25Index:
    """BM25 倒排索引 (内存态)。"""
    docs: list[list[str]] = field(default_factory=list)        # 文档分词后
    doc_ids: list[str] = field(default_factory=list)          # 文档 ID (与 docs 一一对应)
    doc_meta: dict[str, dict] = field(default_factory=dict)   # id -> {category, genre, name, source}
    df: Counter = field(default_factory=Counter)              # 词项 → 文档数
    avgdl: float = 0.0
    k1: float = 1.5
    b: float = 0.75
    created_at: float = field(default_factory=time.time)

    @property
    def N(self) -> int:
        return len(self.docs)

    def add(self, doc_id: str, tokens: list[str], meta: Optional[dict] = None) -> None:
        """添加一篇文档 (分词后)。"""
        if doc_id in self.doc_ids:
            # 重建: 删旧加新
            self.remove(doc_id)
        self.docs.append(tokens)
        self.doc_ids.append(doc_id)
        for t in set(tokens):
            self.df[t] += 1
        self._update_avgdl()
        if meta:
            self.doc_meta[doc_id] = meta

    def remove(self, doc_id: str) -> bool:
        """移除一篇。返回是否成功。"""
        if doc_id not in self.doc_ids:
            return False
        idx = self.doc_ids.index(doc_id)
        old_tokens = self.docs.pop(idx)
        self.doc_ids.pop(idx)
        for t in set(old_tokens):
            self.df[t] -= 1
            if self.df[t] <= 0:
                del self.df[t]
        self.doc_meta.pop(doc_id, None)
        self._update_avgdl()
        return True

    def _update_avgdl(self) -> None:
        if not self.docs:
            self.avgdl = 0.0
            return
        self.avgdl = sum(len(d) for d in self.docs) / len(self.docs)

    def _idf(self, term: str) -> float:
        n = self.df.get(term, 0)
        # 标准 BM25 IDF (加 1 防止负值)
        return math.log((self.N - n + 0.5) / (n + 0.5) + 1.0)

    def score(self, query_tokens: list[str]) -> list[tuple[str, float]]:
        """
        对所有文档打分。
        返回 [(doc_id, score), ...] (仅含 > 0)
        """
        if not self.docs or not query_tokens:
            return []
        out: list[tuple[str, float]] = []
        for i, doc_tokens in enumerate(self.docs):
            doc_id = self.doc_ids[i]
            doc_len = len(doc_tokens)
            if doc_len == 0:
                continue
            tf = Counter(doc_tokens)
            s = 0.0
            for q in query_tokens:
                if q not in tf:
                    continue
                f = tf[q]
                idf = self._idf(q)
                num = f * (self.k1 + 1)
                den = f + self.k1 * (1 - self.b + self.b * doc_len / max(self.avgdl, 1e-6))
                s += idf * (num / den)
            if s > 0:
                out.append((doc_id, s))
        return out

    def top_k(
        self,
        query_tokens: list[str],
        k: int = 5,
        genre: Optional[str] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
        agent: Optional[str] = None,
        doc_type: Optional[str] = None,
    ) -> list[BM25Hit]:
        """
        取 top-k。
        genre/category/source/agent/doc_type 可选过滤。
        """
        scored = self.score(query_tokens)
        # 后置过滤
        if genre or category or source or agent or doc_type:
            kept = []
            for doc_id, sc in scored:
                meta = self.doc_meta.get(doc_id, {})
                if genre and meta.get("genre") != genre:
                    continue
                if category and meta.get("category") != category:
                    continue
                if source and meta.get("source") != source:
                    continue
                if agent:
                    from app.knowledge import agent_in_partition
                    if not agent_in_partition(meta.get("agent", ""), agent):
                        continue
                if doc_type and meta.get("doc_type") != doc_type:
                    continue
                kept.append((doc_id, sc))
            scored = kept
        scored.sort(key=lambda x: x[1], reverse=True)
        out: list[BM25Hit] = []
        for doc_id, sc in scored[:k]:
            meta = self.doc_meta.get(doc_id, {})
            snippet = meta.get("snippet", "")[:80]
            out.append(BM25Hit(doc_id=doc_id, score=sc, snippet=snippet))
        return out


# ────────────────────── 分词 ──────────────────────

# 匹配中文 / 英文单词 / 数字 (3 类)
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z]+|\d+", re.UNICODE)


def tokenize(text: str, use_jieba: bool = True) -> list[str]:
    """
    分词。
    - 中文: 优先 jieba 精确模式 (再过滤停用词)
    - 英文 / 数字: 单独提取
    - 全部小写化

    后处理: 把"修真的""仙侠的"等常见合并词拆开, 让核心词能被检索到
    """
    if not text:
        return []
    text = text.lower()
    if use_jieba:
        # jieba 直接对全文本切
        raw = list(jieba.cut(text, cut_all=False))
    else:
        # 字符级 (1 字 1 token, 不推荐但作为兜底)
        raw = _TOKEN_RE.findall(text)

    # 后处理: 拆"X的"为"X"+"的" (修真/仙侠/古言 等核心词)
    # 这样 "修真" 能被独立检索到
    expanded: list[str] = []
    _SPLIT_XDE = re.compile(
        r"^(修真|修仙|仙侠|古言|都市|悬疑|科幻|魔尊|仙尊|反派|主角|故事|对白|桥段|文风|语料)"
        r"(的|是|了|在|也|都|有|和|与|或)$"
    )
    for t in raw:
        m = _SPLIT_XDE.match(t)
        if m:
            expanded.append(m.group(1))
            expanded.append(m.group(2))
        else:
            expanded.append(t)

    out: list[str] = []
    for t in expanded:
        t = t.strip()
        if not t or t in STOPWORDS:
            continue
        # 过滤纯标点
        if all(c in STOPWORDS_PUNCT for c in t):
            continue
        # 长度过滤 (中文 1 字词常为停用词, 2+ 字更有意义)
        if len(t) == 1 and not _TOKEN_RE.match(t):
            continue
        out.append(t)
    return out


# ────────────────────── 构造 / 持久化 ──────────────────────

# 索引文件路径 (pickle)
INDEX_FILE = INDEX_DIR / "bm25.pkl"


def _doc_to_id(doc: KnowledgeDoc) -> str:
    return f"{doc.source}/{doc.category}/{doc.name}"


def _doc_to_snippet(doc: KnowledgeDoc, max_chars: int = 80) -> str:
    """截取 doc.content 的前 max_chars 字, 去掉 frontmatter。"""
    text = doc.content
    if text.startswith("---"):
        # 跳过 frontmatter
        end = text.find("\n---\n", 3)
        if end != -1:
            text = text[end + 5:]
    text = text.strip().replace("\n", " ")
    return text[:max_chars]


def build_from_knowledge(
    *,
    source: str = "all",       # "all" / "builtin" / "local"
    for_retrieval: bool = True,
) -> BM25Index:
    """
    从 app/knowledge/ 扫描所有 MD, 构 BM25 索引。
    for_retrieval=True → 只取 文风+桥段 ∪ Agent 类 (索引纳入检索范围)
    """
    idx = BM25Index()
    sources = (SOURCE_BUILTIN, LOCAL_DIR.name) if source == "all" else (source,)
    for src in sources:
        for cat in PRESET_CATEGORIES:
            if for_retrieval and cat not in INDEX_RETRIEVAL_CATEGORIES:
                continue
            docs = scan_category(cat, src)
            for d in docs:
                tokens = tokenize(d.content)
                idx.add(
                    doc_id=_doc_to_id(d),
                    tokens=tokens,
                    meta={
                        "name": d.name,
                        "category": d.category,
                        "source": d.source,
                        "genre": d.genre,
                        "tags": d.tags,
                        "agent": d.agent,
                        "doc_type": d.doc_type,
                        "snippet": _doc_to_snippet(d),
                    },
                )
    _logger.info("BM25 索引构建: N=%d, 词汇表=%d, avgdl=%.1f",
                 idx.N, len(idx.df), idx.avgdl)
    return idx


def save(idx: BM25Index, path: Optional[Path] = None) -> Path:
    """持久化到 pickle。"""
    p = path or INDEX_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        pickle.dump(idx, f, protocol=pickle.HIGHEST_PROTOCOL)
    _logger.info("BM25 索引已保存: %s (N=%d)", p, idx.N)
    return p


def load(path: Optional[Path] = None) -> Optional[BM25Index]:
    """
    加载 pickle 索引。
    文件不存在返回 None (需先 build)。
    """
    p = path or INDEX_FILE
    if not p.exists():
        return None
    try:
        with open(p, "rb") as f:
            idx = pickle.load(f)
        _logger.info("BM25 索引已加载: %s (N=%d)", p, idx.N)
        return idx
    except Exception as e:
        _logger.warning("加载 BM25 索引失败: %s (需重建)", e)
        return None


# ────────────────────── 主入口 ──────────────────────

def search(
    query: str,
    *,
    top_k: int = 5,
    genre: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    agent: Optional[str] = None,
    doc_type: Optional[str] = None,
    idx: Optional[BM25Index] = None,
) -> list[BM25Hit]:
    """
    一站式检索。
    优先用传入的 idx, 否则从 pickle 加载, 否则现场 build (仅 builtin 文风+桥段)。
    """
    if idx is None:
        idx = load() or build_from_knowledge()
    if not query.strip():
        return []
    q_tokens = tokenize(query)
    return idx.top_k(q_tokens, k=top_k, genre=genre, category=category,
                     source=source, agent=agent, doc_type=doc_type)


def rebuild() -> BM25Index:
    """重建 + 保存。返回新索引。"""
    idx = build_from_knowledge()
    save(idx)
    return idx


# ────────────────────── CLI 测试入口 ──────────────────────

if __name__ == "__main__":
    import json as _json
    print("=== 重建 BM25 索引 ===")
    idx = rebuild()
    print(f"N={idx.N}, vocab={len(idx.df)}, avgdl={idx.avgdl:.1f}")
    print()
    test_queries = ["修真", "反派", "古言宫廷", "密室", "总裁反杀"]
    for q in test_queries:
        print(f"\nQuery: {q!r}")
        hits = search(q, top_k=3, idx=idx)
        for h in hits:
            print(f"  - {h.doc_id}  score={h.score:.3f}  snippet={h.snippet!r}")
