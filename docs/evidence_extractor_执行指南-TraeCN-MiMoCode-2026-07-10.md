# 8000 本小说风格提取 — Trae CN 执行指南

MiMoCode · 2026-07-10T01:00:00+08:00

## 项目背景

Novel Writer Pure v4.3 是一个 AI 辅助长篇小说创作工具。目标是从 8000 本全本小说中提取可复用的创作资产，形成 Evidence Library，注入 Story Engine 的 Guide 系统辅助生成。

**核心原则：** Evidence（证据）→ Guide（建议）→ Decision（决策）→ Writing（生成）。提取的数据是冷冰冰的事实，不是硬约束。

## 提取架构（三阶段）

```text
8000 本小说
    │
    ├─ [Phase 1] Python 全量统计 (成本: 0, 耗时: ~数小时)
    │   → Author 统计指纹 + 句子模板 + Scene 统计
    │   工具: jieba 分词 + 正则 + 标点统计
    │
    ├─ [Phase 2] Embedding 聚类 (~1000 本, 成本: 低)
    │   → 角色 Voice 聚类 + 叙事模式发现
    │   工具: sentence-transformers 或 OpenAI embedding
    │
    └─ [Phase 3] LLM 蒸馏 (~500 本, 每本 5 片段, ~2500 次调用)
        → Story Pattern + Narrative 倾向 + 高质量 Voice 总结 + Character Evolution
        工具: 任意 LLM API
```

## Phase 1: Python 全量统计（优先做）

### 1.1 Author 统计指纹

对每本书提取：

```python
{
    "book_id": "书名或ID",
    "avg_sentence_len": 18.3,        # 平均句长
    "short_ratio": 0.42,             # 短句占比 (≤15字)
    "medium_ratio": 0.37,            # 中句占比 (16-35字)
    "long_ratio": 0.21,              # 长句占比 (>35字)
    "dialogue_ratio": 0.48,          # 对白占比 (引号内字数/总字数)
    "description_ratio": 0.32,       # 描写占比
    "inner_monologue_ratio": 0.20,   # 内心独白占比
    "exclamation_density": 0.03,     # 感叹号密度
    "ellipsis_density": 0.02,        # 省略号密度
    "question_density": 0.04,        # 问号密度
    "avg_paragraph_len": 85.0,       # 平均段落长度(字)
    "paragraph_count": 1200,         # 段落数
    "vocabulary_richness": 0.65,     # 词汇丰富度 (TTR)
}
```

**分句规则：**
- 按 `。！？` 分句
- 短句 ≤15 字，中句 16-35 字，长句 >35 字

**对白检测：**
- 正则匹配 `"..."` 或 `「...」` 内的文本

### 1.2 句子模板提取

对每本书，提取短/中/长句的**结构模式**（不存原文）：

```python
{
    "pattern_type": "action_pause",   # 模式名
    "length_bucket": "short",         # short/medium/long
    "structure_desc": "动词短句 → 停顿 → 环境描写",
    "example_count": 15,              # 该模式出现次数
    "scene_tag": "battle",            # 场景标签 (如有)
}
```

**模式识别规则（正则+关键词）：**

| 模式 | 特征 |
|------|------|
| `action_pause` | 短动词句 + 短停顿（"他笑了。但没有解释。"） |
| `scene_memory` | 环境描写 + 回忆触发（"暴雨砸在窗上。他突然想起..."） |
| `emotion_insight` | 情绪 + 洞察（"那一刻他终于明白..."） |
| `dialogue_tension` | 连续短对白（"走。""去哪？""别问。"） |
| `description_layer` | 多层描写（视觉→听觉→触觉） |

### 1.3 Scene 统计

按场景类型统计（需要先做场景分类，或按章节采样）：

```python
{
    "scene_type": "battle",           # battle/romance/reveal/transition/climax/setup/payoff/filler
    "avg_sentence_len": 8.2,          # 战斗场景句长偏短
    "dialogue_ratio": 0.12,           # 战斗场景对白少
    "emotion_density": 0.15,          # 情绪词密度
    "sensory_density": 0.25,          # 感官词密度
    "action_density": 0.65,           # 动作词密度
}
```

## Phase 2: Embedding 聚类（Phase 1 完成后）

### 2.1 角色 Voice 聚类

对每本书的主角对白做聚类：

