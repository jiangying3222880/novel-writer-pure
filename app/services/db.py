"""
Shim: 兼容旧接口，全部转发到 app.db._impl
统一后 app.services.db 已无独立逻辑，所有功能由 app.db._impl 提供。
"""
import app.db._impl as _impl_module

init = _impl_module.init
init_db = _impl_module.init_db
get_conn = _impl_module.get_conn
transaction = _impl_module.transaction
close = _impl_module.close
get_db_path = _impl_module.get_db_path
connection = _impl_module.connection

def sqlite_path() -> str:
    from app import app_paths as _app_paths
    return _app_paths.sqlite_path()

def _connect():
    return _impl_module._connect_raw()
