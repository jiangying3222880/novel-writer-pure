"""
B5 SMOKE: 授权系统 (License Manager)
- 机器码生成
- Key 生成 + 验证
- 万能 key
- 激活/降级/持久化
- 插件门禁

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
    print(f"\n[TIMEOUT] smoke_b5_license 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 隔离真实数据
# ============================================================

TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_b5_"))
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

from app.services import license, app_setting_service
from app.services.db import init_db
from app.services.exceptions import NotFoundError, ValidationError


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
# 测试 1: 机器码
# ============================================================

def test_machine_code() -> None:
    section("[B5 1] 机器码生成")

    mc = license.get_machine_code()
    check(len(mc) == 8, f"机器码 8 字符 (实际 {len(mc)}: '{mc}')")
    check(mc.isalnum(), f"机器码字母数字 (实际 '{mc}')")
    check(mc.isupper(), f"机器码大写 (实际 '{mc}')")

    # 同样机器 → 同样机器码
    mc2 = license.get_machine_code()
    check(mc == mc2, f"2 次调用结果一致")

    # 字符都在 KEY_ALPHABET 内
    all_in = all(c in license.KEY_ALPHABET for c in mc)
    check(all_in, f"机器码字符在 KEY_ALPHABET 内")


# ============================================================
# 测试 2: 网络时间
# ============================================================

def test_network_time() -> None:
    section("[B5 2] 网络时间")

    ts = license.get_network_time()
    check(ts > 1700000000, f"时间戳 > 2023 ({ts:.0f})")
    check(ts < 2000000000, f"时间戳 < 2033 ({ts:.0f})")
    # 离本地时间不应差太多 (1 天内)
    import time
    local = time.time()
    check(abs(ts - local) < 86400, f"网络时间与本地时间差 < 1 天 (差 {abs(ts-local):.0f}s)")


# ============================================================
# 测试 3: Key 生成 + 验证
# ============================================================

def test_key_generate_validate() -> None:
    section("[B5 3] Key 生成 + 验证")

    mc = license.get_machine_code()
    # 生成 30 天 key
    key = license.generate_key(mc, days=30)
    check(key.startswith("NV-"), f"key 以前缀 NV- 开头 (实际 '{key}')")
    check(len(key) == len("NV-XXXX-XXXX-XXXX-XXXX"), f"key 长度 = NV-XXXX-XXXX-XXXX-XXXX (实际 {len(key)})")
    # 格式
    parts = key.split("-")
    check(len(parts) == 5 and parts[0] == "NV", f"key 分 5 段 ({parts})")
    check(all(len(p) == 4 for p in parts[1:]), f"4 段每段 4 字符")

    # 验证
    result = license.validate_key(key, current_machine=mc)
    check(result.valid, f"key 验证通过 (error={result.error_msg})")
    check(result.status == license.LicenseStatus.PREMIUM, f"status=PREMIUM")
    check(result.version == license.VERSION_PREMIUM, f"version=premium")
    check(result.remaining_days > 25, f"剩余天数 > 25 (实际 {result.remaining_days})")

    # 用错机器码 → MACHINE_MISMATCH
    result_bad = license.validate_key(key, current_machine="AAAAAAAA")
    check(not result_bad.valid, "错机器码 → invalid")
    check(result_bad.status == license.LicenseStatus.MACHINE_MISMATCH, f"status=MACHINE_MISMATCH")


# ============================================================
# 测试 4: 万能 key
# ============================================================

def test_universal_key() -> None:
    section("[B5 4] 万能 key")

    for uk in license.UNIVERSAL_KEYS:
        result = license.validate_key(uk)
        check(result.valid, f"万能 key 验证通过: {uk[:8]}...")
        check(result.status == license.LicenseStatus.PREMIUM, f"status=PREMIUM")
        check(result.machine_code == "UNIVERSAL", f"machine_code=UNIVERSAL")
        check(result.remaining_days == -1, "永久 (remaining=-1)")


# ============================================================
# 测试 5: 永久 key
# ============================================================

def test_perpetual_key() -> None:
    section("[B5 5] 永久 key (days=0)")

    mc = license.get_machine_code()
    key = license.generate_key(mc, days=0)
    check(key.startswith("NV-"), f"永久 key 格式对 ({key})")
    result = license.validate_key(key, current_machine=mc)
    check(result.valid, f"永久 key 验证通过")
    check(result.remaining_days == -1, f"永久 remaining=-1 (实际 {result.remaining_days})")
    check(result.expire_date == "永久", f"expire_date=永久")


# ============================================================
# 测试 6: 过期 key
# ============================================================

def test_expired_key() -> None:
    section("[B5 6] 过期 key")

    mc = license.get_machine_code()
    # 生成 -1 天的 key (昨天过期) → 不会到未来, 直接篡改 expire_days
    # 用 generate_key(days=1) 然后手工改时间戳不可行
    # 这里直接构造一个过期的 payload
    payload = license._make_key_payload(license.VERSION_PREMIUM, 0, mc)  # 0=永久
    # 把 expire_days 改成 0 (永久), 然后改 sig 也通过
    # 改个不同版本号 (非 0 非 1) → 应视为非法
    bad_payload = bytearray(payload)
    bad_payload[0] = 99
    sig = license._sign(bytes(bad_payload) + b"\x00")
    full = bytes(bad_payload) + sig
    chars = license._b32encode_custom(full)
    key = license.format_key(chars)
    result = license.validate_key(key, current_machine=mc)
    check(not result.valid, f"version 字段乱填 → invalid")
    check(result.status == license.LicenseStatus.INVALID, f"status=INVALID")


# ============================================================
# 测试 7: 错误格式
# ============================================================

def test_bad_formats() -> None:
    section("[B5 7] 错误格式 key")

    # 空
    r = license.validate_key("")
    check(not r.valid and r.status == license.LicenseStatus.INVALID, f"空 key → invalid")

    # 太短
    r = license.validate_key("NV-AAAA")
    check(not r.valid, f"太短 key → invalid")

    # 错的字符 (在 base32 但改几位)
    # 简单: 改 1 字符让签名失败
    r = license.validate_key("NV-ZZZZ-ZZZZ-ZZZZ-ZZZZ")
    check(not r.valid, f"全 Z key → invalid")
    check(r.status == license.LicenseStatus.INVALID, f"status=INVALID")


# ============================================================
# 测试 8: 激活 / 降级
# ============================================================

def test_activate_deactivate() -> None:
    section("[B5 8] 激活 / 降级 / 持久化")

    mc = license.get_machine_code()
    # 1) 默认 STANDARD
    license.reset_cache()
    info = license.load_license()
    check(info.status == license.LicenseStatus.STANDARD, f"默认 STANDARD (实际 {info.status})")
    check(info.version == license.VERSION_STANDARD, f"version=standard")

    # 2) 激活万能 key
    info = license.activate(license.UNIVERSAL_KEYS[0])
    check(info.status == license.LicenseStatus.PREMIUM, f"激活后 PREMIUM (实际 {info.status})")
    check(info.error_msg == "", f"无错误 (实际 '{info.error_msg}')")

    # 3) 重读
    license.reset_cache()
    info2 = license.load_license()
    check(info2.status == license.LicenseStatus.PREMIUM, f"重读后 PREMIUM (实际 {info2.status})")
    check(info2.activated_at != "", f"activated_at 已记录 ('{info2.activated_at}')")

    # 4) 降级
    info3 = license.deactivate()
    check(info3.status == license.LicenseStatus.STANDARD, f"降级后 STANDARD (实际 {info3.status})")

    # 5) 重读 → STANDARD
    license.reset_cache()
    info4 = license.load_license()
    check(info4.status == license.LicenseStatus.STANDARD, f"降级后重读 STANDARD (实际 {info4.status})")

    # 6) 激活无效 key
    info5 = license.activate("NV-ZZZZ-ZZZZ-ZZZZ-ZZZZ")
    check(info5.status != license.LicenseStatus.PREMIUM, f"无效 key 不激活 (实际 {info5.status})")
    # 无效 key 不改 status (保留原)
    license.reset_cache()
    info6 = license.load_license()
    check(info6.status == license.LicenseStatus.STANDARD, f"无效激活后仍 STANDARD")


# ============================================================
# 测试 9: 插件门禁
# ============================================================

def test_plugin_unlock() -> None:
    section("[B5 9] 插件门禁")

    # 标准版: 内置插件解锁, 第三方不解锁
    license.reset_cache()
    info = license.deactivate()
    check(license.is_plugin_unlocked("knowledge_plugin"), "内置 knowledge_plugin 解锁")
    check(license.is_plugin_unlocked("tts_edge"), "内置 tts_edge 解锁")
    check(license.is_plugin_unlocked("usage_analytics"), "内置 usage_analytics 解锁")
    check(not license.is_plugin_unlocked("third_party_xyz"), "第三方插件 标准版不解锁")

    # 高级版: 第三方也解锁
    license.activate(license.UNIVERSAL_KEYS[0])
    license.reset_cache()
    check(license.is_plugin_unlocked("third_party_xyz"), "高级版 第三方插件解锁")
    check(license.is_plugin_unlocked("knowledge_plugin"), "高级版 内置仍解锁")
    check(license.is_premium(), f"is_premium() = True")

    # 降级回去 (留干净环境给后续测试)
    license.deactivate()
    license.reset_cache()


# ============================================================
# 测试 10: 端到端
# ============================================================

def test_e2e() -> None:
    section("[B5 10] 端到端 (生成 + 激活 + 验证 + 降级)")

    mc = license.get_machine_code()
    # 清干净
    license.deactivate()
    license.reset_cache()

    # 1) 生成 90 天 key 给本机
    key = license.generate_key(mc, days=90)
    print(f"  [info] 生成的 key = {key}")

    # 2) 激活
    info = license.activate(key)
    check(info.status == license.LicenseStatus.PREMIUM, f"激活成功 ({info.status})")
    check(info.remaining_days >= 85, f"剩余 ≥ 85 天 (实际 {info.remaining_days})")
    check(info.expire_date != "永久", f"有过期日期 ({info.expire_date})")

    # 3) 重启模拟 (重置缓存)
    license.reset_cache()
    info2 = license.load_license()
    check(info2.status == license.LicenseStatus.PREMIUM, f"重启后 PREMIUM (实际 {info2.status})")
    check(info2.activated_at == info.activated_at, f"activated_at 持久化")

    # 4) 降级
    info3 = license.deactivate()
    check(info3.status == license.LicenseStatus.STANDARD, f"降级 STANDARD")
    license.reset_cache()
    info4 = license.load_license()
    check(info4.status == license.LicenseStatus.STANDARD, f"降级后重读 STANDARD")


# ============================================================
# Main
# ============================================================

def main() -> int:
    print("=" * 60)
    print("B5 SMOKE: 授权系统 (License Manager)")
    print("=" * 60)
    print(f"[setup] tmpdir = {TMPDIR}")

    init_db()
    from app.db import connection
    connection.init(DB_PATH)
    print(f"[setup] DB = {DB_PATH}")

    tests = [
        lambda: test_machine_code(),
        lambda: test_network_time(),
        lambda: test_key_generate_validate(),
        lambda: test_universal_key(),
        lambda: test_perpetual_key(),
        lambda: test_expired_key(),
        lambda: test_bad_formats(),
        lambda: test_activate_deactivate(),
        lambda: test_plugin_unlock(),
        lambda: test_e2e(),
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
        from app.db import connection
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
