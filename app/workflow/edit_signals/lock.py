"""
app/workflow/edit_signals/lock.py

ProjectLock - 文件锁, 防止多个 v4 实例同时操作同一项目信号 (§6.3).

Windows 用 msvcrt 模拟 fcntl (无 LOCK_NB 概念, 用 os.open + O_EXCL 占位).
跨平台: 优先 fcntl, 否则用 _WIN_LOCK 标记文件.
"""
from __future__ import annotations
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from .jsonl_store import SIGNALS_DIR

_logger = logging.getLogger("NovelWriter.edit_signals.lock")

# 信号目录锁
GLOBAL_LOCK_PATH = SIGNALS_DIR / "_lock"


class ProjectLock:
    """文件锁 (§6.3).

    优先 fcntl.flock (Unix/Mac).
    Windows 用 msvcrt 模拟 (open + LOCKING_EX).
    单实例写入: 锁住 _lock 文件 → 其他实例 detect 失败 → 弹窗.
    """

    def __init__(self, project_id, *, blocking: bool = False, timeout: float = 0.0):
        self.project_id = project_id
        self.lock_path = GLOBAL_LOCK_PATH
        self._fd: Optional[object] = None
        self._blocking = blocking
        self._timeout = float(timeout)
        self._is_windows = sys.platform == "win32"

    def acquire(self) -> bool:
        """非阻塞获取. 成功 True."""
        if self._is_windows:
            return self._acquire_windows()
        return self._acquire_unix()

    def _acquire_unix(self) -> bool:
        import fcntl
        try:
            self._fd = open(self.lock_path, "w", encoding="utf-8")
            self._fd.write(f"project_id={self.project_id}\n")
            self._fd.flush()
            op = fcntl.LOCK_EX
            if not self._blocking:
                op |= fcntl.LOCK_NB
            fcntl.flock(self._fd.fileno(), op)
            return True
        except (BlockingIOError, IOError, OSError):
            self._fd = None
            return False
        except Exception as e:
            _logger.warning("acquire_unix 失败: %s", e)
            self._fd = None
            return False

    def _acquire_windows(self) -> bool:
        """Windows 用 msvcrt 模拟 flock (非阻塞)."""
        try:
            import msvcrt
            # 试打开
            fd = open(self.lock_path, "w", encoding="utf-8")
            fd.write(f"project_id={self.project_id}\n")
            fd.flush()
            # 试锁第 0 字节
            if self._blocking:
                msvcrt.locking(fd.fileno(), msvcrt.LK_LOCK, 1)
            else:
                msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
            self._fd = fd
            return True
        except (PermissionError, IOError, OSError):
            if self._fd is not None:
                try:
                    self._fd.close()
                except Exception:
                    pass
            self._fd = None
            return False
        except Exception as e:
            _logger.warning("acquire_windows 失败: %s", e)
            self._fd = None
            return False

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            if self._is_windows:
                import msvcrt
                try:
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
            try:
                self._fd.close()
            except Exception:
                pass
        finally:
            self._fd = None

    def __enter__(self):
        ok = self.acquire()
        if not ok:
            raise RuntimeError(f"无法获取项目锁: {self.project_id}")
        return self

    def __exit__(self, *exc):
        self.release()

    # ── 探测: 锁在谁手里 ──

    @staticmethod
    def is_locked() -> bool:
        """探测当前是否被锁."""
        if not GLOBAL_LOCK_PATH.exists():
            return False
        try:
            # 试 non-blocking 锁, 失败 = 有人在用
            pl = ProjectLock(project_id=0)
            ok = pl.acquire()
            if ok:
                pl.release()
            return not ok
        except Exception:
            return False

    @staticmethod
    def who_is_holding() -> Optional[str]:
        """看锁文件内容, 告诉用户哪个 project_id 在用."""
        if not GLOBAL_LOCK_PATH.exists():
            return None
        try:
            content = GLOBAL_LOCK_PATH.read_text(encoding="utf-8").strip()
            return content or None
        except Exception:
            return None


# ────────────────────── LockGuard (短时占位) ──────────────────────

class LockGuard:
    """上下文管理器: 短时占位锁 (聚类/进化跑时)."""

    def __init__(self, project_id):
        self.project_id = project_id
        self._lock: Optional[ProjectLock] = None

    def __enter__(self):
        self._lock = ProjectLock(self.project_id, blocking=False)
        ok = self._lock.acquire()
        if not ok:
            # 软失败: 跳过, 不阻塞主链路
            _logger.info("项目 %s 锁被占, 跳过本轮", self.project_id)
            return None
        return self._lock

    def __exit__(self, *exc):
        if self._lock is not None:
            self._lock.release()
