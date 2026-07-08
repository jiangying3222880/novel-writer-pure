# M2 设计文档：LLM 客户端 + 全局模型配置 + UI 集成

> Phase 3 子阶段 M2：把"AI"从空壳推到"可配置、可回退、真接入"。
>
> 配套测试：`python -m app.tests.m2_smoke`（8/8）+ `python -m app.tests.m2_ui_stream_smoke`（3/3）

---

## 1. 目标

- 用户能加自己的 LLM 厂商（DeepSeek / 通义 / Claude / Ollama / 任意 OpenAI 兼容端点），不需要改代码
- 项目级关注"写什么"，全局只关心"用什么模型"
- LLM 调用失败不卡死流程（fallback / mock / 解析容错）
- UI 端一键切换"用什么模型"，一键测连通性

---

## 2. 三层职责

| 层 | 文件 | 职责 |
|---|---|---|
| 协议层 | `app/core/llm.py` | `LLMClient` 调 HTTP, 解析 OpenAI/Anthropic 协议, 多 provider fallback, 流式 SSE |
| 配置层 | `app/services/app_setting_service.py` | 全局 provider 列表 / active, 落盘 `%APPDATA%/NovelWriterPure/app_settings.json` |
| 编排层 | `app/core/chapter_generator.py` | 3 agent 接口, 注入式: `Mock*` (M1) ↔ `LLM*` (M2) |
| UI 层 | `app/ui/tabs/settings_tab.py` `app/ui/tabs/generate_tab.py` | 配置表单 + 流式显示 |

**不耦合**：业务层（chapter_service / 项目层）完全不知道 LLM 存在，只接受"generator.run()"。

---

## 3. 协议层 `LLMClient`

### 3.1 抽象

```python
@dataclass
class ProviderConfig:
    name: str
    provider_type: ProviderType   # openai_compat | anthropic
    api_base: str
    api_key: str
    model: str
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: float = 120.0
    priority: int = 0              # 越小越优先 (fallback 链)

class LLMClient:
    def configure(providers: list[ProviderConfig]) -> None
    def chat(messages, temperature, max_tokens, step) -> ChatResponse
    def chat_stream(messages, ...) -> Iterator[str]
```

### 3.2 协议分支

| provider_type | endpoint | 鉴权头 | 关键差异 |
|---|---|---|---|
| `openai_compat` | `{api_base}/chat/completions` | `Authorization: Bearer {key}` | 标准 stream=true + SSE `data: {...}` chunk |
| `anthropic` | `{api_base}/messages` | `x-api-key: {key}` + `anthropic-version: 2023-06-01` | system 字段提到顶层; 流式 event 类型不同 (`content_block_delta`) |

**M2 范围**：仅 2 个协议分支。所有"OpenAI 兼容"厂商（DeepSeek / 通义 / 智谱 / 硅基流动 / Ollama / 自定义 proxy）走同一分支。

### 3.3 Fallback 链

`chat()` 顺序遍历 providers（按 priority 升序）：
- 任一返回成功 → 立即返回
- 全部失败 → 抛 `RuntimeError("All providers failed: ...")` 含每家原因
- 部分失败 → log warning 但继续

**为什么不做加权 / 熔断**：单机桌面场景，同时挂 2 家以上不现实，加复杂度没收益。

### 3.4 流式解析

OpenAI 兼容：
```
data: {"choices":[{"delta":{"content":"你"}}]}
data: {"choices":[{"delta":{"content":"好"}}]}
data: [DONE]
```
- 跳过空 `delta.content` 和 `data: [DONE]`
- 容错：`iter_lines` 偶发空行 / 注释行（`:keep-alive`）

Anthropic:
```
event: content_block_delta
data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"你"}}
```
**M2 暂未实装** Anthropic 流式（chat 已实装，stream 走 openai_compat 路径）。M3 之前要补上。

### 3.5 27 厂商预设（`PROVIDER_PRESETS`）

| 类别 | 厂商 | api_base | 默认 model |
|---|---|---|---|
| 国际 | openai | `https://api.openai.com/v1` | gpt-4o |
| | anthropic | `https://api.anthropic.com/v1` | claude-3-5-sonnet |
| | google | `https://generativelanguage.googleapis.com/v1beta` | gemini-1.5-pro |
| | xai / mistral / cohere | 各家 | 各家 |
| 国内 | deepseek | `https://api.deepseek.com/v1` | deepseek-chat |
| | moonshot / zhipu / zhipu_glm / baidu | 各家 | 各家 |
| | alibaba / qwen / tencent | dashscope / lkeap | qwen-max / hunyuan |
| | yi / step / spark / siliconflow | 各家 | 各家 |
| 聚合 | openrouter / groq / together / fireworks / perplexity | 各家 | 各家默认 |
| 本地 | ollama | `http://localhost:11434/v1` | llama3.1 |
| 自定义 | custom | `http://localhost:11434/v1` (占位) | custom-model |

