# 分卷编排与GBrain检索功能实现计划

---

## 一、需求分析

### 1.1 分卷编排需求

长篇网文创作流程需要增加**分卷编排**环节，目前的单元驱动模式无法很好地支撑长篇故事的宏观规划：

| 需求点 | 描述 |
|--------|------|
| 分卷卷纲规划 | 用户先规划分卷卷纲，定义每卷的核心内容和目标 |
| 单元大纲填充 | 在卷纲基础上，向每个分卷中填充单元，形成单元大纲 |
| 渐进式创作 | 用户可以只规划第一卷，写完后再规划第二卷 |
| 概念驱动 | 用户可以提供一个概念，系统辅助生成卷纲 |

### 1.2 GBrain检索替换需求

将现有检索功能（BM25 + 向量混合检索）替换为GBrain，利用其更先进的混合搜索架构和知识图谱能力：

| 需求点 | 描述 |
|--------|------|
| 混合搜索能力 | 向量+关键词+RRF融合，Recall@5达95% |
| 知识图谱 | 自动实体关系抽取和连线 |
| MCP集成 | 通过MCP协议调用，无需额外API |
| 扩展性 | 支持从本地PGLite到云端Supabase的无缝迁移 |

### 1.3 当前架构分析

**现有检索架构**：
```
知识库文档 (.md)
    ↓
BM25索引 + 向量索引
    ↓
HybridFinder (加权融合)
    ↓
检索结果给AI写作
```

**现有流程**：
```
项目创建 → 单元创建 → 单元大纲 → 写作 → 分章 → 发布
```

**目标流程**：
```
项目创建 → 【分卷卷纲规划】→ 【单元填充到卷】→ 单元大纲 → 写作 → 分章 → 发布
              ↑                             ↑
         GBrain检索支持              GBrain知识图谱支持
```

---

## 二、架构设计

### 2.1 分卷编排数据模型设计

#### 2.1.1 新增 `BookOutline`（卷纲）

```python
@dataclass
class BookOutline:
    id: str
    book_id: str                    # 关联的卷
    project_id: str
    core_theme: str = ""            # 卷核心主题
    emotion_arc: str = ""           # 卷情绪曲线描述
    key_events: str = "[]"          # 关键事件列表（JSON）
    character_arcs: str = "[]"      # 角色弧线（JSON）
    hook_plants: str = "[]"         # 计划埋设的伏笔（JSON）
    hook_payoffs: str = "[]"        # 计划回收的伏笔（JSON）
    target_word_count: int = 0      # 目标字数
    target_unit_count: int = 0      # 目标单元数
    status: str = "planning"        # planning / in_progress / completed
    created_at: str = ...
    updated_at: str = ...
```

#### 2.1.2 扩展 `Book` 模型

| 新增字段 | 类型 | 说明 |
|----------|------|------|
| `outline_id` | str | 关联的卷纲 ID |
| `status` | str | 卷状态：planning / in_progress / completed |
| `word_count` | int | 当前字数统计 |
| `unit_count` | int | 当前单元数统计 |

#### 2.1.3 新增 `VolumeTransition`（卷间过渡）

```python
@dataclass
class VolumeTransition:
    id: str
    project_id: str
    from_book_id: str               # 前一卷
    to_book_id: str                 # 后一卷
    transition_type: str = "direct"  # direct / cliffhanger / time_jump / parallel
    summary: str = ""               # 过渡摘要
    required_memories: str = "[]"    # 需要继承的记忆（JSON）
    created_at: str = ...
```

### 2.2 GBrain检索集成设计

#### 2.2.1 新增 `GBrainClient`（GBrain客户端）

```python
class GBrainClient:
    """
    GBrain 客户端。
    - 通过 MCP 协议调用 GBrain 服务
    - 封装搜索、存储、知识图谱操作
    """
    
    def __init__(self, mcp_server_url: str = "http://localhost:8888"):
        self.mcp_server_url = mcp_server_url
        self._client = None
    
    def search(self, query: str, top_k: int = 5, **filters) -> list[dict]:
        """混合搜索（向量+关键词+RRF）"""
    
    def query(self, question: str) -> str:
        """自然语言问答（GBrain hybrid search）"""
    
    def store(self, slug: str, content: str, tags: list[str] = None) -> None:
        """存储知识到GBrain"""
    
    def get(self, slug: str) -> dict:
        """获取知识页面"""
    
    def get_links(self, slug: str) -> list[dict]:
        """获取知识图谱链接"""
    
    def get_backlinks(self, slug: str) -> list[dict]:
        """获取反向链接"""
    
    def traverse_graph(self, slug: str, depth: int = 5) -> list[dict]:
        """遍历知识图谱"""
```

