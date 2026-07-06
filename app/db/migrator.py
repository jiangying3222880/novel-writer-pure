"""
数据库迁移器（C3: 数据迁移）
- 自动加载 app/db/migrations/ 下的所有 *.sql
- 按文件名升序执行
- 已执行的迁移记到 schema_migrations 表
- 启动时自动跑（idempotent）
"""
import logging
import re
from pathlib import Path

from ._impl import get_conn, transaction, with_lock

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _ensure_migrations_table() -> None:
    """确保 schema_migrations 表存在 (INTEGER PK, 与 app.services.db.init_db 一致)."""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)


def _get_applied() -> set[int]:
    """已应用的迁移版本集合 (int)."""
    conn = get_conn()
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    out: set[int] = set()
    for r in rows:
        v = r["version"]
        try:
            out.add(int(v))
        except (TypeError, ValueError):
            # 老 TEXT PK 数据兼容: "005" → 5
            try:
                out.add(int(str(v)))
            except Exception:
                pass
    return out


def _parse_filename(filename: str) -> int | None:
    """
    从文件名提取版本号 (int).
    例: 009_subtext_full.sql → 9
        005_chapter_drafts.sql → 5
    """
    m = re.match(r"^(\d+)_", filename)
    return int(m.group(1)) if m else None


def _exec_sql_file(path: Path) -> None:
    """执行 1 个 SQL 文件. 逐语句执行 (不用 executescript, 避免隐式提交)."""
    conn = get_conn()
    sql = path.read_text(encoding="utf-8")
    sql_no_comments = re.sub(r"--[^\n]*", "", sql)
    # 拆分语句 (按分号), 过滤空串
    statements = [s.strip() for s in sql_no_comments.split(";") if s.strip()]
    for stmt in statements:
        conn.execute(stmt)


@with_lock
def run_migrations() -> list[int]:
    """
    跑所有未应用的迁移。返回新应用的版本列表 (int).
    使用 transaction() 保证每个迁移文件的原子性。
    """
    _ensure_migrations_table()
    applied = _get_applied()

    files = []
    for path in MIGRATIONS_DIR.glob("*.sql"):
        version = _parse_filename(path.name)
        if version is None:
            logger.warning("跳过无法解析的迁移文件: %s", path.name)
            continue
        files.append((version, path))
    files.sort(key=lambda x: x[0])

    newly_applied: list[int] = []
    conn = get_conn()
    for version, path in files:
        if version in applied:
            continue
        logger.info("应用迁移 %s (%s)", version, path.name)
        try:
            conn.execute("BEGIN")
            _exec_sql_file(path)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)",
                (version,),
            )
            conn.execute("COMMIT")
            newly_applied.append(version)
        except Exception as e:
            conn.execute("ROLLBACK")
            logger.error("迁移 %s 失败: %s", version, e)
            raise

    return newly_applied


def get_current_version() -> str | None:
    """获取当前数据库版本 (最新应用的迁移, 字符串方便显示)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    v = row["version"]
    return f"{int(v):03d}" if v is not None else None


def get_pending_migrations() -> list[int]:
    """列出所有未应用的迁移版本 (int)."""
    _ensure_migrations_table()
    applied = _get_applied()
    files = []
    for path in MIGRATIONS_DIR.glob("*.sql"):
        version = _parse_filename(path.name)
        if version and version not in applied:
            files.append(version)
    return sorted(files)
