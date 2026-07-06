"""
仪表盘数据汇总 (Phase 3 M3).

从 chapters / chapter_drafts / chapter_change_log 聚合:
  - 总章节数 / 总字数
  - 平均 critic 分 / 平均 hook 分
  - 趋势 (按 chapter_no 升序) - 每章 critic_score, hook_score
  - Top 5 弱章 (综合分最低)

输入: project_id
输出: dict {
  "summary": {chapter_count, total_words, avg_critic_score, avg_hook_score},
  "trend":   [{"chapter_no": int, "title": str, "critic_score": int, "hook_score": int, "review_flag": str}],
  "weak_chapters": [...]   # 综合分 = critic*0.5 + hook*0.5, 升序, 最多 5
}
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from app.db import _impl as _db_conn
from app.services import chapter_service, book_service, project_service

log = logging.getLogger(__name__)


def _parse_critic_score(critique_json: Optional[str]) -> Optional[int]:
    """从 chapters.critique JSON 抠 critic.score."""
    if not critique_json:
        return None
    try:
        d = json.loads(critique_json)
        if isinstance(d, dict) and "score" in d:
            return int(d["score"])
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return None


def _parse_hook_score(hook_json: Optional[str]) -> Optional[int]:
    if not hook_json:
        return None
    try:
        d = json.loads(hook_json)
        if isinstance(d, dict) and "score" in d:
            return int(d["score"])
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return None


def _combined_score(critic: Optional[int], hook: Optional[int]) -> Optional[float]:
    """综合分 = critic * 0.5 + hook * 0.5. 任一缺失 -> 只用另一项 (×1)."""
    if critic is None and hook is None:
        return None
    if critic is None:
        return float(hook)
    if hook is None:
        return float(critic)
    return (critic + hook) / 2.0


def collect(project_id: str) -> dict:
    """拉全书数据, 聚合仪表盘."""
    project_service.get(project_id)  # 404 guard
    # 1. 找所有 books 的所有 chapters
    with _db_conn.connection() as conn:
        rows = conn.execute(
            """SELECT c.id, c.chapter_no, c.title, c.word_count, c.review_flag,
                      c.critique, c.final
               FROM chapters c
               JOIN books b ON c.book_id = b.id
               WHERE b.project_id = ?
               ORDER BY b.volume_no, c.chapter_no""",
            (project_id,),
        ).fetchall()

    chapters = [dict(r) for r in rows]
    if not chapters:
        return {
            "summary": {
                "chapter_count": 0, "total_words": 0,
                "avg_critic_score": None, "avg_hook_score": None,
            },
            "trend": [], "weak_chapters": [],
        }

    # 2. 解析每章 critic / hook 分
    trend: list[dict] = []
    critic_scores: list[int] = []
    hook_scores: list[int] = []
    for ch in chapters:
        critic = _parse_critic_score(ch.get("critique"))
        # hook 也存在 chapters.critique 里 (json 里有 hook_score 字段) 或者单独的列
        # 这里约定: chapters.critique 同时存 critic + hook 一起, hook 字段叫 "hook_score"
        # 若没存, 留 None
        try:
            if ch.get("critique"):
                d = json.loads(ch["critique"])
                hook = d.get("hook_score") if isinstance(d, dict) else None
            else:
                hook = None
        except (json.JSONDecodeError, TypeError):
            hook = None
        hook = int(hook) if hook is not None else None
        word_count = int(ch.get("word_count") or 0)
        trend.append({
            "chapter_no": ch.get("chapter_no"),
            "title": ch.get("title") or "",
            "critic_score": critic,
            "hook_score": hook,
            "word_count": word_count,
            "review_flag": ch.get("review_flag") or "pending",
        })
        if critic is not None:
            critic_scores.append(critic)
        if hook is not None:
            hook_scores.append(hook)

    total_words = sum(c.get("word_count", 0) for c in chapters)
    avg_critic = sum(critic_scores) / len(critic_scores) if critic_scores else None
    avg_hook = sum(hook_scores) / len(hook_scores) if hook_scores else None

    # 3. Top 5 弱章
    scored = []
    for entry in trend:
        combined = _combined_score(entry["critic_score"], entry["hook_score"])
        if combined is not None:
            scored.append({
                "chapter_no": entry["chapter_no"],
                "title": entry["title"],
                "critic_score": entry["critic_score"],
                "hook_score": entry["hook_score"],
                "combined": combined,
            })
    scored.sort(key=lambda e: e["combined"])
    weak = scored[:5]

    # 4. 写作 KPI (来自 usage_records, step='write' 的累计)
    try:
        with _db_conn.connection() as conn:
            kpi_row = conn.execute(
                """SELECT
                       COALESCE(SUM(tokens_in), 0) AS total_tokens_in,
                       COALESCE(SUM(tokens_out), 0) AS total_tokens_out,
                       COALESCE(SUM(cost), 0.0) AS total_cost,
                       COALESCE(SUM(duration_ms), 0) AS total_duration_ms,
                       COUNT(*) AS call_count
                   FROM usage_records
                   WHERE project_id = ? AND step = 'write'""",
                (project_id,),
            ).fetchone()
        writing_kpi = {
            "total_tokens_in": int(kpi_row["total_tokens_in"]),
            "total_tokens_out": int(kpi_row["total_tokens_out"]),
            "total_cost": round(float(kpi_row["total_cost"]), 4),
            "total_duration_ms": int(kpi_row["total_duration_ms"]),
            "call_count": int(kpi_row["call_count"]),
        }
    except Exception as e:
        log.warning("[dashboard_service] writing_kpi query failed: %s", e)
        writing_kpi = {
            "total_tokens_in": 0, "total_tokens_out": 0,
            "total_cost": 0.0, "total_duration_ms": 0, "call_count": 0,
        }

    return {
        "summary": {
            "chapter_count": len(chapters),
            "total_words": total_words,
            "avg_critic_score": round(avg_critic, 1) if avg_critic is not None else None,
            "avg_hook_score": round(avg_hook, 1) if avg_hook is not None else None,
        },
        "trend": trend,
        "weak_chapters": weak,
        "writing_kpi": writing_kpi,
    }
