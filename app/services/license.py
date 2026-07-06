"""
B5 授权系统 (License Manager)
业务场景: 标准版永久免费, 高级版需 key 解锁插件
  - 用户点 "升级高级版" → 输入 key → 验证通过 → 解锁
  - 机器码 + 网络时间算 key
  - 万能 key 留给用户+朋友

设计:
  - 机器码: MAC 地址 + 主机名 + OS → SHA256 → 8 字节短码 (16 字符 base32)
  - 网络时间: NTP 池 (pool.ntp.org) → 失败回退本地时间
  - key 格式: NV-XXXX-XXXX-XXXX-XXXX (4 段 4 字符, 共 16 字符有效载荷)
  - key 内容: [version(1B)] [expire_days(2B)] [machine_hash(4B)] [reserved(1B)]
              + [HMAC-SHA256 截 2B]  → 编码为 10 字节 → 16 字符 base32 (5 位/字符)
  - 标准版: 无 key, 永久免费, 高级插件不可用
  - 高级版: 有效 key → 解锁插件
  - 万能 key: 预置特殊字符串 (明文), 任何机器 + 任何时间都通过

存储: 用户的 key 加密存到 app_settings.kv (B5.lic.* 命名空间), 启动时自动加载
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import platform
import re
import socket
import struct
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

_logger = logging.getLogger("NovelWriter.services.license")


# ============================================================
# 常量
# ============================================================

# key 格式
KEY_PREFIX = "NV-"
KEY_SEGMENT_LEN = 4
KEY_SEGMENT_COUNT = 4
KEY_BODY_LEN = KEY_SEGMENT_LEN * KEY_SEGMENT_COUNT  # 16 chars

# key 编码字符 (去歧义 base32 字符)
KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去掉 I O 0 1

# 版本
VERSION_STANDARD = "standard"
VERSION_PREMIUM = "premium"

# 万能 key (明文, 留 1 个 + 内部测试用 1 个, 不放 Git 仓防滥用)
# 注: 实际产品可放用户配置文件
UNIVERSAL_KEYS = [
    "NV-UNIV-ERSL-FRIE-NDXS",   # 用户+朋友通用 (预置)
    "NV-UNIV-ERSL-TEST-LOCAL",   # 内部测试
]

# 时间基准 (key 编码时把"距基准的天数"压缩到 2 字节)
def _epoch_base() -> int:
    import datetime
    return (datetime.date(2026, 1, 1) - datetime.date(1970, 1, 1)).days


EPOCH_BASE = _epoch_base()  # 2026-01-01 = 20089 天从 1970-01-01


# ============================================================
# 错误
# ============================================================

class LicenseError(Exception):
    pass


class LicenseInvalidError(LicenseError):
    pass


class LicenseExpiredError(LicenseError):
    pass


class LicenseMachineMismatchError(LicenseError):
    pass


# ============================================================
# 版次
# ============================================================

class LicenseStatus(str, Enum):
    """授权状态."""
    UNKNOWN = "unknown"           # 未检测 (刚启动)
    STANDARD = "standard"         # 标准版 (默认, 永久免费)
    PREMIUM = "premium"           # 高级版 (key 通过)
    EXPIRED = "expired"           # key 已过期
    INVALID = "invalid"           # key 无效
    MACHINE_MISMATCH = "machine_mismatch"  # key 机器码不匹配


@dataclass
class LicenseInfo:
    """当前授权信息."""
    status: LicenseStatus
    version: str                          # standard / premium
    key: str = ""
    machine_code: str = ""
    expire_date: str = ""                 # YYYY-MM-DD (空 = 永久)
    remaining_days: int = -1              # -1 = 永久, 0 = 今天到期
    activated_at: str = ""
    error_msg: str = ""


# ============================================================
# 工具
# ============================================================

def datetime_to_days(year: int, month: int, day: int) -> int:
    """日期转 1970-01-01 起的天数."""
    import datetime
    d = datetime.date(year, month, day)
    return (d - datetime.date(1970, 1, 1)).days


def days_to_date_str(days: int) -> str:
    """1970-01-01 起的天数 → 'YYYY-MM-DD'."""
    import datetime
    if days < 0:
        return ""
    try:
        d = datetime.date(1970, 1, 1) + datetime.timedelta(days=days)
        return d.strftime("%Y-%m-%d")
    except Exception:
        return ""


# 编码: 8 字节 → KEY_ALPHABET 字符 (类似 base32, 5 位/字符)
# 用 KEY_ALPHABET 替代标准 base32 字母表 (去歧义, 用户易读)
_CHAR_TO_VAL: dict[str, int] = {c: i for i, c in enumerate(KEY_ALPHABET)}


def _b32encode_custom(data: bytes) -> str:
    """真正的 base32 编码 (5 位/字符, 大端).

    - 输入: N 字节 (任何长度)
    - 输出: ceil(N*8/5) 字符
    - 末位不足 5 位 → 补 0
    """
    n_bits = len(data) * 8
    n_chars = (n_bits + 4) // 5  # 向上取整
    out: list[str] = []
    # 把所有字节拼成一个 int, 然后每 5 位取一次
    value = int.from_bytes(data, "big") << ((-n_bits) % 5)  # 末尾补 0
    for i in range(n_chars - 1, -1, -1):
        out.append(KEY_ALPHABET[(value >> (i * 5)) & 0x1F])
    return "".join(out)


def _b32decode_custom(s: str) -> bytes:
    """真正的 base32 解码 (5 位/字符 → 字节, 大端).

    - 字符数 N → 字节数 = (N*5) // 8 (向下取整, 末位补的 0 截掉)
    - 容错: 不在 KEY_ALPHABET 的字符视为 0
    - 注: 编码和解码必须用"5 的整数倍位数"的数据 (如 40/80 位), 否则有 1-7 位 padding
          会丢失. 当前系统所有数据都是 5 字节 (40 位) 或 10 字节 (80 位) 倍数.
    """
    s = s.upper()
    n_bits = len(s) * 5
    n_bytes = n_bits // 8
    value = 0
    for c in s:
        idx = _CHAR_TO_VAL.get(c, 0)
        value = (value << 5) | (idx & 0x1F)
    return value.to_bytes(n_bytes, "big")


# ============================================================
# 机器码
# ============================================================

def _get_mac_address() -> str:
    """取 MAC 地址 (Windows 兼容, 失败回退 00:00:00:00:00:00)."""
    try:
        mac = uuid_getnode()
        if mac and (mac >> 40) % 2 == 0:  # 不是随机 MAC
            return ":".join(f"{(mac >> i) & 0xff:02x}" for i in range(0, 48, 8))
    except Exception:
        pass
    return "00:00:00:00:00:00"


def uuid_getnode() -> Optional[int]:
    """用 uuid.getnode() 拿 MAC (原始整数)."""
    import uuid
    try:
        return uuid.getnode()
    except Exception:
        return None


def get_machine_code() -> str:
    """生成机器码 (5 字节短码 = 8 字符 base32).

    来源: MAC + 主机名 + OS 信息 → SHA256 → 取前 5 字节 → 8 字符 base32 (40 位)
    注: 必须是 5 的整数倍位数才能干净 round-trip (40 位 = 8 字符).
    """
    try:
        mac = _get_mac_address()
        hostname = socket.gethostname() or "unknown"
        os_info = f"{platform.system()}-{platform.release()}"
        raw = f"{mac}|{hostname}|{os_info}".encode("utf-8")
        h = hashlib.sha256(raw).digest()[:5]  # 5 字节 (40 位)
        return _b32encode_custom(h).upper()
    except Exception as e:
        _logger.warning("[license] 取机器码失败: %s", e)
        return "00000000"


# ============================================================
# 网络时间 (NTP)
# ============================================================

_NTP_SERVERS = [
    "pool.ntp.org",
    "time.windows.com",
    "time.nist.gov",
]


def get_network_time() -> float:
    """取网络时间 (Unix 时间戳秒). 失败回退本地时间.

    注: 不阻塞太久 (单次 2s 超时, 失败用本地).
    """
    import socket as _socket
    for server in _NTP_SERVERS:
        try:
            _socket.setdefaulttimeout(2.0)
            client = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            try:
                # NTP 协议: 48 字节包, 前 4 字节是 LI/VN/Mode 等
                pkt = b"\x1b" + 47 * b"\0"
                client.sendto(pkt, (server, 123))
                data, _ = client.recvfrom(1024)
                if len(data) >= 48:
                    # 解析 NTP 时间戳 (从 1900-01-01 起的秒)
                    ts = struct.unpack("!I", data[40:44])[0]
                    ntp_epoch_offset = 2208988800  # 1900-1970 差值
                    return ts - ntp_epoch_offset
            finally:
                client.close()
        except Exception as e:
            _logger.debug("[license] NTP %s 失败: %s", server, e)
            continue
    # 失败回退
    return time.time()


# ============================================================
# 密钥派生
# ============================================================

# 内部 HMAC 密钥 (产品方持有, 用于签 key)
# 注: 这不是真安全 (源码可见), 真正的授权需要联网验证
# 这里只做"离线防破解"层, 高级安全由未来的"联网激活"补
_SECRET = b"NVPure-LicSecret-2026-v1-fixed-salt-donot-share"


def _sign(payload: bytes) -> bytes:
    """对 payload 签名 (HMAC-SHA256, 截 2 字节 = 16 位).

    注: 这是非密码学强度的"防篡改"层 (产品定位是离线桌面工具,
    真正安全靠联网激活或 server 校验). 2 字节提供 65536 种可能,
    足以挡住普通用户改 1 字符就破解.
    """
    return hmac.new(_SECRET, payload, hashlib.sha256).digest()[:2]


# ============================================================
# Key 编码 / 解码
# ============================================================

def _make_key_payload(version: str, expire_days: int, machine_hash: str) -> bytes:
    """构造 key 载荷 (8 字节):
      [version(1B)] [expire_days(2B, BE)] [machine_hash(5B)]
    """
    ver = 1 if version == VERSION_PREMIUM else 0
    payload = bytearray(8)
    payload[0] = ver
    # 2 字节存 expire_days (相对 EPOCH_BASE, 0 = 永久, max = 65535)
    days_offset = expire_days - EPOCH_BASE if expire_days > 0 else 0
    if days_offset < 0:
        days_offset = 0
    if days_offset > 65535:
        days_offset = 65535
    struct.pack_into("!H", payload, 1, days_offset)
    # 5 字节存机器码哈希 (取前 5 字节, 与 get_machine_code 一致)
    mh = _b32decode_custom(machine_hash)[:5]
    payload[3:8] = mh
    # 注: 1+2+5=8 字节
    return bytes(payload)


def _parse_key_payload(data: bytes) -> tuple[str, int, str]:
    """解析 8 字节载荷 → (version, expire_days, machine_hash).

    注: 只接受 version=0 (standard) 或 1 (premium), 其他视为非法.
    """
    if len(data) < 8:
        raise LicenseInvalidError("key 载荷长度不足")
    ver = data[0]
    if ver not in (0, 1):
        raise LicenseInvalidError(f"非法 version 字节 ({ver}), key 损坏")
    version = VERSION_PREMIUM if ver == 1 else VERSION_STANDARD
    days_offset = struct.unpack_from("!H", data, 1)[0]
    expire_days = EPOCH_BASE + days_offset if days_offset > 0 else 0
    mh = data[3:8]
    machine_hash = _b32encode_custom(mh).upper()
    return version, expire_days, machine_hash


# key 编码常量 (适配 16 字符格式: 4 段 × 4 字符)
# 14 字节载荷 + 2 字节 sig = 16 字节 → 16 字符 base32-style
KEY_SIG_LEN = 2
KEY_TOTAL_LEN = 14 + KEY_SIG_LEN  # 16 字节


def format_key(raw_chars: str) -> str:
    """把 16 字符分段 → NV-XXXX-XXXX-XXXX-XXXX 格式."""
    s = raw_chars.replace("-", "").replace(" ", "").upper()
    if len(s) < KEY_BODY_LEN:
        s = s + "0" * (KEY_BODY_LEN - len(s))
    s = s[:KEY_BODY_LEN]
    parts = [s[i:i+KEY_SEGMENT_LEN] for i in range(0, KEY_BODY_LEN, KEY_SEGMENT_LEN)]
    return KEY_PREFIX + "-".join(parts)


def parse_key(key: str) -> bytes:
    """key → 10 字节 (8 载荷 + 2 签名, 经 base32 解码自 16 字符)."""
    s = key.strip().upper()
    if s.startswith(KEY_PREFIX):
        s = s[len(KEY_PREFIX):]
    s = s.replace("-", "").replace(" ", "")
    if len(s) < KEY_BODY_LEN:
        raise LicenseInvalidError(f"key 长度不足 (需要 {KEY_BODY_LEN} 字符)")
    s = s[:KEY_BODY_LEN]
    body = _b32decode_custom(s)  # 16 字符 → 10 字节
    return body


# ============================================================
# 生成 key (供产品方 / 内部测试用)
# ============================================================

def generate_key(machine_code: Optional[str] = None,
                  *, days: int = 365, version: str = VERSION_PREMIUM) -> str:
    """生成 key (供产品方/调试用, 不暴露给用户).

    - machine_code: 留空 = 万能 (任何机器可用)
    - days: 0 = 永久, >0 = 从今天起 N 天
    """
    if machine_code is None or machine_code == "":
        # 万能 key: 用全 0 机器码 + 不校验机器
        machine_code = "00000000"
        universal = True
    else:
        universal = False
    # 过期时间
    if days <= 0:
        expire_days = 0  # 永久
    else:
        net_ts = get_network_time()
        expire_days = int(net_ts // 86400) + days
    # 构造载荷 (14 字节)
    payload = _make_key_payload(version, expire_days, machine_code)
    # 签名 (2 字节)
    sig = _sign(payload + (b"\x01" if universal else b"\x00"))
    # 拼接 16 字节
    full = payload + sig
    # 编码为 KEY_BODY_LEN 字符
    chars = _b32encode_custom(full)
    return format_key(chars)


# ============================================================
# 验证 key
# ============================================================

@dataclass
class ValidationResult:
    valid: bool
    status: LicenseStatus
    version: str = VERSION_STANDARD
    machine_code: str = ""
    expire_date: str = ""
    remaining_days: int = -1
    error_msg: str = ""


def validate_key(key: str, *, current_machine: Optional[str] = None) -> ValidationResult:
    """验证 key.

    - 万能 key → 直接通过
    - 普通 key → 校验 签名 + 机器码 + 过期时间
    """
    if not key or not key.strip():
        return ValidationResult(valid=False, status=LicenseStatus.INVALID, error_msg="key 为空")

    s = key.strip().upper()
    # 1) 万能 key 优先
    if s in [k.upper() for k in UNIVERSAL_KEYS]:
        return ValidationResult(
            valid=True, status=LicenseStatus.PREMIUM,
            version=VERSION_PREMIUM,
            machine_code="UNIVERSAL",
            expire_date="永久",
            remaining_days=-1,
            error_msg="",
        )

    # 2) 解析
    try:
        body = parse_key(s)
    except LicenseInvalidError as e:
        return ValidationResult(valid=False, status=LicenseStatus.INVALID, error_msg=str(e))
    if len(body) < 10:
        return ValidationResult(valid=False, status=LicenseStatus.INVALID,
                                error_msg=f"key 长度异常 ({len(body)} 字节)")

    payload = body[:8]
    sig = body[8:10]

    # 3) 校验签名 (先按 universal=False 试, 再试 universal=True)
    sig_ok = False
    is_universal = False
    for trial_universal in (False, True):
        expected = _sign(payload + (b"\x01" if trial_universal else b"\x00"))
        if hmac.compare_digest(sig, expected):
            sig_ok = True
            is_universal = trial_universal
            break
    if not sig_ok:
        return ValidationResult(valid=False, status=LicenseStatus.INVALID, error_msg="签名错误")

    # 4) 解析载荷
    try:
        version, expire_days, machine_hash = _parse_key_payload(payload)
    except LicenseInvalidError as e:
        return ValidationResult(valid=False, status=LicenseStatus.INVALID, error_msg=str(e))

    # 5) 校验机器码 (万能 key 跳过)
    if not is_universal:
        if current_machine is None:
            current_machine = get_machine_code()
        if machine_hash != current_machine:
            return ValidationResult(
                valid=False, status=LicenseStatus.MACHINE_MISMATCH,
                error_msg=f"key 与本机不匹配 (key={machine_hash}, this={current_machine})",
            )

    # 6) 校验过期
    net_ts = get_network_time()
    today_days = int(net_ts // 86400)
    if expire_days > 0 and today_days > expire_days:
        return ValidationResult(
            valid=False, status=LicenseStatus.EXPIRED,
            version=version, machine_code=machine_hash,
            expire_date=days_to_date_str(expire_days),
            remaining_days=0,
            error_msg=f"key 已过期 ({days_to_date_str(expire_days)})",
        )
    remaining = -1 if expire_days == 0 else max(0, expire_days - today_days)
    return ValidationResult(
        valid=True, status=LicenseStatus.PREMIUM,
        version=version, machine_code=machine_hash,
        expire_date=days_to_date_str(expire_days) if expire_days > 0 else "永久",
        remaining_days=remaining,
        error_msg="",
    )


# ============================================================
# 持久化 (存到 app_settings)
# ============================================================

SETTING_KEY = "license.key"
SETTING_STATUS = "license.status"
SETTING_VERSION = "license.version"
SETTING_ACTIVATED = "license.activated_at"
SETTING_EXPIRE = "license.expire_date"

# 标准版默认状态
DEFAULT_LICENSE = LicenseInfo(
    status=LicenseStatus.STANDARD,
    version=VERSION_STANDARD,
    key="", machine_code="",
    expire_date="永久", remaining_days=-1,
    activated_at="", error_msg="",
)


def load_license() -> LicenseInfo:
    """从 app_settings 加载当前授权信息. 无则返回标准版默认."""
    try:
        from app.services import app_setting_service
        key = app_setting_service.get(SETTING_KEY, default="")
        if not key:
            return LicenseInfo(
                status=LicenseStatus.STANDARD,
                version=VERSION_STANDARD,
                machine_code=get_machine_code(),
                expire_date="永久", remaining_days=-1,
            )
        # 验证
        result = validate_key(key)
        if result.valid:
            return LicenseInfo(
                status=result.status,
                version=result.version,
                key=key,
                machine_code=result.machine_code or get_machine_code(),
                expire_date=result.expire_date or "永久",
                remaining_days=result.remaining_days,
                activated_at=app_setting_service.get(SETTING_ACTIVATED, default=""),
                error_msg="",
            )
        return LicenseInfo(
            status=result.status,
            version=VERSION_STANDARD,
            key=key,
            machine_code=get_machine_code(),
            error_msg=result.error_msg,
        )
    except Exception as e:
        _logger.warning("[license] 加载失败: %s", e)
        return LicenseInfo(
            status=LicenseStatus.STANDARD,
            version=VERSION_STANDARD,
            machine_code=get_machine_code(),
            error_msg=str(e),
        )


def activate(key: str) -> LicenseInfo:
    """激活 key. 成功 → 持久化 + 返回 PREMIUM, 失败 → 返回错误状态.

    不会清掉旧 key (失败时保留以便排查).
    """
    global _default_info
    result = validate_key(key)
    info = LicenseInfo(
        status=result.status,
        version=result.version if result.valid else VERSION_STANDARD,
        key=key,
        machine_code=result.machine_code or get_machine_code(),
        expire_date=result.expire_date or "永久",
        remaining_days=result.remaining_days,
        error_msg=result.error_msg,
    )
    if result.valid:
        try:
            from app.services import app_setting_service
            app_setting_service.set(SETTING_KEY, key)
            app_setting_service.set(SETTING_STATUS, result.status.value)
            app_setting_service.set(SETTING_VERSION, result.version)
            app_setting_service.set(SETTING_EXPIRE, info.expire_date)
            app_setting_service.set(SETTING_ACTIVATED, time.strftime("%Y-%m-%d %H:%M:%S"))
            info.activated_at = time.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            _logger.warning("[license] 持久化失败: %s", e)
            info.error_msg = f"激活成功但持久化失败: {e}"
    # 关键: 激活/失败都重置缓存, 让 get_license() 重新读
    _default_info = None
    return info


def deactivate() -> LicenseInfo:
    """降级到标准版 (清掉 key)."""
    global _default_info
    try:
        from app.services import app_setting_service
        for k in (SETTING_KEY, SETTING_STATUS, SETTING_VERSION,
                  SETTING_ACTIVATED, SETTING_EXPIRE):
            app_setting_service.delete(k)
    except Exception as e:
        _logger.warning("[license] 清 key 失败: %s", e)
    _default_info = None  # 重置缓存
    return LicenseInfo(
        status=LicenseStatus.STANDARD,
        version=VERSION_STANDARD,
        machine_code=get_machine_code(),
        expire_date="永久", remaining_days=-1,
        activated_at="",
        error_msg="",
    )


def is_premium() -> bool:
    """是否高级版 (供插件门禁用)."""
    try:
        info = load_license()
        return info.status == LicenseStatus.PREMIUM
    except Exception:
        return False


def is_plugin_unlocked(plugin_id: str) -> bool:
    """某插件是否解锁 (供插件管理器门禁用). 标准版只解锁内置插件.

    解锁策略: 内置插件 (knowledge / tts / usage) 始终可用, 第三方插件需 PREMIUM.
    """
    BUILTIN_PLUGINS = {"knowledge_plugin", "tts_edge", "usage_analytics",
                       "ai_outline_gen", "knowledge_builtin", "knowledge_local"}
    if plugin_id in BUILTIN_PLUGINS:
        return True
    return is_premium()


# ============================================================
# 工厂
# ============================================================

_default_info: Optional[LicenseInfo] = None


def get_license() -> LicenseInfo:
    """当前授权信息 (带缓存)."""
    global _default_info
    if _default_info is None:
        _default_info = load_license()
    return _default_info


def reset_cache() -> None:
    """重置缓存 (供测试)."""
    global _default_info
    _default_info = None
