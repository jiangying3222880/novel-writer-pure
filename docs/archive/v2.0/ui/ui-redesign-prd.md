# UI 重构 PRD（基于 Solarized 主题原型）

## 来源
用户提供两张原型截图：
- 左：**Solarized Dark**（冷调暗色 / 护眼蓝绿）
- 右：**Solarized Light**（米色玻璃 / 区别暗玻璃）

风格基线：**Solarized 经典调色板**（Ethan Schoonover 2011）。

---

## 1. 目标

1. **重写 `ui/` 整个目录**（保留 3.0 三阶段范式和侧栏 / Tab 导航）
2. **保留 app/ + plugins/ + 数据层完全不动**
3. **新增视觉回归测试**（截图对比深/浅主题）

## 2. 范围

**重写（删除旧 ui/，按原型重写）**：
- `ui/main_window.py` / `main_window_ui.py` — 主窗口
- `ui/navigation/sidebar.py` — 侧栏
- `ui/tabs/*` — 6 个 Tab（小说设定/章节生成/章节编辑/仪表盘/叙事工坊/记忆管理）
- `ui/dialogs/*` — 12+ 个 Dialog
- `ui/widgets/*` — 顶栏/底栏/页脚
- `ui/pages/memory/*` `ui/pages/narrative_lab/*` — 子页面
- `ui/utils/theme.py` — 主题系统（重写 token 表）
- `ui/utils/button_styles.py` — 按钮样式

**保留（不动）**：
- `app/` 数据层 + 工作流 + 业务逻辑
- `plugins/` 插件实现
- `main.py` 入口（但导入会变）
- `tests/` 已有测试

## 3. 主题色板（从原型提取）

### Solarized Dark（冷调暗色 / 护眼蓝绿）

| 角色 | Token | 取值（估算） | 说明 |
|------|-------|-------------|------|
| 背景底 | `bg_base` | `#0F2A36` | 深青蓝 |
| 卡片底 | `bg_elevated` | `#143140` | 略亮 |
| 悬浮层 | `bg_overlay` | `#1A3D4F` | 更亮 |
| 主色 | `accent_primary` | `#2AA198` | 青色（Solarized cyan） |
| 副色 | `accent_secondary` | `#268BD2` | 蓝色（Solarized blue） |
| 信息 | `accent_info` | `#6C71C4` | 紫罗兰（Solarized violet） |
| 成功 | `success` | `#859900` | 绿（Solarized green） |
| 警告 | `warning` | `#B58900` | 黄（Solarized yellow） |
| 危险 | `danger` | `#DC322F` | 红（Solarized red） |
| 文字主 | `text_primary` | `#FDF6E3` | 米白 |
| 文字次 | `text_secondary` | `#93A1A1` | 灰青 |
| 文字弱 | `text_muted` | `#586E75` | 暗青灰 |
| 边框 | `border_default` | `#1F4459` | 中青 |
| 边框强 | `border_strong` | `#2C5E78` | 亮青 |

### Solarized Light（米色玻璃）

| 角色 | Token | 取值（估算） | 说明 |
|------|-------|-------------|------|
| 背景底 | `bg_base` | `#F5EDD8` | 米黄 |
| 卡片底 | `bg_elevated` | `#FBF3DE` | 暖白米 |
| 悬浮层 | `bg_overlay` | `#EFE6D0` | 深米 |
| 主色 | `accent_primary` | `#9F2A4E` | 酒红/品红 |
| 副色 | `accent_secondary` | `#A64286` | 紫红 |
| 信息 | `accent_info` | `#6C71C4` | 紫罗兰 |
| 成功 | `success` | `#789600` | 绿 |
| 警告 | `warning` | `#A87D00` | 暗黄 |
| 危险 | `danger` | `#B91E1B` | 暗红 |
| 文字主 | `text_primary` | `#1A2B33` | 深青黑 |
| 文字次 | `text_secondary` | `#475D69` | 中青 |
| 文字弱 | `text_muted` | `#7A8A93` | 浅青灰 |
| 边框 | `border_default` | `#DCD2B6` | 浅米 |
| 边框强 | `border_strong` | `#B5A87A` | 深米 |

> ⚠️ **以上色值是从截图**目测提取，**需要用户确认**或等用户拿到原 HTML 后校正。

## 4. 实施阶段

### Phase 1: 主题底座（1-2h）
- [ ] 重写 `ui/utils/theme.py`：
  - 新建 `DARK_COLORS` / `LIGHT_COLORS` dict（按上表）
  - 简化 `_QSS_TEMPLATE` 为空字符串（**不再用全局 QSS**，改用每个 widget 的 QSS 选择器 + setObjectName）
  - 保留 `Theme` 类 + 信号总线
- [ ] 重写 `ui/utils/button_styles.py`：5 个语义色对齐新主色
- [ ] 验证：app 启动不崩，主题切换有效果

### Phase 2: 主窗口 + 导航（2-3h）
- [ ] 重写 `ui/main_window.py`：主框架 + 顶栏 + 底栏
- [ ] 重写 `ui/navigation/sidebar.py`：侧栏（按原型 220px 单行布局）
- [ ] 验证：能看到主窗口 + 切 Tab

### Phase 3: 6 个 Tab（4-6h）
- [ ] 重写每个 Tab：保留 `init_ui` + `load_data` 等业务方法，只重排 widget 树 + 样式
- [ ] 关键：业务逻辑方法（信号槽、数据加载）签名不动 → app/ 调用不变

### Phase 4: 12+ Dialog（2-3h）
- [ ] 重写每个 Dialog：保留构造签名和 `get_data` / `exec` 等公开方法
- [ ] 内部 widget 树重画

### Phase 5: 视觉回归测试（1-2h）
- [ ] 写 `tests/visual_regression/`：用 `QApplication` offscreen 跑 + `widget.grab().save()`
- [ ] 深/浅主题各截 1 张基线图（侧栏 + 主页面）
- [ ] 加 `test_visual_regression.py`：每次重构后对比像素差异

**总工作量估算**：10-16h（一天半到两天）

## 5. 风险

| 风险 | 缓解 |
|------|------|
| 业务逻辑被破坏 | **不**重写 Tab/Dialog 的 `__init__` 业务方法（信号槽、load_data、get_data），只重画 widget 树 |
| 主题切换覆盖不全 | Phase 5 视觉测试断言每个 widget 在深/浅下都正常 |
| 新色值用户不接受 | **第 1 步先确认色值** — 让用户看 DARK_COLORS / LIGHT_COLORS 截图后再写 QSS |
| 第三方 widget（matplotlib）样式难统一 | 接受 matplotlib 仍走默认主题，但用 QSS 改背景色 |

## 6. 验收标准

- [ ] 启动 app，主窗口/侧栏/所有 Tab 显示正常
- [ ] 主题切换：所有可见 widget 颜色跟随
- [ ] pytest tests/ 47 个 UI 一致性 + 619 个后端测试 全过
- [ ] tests/visual_regression/ 截深/浅基线图，pixel diff < 5%

## 7. 当前状态

- ✅ 旧 ui/ 全部代码已审计（25 个问题已修 9 个 + 1 个改动布局）
- ✅ Solarized 主题色板估算完成
- ⏳ **等用户确认色值**（DARK/LIGHT_COLORS）
- ⏳ **等用户提供原型 HTML 路径**（用于校准色值 + 检查遗漏细节）
