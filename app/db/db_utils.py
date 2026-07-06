"""
DB 工具函数（C6: 10+ 工具函数）
- JSON 序列化
- 时间戳处理
- 字典转 SQL 参数
- 哈希 / 路径 / 字符串清理
"""
from __future__ import annotations
import json
import hashlib
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


# ────────────────────── JSON 序列化 ──────────────────────

def to_json(obj: Any) -> str:
    """任意对象 → JSON 字符串（用于 SQLite 存）。"""
    return json.dumps(obj, ensure_ascii=False, default=str)


def from_json(text: str | None, default=None):
    """JSON 字符串 → Python 对象。失败返回 default。"""
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


# ────────────────────── 时间戳处理 ──────────────────────

def now_iso() -> str:
    """当前时间 ISO 格式。"""
    return datetime.now().isoformat()


def to_iso(dt: datetime | None) -> str:
    """datetime → ISO 字符串。None → 空串。"""
    return dt.isoformat() if dt else ""


def from_iso(text: str | None) -> datetime | None:
    """ISO 字符串 → datetime。失败返回 None。"""
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def format_relative(ts: str | datetime) -> str:
    """格式化为相对时间（"5 分钟前"）。"""
    if isinstance(ts, str):
        ts = from_iso(ts)
    if ts is None:
        return ""
    diff = (datetime.now() - ts).total_seconds()
    if diff < 60:
        return f"{int(diff)} 秒前"
    if diff < 3600:
        return f"{int(diff // 60)} 分钟前"
    if diff < 86400:
        return f"{int(diff // 3600)} 小时前"
    return f"{int(diff // 86400)} 天前"


# ────────────────────── 字典转 SQL 参数 ──────────────────────

def dict_to_params(d: dict) -> tuple:
    """dict → 元组（按插入顺序取 values）。"""
    return tuple(d.values())


def dict_to_placeholder(d: dict) -> str:
    """dict → "(?, ?, ?)" 占位符。"""
    return "(" + ", ".join(["?"] * len(d)) + ")"


# ────────────────────── 哈希 / ID ──────────────────────

def short_id(text: str = "", length: int = 8) -> str:
    """生成短 ID。空串则用时间戳。"""
    if not text:
        text = str(time.time_ns())
    return hashlib.md5(text.encode()).hexdigest()[:length]


# ────────────────────── 路径 / 文件大小 ──────────────────────

def ensure_dir(path: str | Path) -> Path:
    """确保目录存在（不存在就创建）。"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def format_size(num_bytes: int) -> str:
    """字节数 → 人类可读（"5.2 MB"）。"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


# ────────────────────── 字符串清理 ──────────────────────

def clean_text(text: str) -> str:
    """清理文本：去多余空白、去不可见字符。"""
    if not text:
        return ""
    # 去首尾空白
    text = text.strip()
    # 多余空白合并
    text = re.sub(r"\s+", " ", text)
    return text


def truncate(text: str, max_len: int = 100, suffix: str = "...") -> str:
    """截断文本（超出加 ...）。"""
    if not text or len(text) <= max_len:
        return text
    return text[: max_len - len(suffix)] + suffix


def count_words(text: str) -> int:
    """中英文混合字数统计（中文按 1 字/字，英文按 1 词/词）。"""
    if not text:
        return 0
    # 中文字符数
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    # 英文单词数
    english = len(re.findall(r"\b[a-zA-Z]+\b", text))
    return chinese + english