预设只填 api_base / model，**不影响 provider_type**。`_resolve_provider_type` 按 api_base 启发式判断：
- 含 `anthropic` → `anthropic`
- 其他 → `openai_compat`

---

## 4. 配置层 `app_setting_service`

### 4.1 存储

```json
{
  "providers": [
    {
      "name": "deepseek-main",
      "provider_type": "openai_compat",
      "api_base": "https://api.deepseek.com/v1",
      "api_key": "sk-...",
      "model": "deepseek-chat",
      "max_tokens": 4096,
      "temperature": 0.7,
      "timeout": 120.0,
      "priority": 0
    }
  ],
  "active_provider": "deepseek-main"
}
```

- 路径：`%APPDATA%/NovelWriterPure/app_settings.json`（Windows）/ `~/.local/share/.../app_settings.json`（Linux）
- 写：`tempfile.mkstemp` + `os.replace` 原子写，半写不会污染
- 读：容错（不存在 / 损坏 / 字段缺失 → 空结构 + warning）

### 4.2 公共 API

| 函数 | 行为 | 失败 |
|---|---|---|
| `list_providers()` | 按 priority 升序 | — |
| `get_provider(name)` | 完整配置 | NotFoundError |
| `add_provider(p)` | 默认字段补齐 | ValidationError (name 重复 / 字段类型) |
| `update_provider(name, patch)` | 不允许改名 | NotFoundError / ValidationError |
| `delete_provider(name)` | 联动清空 active | NotFoundError |
| `set_active(name)` | 单选 | NotFoundError |
| `get_active()` | 给 LLMClient 用 | None (无 active) |

### 4.3 校验

- name 必填且唯一
- provider_type ∈ {openai_compat, anthropic}
- api_key / api_base 必须是 str
- model 必填非空
- priority 是 int
- max_tokens > 0
- temperature ∈ [0.0, 2.0]

### 4.4 与项目级 setting_service 的区别

| | app_setting_service | setting_service |
|---|---|---|
| 范围 | 全局（跨项目） | 项目内（每项目一份） |
| 存什么 | LLM provider 配置 | worldbuilding / characters / anti_rules / hooks / voice_profiles / style_fingerprint |
| 文件 | `app_settings.json` | `data/projects/{id}/settings.json` |
| 何时读 | generator 构造时 | 写章节时, 拼 prompt |

---

## 5. 编排层 `ChapterGenerator`

### 5.1 工厂模式

```python
gen = ChapterGenerator()                 # 默认 mock (M1, 离线/测试)
gen = ChapterGenerator(mindset=..., ...)  # 显式注入 (高级用)
gen = ChapterGenerator.from_llm(client)  # 真 LLM (M2, 生产)
```

`from_llm(llm_client)` 把 3 个 mock agent 替换为 LLM 实现，agent 接口签名不变。

### 5.2 三个 agent

| Agent | LLM 调用 | 流式 | 解析容错 |
|---|---|---|---|
| LLMMindsetAgent | `chat()`, step="mindset" | 否 | 6 问 JSON 抽取, 任一字段空回退 mock |
| LLMWriterAgent | `chat_stream()`, step="write" | 是 | LLM 失败回退 mock 4 段 |
| LLMCriticAgent | `chat()`, step="critique" | 否 | 评分 JSON 抽取, 失败回退 (score=50, summary="LLM failed") |

**回退 mock 不是 silent failure**：log warning 让用户能在日志里看到。**不重试**：一次失败就回退，因为 LLM 失败时越重试越浪费 token。

### 5.3 落库

`ChapterGenerator.run()` 全跑完（mindset → write → critic）才落库：
- `chapter_drafts` 表新增一行 (content, source="agent")
- `chapter_change_log` 新增一行 (change_type="regen", note=critic.summary)
- `chapters.current_draft_id` 指向新 draft
- `chapters.status` = "critiqued"
- `chapters.review_flag` = "problem" (score < 60) / "pending"

**取消不落库**：被 `should_cancel()` poll 触发 CancelledError 时，编排器在写库之前 raise，已生成的内容丢弃，章节状态保持原样。

---

## 6. UI 层

### 6.1 设置页（`SettingsTab → ModelSettingsWidget`）

```
┌─ Provider 列表 ──────┬─ 当前 active: deepseek-main ─┐
│ ⭐ deepseek-main     │  Provider 配置               │
│    ollama-local      │  预设: [deepseek ▼]         │
│                       │  名称:   [deepseek-main]    │
│ [➕ 新建]             │  API Base: [https://...]     │
│ [🗑️ 删除]            │  API Key:  [***]             │
│                       │  Model:   [deepseek-chat]   │
│                       │  max_tokens: [4096]         │
│                       │  temperature: [0.7]         │
│                       │  timeout:    [120.0]        │
│                       │  priority:   [0]            │
│                       │                              │
│                       │  [💾 保存] [🧪 测试] [⭐ active]│
└───────────────────────┴──────────────────────────────┘
```