#### 2.2.2 检索适配器设计

```python
class FinderAdapter:
    """
    检索适配器。
    - 统一接口，支持切换检索后端
    - 支持：本地混合检索（BM25+向量）/ GBrain检索
    """
    
    def __init__(self, backend: str = "local"):
        self.backend = backend
        self._finder = None
        self._gbrain = None
    
    def search(self, query: str, top_k: int = 5, **kwargs) -> list[Hit]:
        """统一搜索接口"""
    
    def extract_for_prompt(self, query: str, max_chars: int = 200) -> str:
        """统一拼装接口"""
    
    def extract_for_agent(self, agent: str, query: str, **kwargs) -> str:
        """统一Agent知识拼装接口"""
```

### 2.3 服务层设计

#### 2.3.1 新增 `book_outline_service.py`

| 函数 | 说明 |
|------|------|
| `create(book_id, **fields)` | 创建卷纲 |
| `get(book_id)` | 获取卷纲 |
| `update(book_id, **fields)` | 更新卷纲 |
| `delete(book_id)` | 删除卷纲 |
| `generate_outline(book_id, concept)` | AI 辅助生成卷纲 |
| `validate_outline(book_id)` | 验证卷纲完整性 |

#### 2.3.2 扩展 `book_service.py`

| 函数 | 说明 |
|------|------|
| `create_volume(project_id, title, synopsis, **fields)` | 创建新卷 |
| `list_volumes(project_id)` | 获取项目所有卷 |
| `update_volume(book_id, **fields)` | 更新卷信息 |
| `delete_volume(book_id)` | 删除卷（级联处理） |
| `get_volume_progress(book_id)` | 获取卷进度统计 |
| `transition_volume(book_id, new_status)` | 卷状态流转 |

#### 2.3.3 扩展 `story_unit_service_v2.py`

| 函数 | 说明 |
|------|------|
| `create_for_book(project_id, book_id, title, **fields)` | 在指定卷下创建单元 |
| `list_for_book(project_id, book_id)` | 获取卷下所有单元 |
| `move_to_book(unit_id, book_id)` | 将单元移动到另一卷 |
| `get_book_units_progress(book_id)` | 获取卷下单元进度统计 |

#### 2.3.4 新增 `gbrain_service.py`

| 函数 | 说明 |
|------|------|
| `search(query, top_k, **filters)` | GBrain混合搜索 |
| `query(question)` | 自然语言问答 |
| `store_knowledge(slug, content, tags)` | 存储知识 |
| `get_knowledge(slug)` | 获取知识 |
| `build_graph_from_units(project_id)` | 从单元构建知识图谱 |
| `get_entity_relations(entity_name)` | 获取实体关系 |

### 2.4 UI 设计

#### 2.4.1 新增卷管理视图

```
┌──────────────────────────────────────────────────────┐
│  分卷管理                                             │
├────────────────────┬─────────────────────────────────┤
│ 卷列表（左侧）       │ 卷详情（右侧）                    │
│ ┌─────────────┐    │ ┌─────────────────────────────┐ │
│ │ 📖 第一卷    │    │ │ 卷名：第一卷                │ │
│ │   核心主题   │    │ │ 状态：规划中                │ │
│ │   进度: 0%   │    │ │ 目标字数：10万字            │ │
│ ├─────────────┤    │ │ 目标单元：15个              │ │
│ │ 📖 第二卷    │    │ ├───────────────────────────┤ │
│ │   核心主题   │    │ │ 卷纲编辑区                 │ │
│ │   进度: 0%   │    │ │ （核心主题、情绪曲线、     │ │
│ ├─────────────┤    │ │   关键事件、角色弧线）      │ │
│ │ + 新建卷    │    │ ├───────────────────────────┤ │
│ └─────────────┘    │ │ 单元列表：                │ │
│                    │ │ ┌─────────────────────┐    │ │
│                    │ │ │ 单元1 · 大纲完成     │    │ │
│                    │ │ │ 单元2 · 写作中       │    │ │
│                    │ │ │ + 添加单元           │    │ │
│                    │ │ └─────────────────────┘    │ │
│                    │ └─────────────────────────────┘ │
└────────────────────┴─────────────────────────────────┘
```

#### 2.4.2 新增卷纲生成对话框

