# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file — Novel Writer Pure v4.3

import sys
import os
import importlib

block_cipher = None

# jieba 词典路径
jieba_path = os.path.dirname(importlib.import_module("jieba").__file__)

# zvec C 扩展路径
zvec_path = os.path.dirname(importlib.import_module("zvec").__file__)

a = Analysis(
    ["app/main.py"],
    pathex=[],
    binaries=[],
    datas=[
        (os.path.join(jieba_path, "dict.txt"), "jieba"),
        (os.path.join(zvec_path, "data"), "zvec/data"),
        ("app/resources", "app/resources"),
        ("app/db/migrations", "app/db/migrations"),
    ],
    hiddenimports=[
        "zvec", "zvec._zvec", "zvec.common", "zvec.executor",
        "zvec.extension", "zvec.model", "zvec.tool", "zvec.typing",
        "numpy", "sklearn", "jieba",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NovelWriter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="NovelWriter",
)
