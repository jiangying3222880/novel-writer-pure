"""
SQLite schema for the PySide6 app (kept next to db.py so the app is fully
self-contained - no dependency on the legacy backend/ directory).
"""
from app.db._impl import (
    init as _impl_init,
    init_db,
    get_conn,
    transaction,
    close as _impl_close,
    get_db_path,
    connection as _impl_connection,
)
from app.db import _impl as _impl_module

init = _impl_module.init
close = _impl_module.close

class _ConnectionShim:
    """兼容层: 让 from app.db import connection 后可调用 connection.init()/close()"""
    init = staticmethod(_impl_module.init)
    close = staticmethod(_impl_module.close)
    init_db = staticmethod(_impl_module.init_db)
    get_conn = staticmethod(_impl_module.get_conn)
    transaction = _impl_module.transaction
    get_db_path = staticmethod(_impl_module.get_db_path)
    def __call__(self):
        return _impl_connection()

connection = _ConnectionShim()