1. 提取所有 `"角色名说：..."` 的对白
2. 按角色聚合
3. 对每个角色计算：
   - 平均句长
   - 反问句比例
   - 感叹句比例
   - 口语/俚语比例
   - 情绪强度
4. 用 K-Means 聚成 5-10 个 Voice 原型

**Voice 原型示例：**
```python
{
    "prototype": "iceberg",           # 冰山型
    "avg_sentence_len": 8,
    "question_ratio": 0.15,
    "exclamation_ratio": 0.02,
    "slang_ratio": 0.05,
    "emotion_level": 0.2,
    "characteristics": ["冷嘲热讽", "省略主语", "反问多"]
}
```

### 2.2 叙事模式聚类

用 Embedding 对每本书的前 3 章做聚类，发现叙事模式：

```python
{
    "pattern_name": "underdog_growth",
    "pattern_category": "structure",
    "description": "废柴逆袭：主角受辱→获得机缘→首次反击→引来强敌→成长",
    "book_count": 120,                # 聚类中包含多少本书
    "sample_books": ["斗破苍穹", "武动乾坤", ...]
}
```

## Phase 3: LLM 蒸馏（精选 500 本）

### 3.1 Story Pattern 提取

对每本书喂给 LLM：
- 书名 + 简介 + 前 3 章摘要（每章 500 字）
- 要求输出 JSON：

```json
{
    "pattern_name": "underdog_growth",
    "pattern_category": "structure",
    "event_chain": ["受辱", "获得机缘", "首次反击", "引来强敌", "成长"],
    "golden_three_chapters": "第一章受辱触发系统，第二章打脸奴仆，第三章惊动家族高层",
    "climax_frequency": "每 15 章一次小高潮，每 50 章一次大高潮"
}
```

### 3.2 Voice 总结

对 Phase 2 聚类出的 Voice 原型，用 LLM 生成自然语言描述：

```json
{
    "prototype": "iceberg",
    "summary": "冷傲型：话少但每句都有分量，喜欢反问，情绪内敛，用沉默表达态度",
    "writing_tips": "减少感叹句，增加反问句和省略号，对话留白多"
}
```

### 3.3 Character Evolution

对比同一本书前 1/3 和后 1/3 的角色表现：

```json
{
    "character": "主角",
    "from_trait": "犹豫",
    "to_trait": "坚定",
    "stages": ["受辱隐忍", "初次反抗", "独当一面", "领袖蜕变"]
}
```

## 输出格式

### SQLite 表结构

```sql
-- Phase 1 统计指纹
CREATE TABLE author_fingerprints_v2 (
    book_id TEXT PRIMARY KEY,
    book_name TEXT,
    avg_sentence_len REAL,
    short_ratio REAL,
    medium_ratio REAL,
    long_ratio REAL,
    dialogue_ratio REAL,
    description_ratio REAL,
    inner_monologue_ratio REAL,
    exclamation_density REAL,
    ellipsis_density REAL,
    question_density REAL,
    avg_paragraph_len REAL,
    vocabulary_richness REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Phase 1 句子模板
CREATE TABLE sentence_patterns_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id TEXT,
    pattern_type TEXT,
    length_bucket TEXT,
    structure_desc TEXT,
    example_count INTEGER,
    scene_tag TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Phase 2 Voice 原型
CREATE TABLE voice_prototypes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prototype_name TEXT,
    avg_sentence_len REAL,
    question_ratio REAL,
    exclamation_ratio REAL,
    slang_ratio REAL,
    emotion_level REAL,
    characteristics TEXT,  -- JSON array
    summary TEXT,
    book_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Phase 3 Story Pattern
CREATE TABLE story_patterns_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_name TEXT,
    pattern_category TEXT,
    description TEXT,
    event_chain TEXT,  -- JSON array
    golden_three_chapters TEXT,
    climax_frequency TEXT,
    book_count INTEGER,
    sample_books TEXT,  -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### CSV 备份（Phase 1 用）

每本书一行，方便人工检查：

```csv
book_id,book_name,avg_sentence_len,short_ratio,medium_ratio,long_ratio,dialogue_ratio,...
斗破苍穹,天蚕土豆,16.2,0.45,0.38,0.17,0.52,...
完美世界,辰东,19.8,0.38,0.40,0.22,0.45,...
```

## 存放位置

```text
novel-writer-pure-v4.0/
├── evidence_data/                          ← 提取结果统一存放目录
│   ├── evidence.db                         ← SQLite 主库 (Phase 1-3 全部入库)
│   ├── phase1_author_fingerprints.csv      ← Phase 1 CSV 备份 (人工检查用)
│   ├── phase1_sentence_patterns.csv        ← Phase 1 句子模板 CSV
│   ├── phase2_voice_prototypes.csv         ← Phase 2 Voice 原型 CSV
│   ├── phase3_story_patterns.csv           ← Phase 3 Story Pattern CSV
│   ├── extraction_log.jsonl                ← 提取日志 (每本书一行, 含耗时/错误)
│   └── errors.jsonl                        ← 解析失败的书目记录
│
├── novels/                                 ← 8000 本小说原文 (不入库, 仅读取)
│   ├── 斗破苍穹_天蚕土豆.txt
│   ├── 完美世界_辰东.txt
│   └── ...
│
└── evidence_extractor/                     ← 提取脚本代码
    ├── phase1_statistics.py
    ├── phase2_clustering.py
    ├── phase3_distillation.py
    ├── patterns.py
    ├── voice_clusterer.py
    ├── export_sqlite.py
    └── utils.py
