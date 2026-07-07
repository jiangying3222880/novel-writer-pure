"""
Application entry point — Novel Writer v4.0 (Story OS).

Usage:
    python -m app
"""
from __future__ import annotations
import atexit
import os
import sys
import logging

# Load .env before any app imports
try:
    from dotenv import load_dotenv as _load_dotenv
    from pathlib import Path as _Path
    _env_path = _Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        _load_dotenv(_env_path, override=False)
except ImportError:
    pass

from PySide6.QtCore import Qt, QTranslator, QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from app import __version__
from app.app_paths import LOG_DIR, sqlite_path, apply_storage_overrides_from_settings
from app.core import config as _app_config
from app.core.logger import setup as _setup_logger
from app.db import _impl as _db_connection
from app.ui.main_window import MainWindow


def _setup_logging() -> None:
    _setup_logger(LOG_DIR)
    logging.info("=" * 60)
    logging.info("Novel Writer Pure v%s (Story OS)", __version__)
    logging.info("Log dir: %s", LOG_DIR)

    def _global_excepthook(exc_type, exc_value, exc_tb):
        import traceback
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.error("Uncaught exception:\n%s", tb_str)
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _global_excepthook

    def _qt_message_handler(mode, context, message):
        if mode == QtMsgType.QtWarningMsg:
            logging.warning("[Qt] %s", message)
        elif mode == QtMsgType.QtCriticalMsg:
            logging.error("[Qt Critical] %s", message)
    qInstallMessageHandler(_qt_message_handler)


def main() -> int:
    apply_storage_overrides_from_settings()
    _setup_logging()

    _app_config.load()
    _app_config.validate()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    logging.info("Initialising SQLite at %s", sqlite_path())
    _db_connection.init_db(sqlite_path())

    _app_config.load()
    _app_config.validate()

    app = QApplication(sys.argv)

    # Chinese translations for Qt built-in menus
    import PySide6 as _p6
    _tr_dir = os.path.join(os.path.dirname(_p6.__file__), "translations")
    for _tr_file in ("qtbase_zh_CN.qm", "qt_zh_CN.qm"):
        _tr = QTranslator()
        if _tr.load(_tr_file, _tr_dir):
            app.installTranslator(_tr)
    app.setApplicationName("Novel Writer Pure")
    app.setApplicationDisplayName(f"Novel Writer Pure v{__version__}")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("NovelWriterPure")

    # Service wiring (skip dialog adapters for v4 minimal)
    try:
        from app.core.wiring import wire_default_services as _wire_services
        _wire_services()
    except Exception as e:
        logging.warning("wiring failed: %s", e)

    # Model registry
    try:
        from app.ai.registry import get_registry, inject_env_keys as _inject_env
        _reg = get_registry()
        _reg.init_defaults()
        _reg.reload()
        _inject_env(_reg)
    except Exception as e:
        logging.warning("model registry init failed: %s", e)

    # Theme — 统一到 theme.py 单一主题源 (mockup 配色, 已批准)
    from app.ui.theme import get_theme
    get_theme().apply(app, "dark")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
