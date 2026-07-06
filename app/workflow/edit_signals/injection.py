"""
app/workflow/edit_signals/injection.py

Layer 5: 软提示注入 (Skill Injector) ⭐

3 道防污染:
  1. BM25 相关性: chapter content × candidate pattern_hint
  2. chapter 范围: 同 genre / 同 source_chapters 重合
  3. 新鲜度: 30 天内有活动

3 道不影响写手:
  1. 软提示 (per-candidate 采纳/反例按钮)
  2. per-chapter 关 (chapter meta 写 no_inject)
  3. 反例化按钮 (标 uncertain)

可选 prompt_assembler 注入: settings.signal_inject_to_prompt=true 时
把 [📚 项目内参考] 段塞进 writer prompt (opt-in).
"""
from __future__ import annotations
import logging
import re
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from .models import (
    CandidateSkill, SidecarEntry,
    SKILL_CANDIDATE_STATE, SKILL_PROVEN_STATE, SKILL_BUILTIN_STATE,
    SKILL_UNCERTAIN_STATE, SkillState,
)
from .jsonl_store import (
    CandidateStore, SidecarStore, JSONLStore, get_project_dir,
)

_logger = logging.getLogger("NovelWriter.edit_signals.injection")

# Hard cap (v3.0 §20.2)
INJECT_MAX_SKILLS = 3
INJECT_MAX_TOKENS = 500
INJECT_FRESH_DAYS = 30
INJECT_SAME_GENRE_ONLY = True
UNCERTAIN_PENALTY = 0.3                  # uncertain 降权 (排到 top-K 之外)


# ────────────────────── token 估算 ──────────────────────

def estimate_tokens(text: str) -> int:
    """粗略估算: 1 字符 ≈ 1.5 token (中文, 沿用 prompt_assembler 比例)."""
    return int(len(text or "") * 1.5)


# ────────────────────── BM25 简易版 (无 jieba 依赖) ──────────────────────

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+", re.UNICODE)
_ASCII_RE = re.compile(r"[A-Za-z]+|\d+", re.UNICODE)

# 极小停用词 (避免噪音)
_STOPWORDS = frozenset("""
的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好
这 那 但 还 把 里有 做 让 什么 只 没 出 给 从 当 跟 与 及 或
""".split())


def _tokenize(text: str) -> list[str]:
    """轻量分词: CJK 用 2-gram + ASCII 整词. 无 jieba 依赖.

    例: "他走进屋子" → ["他走", "走进", "屋子"]
    例: "Hello world" → ["hello", "world"]
    """
    if not text:
        return []
    out: list[str] = []
    # CJK 段: 切 2-gram
    for m in _CJK_RE.finditer(text):
        s = m.group()
        if len(s) == 1:
            tok = s  # 单字也保留
            if tok not in _STOPWORDS:
                out.append(tok)
        else:
            for i in range(len(s) - 1):
                bg = s[i:i + 2]
                if bg not in _STOPWORDS:
                    out.append(bg)
    # ASCII 段: 整词
    for m in _ASCII_RE.finditer(text.lower()):
        t = m.group()
        if t in _STOPWORDS or len(t) < 2:
            continue
        out.append(t)
    return out


def bm25_score_simple(query: str, doc: str) -> float:
    """简化版 BM25 (单 doc vs 单 query), 用于 in-memory 排序.

    不做 IDF 精度, 用一个轻量近似:
      - q 出现次数 × 1
      - 文档越短权重越高 (类似短文档 BM25 行为)
    """
    q_toks = _tokenize(query)
    d_toks = _tokenize(doc)
    if not q_toks or not d_toks:
        return 0.0
    tf = Counter(d_toks)
    dl = len(d_toks)
    s = 0.0
    for q in q_toks:
        f = tf.get(q, 0)
        if f <= 0:
            continue
        # BM25 简化: k1=1.5, b=0.75
        num = f * (1.5 + 1)
        den = f + 1.5 * (1 - 0.75 + 0.75 * dl / 100.0)
        s += num / den
    return s


# ────────────────────── 过滤 (3 道防污染) ──────────────────────