```

**关键：** `evidence_data/evidence.db` 是最终产物，后续由 Novel Writer Pure 的 Guide 系统读取。`novels/` 目录只读不写。CSV 文件用于人工抽检，确认准确后可删除。

## 书单来源

小说文件位于 `F:\AI学习资料\小说\`，共 **4396 本 txt 文件，约 11.5GB**。

文件命名格式：
```text
《百炼成仙》（校对版全本）作者：幻雨.txt
《武动乾坤》（精校版全本）作者：天蚕土豆.txt
00后已退休，开局拒绝清冷校花_7319024171596401726.txt
```

提取脚本需读取此目录下的所有 `.txt` 文件（UTF-8 或 GBK 编码）。输出存放在项目目录 `D:\novel-writer-pure-v4.0\evidence_data\`。

## 执行顺序

```text
1. 先用 10 本书跑通 Phase 1，确认统计准确
2. 跑 Phase 1 全量（8000 本，逐本处理，每本处理完释放内存）
3. 人工抽查 10-20 本书的统计结果
4. 用 Phase 1 结果预筛选 ~1000 本（按题材分组取典型 + 按评分排序）
5. 跑 Phase 2（Embedding 聚类，仅 1000 本的摘要）
6. 人工确认 Voice 原型
7. 跑 Phase 3（LLM 蒸馏，500 本精选）
8. 导入 SQLite
```

## 12GB 大文件处理

8000 本小说总计 12GB，无法全量加载到内存。处理策略：

**Phase 1（可处理）：** 逐本读取 → 统计 → 写入 CSV → 释放内存。每本平均 1.5MB，内存峰值 < 10MB。

**Phase 2（需要预筛选）：**
1. Phase 1 完成后，从 CSV 中按条件筛选 ~1000 本
2. 筛选条件：每题材取统计特征最典型的 Top N，或按评分排序
3. 只对这 1000 本的**简介+前3章**做 Embedding（不需要全本）
4. Embedding 输入量：1000 本 × 5000 字 = 5MB，完全可处理

**Phase 3（不受影响）：** 只用简介+前 3 章摘要，不需要全本。

## 代码结构建议

```text
evidence_extractor/
├── phase1_statistics.py      # Phase 1: 全量统计
├── phase2_clustering.py      # Phase 2: Embedding 聚类
├── phase3_distillation.py    # Phase 3: LLM 蒸馏
├── patterns.py               # 句子模式识别规则
├── voice_clusterer.py        # Voice 聚类逻辑
├── export_sqlite.py          # 导入 SQLite
└── utils.py                  # 分句、对白提取等工具函数
```

## 注意事项

1. **先小后大**：先用 10 本书跑通 Phase 1，确认准确后再跑 8000 本
2. **幂等**：每本书生成确定性 ID（MD5），重跑不会重复
3. **容错**：单本书解析失败不影响其他书，记录错误日志
4. **进度**：每 100 本书输出一次进度
5. **编码**：统一 UTF-8，处理 GBK/GB2312 编码的书
6. **内存**：12GB 全量无法加载，Phase 1 逐本处理（读一本→统计→释放），Phase 2 用 Phase 1 结果预筛选 ~1000 本后再做 Embedding
