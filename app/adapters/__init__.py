"""
app/adapters/pyside6/ - PySide6 宿主适配器 (M1 解耦第 2 步).

将宿主 (PySide6) 的能力注入到核心库的 protocol 里.
核心库 import 这个模块, 就能用 PySide6 的 Dialogs / Notifications / etc.

具体用法 (桌面 main.py 启动时):
  from app.adapters.pyside6 import install
  install()
"""