| 功能 | 说明 |
|------|------|
| 概念输入 | 用户输入卷概念（如："主角进入宗门，修炼升级，结识伙伴"） |
| AI 生成 | 调用 AI 生成卷纲（核心主题、情绪曲线、关键事件） |
| GBrain参考 | 通过GBrain搜索相关知识作为参考 |
| 手动编辑 | 用户可以手动调整生成的卷纲 |
| 保存确认 | 确认后保存卷纲 |

#### 2.4.3 新增GBrain设置面板

| 功能 | 说明 |
|------|------|
| 后端切换 | 本地检索 / GBrain检索 |
| GBrain地址 | MCP服务器地址配置 |
| 知识图谱浏览 | 查看实体关系图谱 |
| 知识导入 | 将小说知识导入GBrain |

---

## 三、文件修改清单

### 3.1 新增文件

| 文件路径 | 说明 |
|----------|------|
| `app/services/book_outline_service.py` | 卷纲服务 |
| `app/services/gbrain_service.py` | GBrain服务 |
| `app/knowledge/gbrain_client.py` | GBrain客户端 |
| `app/knowledge/finder_adapter.py` | 检索适配器 |
| `app/db/migrations/030_book_outlines.sql` | 卷纲表迁移 |
| `app/db/migrations/031_volume_transitions.sql` | 卷间过渡表迁移 |
| `app/db/migrations/032_books_extension.sql` | Book表扩展迁移 |
| `app/ui/tabs/volume_tab.py` | 卷管理标签页 |
| `app/ui/tabs/gbrain_tab.py` | GBrain设置标签页 |
| `app/ui/dialogs/volume_outline_dialog.py` | 卷纲生成对话框 |
| `app/ui/dialogs/gbrain_search_dialog.py` | GBrain搜索对话框 |

### 3.2 修改文件

| 文件路径 | 修改内容 |
|----------|----------|
| `app/db/models.py` | 新增 `BookOutline`、`VolumeTransition`，扩展 `Book` |
| `app/services/book_service.py` | 新增卷CRUD、进度统计、状态流转 |
| `app/services/story_unit_service_v2.py` | 新增按卷创建/查询单元、移动单元到卷 |
| `app/knowledge/finder.py` | 接入 `FinderAdapter`，支持GBrain后端 |
| `app/ui/tabs/outline_tab.py` | 增加卷过滤和卷选择 |
| `app/ui/tabs/unit_editor_tab.py` | 显示单元所属卷信息 |
| `app/ui/tabs/settings_tab.py` | 增加GBrain配置选项 |
| `app/core/config.py` | 增加GBrain配置项 |

---

## 四、实施步骤

### 步骤 1：数据库迁移

**目标**：创建卷纲和卷间过渡数据表

**文件**：
- `app/db/migrations/030_book_outlines.sql`
- `app/db/migrations/031_volume_transitions.sql`
- `app/db/migrations/032_books_extension.sql`

**内容**：
- 创建 `book_outlines` 表（id, book_id, project_id, core_theme, emotion_arc, key_events, character_arcs, hook_plants, hook_payoffs, target_word_count, target_unit_count, status, created_at, updated_at）
- 创建 `volume_transitions` 表（id, project_id, from_book_id, to_book_id, transition_type, summary, required_memories, created_at）
- 扩展 `books` 表（outline_id, status, word_count, unit_count）

### 步骤 2：数据模型

**目标**：定义卷纲相关数据类

**文件**：`app/db/models.py`

**内容**：
- 新增 `BookOutline` 数据类
- 新增 `VolumeTransition` 数据类
- 扩展 `Book` 数据类，增加 `outline_id`, `status`, `word_count`, `unit_count` 字段

### 步骤 3：卷纲服务

**目标**：实现卷纲CRUD和AI生成

**文件**：`app/services/book_outline_service.py`

**内容**：
- `create(book_id, **fields)` — 创建卷纲
- `get(book_id)` — 获取卷纲
- `update(book_id, **fields)` — 更新卷纲
- `delete(book_id)` — 删除卷纲
- `generate_outline(book_id, concept)` — 调用AI根据概念生成卷纲
- `validate_outline(book_id)` — 验证卷纲完整性（检查必填字段）

### 步骤 4：卷服务扩展

**目标**：增强卷的管理能力

**文件**：`app/services/book_service.py`

