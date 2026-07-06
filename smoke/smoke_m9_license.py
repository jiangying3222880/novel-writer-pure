"""
smoke_m9_license.py - M9-C 用户系统 + 付费解锁 smoke 测试

覆盖范围:
1. feature_gate 等级比较 / 注册表 / 装饰器
2. license 服务: machine_code, generate, validate, activate, deactivate
3. CLI: license status/activate/deactivate/generate/machine
4. CLI: feature list/check
5. HTTP: /license/{status,activate,deactivate,machine}
6. HTTP: /feature/{list,check}
7. 集成: 激活 key → tier 升 PRO → PRO 功能解锁 → 降级 → 锁回去
8. 万能 key 测试
9. 错误路径 (空 key / 错 key / 错 machine)

通过标准: 全部 OK, 失败时 check() 抛 AssertionError.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import List

# Windows cp936 修复
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 隔离 DB
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
os.environ.setdefault("NOVEL_WRITER_DB_PATH", str(_ROOT / "data" / "smoke_m9_license.db"))
os.environ.setdefault("NOVEL_WRITER_PLUGINS_DIR", str(_ROOT / "plugins_test_m9_license"))
os.environ.setdefault("NOVEL_WRITER_MARKET_DIR", str(_ROOT / "market_test_m9_license"))

# 跑测试前先清掉旧 DB
_db_path = Path(os.environ["NOVEL_WRITER_DB_PATH"])
if _db_path.exists():
    _db_path.unlink()

sys.path.insert(0, str(_ROOT))

_passed = 0
_failed = 0
_errors: List[str] = []


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def check(cond: bool, msg: str) -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ✅ {msg}")
    else:
        _failed += 1
        _errors.append(msg)
        print(f"  ❌ {msg}")


# ============================================================
# Part 1: feature_gate 基础
# ============================================================
def part1_feature_gate() -> None:
    section("[Part 1] feature_gate 等级 / 注册表 / 工具函数")
    from app.services.feature_gate import (
        Tier, tier_rank, tier_meets,
        FEATURE_TIERS, FeatureInfo,
        get_feature_info, required_tier,
        format_tier_badge, format_tier_description, format_feature_line,
    )

    # 等级比较
    check(tier_rank(Tier.FREE) == 0, "FREE rank=0")
    check(tier_rank(Tier.STANDARD) == 1, "STANDARD rank=1")
    check(tier_rank(Tier.PRO) == 2, "PRO rank=2")
    check(tier_meets(Tier.PRO, Tier.STANDARD), "PRO >= STANDARD")
    check(tier_meets(Tier.STANDARD, Tier.STANDARD), "STANDARD >= STANDARD")
    check(tier_meets(Tier.FREE, Tier.FREE), "FREE >= FREE")
    check(not tier_meets(Tier.FREE, Tier.PRO), "FREE < PRO")
    check(not tier_meets(Tier.STANDARD, Tier.PRO), "STANDARD < PRO")

    # 注册表
    check(len(FEATURE_TIERS) >= 10, f"FEATURE_TIERS 注册数 {len(FEATURE_TIERS)} >= 10")
    check("writing.draft" in FEATURE_TIERS, "writing.draft 已注册")
    check("ai.critic" in FEATURE_TIERS, "ai.critic 已注册")
    check("export.epub" in FEATURE_TIERS, "export.epub 已注册")
    check("export.cover" in FEATURE_TIERS, "export.cover 已注册")

    # FeatureInfo
    info = FEATURE_TIERS["ai.critic"]
    check(isinstance(info, FeatureInfo), "ai.critic 是 FeatureInfo 实例")
    check(info.tier == Tier.PRO, "ai.critic tier=PRO")
    check(info.name == "AI Critic 评估", "ai.critic name OK")
    check(len(info.description) > 0, "ai.critic 有描述")

    # get_feature_info
    check(get_feature_info("ai.critic") is not None, "get_feature_info('ai.critic') OK")
    check(get_feature_info("nonexistent") is None, "get_feature_info 不存在的功能 None")

    # required_tier
    check(required_tier("ai.critic") == Tier.PRO, "ai.critic required=PRO")
    check(required_tier("writing.draft") == Tier.STANDARD, "writing.draft required=STANDARD")
    check(required_tier("core.editor") == Tier.FREE, "core.editor required=FREE")
    check(required_tier("nonexistent") == Tier.FREE, "required_tier 不存在 fallback=FREE")

    # 格式化
    badge = format_tier_badge(Tier.PRO)
    check("🥇" in badge, "PRO badge 含 🥇")
    check("专业版" in badge, "PRO badge 含 '专业版'")
    check("🥉" in format_tier_badge(Tier.FREE), "FREE badge 含 🥉")
    check("🥈" in format_tier_badge(Tier.STANDARD), "STANDARD badge 含 🥈")

    desc = format_tier_description(Tier.STANDARD)
    check("默认" in desc or "标准" in desc, "STANDARD desc OK")

    line = format_feature_line("ai.critic", FEATURE_TIERS["ai.critic"], False)
    check("🔒" in line, "未解锁 line 含 🔒")
    check("ai.critic" in line, "line 含 feature_id")
    check("PRO" in line, "line 含 required tier")
    line2 = format_feature_line("ai.critic", FEATURE_TIERS["ai.critic"], True)
    check("✅" in line2, "解锁 line 含 ✅")


# ============================================================
# Part 2: get_tier + check_feature 默认行为
# ============================================================
def part2_default_tier() -> None:
    section("[Part 2] 默认 tier 行为 (无 license)")
    # 干净环境: 先清掉
    from app.services import license as _lic
    _lic.reset_cache()
    try:
        _lic.deactivate()
    except Exception:
        pass

    from app.services.feature_gate import get_tier, check_feature, Tier
    tier = get_tier()
    # 没有 license 时应该是 STANDARD (默认)
    check(tier == Tier.STANDARD, f"无 license 时 tier={tier.value}")

    # FREE 功能默认解锁
    check(check_feature("core.editor") is True, "FREE 功能 core.editor 解锁")
    check(check_feature("core.project") is True, "FREE 功能 core.project 解锁")

    # STANDARD 功能 (默认 tier) 也解锁
    check(check_feature("writing.draft") is True, "STANDARD 功能默认解锁")
    check(check_feature("export.md") is True, "STANDARD export.md 默认解锁")

    # PRO 功能默认不解锁
    check(check_feature("ai.critic") is False, "PRO 功能 ai.critic 默认锁")
    check(check_feature("export.epub") is False, "PRO export.epub 默认锁")
    check(check_feature("export.cover") is False, "PRO export.cover 默认锁")
    check(check_feature("ai.router.parallel") is False, "PRO ai.router.parallel 默认锁")


# ============================================================
# Part 3: license 工具 (machine / key 编解码 / 验证)
# ============================================================
def part3_license_util() -> None:
    section("[Part 3] license 工具 (machine / key 编解码 / 验证)")
    from app.services.license import (
        get_machine_code, generate_key, validate_key, LicenseStatus,
        UNIVERSAL_KEYS, VERSION_PREMIUM, VERSION_STANDARD,
        format_key, parse_key,
    )

    # 机器码: 8 字符
    mc = get_machine_code()
    check(len(mc) == 8, f"机器码长度 8: {mc}")
    check(mc.isalnum() or mc.isalpha(), f"机器码是字母数字: {mc}")
    # 全部大写
    check(mc == mc.upper(), "机器码全部大写")

    # 生成 key (universal)
    uk = generate_key()  # 没 machine_code → universal
    check(uk.startswith("NV-"), f"universal key 格式: {uk}")
    # 注: 新生成的 universal key 不一定命中白名单 (UNIVERSAL_KEYS 是预置常量);
    # 只要它能通过 validate_key(universal=True) 就行
    r = validate_key(uk)
    check(r.valid, f"新生成 universal key 通过验证: {uk}")
    check(r.status == LicenseStatus.PREMIUM, f"新生成 universal key status=PREMIUM")

    # 验证白名单的 universal keys (预置)
    for ukey in UNIVERSAL_KEYS:
        r = validate_key(ukey)
        check(r.valid, f"万能 key '{ukey}' 通过")
        check(r.status == LicenseStatus.PREMIUM, f"万能 key '{ukey}' status=PREMIUM")
        check(r.version == VERSION_PREMIUM, f"万能 key '{ukey}' version=PREMIUM")

    # 生成 key (绑定机器)
    mk = generate_key(mc, days=30)
    check(mk.startswith("NV-"), f"绑机器 key 格式: {mk}")
    r = validate_key(mk, current_machine=mc)
    check(r.valid, f"绑机器 key 本机通过")
    check(r.status == LicenseStatus.PREMIUM, "绑机器 key status=PREMIUM")
    check(r.remaining_days > 0 and r.remaining_days <= 30, f"剩余天数 {r.remaining_days} <= 30")

    # 同 key 错误机器
    r2 = validate_key(mk, current_machine="AAAAAAAA")  # 错机器
    check(not r2.valid, "绑机器 key 错机器拒绝")
    check(r2.status == LicenseStatus.MACHINE_MISMATCH, "错机器 status=MACHINE_MISMATCH")

    # 错 key
    r3 = validate_key("NV-XXXX-XXXX-XXXX-XXXX")
    check(not r3.valid, "错 key 拒绝")
    check(r3.status == LicenseStatus.INVALID, "错 key status=INVALID")

    # 空 key
    r4 = validate_key("")
    check(not r4.valid, "空 key 拒绝")
    r5 = validate_key("   ")
    check(not r5.valid, "空白 key 拒绝")

    # format_key / parse_key
    raw = "abcdefghijklmnop"
    formatted = format_key(raw)
    check(formatted == "NV-ABCD-EFGH-IJKL-MNOP", f"format_key 正确: {formatted}")
    parsed = parse_key(formatted)
    check(len(parsed) == 10, f"parse_key 出 10 字节: got {len(parsed)}")


# ============================================================
# Part 4: license 持久化 (activate / load / deactivate)
# ============================================================
def part4_license_persist() -> None:
    section("[Part 4] license 持久化 (activate / load / deactivate)")
    from app.services import license as _lic
    from app.services.license import (
        activate, load_license, deactivate, get_license,
        LicenseStatus, reset_cache,
    )
    from app.services.feature_gate import get_tier, check_feature, Tier

    # 起点: 无 key
    _lic.deactivate()
    reset_cache()
    info = load_license()
    check(info.status == LicenseStatus.STANDARD, f"无 key 时 status=STANDARD, got={info.status}")
    check(get_tier() == Tier.STANDARD, "无 key 时 tier=STANDARD")

    # 激活 universal key
    uk = _lic.UNIVERSAL_KEYS[0]
    info2 = activate(uk)
    check(info2.status == LicenseStatus.PREMIUM, f"激活 universal 后 status=PREMIUM, got={info2.status}")
    check(info2.version == _lic.VERSION_PREMIUM, "激活后 version=premium")
    reset_cache()
    check(get_tier() == Tier.PRO, "激活 universal 后 tier=PRO")
    check(check_feature("ai.critic") is True, "PRO 功能 ai.critic 解锁")
    check(check_feature("export.epub") is True, "PRO export.epub 解锁")
    check(check_feature("ai.router.parallel") is True, "PRO ai.router.parallel 解锁")

    # 持久化检查 (load_license 读 app_settings)
    info3 = load_license()
    check(info3.status == LicenseStatus.PREMIUM, "load_license 读出来仍是 PREMIUM")

    # 降级
    info4 = deactivate()
    check(info4.status == LicenseStatus.STANDARD, f"deactivate 后 status=STANDARD, got={info4.status}")
    reset_cache()
    check(get_tier() == Tier.STANDARD, "deactivate 后 tier=STANDARD")
    check(check_feature("ai.critic") is False, "降级后 PRO 功能锁回去")

    # 激活错 key → 失败
    info5 = activate("NV-XXXX-XXXX-XXXX-XXXX")
    check(info5.status != LicenseStatus.PREMIUM, "错 key 激活失败")
    check(info5.error_msg != "", "错 key 有 error_msg")

    # 激活空 key → 失败
    info6 = activate("")
    check(info6.status != LicenseStatus.PREMIUM, "空 key 激活失败")

    # 清理
    _lic.deactivate()


# ============================================================
# Part 5: require_tier 装饰器
# ============================================================
def part5_decorator() -> None:
    section("[Part 5] require_tier 装饰器")
    from app.services import license as _lic
    from app.services.license import deactivate
    from app.services.feature_gate import (
        require_tier, FeatureLockedError, get_tier, Tier,
    )

    # 标准版
    deactivate()
    _lic.reset_cache()
    check(get_tier() == Tier.STANDARD, "标准版")

    @require_tier("ai.critic")
    def pro_only_fn():
        return "PRO OK"

    @require_tier("writing.draft")
    def std_fn():
        return "STANDARD OK"

    @require_tier("core.editor")
    def free_fn():
        return "FREE OK"

    # PRO 功能: 标准版 → 抛
    try:
        pro_only_fn()
        check(False, "PRO fn 标准版应该抛")
    except FeatureLockedError as e:
        check(e.required == Tier.PRO, f"FeatureLockedError required=PRO, got={e.required}")
        check(e.actual == Tier.STANDARD, "FeatureLockedError actual=STANDARD")

    # STANDARD 功能: 标准版 → OK
    check(std_fn() == "STANDARD OK", "STANDARD fn 标准版 OK")

    # FREE 功能: 标准版 → OK
    check(free_fn() == "FREE OK", "FREE fn 标准版 OK")

    # 激活 universal → 升 PRO → PRO 功能可用
    _lic.activate(_lic.UNIVERSAL_KEYS[0])
    _lic.reset_cache()
    check(get_tier() == Tier.PRO, "升 PRO")
    check(pro_only_fn() == "PRO OK", "PRO fn 升 PRO 后 OK")

    # assert_feature 也测
    from app.services.feature_gate import assert_feature
    try:
        # 用一个 PRO 功能, 标准版会抛
        # 但我们刚升 PRO, 不抛
        assert_feature("ai.critic")
        check(True, "assert_feature PRO tier 不抛")
    except FeatureLockedError:
        check(False, "assert_feature PRO tier 不应该抛")

    # 降级
    deactivate()
    _lic.reset_cache()
    try:
        assert_feature("ai.critic")
        check(False, "assert_feature 标准版抛")
    except FeatureLockedError as e:
        check(e.feature_id == "ai.critic", "FeatureLockedError feature_id=ai.critic")


# ============================================================
# Part 6: CLI
# ============================================================
def _run_cli(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable] + args,
        capture_output=True, text=True, timeout=timeout, cwd=str(_ROOT),
        env={**os.environ, "PYTHONPATH": str(_ROOT),
             "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        encoding="utf-8", errors="replace",
    )


def part6_cli() -> None:
    section("[Part 6] CLI (license + feature)")
    from app.services import license as _lic
    _lic.deactivate()  # 起点干净

    from app.cli import build_parser
    p = build_parser()
    check(p is not None, "build_parser() OK")

    # license status (标准版)
    r = _run_cli(["-m", "app.cli", "license", "status"])
    check(r.returncode == 0, f"CLI license status rc=0 (rc={r.returncode})")
    check("标准版" in (r.stdout or "") or "STANDARD" in (r.stdout or ""),
          f"CLI status 显 STANDARD: {r.stdout[:200]!r}")

    # license status --json
    r = _run_cli(["-m", "app.cli", "license", "status", "--json"])
    check(r.returncode == 0, f"CLI status --json rc=0 (rc={r.returncode})")
    try:
        j = json.loads(r.stdout or "{}")
        check(j.get("tier") in ("standard", "pro"), f"--json tier={j.get('tier')}")
        check("features" in j and len(j["features"]) >= 10, "--json 含 features 列表")
    except Exception as e:
        check(False, f"CLI status --json 解析失败: {e}")

    # license machine
    r = _run_cli(["-m", "app.cli", "license", "machine"])
    check(r.returncode == 0, f"CLI machine rc=0 (rc={r.returncode})")
    check("机器码" in (r.stdout or ""), f"CLI machine 显 '机器码'")

    # license generate (万能)
    r = _run_cli(["-m", "app.cli", "license", "generate", "--days", "30"])
    check(r.returncode == 0, f"CLI generate rc=0 (rc={r.returncode})")
    stdout = r.stdout or ""
    # 抓出 NV- 开头的 key (4段-4段-4段-4段 = 19 字符)
    import re
    m = re.search(r"NV-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}", stdout)
    check(m is not None, f"CLI generate 输出 key: {stdout[:300]!r}")
    generated_key = m.group(0) if m else None

    # license activate --key <generated>
    if generated_key:
        r = _run_cli(["-m", "app.cli", "license", "activate", "--key", generated_key])
        check(r.returncode == 0, f"CLI activate rc=0 (rc={r.returncode}, stderr={r.stderr[:200]!r})")
        check("激活成功" in (r.stdout or ""), f"CLI activate 显成功: {r.stdout[:200]!r}")

        # 状态应升 PRO
        r = _run_cli(["-m", "app.cli", "license", "status"])
        check("🥇" in (r.stdout or "") or "专业版" in (r.stdout or "") or "PREMIUM" in (r.stdout or "").upper(),
              f"激活后 status 显 PRO/PREMIUM: {r.stdout[:200]!r}")

    # feature list
    r = _run_cli(["-m", "app.cli", "feature", "list"])
    check(r.returncode == 0, f"CLI feature list rc=0 (rc={r.returncode})")
    check("ai.critic" in (r.stdout or ""), f"CLI feature list 含 ai.critic")

    # feature list --json
    r = _run_cli(["-m", "app.cli", "feature", "list", "--json"])
    try:
        j = json.loads(r.stdout or "{}")
        check(len(j.get("features", [])) >= 10, f"CLI feature --json {len(j.get('features', []))} features")
    except Exception as e:
        check(False, f"CLI feature list --json 解析失败: {e}")

    # feature check (锁的 - 标准版下; 但已激活, 应该解锁)
    r = _run_cli(["-m", "app.cli", "feature", "check", "--feature-id", "ai.critic"])
    # 升 PRO 后应该 OK
    if "已解锁" in (r.stdout or ""):
        check(r.returncode == 0, "feature check ai.critic 解锁 → rc=0")
    else:
        # 仍 STANDARD (生成/激活失败) → 应该 rc != 0
        check(r.returncode != 0, f"feature check ai.critic 锁 → rc!=0 (rc={r.returncode})")

    # feature check 不存在
    r = _run_cli(["-m", "app.cli", "feature", "check", "--feature-id", "nope.feature"])
    check(r.returncode != 0, f"feature check nope → rc!=0 (rc={r.returncode})")

    # license deactivate --confirm
    r = _run_cli(["-m", "app.cli", "license", "deactivate"])
    check(r.returncode != 0, "CLI deactivate 不加 --confirm → rc!=0")

    r = _run_cli(["-m", "app.cli", "license", "deactivate", "--confirm"])
    check(r.returncode == 0, f"CLI deactivate --confirm rc=0 (rc={r.returncode})")
    check("已降级" in (r.stdout or ""), f"CLI deactivate 显 '已降级': {r.stdout[:200]!r}")

    # 清理
    _lic.deactivate()


# ============================================================
# Part 7: HTTP 端点
# ============================================================
def part7_http() -> None:
    section("[Part 7] HTTP 端点 (license + feature)")
    from app.services import license as _lic
    _lic.deactivate()
    from app.extension_api.http_bridge import start_server, _ROUTES

    # 路由注册
    check(("GET", "/license/status") in _ROUTES, "/license/status 注册")
    check(("POST", "/license/activate") in _ROUTES, "/license/activate 注册")
    check(("POST", "/license/deactivate") in _ROUTES, "/license/deactivate 注册")
    check(("GET", "/license/machine") in _ROUTES, "/license/machine 注册")
    check(("GET", "/feature/list") in _ROUTES, "/feature/list 注册")
    check(("GET", "/feature/check") in _ROUTES, "/feature/check 注册")

    # 起 server
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = start_server("127.0.0.1", port)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"

    def _get(path):
        return urllib.request.urlopen(base + path, timeout=5).read().decode("utf-8")

    def _post(path, body):
        req = urllib.request.Request(
            base + path, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        return urllib.request.urlopen(req, timeout=10).read().decode("utf-8")

    try:
        # GET /license/status (标准版)
        r = _get("/license/status")
        j = json.loads(r)
        check(j.get("ok") is True, "GET /license/status ok=True")
        check(j.get("tier") in ("standard", "pro"), f"/license/status tier={j.get('tier')}")
        check(j["license"]["status"] == "standard", f"license.status=standard, got={j['license']['status']}")
        check(len(j["features"]) >= 10, f"features 数量 {len(j['features'])}")

        # GET /license/machine
        r = _get("/license/machine")
        j = json.loads(r)
        check(j.get("ok") is True, "GET /license/machine ok=True")
        check(len(j.get("machine_code", "")) == 8, f"machine_code 长度: {j.get('machine_code')}")

        # POST /license/activate 错 key
        r = _post("/license/activate", {"key": "NV-XXXX-XXXX-XXXX-XXXX"})
        j = json.loads(r)
        check(j.get("ok") is False, "POST /license/activate 错 key → ok=False")

        # POST /license/activate 空 key
        r = _post("/license/activate", {"key": ""})
        j = json.loads(r)
        check(j.get("ok") is False, "POST /license/activate 空 key → ok=False")

        # POST /license/activate 缺 key
        r = _post("/license/activate", {})
        j = json.loads(r)
        check(j.get("ok") is False, "POST /license/activate 缺 key → ok=False")

        # POST /license/activate universal (从 license 模块拿白名单)
        from app.services.license import UNIVERSAL_KEYS
        uk = UNIVERSAL_KEYS[0]
        r = _post("/license/activate", {"key": uk})
        j = json.loads(r)
        check(j.get("ok") is True, f"POST /license/activate universal ok=True (err={j.get('error_msg')})")
        check(j.get("status") == "premium", f"激活后 status=premium, got={j.get('status')}")

        # 状态升 PRO
        r = _get("/license/status")
        j = json.loads(r)
        check(j.get("tier") == "pro", f"激活后 tier=pro, got={j.get('tier')}")
        # 验证 ai.critic 解锁
        pro_count = sum(1 for f in j["features"] if f["unlocked"])
        check(pro_count > 15, f"激活后 unlocked 数量 {pro_count} > 15")

        # GET /feature/list
        r = _get("/feature/list")
        j = json.loads(r)
        check(j.get("ok") is True, "GET /feature/list ok=True")
        check(j.get("tier") == "pro", f"/feature/list tier=pro, got={j.get('tier')}")

        # GET /feature/check?feature_id=ai.critic (已解锁)
        r = _get("/feature/check?feature_id=ai.critic")
        j = json.loads(r)
        check(j.get("ok") is True, "GET /feature/check ok=True")
        check(j.get("unlocked") is True, f"ai.critic unlocked=True, got={j.get('unlocked')}")

        # GET /feature/check 缺 feature_id
        r = _get("/feature/check")
        j = json.loads(r)
        check(j.get("ok") is False, "/feature/check 缺 feature_id → ok=False")

        # GET /feature/check 不存在
        r = _get("/feature/check?feature_id=nope")
        j = json.loads(r)
        check(j.get("ok") is False, "/feature/check nope → ok=False")

        # POST /license/deactivate
        r = _post("/license/deactivate", {})
        j = json.loads(r)
        check(j.get("ok") is True, "POST /license/deactivate ok=True")
        check(j.get("status") == "standard", f"deactivate 后 status=standard, got={j.get('status')}")

        # 验证降级 → 锁回去
        r = _get("/feature/check?feature_id=ai.critic")
        j = json.loads(r)
        check(j.get("unlocked") is False, f"deactivate 后 ai.critic unlocked=False, got={j.get('unlocked')}")

        # 回归 /health
        r = _get("/health")
        j = json.loads(r)
        check(j.get("ok") is True, "GET /health 仍 OK")

    finally:
        server.shutdown()
        server.server_close()
        _lic.deactivate()


# ============================================================
# Part 8: 集成 (CLI + HTTP + Service 全链路)
# ============================================================
def part8_integration() -> None:
    section("[Part 8] 集成: CLI generate → activate → HTTP check → deactivate")
    from app.services import license as _lic
    _lic.deactivate()

    # 1) CLI 生成 universal key
    r = _run_cli(["-m", "app.cli", "license", "generate", "--days", "0", "--json"])
    check(r.returncode == 0, f"CLI generate --json rc=0 (rc={r.returncode}, stderr={r.stderr[:200]!r})")
    # CLI 可能先打印提示行, 从 stdout 提取 JSON 段 ({...})
    json_text = ""
    if r.stdout:
        start = r.stdout.find("{")
        end = r.stdout.rfind("}")
        if start != -1 and end != -1 and end > start:
            json_text = r.stdout[start:end + 1]
    try:
        gen = json.loads(json_text or "{}")
        key = gen.get("key", "")
        check(key.startswith("NV-"), f"生成 key 格式: {key!r} (stdout={r.stdout[:200]!r})")
    except Exception as e:
        check(False, f"generate --json 解析失败: {e}, stdout={r.stdout[:200]!r}, stderr={r.stderr[:200]!r}")
        return

    # 2) CLI activate
    r = _run_cli(["-m", "app.cli", "license", "activate", "--key", key])
    check(r.returncode == 0, f"CLI activate rc=0 (rc={r.returncode})")

    # 3) 通过 in-process 验证 tier
    from app.services.feature_gate import get_tier, check_feature, Tier
    _lic.reset_cache()
    check(get_tier() == Tier.PRO, f"激活后 tier=PRO, got={get_tier()}")

    # 4) 验证 PRO 功能解锁
    pro_features = ["ai.critic", "export.epub", "export.cover",
                    "ai.router.parallel", "ai.cache", "publish.oneclick",
                    "subtext.auto"]
    unlocked_count = 0
    for fid in pro_features:
        if check_feature(fid):
            unlocked_count += 1
    check(unlocked_count == len(pro_features),
          f"PRO 功能全部解锁 ({unlocked_count}/{len(pro_features)})")

    # 5) CLI deactivate
    r = _run_cli(["-m", "app.cli", "license", "deactivate", "--confirm"])
    check(r.returncode == 0, f"CLI deactivate rc=0 (rc={r.returncode})")
    _lic.reset_cache()
    check(get_tier() == Tier.STANDARD, f"降级后 tier=STANDARD, got={get_tier()}")

    # 6) 锁回去
    for fid in pro_features:
        if check_feature(fid):
            check(False, f"降级后 {fid} 应该锁")
    check(True, "降级后所有 PRO 功能锁回去")

    # 7) FREE 功能始终解锁
    free_features = ["core.editor", "core.project", "core.chapter.create"]
    for fid in free_features:
        if not check_feature(fid):
            check(False, f"FREE 功能 {fid} 应该一直解锁")
    check(True, "FREE 功能跨 tier 始终解锁")

    # 清理
    _lic.deactivate()


# ============================================================
# Part 9: 错误路径
# ============================================================
def part9_errors() -> None:
    section("[Part 9] 错误路径 & 边界")
    from app.services import license as _lic
    from app.services.license import (
        validate_key, LicenseStatus, LicenseError, LicenseInvalidError,
    )
    from app.services.feature_gate import (
        require_tier, FeatureLockedError, get_feature_info, list_features,
    )

    # 各种错 key
    for bad in ("", "  ", "NV-", "NV-XXXX", "NV-XXXX-XXXX-XXXX-XXXX",
                "NV-1234-5678-9012-3456",  # 错 alphabet? 试试
                "INVALID-XXXX-XXXX-XXXX-XXXX"):
        r = validate_key(bad)
        check(not r.valid, f"错 key {bad!r} 拒绝")

    # get_feature_info 不存在不抛
    check(get_feature_info("totally.fake") is None, "不存在的 feature 不抛")

    # list_features 总返回
    feats = list_features()
    check(len(feats) == len(_lic.FEATURE_TIERS) if hasattr(_lic, "FEATURE_TIERS") else len(feats) > 0,
          f"list_features 数量 > 0 (got {len(feats)})")
    # 所有项都是 (str, FeatureInfo, bool)
    for item in feats:
        if not (isinstance(item, tuple) and len(item) == 3 and isinstance(item[2], bool)):
            check(False, f"list_features 项格式错: {item}")
            break
    else:
        check(True, "list_features 项格式都正确")

    # require_tier 装饰器: feature_id 未知
    try:
        @require_tier("totally.fake.feature")
        def fake_fn():
            return "ok"
        fake_fn()
        check(False, "未知 feature 应该抛")
    except FeatureLockedError as e:
        check(e.feature_id == "totally.fake.feature", "未知 feature 抛 FeatureLockedError")


# ============================================================
# main
# ============================================================
def main() -> int:
    print("M9-C 用户系统 + 付费解锁 smoke 测试\n")
    parts = [
        ("Part 1 feature_gate 基础", part1_feature_gate),
        ("Part 2 默认 tier", part2_default_tier),
        ("Part 3 license 工具", part3_license_util),
        ("Part 4 license 持久化", part4_license_persist),
        ("Part 5 装饰器", part5_decorator),
        ("Part 6 CLI", part6_cli),
        ("Part 7 HTTP", part7_http),
        ("Part 8 集成", part8_integration),
        ("Part 9 错误路径", part9_errors),
    ]
    for name, fn in parts:
        try:
            fn()
        except Exception as e:
            check(False, f"{name} 异常: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n========== {_passed} passed / {_failed} failed ==========")
    if _errors:
        print("\n失败项:")
        for e in _errors:
            print(f"  - {e}")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
