"""
SQLite connection manager (C2: 单例 + 锁)
- 1 个全局连接 + threading lock
- 4.0 是桌面应用（1 用户）→ 1 连接足够
- 隔离级别 / journal_mode 从 config 读 (避免硬编码)
- transaction() 上下文管理器保证多语句原子性
- init_db() 负责建表 + 跑迁移
"""
import contextlib
import sqlite3
import threading
from pathlib import Path
from typing import Iterator, Optional


_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None
_db_path: Optional[Path] = None
_schema_path: Optional[Path] = None  # 用于 init_db


def _read_pragmas() -> tuple:
    """从 config 读 journal_mode / isolation_level. config 不可用 → 用硬编码兜底."""
    journal_mode = "WAL"
    isolation_level: Optional[str] = None
    try:
        from app.core import config as _app_config
        journal_mode = _app_config.get_db_journal_mode() or "WAL"
        isolation_level = _app_config.get_db_isolation_level()
    except Exception:
        # config 未 init / DB 未起 → 走默认
        pass
    return journal_mode, isolation_level


def _connect_raw(db_path: Path | None = None) -> sqlite3.Connection:
    """Create a raw SQLite connection (no global state). Used by both init() and init_db().

    WAL 模式在某些受限路径下会创建 -wal/-shm 文件失败 (OneDrive 同步目录、
    受限的 %APPDATA% 等). 这里先尝试 WAL, 失败则降级到 DELETE 模式,
    保证连接始终可用. DELETE 模式牺牲一点点并发性能, 但功能完全一致.
    """
    if db_path is None:
        from app import app_paths as _ap
        db_path = Path(_ap.sqlite_path())
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        # 路径不允许 WAL (网络盘/同步目录/权限受限) → 降级 DELETE
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
        except sqlite3.DatabaseError:
            pass
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(db_path: str | Path) -> sqlite3.Connection:
    """
    初始化全局数据库连接。
    - 4.0 启动时调用一次
    - 后续 get_conn() 直接拿
    """
    global _conn, _db_path, _schema_path
    db_path = Path(db_path)
    _schema_path = db_path.parent.parent / "db" / "schema.sql"  # app/db/schema.sql

    journal_mode, isolation_level = _read_pragmas()

    with _lock:
        if _conn is not None:
            return _conn
        _conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,  # 多线程安全（由 _lock 保证）
            isolation_level=isolation_level,  # None = autocommit (默认)
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
        _conn.execute(f"PRAGMA journal_mode = {journal_mode}")
        _db_path = db_path
        return _conn


def init_db(db_path: str | Path | None = None) -> None:
    """
    初始化数据库: 建表 + 跑迁移。

    如果传入 db_path 则用该路径; 否则从 app.app_paths.sqlite_path() 获取.
    此函数会创建全局连接 (调用 init), 因此通常在 init() 之后调用一次.
    """
    global _schema_path
    if db_path:
        target_path = Path(db_path)
    elif _db_path:
        target_path = _db_path
    else:
        from app import app_paths
        target_path = Path(app_paths.sqlite_path())

    # schema.sql 始终从 app/db/ 目录定位 (不依赖 db_path 的层级结构)
    _schema_path = Path(__file__).parent / "schema.sql"

    # 用临时连接跑 schema + migrations (不依赖全局连接)
    conn = _connect_raw(target_path)
    try:
        # 1. Migrations tracking table
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version INTEGER PRIMARY KEY,"
            "  applied_at TEXT DEFAULT (datetime('now', 'localtime'))"
            ");"
        )

        # 2. Baseline schema (always idempotent)
        if _schema_path and _schema_path.exists():
            conn.executescript(_schema_path.read_text(encoding="utf-8"))
        elif not _schema_path:
            raise FileNotFoundError("schema.sql path not set, call init() first")

        # 3. Apply pending migrations in version order
        migrations_dir = _schema_path.parent / "migrations"
        if migrations_dir.exists():
            applied = {
                row["version"]
                for row in conn.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            for sql_file in sorted(migrations_dir.glob("*.sql")):
                # Parse "005_chapter_drafts.sql" -> 5
                try:
                    version = int(sql_file.stem.split("_", 1)[0])
                except ValueError:
                    raise RuntimeError(
                        f"Migration file {sql_file.name} must start with a "
                        f"zero-padded integer prefix (e.g. 005_xxx.sql)"
                    )
                if version in applied:
                    continue
                conn.executescript(sql_file.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)",
                    (version,),
                )
        conn.commit()
    finally:
        conn.close()

    # 确保全局连接也初始化 (如果还没 init 的话)
    if _conn is None:
        init(target_path)


def get_conn() -> sqlite3.Connection:
    """获取全局连接（只读/单语句操作用）。多语句写操作请用 transaction()。"""
    if _conn is None:
        raise RuntimeError("DB 未初始化，请先调 init(db_path)")
    return _conn


@contextlib.contextmanager
def transaction():
    """
    事务上下文管理器: 持有全局锁 + BEGIN/COMMIT/ROLLBACK。
    多语句写操作必须用这个, 保证原子性。

    用法:
        with transaction() as conn:
            conn.execute("DELETE FROM ...")
            conn.execute("INSERT INTO ...")
        # 正常 → 自动 COMMIT
        # 异常 → 自动 ROLLBACK
    """
    with _lock:
        conn = get_conn()
        conn.execute("BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


@contextlib.contextmanager
def connection():
    """上下文管理器: 每次新建一个连接用于只读查询 (等同于 _connect_raw(None))."""
    conn = _connect_raw()
    try:
        yield conn
    finally:
        conn.close()


def close() -> None:
    """关闭全局连接。4.0 退出时调用。"""
    global _conn, _db_path
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
            _db_path = None


def get_db_path() -> Path:
    """获取当前 DB 文件路径。"""
    if _db_path is None:
        raise RuntimeError("DB 未初始化")
    return _db_path


def with_lock(func):
    """
    装饰器：在 DB 操作期间持有全局锁。
    用法:
        @with_lock
        def my_db_op():
            conn = get_conn()
            conn.execute(...)
    """
    def wrapper(*args, **kwargs):
        with _lock:
            return func(*args, **kwargs)
    return wrapper