**内容**：
- `create_volume(project_id, title, synopsis, **fields)` — 创建新卷
- `list_volumes(project_id)` — 获取项目所有卷
- `update_volume(book_id, **fields)` — 更新卷信息
- `delete_volume(book_id)` — 删除卷（级联删除关联单元、大纲）
- `get_volume_progress(book_id)` — 获取卷进度（字数、单元数、完成率）
- `transition_volume(book_id, new_status)` — 卷状态流转

### 步骤 5：单元服务扩展

**目标**：支持按卷管理单元

**文件**：`app/services/story_unit_service_v2.py`

**内容**：
- `create_for_book(project_id, book_id, title, **fields)` — 在指定卷下创建单元
- `list_for_book(project_id, book_id)` — 获取卷下所有单元
- `move_to_book(unit_id, book_id)` — 将单元移动到另一卷
- `get_book_units_progress(book_id)` — 获取卷下单元进度统计

### 步骤 6：GBrain客户端

**目标**：实现GBrain MCP客户端

**文件**：`app/knowledge/gbrain_client.py`

**内容**：
- 封装MCP协议调用
- 实现search、query、store、get、get_links、get_backlinks、traverse_graph方法
- 错误处理和重试机制

### 步骤 7：检索适配器

**目标**：实现统一检索接口，支持后端切换

**文件**：`app/knowledge/finder_adapter.py`

**内容**：
- `FinderAdapter`类，统一search/extract_for_prompt/extract_for_agent接口
- 支持local和gbrain两种后端模式
- 根据配置自动选择后端

### 步骤 8：GBrain服务

**目标**：实现GBrain业务服务

**文件**：`app/services/gbrain_service.py`

**内容**：
- `search(query, top_k, **filters)` — GBrain混合搜索
- `query(question)` — 自然语言问答
- `store_knowledge(slug, content, tags)` — 存储知识
- `build_graph_from_units(project_id)` — 从单元构建知识图谱
- `get_entity_relations(entity_name)` — 获取实体关系

### 步骤 9：UI实现（卷管理）

**目标**：实现卷管理界面

**文件**：
- `app/ui/tabs/volume_tab.py` — 卷管理标签页
- `app/ui/dialogs/volume_outline_dialog.py` — 卷纲生成对话框

**内容**：
- 卷列表展示
- 卷详情编辑
- 卷纲编辑（核心主题、情绪曲线、关键事件、角色弧线）
- 单元列表（卷下的单元）
- AI生成卷纲对话框（集成GBrain搜索参考）

### 步骤 10：UI实现（GBrain设置）

**目标**：实现GBrain设置和搜索界面

**文件**：
- `app/ui/tabs/gbrain_tab.py` — GBrain设置标签页
- `app/ui/dialogs/gbrain_search_dialog.py` — GBrain搜索对话框

**内容**：
- 后端切换（本地/GBrain）
- GBrain MCP地址配置
- 知识图谱浏览
- 知识导入功能
- GBrain搜索对话框

### 步骤 11：现有视图扩展

**目标**：在现有视图中集成卷信息和GBrain检索

**文件**：
- `app/ui/tabs/outline_tab.py` — 增加卷过滤
- `app/ui/tabs/unit_editor_tab.py` — 显示单元所属卷
- `app/ui/tabs/settings_tab.py` — 增加GBrain配置选项

**内容**：
- 大纲视图增加卷过滤下拉框
- 单元编辑器显示所属卷信息和卷纲摘要
- 单元创建对话框增加卷选择
- 设置界面增加GBrain配置

### 步骤 12：配置集成

**目标**：增加GBrain配置项

**文件**：`app/core/config.py`

**内容**：
- 增加 `retrieval_backend` 配置项（local/gbrain）
- 增加 `gbrain_mcp_url` 配置项
- 增加 `gbrain_enabled` 配置项

### 步骤 13：测试

**目标**：验证分卷编排和GBrain检索功能

**文件**：`smoke/smoke_v4_volume.py`（新增）、`smoke/smoke_v4_gbrain.py`（新增）

**测试内容**：
- 卷创建和查询
- 卷纲创建和更新
- AI生成卷纲
- 单元分配到卷
- 卷进度统计
- 卷间过渡创建
- GBrain搜索集成
- GBrain知识存储
- 检索适配器切换

---

## 五、依赖与集成

### 5.1 GBrain安装与配置

```bash
# 安装GBrain（Bun运行时）
curl -fsSL https://bun.sh/install | bash
bun install -g gbrain

# 初始化GBrain（创建本地PGLite数据库）
gbrain init

# 启动MCP服务器
gbrain serve --port 8888

# 导入知识库
gbrain import app/knowledge/builtin/
```

