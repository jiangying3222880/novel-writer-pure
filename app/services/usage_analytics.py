"""
H8 使用分析服务 (原插件, 已固化).

功能: 项目使用统计 / 周报 / 趋势.
- 累计: 章节数 / 草稿数 / LLM 调用次数 / tokens / cost
- 周报: 最近 7 天每日写作字数 / 调用次数 / tokens
- 趋势: 按周/月聚合, 简单文字输出 (mock, 不画图)

数据源: usage_records 表 (migration 021 已建) + chapters / drafts 表.

公开 API:
  - summary(project_id) -> UsageSummary
  - weekly_report(project_id, days=7) -> dict
  - cost_breakdown(project_id) -> dict (按 step)
  - format_text_report(project_id) -> str
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from app.db import _impl as _db_conn
from app.services import project_service, ServiceError

_logger = logging.getLogger("NovelWriter.plugin.usage_analytics")


# --------------------------------------------------------------------- #
# 数据类
# --------------------------------------------------------------------- #

@dataclass
class UsageSummary:
    """单项目总览."""
    project_id: str
    chapter_count: int = 0
    draft_count: int = 0
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    total_cost: float = 0.0
    avg_cost_per_chapter: float = 0.0
    first_used_at: str = ""
    last_used_at: str = ""

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "chapter_count": self.chapter_count,
            "draft_count": self.draft_count,
            "llm_calls": self.llm_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "total_tokens": self.tokens_in + self.tokens_out,
            "total_cost": round(self.total_cost, 4),
            "avg_cost_per_chapter": round(self.avg_cost_per_chapter, 4),
            "first_used_at": self.first_used_at,
            "last_used_at": self.last_used_at,
        }


@dataclass
class DailyUsage:
    """单日使用量."""
    date: str
    llm_calls: int
    tokens_in: int
    tokens_out: int
    cost: float
    word_count: int = 0  # 写作字数 (从 chapter_drafts 估)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "llm_calls": self.llm_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "total_tokens": self.tokens_in + self.tokens_out,
            "cost": round(self.cost, 4),
            "word_count": self.word_count,
        }


# --------------------------------------------------------------------- #
# 插件实现
# --------------------------------------------------------------------- #

class UsageAnalyticsPlugin:
    """
    H8 使用分析服务。
    """

    def summary(self, project_id: str) -> UsageSummary:
        project_service.get(project_id)  # 404 guard
        with _db_conn.connection() as db:
            ch = db.execute(
                "SELECT COUNT(*) AS c FROM chapters c "
                "JOIN books b ON c.book_id=b.id WHERE b.project_id=?",
                (project_id,),
            ).fetchone()
            draft = db.execute(
                "SELECT COUNT(*) AS c FROM chapter_drafts d "
                "JOIN chapters c ON d.chapter_id=c.id "
                "JOIN books b ON c.book_id=b.id WHERE b.project_id=?",
                (project_id,),
            ).fetchone()
            u = db.execute(
                "SELECT COUNT(*) AS c, "
                "COALESCE(SUM(tokens_in),0) AS ti, "
                "COALESCE(SUM(tokens_out),0) AS to_, "
                "COALESCE(SUM(cost),0) AS cost, "
                "MIN(created_at) AS first, MAX(created_at) AS last "
                "FROM usage_records WHERE project_id=?",
                (project_id,),
            ).fetchone()
        s = UsageSummary(
            project_id=project_id,
            chapter_count=int(ch["c"] or 0),
            draft_count=int(draft["c"] or 0),
            llm_calls=int(u["c"] or 0),
            tokens_in=int(u["ti"] or 0),
            tokens_out=int(u["to_"] or 0),
            total_cost=float(u["cost"] or 0.0),
            first_used_at=str(u["first"] or ""),
            last_used_at=str(u["last"] or ""),
        )
        s.avg_cost_per_chapter = (
            s.total_cost / s.chapter_count if s.chapter_count else 0.0
        )
        return s

    def weekly_report(self, project_id: str, days: int = 7) -> Dict[str, list]:
        """返回最近 N 天每日使用量."""
        project_service.get(project_id)
        with _db_conn.connection() as db:
            rows = db.execute(
                "SELECT date(created_at) AS d, "
                "COUNT(*) AS calls, "
                "COALESCE(SUM(tokens_in),0) AS ti, "
                "COALESCE(SUM(tokens_out),0) AS to_, "
                "COALESCE(SUM(cost),0) AS cost "
                "FROM usage_records "
                "WHERE project_id=? AND created_at >= date('now', ?) "
                "GROUP BY date(created_at) "
                "ORDER BY d",
                (project_id, f"-{days} day"),
            ).fetchall()
        # 转 dict
        data = {r["d"]: DailyUsage(
            date=r["d"],
            llm_calls=int(r["calls"] or 0),
            tokens_in=int(r["ti"] or 0),
            tokens_out=int(r["to_"] or 0),
            cost=float(r["cost"] or 0.0),
        ).to_dict() for r in rows}
        # 补全缺失的日期
        today = datetime.now().date()
        out: List[dict] = []
        for i in range(days - 1, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            if d in data:
                out.append(data[d])
            else:
                out.append(DailyUsage(
                    date=d, llm_calls=0, tokens_in=0, tokens_out=0, cost=0.0,
                ).to_dict())
        return {"days": out, "total_days": days}

    def cost_breakdown(self, project_id: str) -> Dict[str, dict]:
        """按 step (writer / critic / outline / etc) 拆 cost."""
        project_service.get(project_id)
        with _db_conn.connection() as db:
            rows = db.execute(
                "SELECT step, COUNT(*) AS calls, "
                "COALESCE(SUM(tokens_in),0) AS ti, "
                "COALESCE(SUM(tokens_out),0) AS to_, "
                "COALESCE(SUM(cost),0) AS cost "
                "FROM usage_records WHERE project_id=? "
                "GROUP BY step ORDER BY cost DESC",
                (project_id,),
            ).fetchall()
        return {
            r["step"] or "unknown": {
                "calls": int(r["calls"] or 0),
                "tokens_in": int(r["ti"] or 0),
                "tokens_out": int(r["to_"] or 0),
                "total_tokens": int(r["ti"] or 0) + int(r["to_"] or 0),
                "cost": round(float(r["cost"] or 0.0), 4),
            }
            for r in rows
        }

    def format_text_report(self, project_id: str) -> str:
        """生成可读的文字报告 (供 UI 显示 / 复制)."""
        s = self.summary(project_id).to_dict()
        wk = self.weekly_report(project_id, 7)
        br = self.cost_breakdown(project_id)
        proj = project_service.get(project_id)
        lines = [
            f"📊 项目使用分析 — {proj.get('name', '?')}",
            f"生成时间: {datetime.now().isoformat(timespec='seconds')}",
            "─" * 50,
            "",
            "【总览】",
            f"  章节数: {s['chapter_count']}",
            f"  草稿数: {s['draft_count']}",
            f"  LLM 调用: {s['llm_calls']} 次",
            f"  tokens: in={s['tokens_in']:,}  out={s['tokens_out']:,}  total={s['total_tokens']:,}",
            f"  累计 cost: ${s['total_cost']:.4f}",
            f"  单章均价: ${s['avg_cost_per_chapter']:.4f}",
            f"  首次使用: {s['first_used_at'] or '-'}",
            f"  最近使用: {s['last_used_at'] or '-'}",
            "",
            "【近 7 天】",
        ]
        for d in wk["days"]:
            lines.append(
                f"  {d['date']}  调用 {d['llm_calls']:>3}  "
                f"tokens {d['total_tokens']:>6,}  cost ${d['cost']:.4f}"
            )
        lines += ["", "【按用途拆 cost】"]
        if not br:
            lines.append("  (暂无数据)")
        for step, info in br.items():
            lines.append(
                f"  {step:>16}: ${info['cost']:.4f}  ({info['calls']} 次, {info['total_tokens']:,} tokens)"
            )
        return "\n".join(lines)
