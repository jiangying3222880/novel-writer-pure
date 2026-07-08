# Step B+: Narrative Stability Scaffold
## v4.0 长文本稳定性测试框架设计

### 目的
在 50 章+ 长篇写作压力下验证 conditioning 收敛的实际效果，
不依赖真实 LLM 调用，通过 mock agent 输出模拟叙事漂移检测。

### 核心指标

#### D1: Guide 采纳率漂移
- 测量: 每 10 个 Unit 统计 decision_service 的 adopted/ignored 比例
- 阈值: 采纳率不应连续 3 个窗口下降超过 20%
- 实现: `summary(unit_id)` 聚合统计

#### D2: 角色状态一致性
- 测量: character_tracker 的快照序列是否连续 (相邻 snapshot 的时间戳差异)
- 阈值: 单次跳跃不超过 3 个 story_order
- 实现: `character_state.get_tracker_history()`

#### D3: 伏笔生命周期
- 测量: unit_hook_map 中的 hooks 在 planted→paid_off 之间跨越的 unit 数
- 阈值: 不超过 10 个 Unit (避免"遗忘钩子")
- 实现: `unit_hook_service.list_active_hooks()` 追踪

#### D4: 记忆 L4 废弃率
- 测量: memory_manager.after_writing() 返回的 faded_count 累计值
- 阈值: 不应超过总 memory 条目的 30%
- 实现: `memory.list_by_level(4)` + `memory_manager.after_writing().faded_count`

#### D5: Decision 轨迹一致性
- 测量: 两个入口 (run_unit + run_chapter) 在同一 Unit 上产生的 decision 序列
- 阈值: 完全一致 (100%)
- 实现: 当前 G18 已覆盖

### 测试框架结构

```python
class NarrativeStabilityHarness:
    """模拟 50 个 Unit 序列的叙事稳定性测试."""
    
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.units: list[str] = []
        self.metrics: list[StabilitySnapshot] = []
    
    def run_sequence(self, n_units: int = 50):
        """运行 n 个 Unit 的模拟序列.
        
        每个 Unit:
        1. 调用 run_unit() (mock LLM)
        2. 收集 D1-D5 指标
        3. 记录 StabilitySnapshot
        """
        ...
    
    def detect_drift(self) -> list[DriftWarning]:
        """检测叙事漂移信号."""
        ...
```

### StabilitySnapshot 数据结构

```python
@dataclass
class StabilitySnapshot:
    unit_index: int
    unit_id: str
    guide_adoption_rate: float        # D1
    character_continuity_score: float  # D2
    max_hook_span: int                 # D3
    cumulative_faded_ratio: float      # D4
    decision_identity_ok: bool         # D5
    warnings: list[str]                # 任何异常
```

### DriftWarning 分类

| 类型 | 严重度 | 触发条件 |
|------|--------|---------|
| GUIDE_DECLINE | HIGH | 采纳率连续 3 窗口下降 >20% |
| CHARACTER_FORK | HIGH | 角色快照跳跃 >3 story_order |
| HOOK_ORPHAN | MEDIUM | 钩子跨 10+ Unit 未回收 |
| MEMORY_AMNESIA | MEDIUM | L4 废弃率 >30% |
| DECISION_DIVERGE | CRITICAL | run_unit vs run_chapter decision 不一致 |

### 集成方式

1. **快速模式**: 5 个 Unit 序列, 仅检查 D5 (decision 一致性)
2. **完整模式**: 50 个 Unit 序列, 检查全部 D1-D5
3. **CI 集成**: 快速模式在每次推送时运行 (目标 <10 秒)

### 当前状态
- ✅ D5 (Decision 轨迹一致性): G18 已覆盖, 28/28 通过
- ✅ D1-D4: G19 已实现, 3/3 通过 (smoke/smoke_g19_stability_harness.py)
- ✅ NarrativeStabilityHarness: 已实现, 支持 stable/drift 双模式
- ✅ SVG 轨迹可视化: g19_trajectory.svg 自动生成
- ✅ smoke_quick.py 已注册 G19

### G19 测试结果 (2026-07-06)
| 测试 | 结果 | 详情 |
|------|------|------|
| Stable 模式 | ✅ 0 warnings | D1=0.900 D2=0.907 D3=0.757 D4=0.985 |
| Drift 检测 | ✅ 15 warnings | CHARACTER_LOST + GUIDE_DECLINE + MEMORY_AMNESIA |
| 轨迹图 | ✅ SVG | 4 指标线 + 阈值 + 漂移标记点 |

### 依赖
- 直接 SQL 查询绕过 dual-connection 问题
- 隔离 DB: _setup_temp_db + _init_db
- character_tracker.record() 保留服务层调用 (该路径已验证稳定)