def _is_fresh(entry: dict, *, days: int = INJECT_FRESH_DAYS, now: Optional[float] = None) -> bool:
    last = float(entry.get("last_activity_at", 0) or 0)
    if not last:
        return True
    cur = now if now is not None else time.time()
    return (cur - last) < days * 86400


def _same_genre(candidate: dict, chapter: dict) -> bool:
    """chapter 与 candidate 的 genre 是否一致 (无 genre 时宽松)."""
    if not INJECT_SAME_GENRE_ONLY:
        return True
    chap_genre = (chapter.get("genre") or "").strip()
    cand_genres = candidate.get("source_chapter_genres") or []
    if not chap_genre or not cand_genres:
        return True
    return chap_genre in cand_genres


def _in_source_chapter(candidate: dict, chapter_id) -> bool:
    """candidate 是否来自同/相邻章节 (防冷门污染)."""
    sources = candidate.get("source_chapters", []) or []
    if not sources:
        return True
    return chapter_id in sources


# ────────────────────── 主入口: select_skills_for_chapter ──────────────────────

def select_skills_for_chapter(
    chapter: dict,
    candidates: list[dict],
    sidecar: Optional[dict] = None,
    *,
    max_skills: int = INJECT_MAX_SKILLS,
    max_tokens: int = INJECT_MAX_TOKENS,
    fresh_days: int = INJECT_FRESH_DAYS,
    now: Optional[float] = None,
) -> list[dict]:
    """给 chapter 选 top-K 相关 + 有用 Skill (Layer 5 §21.2).

    流程:
      1. 过滤: state 必须是 active/proven/builtin (排除 stale/archived/uncertain 优先)
      2. 新鲜度: 30 天内有活动
      3. chapter 范围: 同 genre / 同 source_chapter
      4. BM25 相关性: top-K
      5. token 截断

    Returns:
        选中的候选 dict 列表, 每条带 _inject_score 字段
    """
    sidecar = sidecar or {}
    chapter_text = (chapter.get("content") or chapter.get("title") or "")[:2000]
    chapter_id = str(chapter.get("id") or chapter.get("chapter_id") or "")

    # 1. 状态过滤
    active_states = {SKILL_CANDIDATE_STATE, SKILL_PROVEN_STATE, SKILL_BUILTIN_STATE, "active", "proven", "builtin"}
    pool = []
    for c in candidates:
        st = c.get("state", SKILL_CANDIDATE_STATE)
        if st in (SKILL_STALE := SkillState.STALE, SkillState.ARCHIVED):
            continue
        if st not in active_states:
            continue
        # uncertain 仍进, 但降权
        pool.append(c)
    if not pool:
        return []

    # 2. 新鲜度
    if sidecar:
        pool = [
            c for c in pool
            if _is_fresh(sidecar.get(c.get("name"), {}), days=fresh_days, now=now)
        ]
    if not pool:
        return []

    # 3. chapter 范围 (genre 宽松, source_chapter 严)
    pool = [c for c in pool if _in_source_chapter(c, chapter_id) and _same_genre(c, chapter)]
    if not pool:
        return []

    # 4. BM25 相关性打分
    scored: list[tuple[dict, float]] = []
    for c in pool:
        hint = c.get("generalized_rule") or c.get("pattern_hint") or c.get("name", "")
        score = bm25_score_simple(chapter_text, hint)
        # uncertain 降权
        if c.get("state") == SKILL_UNCERTAIN_STATE:
            score *= UNCERTAIN_PENALTY
        # builtin / proven 微加成 (信任度)
        if c.get("state") == SKILL_BUILTIN_STATE:
            score *= 1.1
        elif c.get("state") == SKILL_PROVEN_STATE:
            score *= 1.05
        if score > 0:
            c2 = dict(c)
            c2["_inject_score"] = score
            scored.append((c2, score))
    scored.sort(key=lambda x: x[1], reverse=True)

    # 5. token 截断
    result: list[dict] = []
    total_tokens = 0
    for cand, score in scored[:max_skills]:
        hint = cand.get("generalized_rule") or cand.get("pattern_hint") or cand.get("name", "")
        tokens = estimate_tokens(hint)
        if total_tokens + tokens > max_tokens:
            break
        result.append(cand)
        total_tokens += tokens
    return result