- **预设下拉**只填 api_base / model（仅当字段为空时），**不写死 provider_type**
- **测试连接**：用当前表单内容（不一定要先保存）发 1 条 "hi"，8 token 验证连通性
- **active 切换**：单选，写到 `active_provider` 字段
- **删除 active**：联动清空 `active_provider`

### 6.2 生成页（`GenerateTab → GenerateWorker`）

M2 改造点：

```python
# 之前
self._generator = ChapterGenerator()  # mock

# 现在
gen, info_msg = _build_generator_for_active_provider()
self._generator = gen
self._info_msg = info_msg
```

新增 `info` signal（区别于 `error`）：软提示，比如"未配 active provider, 已用 mock"。

`_build_generator_for_active_provider()` 流程：
1. `app_setting_service.get_active()` 拿配置
2. 没配 → 返 mock + info_msg
3. 配了 → 构造 `LLMClient` + `ChapterGenerator.from_llm()`
4. 构造抛错（api_key 缺失 / provider_type 非法）→ 返 mock + info_msg

**Worker 跑在 QThread 中**，UI 流式显示：

```
[生成] 按钮
    ↓ QThread.started → worker.run()
[⏳ 生成中…]
    chunk signal → 实时 append to QPlainTextEdit
    mindset_ready → log (TODO: 折叠显示)
    critic_ready → status_label "📖 Critic 评分: 88"
    done → status_label "✅ 完成 | 📖 88 | 草稿已保存"
    error → status_label "❌ {msg}"
    info → status_label "ℹ️ {msg}"
[停止] 按钮 → worker.cancel() → 下一个 chunk 检查时 raise CancelledError
```

---

## 7. 决策点（不写的边界）

### 7.1 不做
- ❌ **多 LLM 并行 voting**：太重，单作者作品风格要一致，不该让多家投票
- ❌ **自动选择最快 provider**：用户自己选，人比 latency 敏感
- ❌ **API key 加密存**：开发期内置简单 base64 即可；上 PyInstaller 打包时再上 keyring（M3）
- ❌ **TLS 证书自定义**：桌面端跑 OpenAI 默认就够
- ❌ **provider import / export JSON**：单机单用户，没意义

### 7.2 推迟到 M3
- ⚠️ **Anthropic 流式解析**（chat 已实装，stream 走 openai_compat 路径）
- ⚠️ **Provider 状态面板**（延迟 / 错误率 / token 用量）→ `usage_record` 已经记录，等仪表盘
- ⚠️ **多 provider 权重负载**（priority 0/1 已支持顺序，但不做并发）
- ⚠️ **流式中断后断点续传**（关闭程序就丢）

### 7.3 永远不做（原则）
- 🚫 **让 AI 改 AI 写的章节而不经人**：M1 决策定调，Critic 是顾问不是守门人
- 🚫 **Provider 配置走云同步**：单机离线
- 🚫 **强制锁定某家 provider**：必须能一键切回 mock / 旧 provider

---

## 8. 测试矩阵

| 测试 | 覆盖 |
|---|---|
| `m2_smoke[1/8]` OpenAI chat 解析 | 响应 JSON 字段提取, usage 统计, 请求 payload |
| `m2_smoke[2/8]` OpenAI stream SSE | chunk 累加, 空 delta 跳过, [DONE] 终止 |
| `m2_smoke[3/8]` Anthropic chat 解析 | content blocks 拼接, system 字段拆分, headers |
| `m2_smoke[4/8]` Fallback | a 失败 → 切 b, 全失败 RuntimeError |
| `m2_smoke[5/8]` 空 providers | 抛 RuntimeError |
| `m2_smoke[6/8]` app_setting_service CRUD | add / get / update / delete / active / 校验 |
| `m2_smoke[7/8]` SettingsTab UI | _match_preset / _resolve_provider_type / _on_save / _on_delete |
| `m2_smoke[8/8]` ChapterGenerator e2e | stub LLM 走 3 agent 落库, draft + change_log 验证 |
| `m2_ui_stream_smoke[1/3]` 无 active | info signal + mock 落库 |
| `m2_ui_stream_smoke[2/3]` 有 active | stub LLM 走通, draft_id 落库 |
| `m2_ui_stream_smoke[3/3]` cancel | CancelledError, 0 个 chunk, 状态保持 draft |

---

## 9. M2 范围外但要记得的事

- M3 要做的: HookAnalyzer, 段落重写工具, 实体管理面板, 仪表盘追读率
- 集成 2.0 prompt 资产: 风格指纹 / 声音档案 / 潜文本卡 / 反规则（部分已通过项目级 setting_service 落库，WriterAgent prompt 中要组装）
- API key 加密（打包发布前必须上 keyring）
- 流式 Anthropic 解析

---

**变更记录**

- 2026-06-08: m2 收尾。11/11 测试通过。
