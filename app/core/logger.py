"""
日志系统 (B6: 完整做)
- 项目文件夹下 logs/ 子目录
- 每天 1 个日志文件
- 自动清理 N 天前的日志 (N 从 config 读)
- 控制台 + 文件双输出
"""
from __future__ import annotations
import logging
import logging.handlers
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from app.core import config as _app_config
from app.core.version import APP_NAME

# 全局 logger 单例
_root_logger: Optional[logging.Logger] = None
_log_dir: Optional[Path] = None
_log_retention_days = 7


def setup(
    log_dir: str | Path,
    level: int = logging.INFO,
    retention_days: Optional[int] = None,
    max_bytes: Optional[int] = None,
    console: bool = True,
) -> logging.Logger:
    """
    初始化日志系统。
    - log_dir: 日志目录 (项目文件夹下的 logs/)
    - retention_days: 保留天数 (None = 从 config 读, 默认 7)
    - max_bytes: 单文件最大字节 (None = 从 config 读, 默认 10MB)
    """
    global _root_logger, _log_dir, _log_retention_days

    # 缺省从 config 读 (避免硬编码 7 / 10MB)
    if retention_days is None:
        try:
            retention_days = _app_config.get_log_retention_days()
        except Exception:
            retention_days = 7
    if max_bytes is None:
        try:
            max_bytes = _app_config.get_log_max_bytes()
        except Exception:
            max_bytes = 10 * 1024 * 1024

    _log_dir = Path(log_dir)
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_retention_days = retention_days

    logger = logging.getLogger(APP_NAME)
    logger.setLevel(level)
    logger.propagate = False

    # 清理已有 handler (重复 setup)
    for h in list(logger.handlers):
        logger.removeHandler(h)

    # 文件 handler (按天轮转)
    log_file = _log_dir / f"{APP_NAME}_{datetime.now():%Y%m%d}.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=0,              # 按天轮转 (不用按大小)
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    # 控制台 handler
    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_fmt = logging.Formatter(
            "[%(levelname)s] %(message)s",
        )
        console_handler.setFormatter(console_fmt)
        logger.addHandler(console_handler)

    _root_logger = logger
    logger.info("=" * 60)
    logger.info("日志系统初始化: %s", log_file)
    logger.info("=" * 60)

    # 启动时清理旧日志
    cleanup_old_logs()

    return logger


def get_logger(name: str = "") -> logging.Logger:
    """获取 logger (子模块用)。"""
    if _root_logger is None:
        # 兜底：未 init 就调，先创建一个 stderr-only 的
        logging.basicConfig(
            level=logging.INFO,
            format="[%(levelname)s] %(message)s",
        )
    base = APP_NAME if _root_logger else ""
    return logging.getLogger(f"{base}.{name}" if name else base)


def cleanup_old_logs() -> int:
    """
    清理 _log_retention_days 天前的日志文件。
    返回清理的文件数。
    """
    if _log_dir is None or not _log_dir.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=_log_retention_days)
    removed = 0
    for log_file in _log_dir.glob(f"{APP_NAME}_*.log*"):
        try:
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if mtime < cutoff:
                log_file.unlink()
                removed += 1
        except OSError:
            pass
    if removed and _root_logger:
        _root_logger.info("已清理 %d 个旧日志文件 (>%d 天)", removed, _log_retention_days)
    return removed


def get_log_dir() -> Optional[Path]:
    return _log_dir


def shutdown() -> None:
    """关闭日志 (退出时调)。"""
    global _root_logger
    if _root_logger:
        for h in list(_root_logger.handlers):
            h.close()
            _root_logger.removeHandler(h)
        _root_logger = None
