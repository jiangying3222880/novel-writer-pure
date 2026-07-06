"""
H4 SMOKE: 配置系统 (B7+config.py 整合)
- DEFAULT_SETTINGS 完整性
- seed_models.json 加载
- 便捷访问器 (engine.max_retries / log.retention_days / etc.)
- validate() 校验
- set() / get() / delete() / reset_all() 持久化
- registry 加载 seed_models 正确

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
    print(f"\n[TIMEOUT] smoke_h4_config 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 隔离真实数据
# ============================================================

TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_h4_"))
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

from app.core import config
from app.core import constants
try:
    from app.core.config import (
        load, get, set as config_set, validate, reset_all, all_keys,
        get_engine_max_retries, get_engine_retry_delays,
        get_log_retention_days, get_log_max_bytes,
        get_plugins_dir, get_db_journal_mode, get_db_isolation_level,
    )
    _HAS_GET_PLUGINS_DIR = True
except ImportError:
    _HAS_GET_PLUGINS_DIR = False
    from app.core.config import (
        load, get, set as config_set, validate, reset_all, all_keys,
        get_engine_max_retries, get_engine_retry_delays,
        get_log_retention_days, get_log_max_bytes,
        get_db_journal_mode, get_db_isolation_level,
    )
    # get_plugins_dir 已被废弃, 用 None 占位
    get_plugins_dir = lambda: None  # type: ignore
from app.ai import registry as ai_registry
from app.services.db import init_db
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
# 测试 1: DEFAULT_SETTINGS 完整性
# ============================================================

def test_default_settings_complete() -> None:
    section("[H4 1] DEFAULT_SETTINGS 完整性")

    # 必须存在 (P1-P5 都涉及)
    required_keys = [
        "engine.max_retries",
        "engine.retry_delays",
        "engine.use_fallback",
        "log.retention_days",
        "log.max_bytes",
        "plugins.dir",
        "db.journal_mode",
        "db.isolation_level",
        "model.price_updated_at",
        "subtext.default_mode",
        "genre.max_primary",
        "genre.max_aux",
        "ui.theme",
        "ui.scale",
        "ui.font_size",
        "ui.line_spacing",
    ]
    settings = constants.DEFAULT_SETTINGS
    for k in required_keys:
        check(k in settings, f"DEFAULT_SETTINGS 包含 {k!r}")


# ============================================================
# 测试 2: seed_models.json 加载
# ============================================================

def test_seed_models_loaded() -> None:
    section("[H4 2] seed_models.json 加载")

    # 路径存在
    check(ai_registry.SEED_MODELS_PATH.exists(),
          f"seed_models.json 存在 ({ai_registry.SEED_MODELS_PATH})")

    # DEFAULT_MODELS 至少 4 个 (M11-B 加了 4 个新 provider, 当前 8 个)
    _n = len(ai_registry.get_default_models())
    check(_n >= 4, f"DEFAULT_MODELS >= 4 个 (实际 {_n})")

    # 每个都有必须字段
    required = ["id", "name", "provider", "model_name", "input_price", "output_price", "role"]
    for m in ai_registry.get_default_models():
        for f in required:
            check(f in m, f"模型 {m.get('id', '?')!r} 含字段 {f!r}")

    # 价格都是正数
    for m in ai_registry.get_default_models():
        check(isinstance(m["input_price"], (int, float)) and m["input_price"] >= 0,
              f"{m['id']!r} input_price >= 0 ({m['input_price']})")
        check(isinstance(m["output_price"], (int, float)) and m["output_price"] >= 0,
              f"{m['id']!r} output_price >= 0 ({m['output_price']})")

    # 至少 1 个 primary
    primaries = [m for m in ai_registry.get_default_models() if m["role"] == "primary"]
    check(len(primaries) >= 1, f"至少 1 个 primary 模型 (实际 {len(primaries)})")


# ============================================================
# 测试 3: 便捷访问器
# ============================================================

def test_helper_accessors() -> None:
    section("[H4 3] 便捷访问器")

    # 初始化
    init_db()
    connection.init(DB_PATH)
    config.reset_all()    # 清掉 DB 里的覆盖
    config.load()

    # 引擎
    mr = get_engine_max_retries()
    check(mr == 3, f"engine.max_retries = 3 (实际 {mr})")
    rd = get_engine_retry_delays()
    check(rd == [2, 4, 8], f"engine.retry_delays = [2,4,8] (实际 {rd})")

    # 日志
    rd_days = get_log_retention_days()
    check(rd_days == 7, f"log.retention_days = 7 (实际 {rd_days})")
    mb = get_log_max_bytes()
    check(mb == 10 * 1024 * 1024, f"log.max_bytes = 10MB (实际 {mb})")

    # 插件 (V3.4+ 已废弃, 若函数不存在则跳过)
    if _HAS_GET_PLUGINS_DIR:
        pd = get_plugins_dir()
        check(isinstance(pd, Path) and pd.name == "plugins",
              f"plugins.dir = 'plugins' (实际 {pd})")
    else:
        print("  [SKIP] plugins.dir (已废弃)")

    # DB
    jm = get_db_journal_mode()
    check(jm == "WAL", f"db.journal_mode = WAL (实际 {jm})")
    il = get_db_isolation_level()
    check(il is None, f"db.isolation_level = None (autocommit) (实际 {il})")


# ============================================================
# 测试 4: validate() 校验
# ============================================================

def test_validate() -> None:
    section("[H4 4] validate() 校验")

    # 默认值全合法
    errors = validate()
    check(len(errors) == 0, f"默认值校验通过 (errors={errors})")

    # 改坏一个值 → 应报错
    config_set("engine.max_retries", 0)
    errors2 = validate()
    check(len(errors2) > 0 and any("max_retries" in e for e in errors2),
          f"max_retries=0 应报错 (实际 {errors2})")

    # 改回
    config_set("engine.max_retries", 3)
    errors3 = validate()
    check(len(errors3) == 0, f"改回后校验通过")

    # 改坏 theme
    config_set("ui.theme", "pink")
    errors4 = validate()
    check(len(errors4) > 0 and any("ui.theme" in e for e in errors4),
          f"ui.theme='pink' 应报错 (实际 {errors4})")
    config_set("ui.theme", "light")

    # 改坏 journal_mode
    config_set("db.journal_mode", "BOGUS")
    errors5 = validate()
    check(len(errors5) > 0 and any("journal_mode" in e for e in errors5),
          f"db.journal_mode='BOGUS' 应报错")
    config_set("db.journal_mode", "WAL")


# ============================================================
# 测试 5: set / get / delete / reset_all
# ============================================================

def test_set_get_delete() -> None:
    section("[H4 5] set / get / delete / reset_all")

    config.reset_all()
    config.load()

    # 1) set 不持久化
    config_set("engine.max_retries", 5, persist=False)
    check(get("engine.max_retries") == 5, f"set persist=False 内存 = 5")

    # 2) set 持久化
    config_set("engine.max_retries", 7, persist=True)
    # 重新 load 应该读到 7 (DB 覆盖默认)
    config._loaded = False    # 强制重载
    config.load()
    check(get("engine.max_retries") == 7, f"DB 覆盖默认 = 7 (实际 {get('engine.max_retries')})")

    # 3) 删 → 恢复默认
    config.delete("engine.max_retries")
    check(get("engine.max_retries") == 3, f"delete 恢复默认 = 3")

    # 4) reset_all → 全清
    config_set("engine.max_retries", 99, persist=True)
    config_set("ui.theme", "dark", persist=True)
    config.reset_all()
    config._loaded = False
    config.load()
    check(get("engine.max_retries") == 3, f"reset_all 后 max_retries=3")
    check(get("ui.theme") == "light", f"reset_all 后 ui.theme=light")

    # 5) all_keys 至少 16 项
    keys = all_keys()
    check(len(keys) >= 16, f"all_keys >= 16 (实际 {len(keys)})")


# ============================================================
# 测试 6: registry.init_defaults 走 seed
# ============================================================

def test_registry_init_from_seed() -> None:
    section("[H4 6] registry.init_defaults 从 seed 加载")

    # 清表
    conn = connection.get_conn()
    conn.execute("DELETE FROM model_configs")
    conn.commit() if False else None    # autocommit 模式

    # 触发初始化
    ai_registry.reset_registry()
    reg = ai_registry.get_registry()
    reg.init_defaults()

    # 4 个内置预置在 DB
    rows = conn.execute("SELECT id FROM model_configs WHERE built_in=1").fetchall()
    seed_ids = {r["id"] for r in rows}
    expected = {m["id"] for m in ai_registry.get_default_models()}
    check(seed_ids == expected,
          f"DB 含全部 seed 预置 (差异: {seed_ids ^ expected})")

    # reload 后内存 >= 4 个 (M11-B 加 4 个, 当前 8)
    reg.reload()
    check(len(reg.list_all()) >= 4, f"reload 后内存 >= 4 个 (实际 {len(reg.list_all())})")
    check(reg.get_primary() is not None, f"get_primary() 不为 None")
    check(reg.get_fallback() is not None, f"get_fallback() 不为 None")


# ============================================================
# 测试 7: DB 持久化覆盖
# ============================================================

def test_db_persistence_override() -> None:
    section("[H4 7] DB 持久化覆盖")

    config.reset_all()
    config.load()

    # 持久化一个新 key
    conn = connection.get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
        ("engine.max_retries", "10"),
    )

    # 强制重载
    config._loaded = False
    config.load()

    check(get_engine_max_retries() == 10,
          f"DB 覆盖后 max_retries = 10 (实际 {get_engine_max_retries()})")

    # 清掉
    conn.execute("DELETE FROM app_settings WHERE key='engine.max_retries'")
    config._loaded = False
    config.load()
    check(get_engine_max_retries() == 3, f"清掉后恢复默认 3")


# ============================================================
# Main
# ============================================================

def main() -> int:
    print("=" * 60)
    print("H4 SMOKE: 配置系统 (DEFAULT_SETTINGS + seed_models + helpers)")
    print("=" * 60)
    print(f"[setup] tmpdir = {TMPDIR}")

    tests = [
        lambda: test_default_settings_complete(),
        lambda: test_seed_models_loaded(),
        lambda: test_helper_accessors(),
        lambda: test_validate(),
        lambda: test_set_get_delete(),
        lambda: test_registry_init_from_seed(),
        lambda: test_db_persistence_override(),
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
    import time
    import shutil
    try:
        connection.close()
    except Exception:
        pass
    time.sleep(0.1)
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


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        _cleanup()
    sys.exit(rc)
