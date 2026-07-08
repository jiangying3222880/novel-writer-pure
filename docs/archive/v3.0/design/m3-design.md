# Phase 3 M3 设计文档

> M3 交付物 + 实现说明（设计思路详见 [phase3-design.md](phase3-design.md)）

## 1. M3 范围

| 模块 | 文件 | 状态 |
|---|---|---|
| 段落重写 (mock + LLM) | `app/core/paragraph_rewriter.py` | ✅ |
| HookAnalyzer (5 维追读分) | `app/core/hook_analyzer.py` | ✅ |
| 仪表盘 (Dashboard) | `app/services/dashboard_service.py` + `app/ui/tabs/dashboard_tab.py` | ✅ |
| 实体重塑 (entity rename) | `app/core/entity_manager.py` + `app/ui/tabs/entity_tab.py` | ✅ |
| 关键词扫描 (scanner) | `app/core/scanner.py` | ✅ |
| 批量重生成 (batch) | `app/core/batch_regenerator.py` | ✅ |
| Prompt 资产组装器 | `app/core/prompt_assembler.py` | ✅ |
| API key 加密 (keyring + base64 回退) | `app/services/keyring_store.py` | ✅ |
| Anthropic 流式 event-stream 解析 | `app/core/llm.py:_call_anthropic_stream` | ✅ |
| 段落重写 UI 面板 | `app/ui/tabs/editor_tab.py:EvaluationPanel` | ✅ |
| MainWindow 5 tab 布局 | `app/ui/main_window.py` | ✅ |

## 2. 关键设计决策

### 2.1 EvaluationPanel 通过 `host` 引用 EditorTab
原 `parent_editor()` 依赖 `self.parent()` 拿到 EditorTab.editor，但 EvaluationPanel 嵌在 QSplitter 内，QWidget parent 是 splitter 不是 EditorTab。
修复：构造时显式接收 `host=self`，存为 `self.host`，优先用 `host.editor`。

### 2.2 Mock 段落重写走 `改写: ` 前缀
- `MockScopedRewriter.run()` 把目标段前缀改为 `改写: `，便于测试断言
- LLM 失败时（JSON 解析失败）`success=False`，UI 显示 ❌，原文不替换

### 2.3 仪表盘 3 数字 + 2 趋势 + Top5 弱章
- 数字：章节数 / 总字数 / 平均综合分（critic 与 hook 取均）
- 趋势：Critic 文学分、Hook 追读分（手绘 QPainter 折线）
- 弱章：综合分升序前 5

### 2.4 实体重塑只改 `entity_appearances` 索引
- 不改 `chapter.draft` 文本
- 提供 `dry_run=True` 预览影响范围
- 改名前校验同名校验 + 存在性（NotFoundError）

### 2.5 Batch 重生成用 on_chapter_start 通知 + should_cancel
- 在 `should_cancel()` 检查**之前**调 `on_chapter_start`，让回调有机会设置 cancel flag
- CancelledError 不算失败，记入 `cancelled=True`

### 2.6 Anthropic 流式 SSE
- 解析 `event: content_block_delta` + `delta.type=text_delta` → 累积 `text` 字段
- 跳过 `event:` 行 / 空行 / 未知事件类型
- 与 OpenAI 兼容流走相同 `_call_one_stream` 入口

## 3. 测试覆盖

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `m0_smoke` | 8 | 迁移 / drafts / change_log / entity_appearances |
| `m1_smoke` | 5 | ChapterGenerator (mock agents / 落库 / cancel / DI) |
| `m1_ui_smoke` | 2 | Generate UI 流式 + cancel |
| `m2_smoke` | 8 | LLM 多协议 / fallback / app_setting / SettingsTab |
| `m2_ui_stream_smoke` | 3 | Worker + mock LLM + cancel |
| `m3_smoke` | 9+2 | keyring / prompt / paragraph_rewriter / hook / dashboard / scanner / entity / batch / Anthropic stream |
| `m3_ui_smoke` | 4 | Dashboard / Editor 段落重写 / Entity / MainWindow 5 tab |

跑全套：

```bash
python -m app.tests.m0_smoke
python -m app.tests.m1_smoke
python -m app.tests.m1_ui_smoke
python -m app.tests.m2_smoke
python -m app.tests.m2_ui_stream_smoke
python -m app.tests.m3_smoke
python -m app.tests.m3_ui_smoke
```

## 4. 真人测试前 Checklist

- [x] 7 个 smoke 全 exit 0
- [x] 段落重写（光标段 + 按序号）UI 走通
- [x] 仪表盘数字 / 趋势 / 弱章表正确
- [x] 实体重塑（preview + execute）UI 走通
- [x] 关键词扫描 + 批量重生成 + Anthropic 流式
- [x] MainWindow 5 tab 加载不闪退

## 5. 真人测试建议路径

1. 启动 `start-pyqt6.bat`
2. 「小说设定」建项目 + 写世界观 / 角色 / 反规则 / 风格指纹
3. 「章节生成」配 active provider（API key 加密存）→ 生成第 1 章
4. 「章节编辑」检查 Critic/Hook 面板，用段落重写调一两段
5. 「创作总览」看数字和趋势
6. 「实体管理」列出实体 + 试着重塑一个
7. 回到「章节生成」批量重生成 3-5 章观察 batch 进度条
8. 切换模型（如 DeepSeek → Claude）验证 provider fallback

## 6. 已知限制 / 后续

- `keyring` 在某些环境不可用，自动回退 base64 混淆（不抗逆向，仅防误看）
- Dashboard 趋势图是手绘 QPainter，未接入 matplotlib / pyqtgraph
- 段落重写 LLM prompt 还没接项目级 anti_rules 和 style_fingerprint（预留 prompt_assembler 集成点）
- 批量重生成目前是同步跑，长任务需 UI 自己起 worker
