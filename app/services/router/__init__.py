"""
M11-B: LLM Router 服务层 (L2 业务包装).

app/ai/ 内是 L1 引擎 (router.py / fallback.py / parallel.py / providers.py).
app/services/router/ 是 L2 服务层:
  - signals.py:  业务级信号 (router.used / router.cache_hit / router.fallback)
  - real_client.py: 真实 HTTP 调用 (包装 app.ai.providers + 写事件 + 计费)

为什么 L2 还要再包一层 (不在 L1 直接发业务事件)?
- L1 保持纯净 (只跟 app/ai/registry 打交道, 不依赖 L2 services)
- 业务级事件名可换 (router.* 替代 model.*), 旧订阅者不破坏
- 后续 dashboard / 用量分析 / 缓存策略等业务模块都从 L2 拿
"""
from __future__ import annotations