### 5.2 依赖关系

```
volume_tab.py
    ├── book_service.py (卷CRUD)
    ├── book_outline_service.py (卷纲CRUD)
    ├── story_unit_service_v2.py (单元按卷查询)
    └── app/ai/engine.py (AI生成卷纲)

gbrain_tab.py
    ├── gbrain_service.py (GBrain操作)
    ├── finder_adapter.py (检索适配器)
    └── app/core/config.py (配置)

finder_adapter.py
    ├── finder.py (本地混合检索)
    └── gbrain_client.py (GBrain客户端)
```

### 5.3 集成点

1. **卷创建** → 创建 `Book` 记录，自动创建空的 `BookOutline`
2. **卷纲生成** → 调用AI引擎生成，同时通过GBrain搜索相关知识
3. **单元创建** → 指定 `book_id`，关联到特定卷
4. **进度统计** → 实时计算卷下单元进度和字数
5. **状态流转** → 卷状态（planning → in_progress → completed）
6. **检索切换** → 通过配置切换本地/GBrain检索后端
7. **知识图谱** → 将小说实体存储到GBrain，构建知识图谱

---

## 六、风险与处理

| 风险 | 处理方式 |
|------|----------|
| 数据迁移兼容性 | 使用增量迁移，不修改现有字段 |
| 卷删除级联 | 提供删除选项（删除卷及所有单元 / 仅删除卷，单元保留但解除关联） |
| AI生成质量 | 提供手动编辑能力，AI生成仅作为参考 |
| 单元跨卷移动 | 更新 `book_id` 字段，保持单元顺序连续性 |
| 卷间过渡管理 | 提供卷间过渡数据结构，记录前后卷的关联关系 |
| GBrain启动依赖 | 提供fallback机制，GBrain不可用时自动切换到本地检索 |
| GBrain知识导入 | 支持增量导入和版本管理 |
| MCP协议兼容性 | 使用标准MCP协议，版本号检查 |

---

## 七、完成标准

| 验收项 | 验证方式 |
|--------|----------|
| 卷创建成功 | 创建卷后能在列表中看到 |
| 卷纲编辑 | 能创建、修改、删除卷纲 |
| AI生成卷纲 | 输入概念后能生成卷纲内容 |
| 单元分配到卷 | 创建单元时能选择目标卷 |
| 卷进度统计 | 能看到卷的字数和单元完成率 |
| 卷状态流转 | 能切换卷的状态（规划中/进行中/已完成） |
| 卷间过渡 | 能创建前后卷的过渡关系 |
| GBrain连接 | 配置MCP地址后能成功连接 |
| GBrain搜索 | 能通过GBrain进行混合搜索 |
| GBrain知识存储 | 能将知识存储到GBrain |
| 检索切换 | 能在本地/GBrain后端之间切换 |
| 测试通过 | 所有烟雾测试通过 |

---

## 八、预估工作量

| 步骤 | 复杂度 | 预估文件数 |
|------|--------|----------|
| 数据库迁移 | 低 | 3个SQL文件 |
| 数据模型 | 低 | 1个文件修改 |
| 卷纲服务 | 中 | 1个新文件 |
| 卷服务扩展 | 低 | 1个文件修改 |
| 单元服务扩展 | 低 | 1个文件修改 |
| GBrain客户端 | 中 | 1个新文件 |
| 检索适配器 | 中 | 1个新文件 |
| GBrain服务 | 中 | 1个新文件 |
| UI卷管理 | 高 | 2个新文件 |
| UI GBrain设置 | 中 | 2个新文件 |
| 现有视图扩展 | 中 | 3个文件修改 |
| 配置集成 | 低 | 1个文件修改 |
| 测试 | 中 | 2个新文件 |

---

## 九、后续扩展

1. **卷级引导引擎**：为卷级别提供引导信号（卷级压力、卷级一致性）
2. **卷级因果图**：展示卷内单元之间的因果关系
3. **卷级情绪曲线可视化**：可视化展示卷的情绪变化
4. **多卷并行写作**：支持同时处理多个卷的写作
5. **卷级知识继承**：卷间记忆和状态的自动继承
6. **GBrain知识图谱增强**：利用GBrain知识图谱进行智能推荐和情节分析
7. **GBrain Minions集成**：利用GBrain任务队列进行后台知识处理
8. **多语言支持**：利用GBrain的跨语言能力支持多语种小说创作