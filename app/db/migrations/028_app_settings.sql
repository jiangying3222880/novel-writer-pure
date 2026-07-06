-- 028: app_settings
-- 全局 KV 配置 (P0-P5 硬编码清理用到)
-- 启动时由 init_db() 跑迁移, 不需要手动

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT,                       -- JSON 序列化
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_app_settings_key ON app_settings(key);
