"""
API key 加密存储 (Phase 3 M3).

用 base64 简单混淆 + 平台 keyring (可选).

策略:
  1. 优先用 keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service)
  2. 失败回退 base64 (仅混淆, 不算真加密 - 但本地单机防意外看)
  3. 在 app_settings.json 中只存 "ENC:xxx" / "B64:xxx" 前缀的密文, 明文不落盘

用法:
    from app.services.keyring_store import encrypt_key, decrypt_key
    enc = encrypt_key("sk-xxx")
    api_key = decrypt_key(enc)  # -> "sk-xxx"
"""
from __future__ import annotations
import base64
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)

_KEYRING_SERVICE = "NovelWriterPure"
_KEYRING_USER_PREFIX = "llm_api_key:"
_USE_KEYRING = True  # 全局开关 (导入失败会自动回退)


# --------------------------------------------------------------------- #
# Keyring 探测 (best-effort, 延迟到首次使用)
# --------------------------------------------------------------------- #

_KEYRING_AVAILABLE: Optional[bool] = None
_keyring = None


def _ensure_keyring() -> bool:
    """延迟探测 keyring 可用性 (首次调用时, 非 import 时)."""
    global _USE_KEYRING, _KEYRING_AVAILABLE, _keyring
    if _KEYRING_AVAILABLE is not None:
        return _KEYRING_AVAILABLE
    try:
        import keyring as _kr_mod  # type: ignore
        _keyring = _kr_mod.get_keyring()
        _KEYRING_AVAILABLE = True
    except Exception as e:
        log.warning(f"[keyring] not available, fallback to base64: {e}")
        _KEYRING_AVAILABLE = False
        _USE_KEYRING = False
    return _KEYRING_AVAILABLE


# --------------------------------------------------------------------- #
# 加密 / 解密
# --------------------------------------------------------------------- #

def _b64_encrypt(plain: str) -> str:
    return "B64:" + base64.b64encode(plain.encode("utf-8")).decode("ascii")


def _b64_decrypt(token: str) -> str:
    raw = token[len("B64:"):]
    return base64.b64decode(raw.encode("ascii")).decode("utf-8")


def _kr_encrypt(provider_name: str, plain: str) -> str:
    if not _ensure_keyring():
        return _b64_encrypt(plain)
    try:
        _keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER_PREFIX + provider_name, plain)
        return f"KR:{provider_name}"
    except Exception as e:
        log.warning(f"[keyring] set_password failed: {e}, fallback to base64")
        return _b64_encrypt(plain)


def _kr_decrypt(token: str) -> str:
    if not token.startswith("KR:"):
        return _b64_decrypt(token)
    name = token[len("KR:"):]
    if not _ensure_keyring():
        raise RuntimeError("keyring not available but token requires it")
    plain = _keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER_PREFIX + name)
    if plain is None:
        raise RuntimeError(f"keyring entry not found for {name}")
    return plain


def encrypt_key(plain: str, *, provider_name: str = "default") -> str:
    """加密 API key. 返回带前缀的密文 (KR: / B64:).

    - plain="" -> 返回空字符串
    - 已加密的 (KR:/B64:) 透传
    """
    if not plain:
        return ""
    if plain.startswith(("KR:", "B64:")):
        return plain
    return _kr_encrypt(provider_name, plain)


def decrypt_key(token: str) -> str:
    """解密密文 -> 明文. 未加密的 (无前缀) 透传 (兼容老数据)."""
    if not token:
        return ""
    if token.startswith(("KR:", "B64:")):
        return _kr_decrypt(token)
    # 明文 (无前缀) - 直接返回, 兼容老数据, 但 log warning 提醒升级
    log.warning("[keyring] token without prefix, treating as plaintext. Re-save to encrypt.")
    return token
