"""
Allow `python -m app` to launch the PySide6 application.
"""
from __future__ import annotations

import sys

from app.main import main


if __name__ == "__main__":
    sys.exit(main())
