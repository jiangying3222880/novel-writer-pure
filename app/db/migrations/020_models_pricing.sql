-- 020: models_pricing
-- A3 + A4 拍板: 模型注册表 (3 层)
-- 1. 内置预置 (built_in = 1, 用户不可删)
-- 2. 用户 UI 配置 (built_in = 0, 用户可改)
-- 3. DB 存 (本表)

CREATE TABLE IF NOT EXISTS model_configs (
    id TEXT PRIMARY KEY,                -- 用户起的名字 (e.g. "主力-mini")
    provider TEXT NOT NULL,             -- openai_compat / anthropic
    model_name TEXT NOT NULL,           -- gpt-4o-mini / claude-3.5-sonnet
    base_url TEXT DEFAULT '',
    api_key TEXT DEFAULT '',
    role TEXT DEFAULT 'primary',        -- primary / fallback
    rpm_limit INTEGER DEFAULT 60,
    tpm_limit INTEGER DEFAULT 90000,
    input_price REAL DEFAULT 0.0,        -- ¥/M tokens
    output_price REAL DEFAULT 0.0,
    max_tokens INTEGER DEFAULT 4096,
    supports_streaming INTEGER DEFAULT 1,
    supports_thinking INTEGER DEFAULT 0,
    built_in INTEGER DEFAULT 0,         -- 1 = 预置, 0 = 用户加
    price_updated_at TEXT DEFAULT (datetime('now')),
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mc_role ON model_configs(role);
