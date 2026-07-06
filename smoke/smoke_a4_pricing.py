"""
A4 SMOKE: 定价服务 (Pricing Service)
- get_price / list_prices
- estimate_cost
- format_price_usd / cny / per_million
- format_price_info_line
- update_price + 价格时效
- get_warning_text
- cost_summary_by_model

5 分钟自动超时
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

# stdout UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 5 分钟全局超时
_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_a4_pricing 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 隔离真实数据
# ============================================================

TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_a4_"))
DB_PATH = TMPDIR / "test.db"
STORY_DIR = TMPDIR / "story"
STORY_DIR.mkdir(parents=True, exist_ok=True)

import app.app_paths
app.app_paths.sqlite_path = lambda: DB_PATH

import app.services.file_store
app.services.file_store.BASE_DIR = STORY_DIR

# ============================================================
# 真正的 import
# ============================================================

from app.services import pricing
from app.services.db import init_db
from app.ai.registry import get_registry, reset_registry, ModelRegistry
from app.db import connection


# ============================================================
# 工具
# ============================================================

fails: list[str] = []
passed: int = 0


def check(cond, msg: str) -> None:
    global passed
    if cond:
        passed += 1
        print(f"  [PASS] {msg}")
    else:
        fails.append(msg)
        print(f"  [FAIL] {msg}")


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


# ============================================================
# 测试 1: 数据初始化 (内置 4 个模型)
# ============================================================

def test_registry_init() -> None:
    section("[A4 1] registry 初始化 (内置 4 个模型)")
    reg = get_registry()
    reg.init_defaults()
    reg.reload()
    models = reg.list_all()
    check(len(models) >= 4, f"≥ 4 个内置模型 (实际 {len(models)})")
    ids = {m.id for m in models}
    check("preset_gpt4o_mini" in ids, "GPT-4o mini 存在")
    check("preset_gpt4o" in ids, "GPT-4o 存在")
    check("preset_deepseek" in ids, "DeepSeek 存在")
    check("preset_claude_sonnet" in ids, "Claude Sonnet 存在")


# ============================================================
# 测试 2: get_price
# ============================================================

def test_get_price() -> None:
    section("[A4 2] get_price: 单个模型")
    info = pricing.get_price("preset_gpt4o_mini")
    check(info is not None, "GPT-4o mini 存在")
    if info:
        check(info.input_price == 0.15, f"input_price=0.15 (实际 {info.input_price})")
        check(info.output_price == 0.60, f"output_price=0.60 (实际 {info.output_price})")
        check(not info.is_free, f"非免费")
        check(info.age_days >= 0, f"age_days={info.age_days}")
        check(info.price_updated_at != "", f"price_updated_at 已设")

    # 不存在
    info_none = pricing.get_price("nonexistent")
    check(info_none is None, "不存在 → None")


# ============================================================
# 测试 3: list_prices
# ============================================================

def test_list_prices() -> None:
    section("[A4 3] list_prices: 列出所有")
    all_p = pricing.list_prices()
    check(len(all_p) >= 4, f"≥ 4 个 (实际 {len(all_p)})")
    # 按 role 排序: primary 在前
    roles = [p.role for p in all_p]
    primary_indices = [i for i, r in enumerate(roles) if r == "primary"]
    fallback_indices = [i for i, r in enumerate(roles) if r == "fallback"]
    if primary_indices and fallback_indices:
        check(max(primary_indices) < min(fallback_indices), "primary 在 fallback 前")


# ============================================================
# 测试 4: estimate_cost
# ============================================================

def test_estimate_cost() -> None:
    section("[A4 4] estimate_cost: 估算 token 成本")

    # GPT-4o mini: 0.15 / 0.60 (USD/1M)
    # 1000 in + 500 out = 0.15*0.001 + 0.60*0.0005 = 0.00015 + 0.0003 = 0.00045 USD
    cost = pricing.estimate_cost("preset_gpt4o_mini", 1000, 500)
    check(abs(cost - 0.00045) < 1e-6, f"1000+500 ≈ 0.00045 USD (实际 {cost})")

    # 0 tokens
    cost_zero = pricing.estimate_cost("preset_gpt4o_mini", 0, 0)
    check(cost_zero == 0.0, f"0 tokens → 0 cost (实际 {cost_zero})")

    # 不存在 → 0
    cost_404 = pricing.estimate_cost("nonexistent", 1000, 500)
    check(cost_404 == 0.0, f"不存在 → 0 cost (实际 {cost_404})")

    # Claude (3.0 / 15.0)
    # 2000 in + 1000 out = 3*0.002 + 15*0.001 = 0.006 + 0.015 = 0.021 USD
    cost_claude = pricing.estimate_cost("preset_claude_sonnet", 2000, 1000)
    check(abs(cost_claude - 0.021) < 1e-4, f"Claude 2000+1000 ≈ 0.021 USD (实际 {cost_claude})")


# ============================================================
# 测试 5: 格式化价格
# ============================================================

def test_format_prices() -> None:
    section("[A4 5] 格式化: USD/CNY/单行")

    # USD
    s = pricing.format_price_usd(0.05)
    check("约" in s, f"USD 必带'约' (实际 '{s}')")
    check("$" in s, f"USD 含 $ (实际 '{s}')")

    s0 = pricing.format_price_usd(0)
    check("免费" in s0, f"0 USD → '免费' (实际 '{s0}')")

    # CNY
    s_cny = pricing.format_price_cny(0.05)
    check("约" in s_cny, f"CNY 必带'约' (实际 '{s_cny}')")
    check("¥" in s_cny, f"CNY 含 ¥ (实际 '{s_cny}')")

    # per_million
    s_pm = pricing.format_price_per_million(0.15)
    check("¥" in s_pm, f"per_million 含 ¥ (实际 '{s_pm}')")
    check("1M" in s_pm, f"per_million 含 1M (实际 '{s_pm}')")

    s_pm0 = pricing.format_price_per_million(0)
    check("免费" in s_pm0, f"0 价格 → '免费' (实际 '{s_pm0}')")

    # info line
    info = pricing.get_price("preset_gpt4o_mini")
    if info:
        line = pricing.format_price_info_line(info)
        # 用 model_name 而非 display name (display name 不存 DB)
        check("gpt-4o-mini" in line, f"info line 含 model_name (实际 '{line}')")
        check("更新于" in line, f"info line 含'更新于' (实际 '{line}')")
        check("openai" in line.lower(), f"info line 含 provider (实际 '{line}')")


# ============================================================
# 测试 6: update_price
# ============================================================

def test_update_price() -> None:
    section("[A4 6] update_price: 改价 + 刷新 timestamp")

    # 改 GPT-4o mini
    ok = pricing.update_price("preset_gpt4o_mini", input_price=0.20, output_price=0.80)
    check(ok, f"更新成功 (实际 {ok})")
    info = pricing.get_price("preset_gpt4o_mini")
    if info:
        check(info.input_price == 0.20, f"input_price=0.20 (实际 {info.input_price})")
        check(info.output_price == 0.80, f"output_price=0.80 (实际 {info.output_price})")
        check(info.age_days == 0, f"age_days=0 (刚更新, 实际 {info.age_days})")
        check(not info.is_stale, f"非 stale")

    # 只改 input
    ok2 = pricing.update_price("preset_gpt4o_mini", input_price=0.25)
    check(ok2, f"只改 input 成功")
    info2 = pricing.get_price("preset_gpt4o_mini")
    if info2:
        check(info2.input_price == 0.25, f"input_price=0.25")
        check(info2.output_price == 0.80, f"output_price 保持 0.80")

    # 不存在
    ok3 = pricing.update_price("nonexistent", input_price=0.1)
    check(not ok3, f"不存在 → False (实际 {ok3})")

    # 都为 None
    ok4 = pricing.update_price("preset_gpt4o_mini")
    check(not ok4, f"都 None → False")


# ============================================================
# 测试 7: 免费模型
# ============================================================

def test_free_model() -> None:
    section("[A4 7] 免费模型 (价格都 0)")

    # 把 DeepSeek 改成免费
    pricing.update_price("preset_deepseek", input_price=0.0, output_price=0.0)
    info = pricing.get_price("preset_deepseek")
    check(info is not None and info.is_free, f"DeepSeek → 免费")
    cost = pricing.estimate_cost("preset_deepseek", 10000, 5000)
    check(cost == 0.0, f"免费模型 cost=0 (实际 {cost})")


# ============================================================
# 测试 8: 时效性 (stale)
# ============================================================

def test_stale() -> None:
    section("[A4 8] 时效性: stale 检测")
    # 把 GPT-4o 的 updated_at 改成 60 天前
    cur = connection.get_conn()
    cur.execute(
        "UPDATE model_configs SET price_updated_at = datetime('now', '-60 days') "
        "WHERE id = 'preset_gpt4o'",
    )
    cur.commit()

    info = pricing.get_price("preset_gpt4o")
    check(info is not None, "GPT-4o 存在")
    if info:
        check(info.age_days >= 59, f"age_days ≥ 59 (实际 {info.age_days})")
        check(info.is_stale, f"is_stale=True (实际 {info.is_stale})")
        line = pricing.format_price_info_line(info)
        check("可能过期" in line, f"info line 标 [可能过期] (实际 '{line}')")

    # list_stale_models
    stale = pricing.list_stale_models(threshold_days=30)
    stale_ids = [s.model_id for s in stale]
    check("preset_gpt4o" in stale_ids, f"GPT-4o 在 stale 列表")


# ============================================================
# 测试 9: 偏差提示
# ============================================================

def test_warning() -> None:
    section("[A4 9] 偏差提示")
    text = pricing.get_warning_text()
    check("可能与实际有偏差" in text or "可能" in text,
          f"偏差提示含 '可能' (实际 '{text[:50]}...')")
    check("账单" in text or "厂商" in text, f"提示含 '账单/厂商' (实际 '{text[:50]}...')")


# ============================================================
# 测试 10: 纯函数 estimate_cost_with_prices
# ============================================================

def test_pure_fn() -> None:
    section("[A4 10] 纯函数 estimate_cost_with_prices")
    # 1 USD/1M in, 2 USD/1M out, 5000 in + 2000 out
    cost = pricing.estimate_cost_with_prices(1.0, 2.0, 5000, 2000)
    # 0.005 * 1 + 0.002 * 2 = 0.005 + 0.004 = 0.009
    check(abs(cost - 0.009) < 1e-6, f"1*5000+2*2000 → 0.009 (实际 {cost})")
    cost0 = pricing.estimate_cost_with_prices(0, 0, 1000, 1000)
    check(cost0 == 0, f"全 0 → 0 (实际 {cost0})")


# ============================================================
# 测试 11: cost_summary_by_model (结构正确性, 不假设空表)
# ============================================================

def test_cost_summary() -> None:
    section("[A4 11] cost_summary_by_model 结构")
    summary = pricing.cost_summary_by_model(days=30)
    # 不假设空表 (其他 smoke 跑过后 usage_records 可能有数据)
    # 但要求每条都有正确字段
    if summary:
        first = summary[0]
        check("model" in first, f"含 model 字段 (实际 {list(first.keys())})")
        check("tokens_in" in first, f"含 tokens_in")
        check("tokens_out" in first, f"含 tokens_out")
        check("cost_usd" in first, f"含 cost_usd")
        check("calls" in first, f"含 calls")
        # cost 应 ≥ 0
        check(first["cost_usd"] >= 0, f"cost_usd ≥ 0 (实际 {first['cost_usd']})")
    else:
        check(summary == [], f"无记录 → 空列表")

    # 限制项目 (假设没项目 = 空)
    summary_proj = pricing.cost_summary_by_model(project_id="nonexistent_pid", days=30)
    check(summary_proj == [], f"不存在的项目 → 空列表 (实际 {summary_proj})")


# ============================================================
# Main
# ============================================================

def main() -> int:
    print("=" * 60)
    print("A4 SMOKE: 定价服务 (Pricing Service)")
    print("=" * 60)
    print(f"[setup] tmpdir = {TMPDIR}")

    init_db()
    connection.init(DB_PATH)
    print(f"[setup] DB = {DB_PATH}")

    tests = [
        lambda: test_registry_init(),
        lambda: test_get_price(),
        lambda: test_list_prices(),
        lambda: test_estimate_cost(),
        lambda: test_format_prices(),
        lambda: test_update_price(),
        lambda: test_free_model(),
        lambda: test_stale(),
        lambda: test_warning(),
        lambda: test_pure_fn(),
        lambda: test_cost_summary(),
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            fails.append(f"{t.__name__} 异常")
            print(f"\n✗ {t.__name__}: EXCEPTION — {type(e).__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"通过: {passed}    失败: {len(fails)}")
    if fails:
        print("\n失败列表:")
        for f in fails:
            print(f"  - {f}")
        print("=" * 60)
        return 1
    print(f"全部 {passed} 项检查通过 ✓")
    print("=" * 60)
    return 0


def _cleanup() -> None:
    import time as _t
    import shutil
    try:
        connection.close()
    except Exception:
        pass
    _t.sleep(0.1)
    for ext in ("", "-wal", "-shm"):
        f = DB_PATH.parent / f"{DB_PATH.name}{ext}"
        if f.exists():
            try:
                f.unlink()
            except (PermissionError, OSError):
                pass
    try:
        shutil.rmtree(STORY_DIR, ignore_errors=True)
    except Exception:
        pass
    try:
        TMPDIR.rmdir()
    except (PermissionError, OSError):
        pass
    reset_registry()


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        _cleanup()
    sys.exit(rc)
