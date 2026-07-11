# zvec 打包兼容性说明

MiMoCode · 2026-07-11T01:30:00+08:00

## 问题

zvec 0.5.1 包含：
1. **C 扩展**: `_zvec.cp312-win_amd64.pyd` (平台特定)
2. **打包数据**: `data/jieba_dict/` (jieba 词典)
3. **多个 Python 子包**: common/ executor/ extension/ model/ tool/ typing/

PyInstaller 默认只打包纯 Python 模块，C 扩展和数据文件需要显式配置。

## 解决方案

### 方案 1: PyInstaller spec 文件（推荐）

创建 `novel-writer.spec`:

```python
# novel-writer.spec
a = Analysis(
    ['app/main.py'],
    datas=[
        # zvec jieba 词典
        (os.path.join(site.getsitepackages()[0], 'zvec', 'data', 'jieba_dict'), 'zvec/data/jieba_dict'),
        # 项目资源
        ('app/resources', 'app/resources'),
        ('app/db/migrations', 'app/db/migrations'),
    ],
    hiddenimports=[
        'zvec',
        'zvec._zvec',
        'zvec.common',
        'zvec.executor',
        'zvec.extension',
        'zvec.model',
        'zvec.tool',
        'zvec.typing',
    ],
)
```

### 方案 2: PyInstaller 命令行

```bash
pyinstaller --name novel-writer \
  --collect-all zvec \
  --add-data "venv/Lib/site-packages/zvec/data/jieba_dict:zvec/data/jieba_dict" \
  app/main.py
```

### 方案 3: pyproject.toml 配置

```toml
[tool.pyinstaller]
hiddenimports = ["zvec", "zvec._zvec"]
datas = [
    ["venv/Lib/site-packages/zvec/data/jieba_dict", "zvec/data/jieba_dict"],
]
```

## 验证步骤

打包后验证：
```bash
# 1. 检查 C 扩展是否包含
dist/novel-writer/_zvec.cp312-win_amd64.pyd

# 2. 检查 jieba 词典是否包含
dist/novel-writer/zvec/data/jieba_dict/jieba.dict.utf8

# 3. 运行 smoke 测试
python smoke/smoke_d2_finder.py
```

## 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| C 扩展平台不匹配 | Windows .pyd 不能在 Linux/macOS 用 | 需要为每个平台单独打包 |
| jieba 词典缺失 | FTS 中文分词失败 | --add-data 显式包含 |
| zvec 版本升级后 C 扩展变化 | 打包失败 | 锁定 zvec 版本 (>=0.5.0,<0.6.0) |