# ────────────────────── Injector 主类 (集成 Sidecar 读取) ──────────────────────

class SkillInjector:
    """Layer 5 注入器: 包装 select_skills_for_chapter + 集成 sidecar 状态."""

    def __init__(self, project_id):
        self.project_id = project_id
        self.project_dir = get_project_dir(project_id)
        self.cand_store = CandidateStore(self.project_dir)
        self.sidecar = SidecarStore(self.project_dir)

    def select_for_chapter(
        self,
        chapter: dict,
        *,
        max_skills: int = INJECT_MAX_SKILLS,
        max_tokens: int = INJECT_MAX_TOKENS,
    ) -> list[dict]:
        """给章节选 top-K Skill."""
        candidates = self.cand_store.list_all()
        return select_skills_for_chapter(
            chapter=chapter,
            candidates=candidates,
            sidecar=self.sidecar.get_all(),
            max_skills=max_skills,
            max_tokens=max_tokens,
        )

    def build_prompt_segment(
        self,
        chapter: dict,
        *,
        max_skills: int = INJECT_MAX_SKILLS,
        max_tokens: int = INJECT_MAX_TOKENS,
    ) -> str:
        """构建 [📚 项目内参考] prompt 段 (供 prompt_assembler 注入, opt-in)."""
        skills = self.select_for_chapter(chapter, max_skills=max_skills, max_tokens=max_tokens)
        if not skills:
            return ""
        lines = ["[📚 项目内参考]"]
        for s in skills:
            rule = s.get("generalized_rule") or s.get("pattern_hint") or s.get("name", "")
            if rule:
                lines.append(f"- {rule}")
        return "\n".join(lines)

    def on_user_accept(self, name: str) -> None:
        """[采纳] 按钮: use_count++ + touch (last_activity_at=now)."""
        self.sidecar.update(name, use_count=int(self.sidecar.get(name, {}).get("use_count", 0)) + 1)
        # touch 推 last_activity_at
        entry = self.sidecar.get(name) or {}
        entry["last_activity_at"] = time.time()
        entry["activity_count"] = int(entry.get("activity_count", 0)) + 1
        # 自动复活
        st = entry.get("status", "active")
        if st in (SkillState.STALE, SkillState.ARCHIVED):
            entry["status"] = "active"
            entry["state"] = "active"
        self.sidecar.set(name, entry)

    def on_user_reject(self, name: str) -> None:
        """[✗] 按钮: patch_count++ + 标 uncertain + 注入降权."""
        entry = self.sidecar.get(name) or {"name": name}
        entry["patch_count"] = int(entry.get("patch_count", 0)) + 1
        entry["last_patched_at"] = time.time()
        entry["state"] = SKILL_UNCERTAIN_STATE
        entry["status"] = SKILL_UNCERTAIN_STATE
        entry["last_activity_at"] = time.time()
        self.sidecar.set(name, entry)
        # 同步 candidate.state
        for cand in self.cand_store.list_all():
            if cand.get("name") == name:
                cand["state"] = SKILL_UNCERTAIN_STATE
                try:
                    if cand.get("kind") == "anti_pattern":
                        from .models import AntiPattern
                        self.cand_store.save(AntiPattern.from_dict(cand))
                    else:
                        from .models import CandidateSkill
                        self.cand_store.save(CandidateSkill.from_dict(cand))
                except Exception as e:
                    _logger.warning("反例化写回失败 %s: %s", name, e)
                break

    def is_chapter_disabled(self, chapter_meta: Optional[dict]) -> bool:
        """per-chapter 关 (chapter meta 写 no_inject=true)."""
        if not chapter_meta:
            return False
        return bool(chapter_meta.get("no_inject"))

    def disable_for_chapter(self, chapter_meta: dict) -> dict:
        """per-chapter 关: 写到 chapter meta."""
        if not isinstance(chapter_meta, dict):
            chapter_meta = {}
        chapter_meta["no_inject"] = True
        return chapter_meta

    def enable_for_chapter(self, chapter_meta: dict) -> dict:
        if not isinstance(chapter_meta, dict):
            chapter_meta = {}
        chapter_meta["no_inject"] = False
        return chapter_meta
