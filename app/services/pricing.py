"""
A4 定价服务 (Pricing Service)
业务场景: 写一章 3000 字 → 用户问"花了多少钱 / 哪个模型便宜"
  - 显示 "约 ¥0.05" (含"约"字避免误导)
  - 显示 "价格更新于 2026-06-01, 可能与实际有偏差" (避免误信)
  - 估算 token 数 → 算成本

数据源: model_configs (A3 同一张表) - input_price / output_price / price_updated_at
单位约定: USD / 1M tokens (input_price=0.15 → 100 万 input tokens 收 0.15 USD)

设计原则:
  - 价格显示一律加 "约" 字 (即使数据准, 也不能 100% 保证厂商没调价)
  - 必带 "价格更新于 YYYY-MM-DD" + "可能与实际有偏差"
  - 0 价格的模型 (mock / 本地) → 标 "免费"
  - 超过 30 天未更新 → 标 "价格可能过期, 建议核对"
  - 0 tokens 费用 (不调 API) → 0 cost, 仍记录用量
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.db import _impl as _db_conn

_logger = logging.getLogger("NovelWriter.services.pricing")


def _conn():
    return _db_conn.get_conn()


# ============================================================
# 常量
# ============================================================

# 30 天未更新视为"价格可能过期"
STALE_THRESHOLD_DAYS = 30

# USD → CNY 汇率 (固定, 不联网, 4.0 桌面版)
USD_TO_CNY = 7.2

# 偏差提示文案 (供 UI 直接显示)
PRICE_WARNING_TEXT = (
    "价格仅供参考, 可能与实际计费有偏差, 以模型厂商账单为准。\n"
    "本表价格若超过 30 天未更新, 会标黄提示, 建议核对。"
)


# ============================================================
# 数据类型
# ============================================================

@dataclass
class PriceInfo:
    """一个模型的价格信息."""
    model_id: str
    model_name: str
    provider: str
    role: str
    input_price: float = 0.0     # USD / 1M tokens
    output_price: float = 0.0
    price_updated_at: str = ""
    is_free: bool = False        # 两个价都 0
    age_days: int = 0
    is_stale: bool = False       # > STALE_THRESHOLD_DAYS


# ============================================================
# 查
# ============================================================

def _row_to_info(row) -> PriceInfo:
    """从 DB row 构造 PriceInfo (含时效性计算)."""
    updated_at = row["price_updated_at"] or ""
    age = _calc_age_days(updated_at)
    is_free = (row["input_price"] or 0) == 0 and (row["output_price"] or 0) == 0
    return PriceInfo(
        model_id=row["id"],
        model_name=row["model_name"],
        provider=row["provider"],
        role=row["role"] or "primary",
        input_price=row["input_price"] or 0.0,
        output_price=row["output_price"] or 0.0,
        price_updated_at=updated_at,
        is_free=is_free,
        age_days=age,
        is_stale=(age > STALE_THRESHOLD_DAYS),
    )


def _calc_age_days(updated_at: str) -> int:
    """距 updated_at 多少天. 解析失败 → 999 (视为过期)."""
    if not updated_at:
        return 999
    try:
        # SQLite 默认格式: "YYYY-MM-DD HH:MM:SS"
        dt = datetime.strptime(updated_at[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.fromisoformat(updated_at)
        except ValueError:
            return 999
    delta = datetime.now() - dt
    return max(0, delta.days)


def get_price(model_id: str) -> Optional[PriceInfo]:
    """取一个模型的价格信息. None = 不存在."""
    cur = _conn()
    row = cur.execute(
        "SELECT * FROM model_configs WHERE id = ?", (model_id,),
    ).fetchone()
    if not row:
        return None
    return _row_to_info(row)


def list_prices() -> list[PriceInfo]:
    """列出所有模型的价格信息 (primary 在前, 同 role 内按 model_name 排)."""
    cur = _conn()
    rows = cur.execute(
        "SELECT * FROM model_configs "
        "ORDER BY CASE role WHEN 'primary' THEN 0 WHEN 'fallback' THEN 1 ELSE 2 END, model_name",
    ).fetchall()
    return [_row_to_info(r) for r in rows]


def get_enabled_prices() -> list[PriceInfo]:
    """列出启用的模型 (有 api_key + 有价格)."""
    cur = _conn()
    rows = cur.execute(
        "SELECT * FROM model_configs "
        "WHERE api_key != '' AND (input_price > 0 OR output_price > 0) "
        "ORDER BY role, model_name",
    ).fetchall()
    return [_row_to_info(r) for r in rows]


# ============================================================
# 算
# ============================================================

def estimate_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """估算成本 (USD). 无价格 → 0.

    公式: (input_tokens / 1M) * input_price + (output_tokens / 1M) * output_price
    """
    info = get_price(model_id)
    if not info or info.is_free:
        return 0.0
    in_cost = (input_tokens / 1_000_000.0) * info.input_price
    out_cost = (output_tokens / 1_000_000.0) * info.output_price
    return round(in_cost + out_cost, 6)


def estimate_cost_with_prices(
    input_price: float,
    output_price: float,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """纯函数: 给定价格 + tokens 算成本 (供不查 DB 的场景)."""
    in_cost = (input_tokens / 1_000_000.0) * input_price
    out_cost = (output_tokens / 1_000_000.0) * output_price
    return round(in_cost + out_cost, 6)


# ============================================================
# 格式化 (供 UI 显示)
# ============================================================

def format_price_usd(usd: float) -> str:
    """USD → '约 $X.XXXXXX' (足够精度避免 0 显示)."""
    if usd <= 0:
        return "免费"
    if usd < 0.01:
        return f"约 ${usd:.6f}"
    return f"约 ${usd:.4f}"


def format_price_cny(usd: float) -> str:
    """USD → '约 ¥X.XX' (按 USD_TO_CNY 汇率)."""
    if usd <= 0:
        return "免费"
    cny = usd * USD_TO_CNY
    if cny < 0.01:
        return f"约 ¥{cny:.4f}"
    return f"约 ¥{cny:.2f}"


def format_price_per_million(price: float) -> str:
    """单价格式化: '¥0.76 / 1M tokens'."""
    if price <= 0:
        return "免费"
    cny = price * USD_TO_CNY
    return f"¥{cny:.2f} / 1M tokens"


def format_price_info_line(info: PriceInfo) -> str:
    """单行展示: 'GPT-4o mini (openai_compat): ¥1.08/1M 入 + ¥4.32/1M 出, 更新于 2026-06-01'."""
    if info.is_free:
        return f"{info.model_name} ({info.provider}): 免费 (本地/mock)"
    in_str = format_price_per_million(info.input_price)
    out_str = format_price_per_million(info.output_price)
    updated = info.price_updated_at[:10] if info.price_updated_at else "未知"
    stale_tag = " [可能过期]" if info.is_stale else ""
    return f"{info.model_name} ({info.provider}): {in_str} 入 + {out_str} 出, 更新于 {updated}{stale_tag}"


def get_warning_text() -> str:
    """统一偏差提示 (供欢迎页 / tokens 提醒 / 模型列表顶部)."""
    return PRICE_WARNING_TEXT


# ============================================================
# 改
# ============================================================

def update_price(
    model_id: str,
    *,
    input_price: Optional[float] = None,
    output_price: Optional[float] = None,
) -> bool:
    """更新一个模型的价格, 刷新 price_updated_at.

    只更新提供的字段, 其他保留. 返回是否真的更新了.
    """
    cur = _conn()
    row = cur.execute(
        "SELECT id FROM model_configs WHERE id = ?", (model_id,),
    ).fetchone()
    if not row:
        return False

    sets = []
    args = []
    if input_price is not None:
        sets.append("input_price = ?")
        args.append(float(input_price))
    if output_price is not None:
        sets.append("output_price = ?")
        args.append(float(output_price))
    if not sets:
        return False
    sets.append("price_updated_at = datetime('now')")
    args.append(model_id)
    cur.execute(
        f"UPDATE model_configs SET {', '.join(sets)} WHERE id = ?",
        args,
    )
    cur.commit()
    return True


def list_stale_models(*, threshold_days: int = STALE_THRESHOLD_DAYS) -> list[PriceInfo]:
    """列出超 threshold_days 未更新的模型 (供 UI 标黄)."""
    all_p = list_prices()
    return [p for p in all_p if p.is_stale and threshold_days > 0 and p.age_days >= threshold_days]


# ============================================================
# 时间窗口统计 (供 A4 仪表盘)
# ============================================================

def cost_summary_by_model(
    project_id: Optional[str] = None,
    *, days: int = 30,
) -> list[dict]:
    """最近 N 天按模型分组的成本 (来自 usage_records, 需先有数据)."""
    cur = _conn()
    # 计算截止时间戳 (简化: 用 N 天前的日期)
    cutoff = datetime.now()
    try:
        from datetime import timedelta
        cutoff_dt = cutoff - timedelta(days=days)
        cutoff_str = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        cutoff_str = "1970-01-01"

    if project_id:
        rows = cur.execute(
            "SELECT model, SUM(tokens_in) AS ti, SUM(tokens_out) AS to_, SUM(cost) AS c, COUNT(*) AS n "
            "FROM usage_records WHERE project_id = ? AND created_at >= ? "
            "GROUP BY model ORDER BY c DESC",
            (project_id, cutoff_str),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT model, SUM(tokens_in) AS ti, SUM(tokens_out) AS to_, SUM(cost) AS c, COUNT(*) AS n "
            "FROM usage_records WHERE created_at >= ? "
            "GROUP BY model ORDER BY c DESC",
            (cutoff_str,),
        ).fetchall()
    return [
        {
            "model": r["model"] or "未知",
            "tokens_in": int(r["ti"] or 0),
            "tokens_out": int(r["to_"] or 0),
            "cost_usd": float(r["c"] or 0.0),
            "calls": int(r["n"] or 0),
        }
        for r in rows
    ]
