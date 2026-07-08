"""
Orchestrator (将军) — 8 Agent 调度 + 改稿循环 + 追读率.

设计: 调度 8 个辅助 Agent 协同完成一章写作, 包含记忆拼装、上下文构建、
资料研究、压力决策、RAG 检索、精炼提示、写作、评估门控改稿、落库 9 步。

v3.5.1+ (work-5):
- run_unit() 成为主入口, run_chapter() 标记 @deprecated 兜底
- use_guide_system=True 全路径统一注入 Guide/Decision/Graph (v4.0+ 已收敛)
- 老项目 Chapter 自动通过 virtual_unit_adapter 包装为 Virtual Unit
"""
from __future__ import annotations
import logging
import time
import uuid
import warnings
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from app.agents.base import AgentBase, AgentRole, AgentState
from app.agents.report import Report, ReportKind

_logger = logging.getLogger("NovelWriter.agents.orchestrator")


def _safe_json_list(v) -> list:
    """把可能为 JSON 字符串/列表的字段安全解析为字符串列表."""
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


# ============================================================
# 编排配置
# ============================================================
@dataclass
class OrchestratorConfig:
    """编排参数 (可调)."""
    pass_score: int = 60                # 评估分阈值
    max_revisions: int = 2              # 评估分低时最多让写手改几轮
    retention_low: float = 0.30         # 追读率低 (<30%) 调剧情
    retention_high: float = 0.70        # 追读率高 (>70%) 维持
    enable_retention_adjust: bool = True  # 开启追读率调剧情
    enable_revision_loop: bool = True     # 开启评估门控改稿循环


@dataclass
class OrchestratorResult:
    """run_chapter() 返回值 (供 UI 展示)."""
    ok: bool
    project_id: str
    chapter_id: str
    content: str = ""
    score: int = 0
    revisions: int = 0                  # 改稿轮数
    reports: list[Report] = field(default_factory=list)
    refined_prompt: str = ""            # 编排精炼后的最终 prompt
    retention_adjusted: bool = False    # 是否触发了追读率调剧情
    error: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "project_id": self.project_id,
            "chapter_id": self.chapter_id,
            "content_chars": len(self.content),
            "score": self.score,
            "revisions": self.revisions,
            "retention_adjusted": self.retention_adjusted,
            "refined_prompt_chars": len(self.refined_prompt),
            "report_count": len(self.reports),
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


# ============================================================
# Orchestrator
# ============================================================
class Orchestrator:
    """
    将军: 调度 6 个辅助 Agent 协同完成写作.
    """

    def __init__(
        self,
        helpers: Optional[dict[str, AgentBase]] = None,
        config: Optional[OrchestratorConfig] = None,
    ) -> None:
        self.config = config or OrchestratorConfig()
        # helpers: role.value -> AgentBase
        if helpers is None:
            self.helpers = self._build_default_helpers()
        else:
            self.helpers = dict(helpers)
        # 内部状态
        self._run_id: str = ""
        self._cancelled: bool = False
        # 累计 metrics
        self.run_count: int = 0
        self.last_result: Optional[OrchestratorResult] = None

    def _build_default_helpers(self) -> dict[str, AgentBase]:
        """默认填 8 个辅助 Agent (StoryTeller/Editor/Critic/Retriever/Researcher/ContextBuilder/Memory/Pressure)."""
        # 延迟 import 避免循环
        from app.agents.helpers import (
            storyteller, editor, critic, retriever, researcher,
            context_builder, memory_keeper, pressure_watcher,
        )
        return {
            AgentRole.WRITER.value: storyteller.StoryTeller(),
            AgentRole.EDITOR.value: editor.Editor(),
            AgentRole.CRITIC.value: critic.Critic(),
            AgentRole.RETRIEVER.value: retriever.Retriever(),
            AgentRole.RESEARCHER.value: researcher.Researcher(),
            AgentRole.CONTEXT_BUILDER.value: context_builder.ContextBuilder(),
            AgentRole.MEMORY.value: memory_keeper.MemoryKeeper(),
            AgentRole.PRESSURE.value: pressure_watcher.PressureWatcher(),
        }

    def register(self, agent: AgentBase) -> None:
        """注册 (替换) 一个辅助 Agent."""
        self.helpers[agent.role.value] = agent

    def cancel(self) -> None:
        """取消整轮 (各 helper 也取消)."""
        self._cancelled = True
        for h in self.helpers.values():
            h.cancel()

    # ----------------- 7 步编排 ----------------- #

    def run_chapter(
        self,
        project_id: str,
        chapter_id: str,
        *,
        on_step: Optional[Any] = None,
        retention: Optional[float] = None,
    ) -> OrchestratorResult:
        """[DEPRECATED v3.5.1] 请改用 run_unit(). 章节驱动已废弃.

        兜底保留: 走旧路径, 与 v3.4 行为完全一致.

        推荐: 章节自动包装为 Virtual Unit, 走 run_unit() 主入口.
        """
        warnings.warn(
            "Orchestrator.run_chapter() is deprecated since v3.5.1. "
            "Use run_unit() instead — chapter will be wrapped as Virtual Unit automatically.",
            DeprecationWarning,
            stacklevel=2,
        )

        try:
            from app.services import virtual_unit_adapter as _vua
            unit_id = _vua.wrap_chapter_as_virtual_unit(chapter_id)
            return self.run_unit(
                project_id, unit_id,
                on_step=on_step,
                retention=retention,
                use_guide_system=True,  # v4.0+ 统一注入 Guide/Decision/Graph
            )
        except Exception as e:
            _logger.warning("Virtual Unit 包装失败, 继续走旧章节路径: %s", e)

        self._run_id = "run_" + uuid.uuid4().hex[:8]
        self._cancelled = False
        t0 = time.time()
        reports: list[Report] = []

        def _emit(step: int, label: str) -> None:
            if on_step:
                try:
                    on_step(step, label)
                except Exception:
                    pass

        try:
            # ---- Step 1: Memory 拼装 ----
            _emit(1, "拼装记忆")
            mem_r = self._dispatch(AgentRole.MEMORY, project_id, chapter_id, step=1)
            reports.append(mem_r)
            if not mem_r.ok:
                return self._fail(project_id, chapter_id, reports, f"记忆拼装失败: {mem_r.error}", t0)
            self._check_cancel()

            # ---- Step 2: 上下文构建 (世界观/角色/伏笔/风格/心智) ----
            _emit(2, "构建上下文")
            ctx_r = self._dispatch(AgentRole.CONTEXT_BUILDER, project_id, chapter_id, step=2)
            reports.append(ctx_r)
            self._check_cancel()

            # ---- Step 3: 资料研究 (历史/题材相关) ----
            _emit(3, "资料研究")
            res_r = self._dispatch(AgentRole.RESEARCHER, project_id, chapter_id, step=3)
            reports.append(res_r)
            self._check_cancel()

            # ---- Step 4: 压力计 (决策) ----
            _emit(4, "压力决策")
            pres_r = self._dispatch(AgentRole.PRESSURE, project_id, chapter_id,
                                     step=4, extra={"memory_zone": mem_r.data.get("zone", "green")})
            reports.append(pres_r)
            self._check_cancel()

            # ---- Step 5: RAG 检索 (文风+桥段) ----
            _emit(5, "知识检索")
            ret_r = self._dispatch(AgentRole.RETRIEVER, project_id, chapter_id, step=5)
            reports.append(ret_r)
            self._check_cancel()

            # ---- Step 6: 精炼 + 追读率调剧情 ----
            _emit(6, "精炼提示")
            refined, retention_adjusted = self._refine(
                mem_r=mem_r, ctx_r=ctx_r, res_r=res_r,
                pres_r=pres_r, ret_r=ret_r, retention=retention,
            )

            # ---- Step 7: 写 (写手 = 士兵, 只看精炼版) ----
            _emit(7, "写作中")
            write_r = self._dispatch(AgentRole.WRITER, project_id, chapter_id,
                                     step=7, extra={"refined_prompt": refined, "is_initial": True})
            reports.append(write_r)
            if not write_r.ok:
                return self._fail(project_id, chapter_id, reports, f"写手失败: {write_r.error}", t0)
            self._check_cancel()

            # ---- Step 8: 评估 + 改稿循环 (回调门控) ----
            score = 0
            revisions = 0
            if self.config.enable_revision_loop:
                while revisions < self.config.max_revisions:
                    _emit(8, f"评估 (第 {revisions + 1} 轮)")
                    ed_r = self._dispatch(AgentRole.EDITOR, project_id, chapter_id,
                                           step=8, extra={"content": write_r.data.get("content", "")})
                    reports.append(ed_r)
                    crit_r = self._dispatch(AgentRole.CRITIC, project_id, chapter_id,
                                             step=8, extra={"content": write_r.data.get("content", "")})
                    reports.append(crit_r)
                    score = self._aggregate_score(ed_r, crit_r)
                    if score >= self.config.pass_score:
                        break
                    # 没过关 → 让写手改稿
                    revisions += 1
                    refine2 = self._build_refine_from_feedback(ed_r, crit_r)
                    _emit(8, f"改稿 (第 {revisions} 轮)")
                    write_r = self._dispatch(AgentRole.WRITER, project_id, chapter_id,
                                             step=8, extra={
                                                 "refined_prompt": refine2,
                                                 "is_initial": False,
                                                 "prev_content": write_r.data.get("content", ""),
                                             })
                    reports.append(write_r)
                    self._check_cancel()
            else:
                _emit(8, "评估 (单轮)")
                ed_r = self._dispatch(AgentRole.EDITOR, project_id, chapter_id,
                                       step=8, extra={"content": write_r.data.get("content", "")})
                reports.append(ed_r)
                score = ed_r.data.get("score", 0)

            # ---- Step 9: 落库 ----
            _emit(9, "落库")
            persist_r = self._dispatch_persist(project_id, chapter_id, write_r, score)
            reports.append(persist_r)

            self.run_count += 1
            result = OrchestratorResult(
                ok=True, project_id=project_id, chapter_id=chapter_id,
                content=write_r.data.get("content", ""),
                score=score, revisions=revisions, reports=reports,
                refined_prompt=refined, retention_adjusted=retention_adjusted,
                duration_ms=int((time.time() - t0) * 1000),
            )
            self.last_result = result
            return result
        except _OrchCancelled:
            return self._fail(project_id, chapter_id, reports, "用户取消", t0)
        except Exception as e:
            _logger.exception("[orch] run_chapter 异常")
            return self._fail(project_id, chapter_id, reports, f"{type(e).__name__}: {e}", t0)

    # ----------------- run_unit (v3.5.1 主入口) ----------------- #

    def run_unit(
        self,
        project_id: str,
        unit_id: str,
        *,
        on_step: Optional[Any] = None,
        retention: Optional[float] = None,
        use_guide_system: bool = True,
        use_v4_pipeline: bool = False,
    ) -> OrchestratorResult:
        """v3.5.1 主入口: 单元驱动编排.

        流程:
          1. MemoryKeeper → 拼装记忆
          2. ContextBuilder → 上下文 (unit entry/exit)
          3. Researcher → 资料 (不变)
          4. PressureWatcher → 压力 (unit)
          5. Retriever → RAG (不变)
          6. _refine() → 精炼提示
          7. 写作 (单元内部由 unit_writing_service 分段)
          8. Editor+Critic → 评估改稿
          9. 落库 (snapshot + Event Diff 由 run_unit 完成时自动)

        Args:
            unit_id: Story Unit v2 ID
            use_guide_system: A/B 灰度
              - False (默认): 走旧路径, 行为与 v3.4 一致
              - True: 新路径, 注入 collect_guides() 的 Advice

        Returns:
            OrchestratorResult (含 chapter_id 字段设为 unit 的 source_unit_id,
            兼容 UI 旧展示)

        注: 实际 chapter 创建由 ChapterExporter 在 UI 层按需触发,
        Orchestrator 只产 Unit 流.
        """
        self._run_id = "run_unit_" + uuid.uuid4().hex[:8]
        self._cancelled = False
        t0 = time.time()
        reports: list[Report] = []

        def _emit(step: int, label: str) -> None:
            if on_step:
                try:
                    on_step(step, label)
                except Exception:
                    pass

        # chapter_id 在 unit 模式下用于兼容 UI, 用 unit_id 代替
        chapter_id = unit_id

        try:
            _emit(0, f"Unit 编排启动 (guide={'ON' if use_guide_system else 'OFF'})")
            _logger.info(
                "[orch] run_unit start: project=%s unit=%s use_guide_system=%s",
                project_id, unit_id, use_guide_system,
            )

            # v3.5.1 新路径: 收集 Guide + (v3.6) 上轮 Decision + (v4.0) 冲突图
            guide_block = ""
            decisions_block = ""
            graph_block = ""
            current_guides: list = []  # v3.6: 保存以备 Decision 记录
            if use_guide_system:
                try:
                    from app.core.types import collect_guides
                    current_guides = collect_guides(unit_id, project_id=project_id)
                    if current_guides:
                        guide_block = "\n\n## Story Guidance (建议, 非强制)\n" + \
                            "\n".join(g.to_prompt_block() for g in current_guides[:10])
                        _logger.info("[orch] 注入 %d 个 Guide (max 10)", len(current_guides))
                except Exception as e:
                    _logger.warning("[orch] collect_guides 失败 (降级): %s", e)

                # v3.6: 收集上轮 Decision, 注入 prompt
                try:
                    from app.services.decision_service import list_for_unit, build_decisions_block
                    prev_decisions = list_for_unit(unit_id)
                    if prev_decisions:
                        decisions_block = "\n\n" + build_decisions_block(prev_decisions)
                        _logger.info("[orch] 注入 %d 条上轮 Decision", len(prev_decisions))
                except Exception as e:
                    _logger.warning("[orch] Decision 收集失败 (降级): %s", e)

                # v4.0: 冲突图 (复用 collect_guides 内部已标注的 conflicts_with/supports, 不重复 analyze)
                try:
                    from app.services.guide_graph import build_graph_block_from_guides
                    graph_block = "\n\n" + build_graph_block_from_guides(current_guides)
                    graph_block = graph_block.strip()
                    if graph_block:
                        _logger.info("[orch] 注入冲突图")
                    else:
                        graph_block = ""
                except Exception as e:
                    _logger.warning("[orch] 冲突图构建失败 (降级): %s", e)

            # ---- v4 快速路径: UnitRunner 全链路 ----
            if use_v4_pipeline:
                return self._run_v4_pipeline(
                    project_id, unit_id, chapter_id,
                    on_step=_emit, t0=t0, reports=reports,
                )

            # ---- Step 1: Memory 拼装 ----
            _emit(1, "拼装记忆")
            mem_r = self._dispatch(AgentRole.MEMORY, project_id, chapter_id, step=1)
            reports.append(mem_r)
            if not mem_r.ok:
                return self._fail(project_id, chapter_id, reports, f"记忆拼装失败: {mem_r.error}", t0)
            self._check_cancel()

            # ---- Step 2: 上下文构建 ----
            _emit(2, "上下文构建")
            ctx_r = self._dispatch(AgentRole.CONTEXT_BUILDER, project_id, chapter_id, step=2)
            reports.append(ctx_r)
            if not ctx_r.ok:
                return self._fail(project_id, chapter_id, reports, f"上下文构建失败: {ctx_r.error}", t0)
            self._check_cancel()

            # ---- Step 3: Researcher ----
            _emit(3, "资料研究")
            res_r = self._dispatch(AgentRole.RESEARCHER, project_id, chapter_id, step=3)
            reports.append(res_r)
            self._check_cancel()

            # ---- Step 4: PressureWatcher ----
            _emit(4, "压力观察")
            pw_r = self._dispatch(AgentRole.PRESSURE, project_id, chapter_id, step=4)
            reports.append(pw_r)
            self._check_cancel()

            # ---- Step 5: Retriever ----
            _emit(5, "知识检索")
            ret_r = self._dispatch(AgentRole.RETRIEVER, project_id, chapter_id, step=5)
            reports.append(ret_r)
            self._check_cancel()

            # ---- Step 6: 精炼 + (可选) Guide/Decision 注入 ----
            _emit(6, "精炼提示")
            extra_block = (guide_block + decisions_block + graph_block) if use_guide_system else ""
            refined = self._refine(
                mem_r=mem_r, ctx_r=ctx_r, res_r=res_r,
                pres_r=pw_r, ret_r=ret_r,
                extra_block=extra_block,
            )

            # ---- v4.0: 写前因果审查 (设计 §6) ----
            _emit(6, "因果审查")
            try:
                causal_review = self.review_causality(project_id, unit_id)
                if causal_review.get("ok"):
                    for iss in causal_review.get("issues", []):
                        _logger.info(
                            "[orch] 因果审查 %s: %s",
                            iss.get("type"), iss.get("message"),
                        )
                else:
                    _logger.warning(
                        "[orch] 因果审查返回失败: %s", causal_review.get("error")
                    )
            except Exception as e:
                _logger.warning("[orch] 因果审查失败 (降级): %s", e)

            # ---- Step 7-9: 写作 + 评估 + 落库 ----
            _emit(7, "写作")
            write_r = self._dispatch(AgentRole.WRITER, project_id, chapter_id,
                                      step=7, extra={"refined_prompt": refined})
            reports.append(write_r)
            if not write_r.ok:
                return self._fail(project_id, chapter_id, reports, f"写作失败: {write_r.error}", t0)
            self._check_cancel()

            _emit(8, "评估改稿")
            score = self.config.pass_score
            revisions = 0
            ed_r = self._dispatch(AgentRole.EDITOR, project_id, chapter_id, step=8,
                                   extra={"content": write_r.data.get("content", "")})
            crit_r = self._dispatch(AgentRole.CRITIC, project_id, chapter_id, step=8,
                                     extra={"content": write_r.data.get("content", "")})
            reports.extend([ed_r, crit_r])
            score = self._aggregate_score(ed_r, crit_r)

            # 改稿循环 (与 v3.4 一致, A/B 不影响)
            while (score < self.config.pass_score
                   and revisions < self.config.max_revisions
                   and self.config.enable_revision_loop):
                revisions += 1
                _emit(8, f"改稿第{revisions}轮")
                refined = self._build_refine_from_feedback(ed_r, crit_r)
                write_r = self._dispatch(AgentRole.WRITER, project_id, chapter_id,
                                          step=8, extra={"refined_prompt": refined})
                reports.append(write_r)
                if not write_r.ok:
                    break
                ed_r = self._dispatch(AgentRole.EDITOR, project_id, chapter_id, step=8,
                                       extra={"content": write_r.data.get("content", "")})
                crit_r = self._dispatch(AgentRole.CRITIC, project_id, chapter_id, step=8,
                                         extra={"content": write_r.data.get("content", "")})
                reports.extend([ed_r, crit_r])
                score = self._aggregate_score(ed_r, crit_r)

            # ---- Step 9: 落库 (v4.0: unit 路径走 unit_paragraph_service) ----
            _emit(9, "落库")
            persist_r = self._dispatch_persist(project_id, chapter_id, write_r, score,
                                                store_as_unit=True)
            reports.append(persist_r)

            # v3.6: 自动记录 Decision (仅 use_guide_system=True 且有 Guide)
            if use_guide_system and current_guides:
                try:
                    from app.services.decision_service import record_batch
                    record_batch(unit_id, current_guides,
                                 project_id=project_id, step_no=0)
                    _logger.info("[orch] 记录 %d 条 Decision", len(current_guides))
                except Exception as e:
                    _logger.warning("[orch] Decision 记录失败 (降级): %s", e)

            # v4.0: Story Compiler —— 写完 Unit 后自动分析影响范围
            try:
                from app.services.story_compiler import analyze_impact
                impact = analyze_impact(unit_id)
                if impact.has_impact:
                    _logger.info(
                        "[orch] Impact: unit=%s → %d affected units (%s)",
                        unit_id[:8], len(impact.impacted_units),
                        ", ".join(t for t in impact.by_type),
                    )
            except Exception as e:
                _logger.warning("[orch] Story Compiler 影响分析失败 (降级): %s", e)

            # v4.0: 写后因果更新
            try:
                draft_text = write_r.data.get("text", "") if isinstance(write_r.data, dict) else ""
                self.update_causal_graph(project_id, unit_id, draft_text)
            except Exception as e:
                _logger.warning("[orch] 因果图更新失败 (降级): %s", e)

            duration_ms = int((time.time() - t0) * 1000)
            return OrchestratorResult(
                ok=True,
                project_id=project_id,
                chapter_id=chapter_id,
                content=write_r.data.get("text", "") if isinstance(write_r.data, dict) else "",
                score=score,
                revisions=revisions,
                reports=reports,
                refined_prompt=refined,
                retention_adjusted=False,
                duration_ms=duration_ms,
            )
        except _OrchCancelled:
            return self._fail(project_id, chapter_id, reports, "用户取消", t0)
        except Exception as e:
            _logger.exception("[orch] run_unit 异常")
            return self._fail(project_id, chapter_id, reports, f"{type(e).__name__}: {e}", t0)

    # ----------------- v4 快速路径 ----------------- #

    def _run_v4_pipeline(
        self,
        project_id: str,
        unit_id: str,
        chapter_id: str,
        *,
        on_step: Any,
        t0: float,
        reports: list,
    ) -> OrchestratorResult:
        """v4 快速路径: UnitRunner 全链路 (State→Signals→Decision→Prompt→Write).

        跳过旧的 5-agent 编排, 直接用 v4 pipeline 生成 prompt → 写手 → 落库.
        """
        from story.runtime.unit_runner import UnitRunner

        runner = UnitRunner()

        # Step 1: v4 全链路生成 prompt
        on_step(1, "v4: 构建 prompt")
        v4_result = runner.run(project_id, unit_id)
        if not v4_result.ok:
            return self._fail(project_id, chapter_id, reports,
                              f"v4 pipeline 失败: {v4_result.error}", t0)
        self._check_cancel()

        # 提取 v4 编译好的 prompt (取 user message 作为 refined_prompt)
        compiled = v4_result.prompt
        refined = ""
        if compiled and compiled.messages:
            for msg in compiled.messages:
                if msg.get("role") == "user":
                    refined = msg.get("content", "")
                    break

        _logger.info(
            "[orch-v4] prompt ready: strategy=%s tokens=%d",
            v4_result.decision.label if v4_result.decision else "?",
            compiled.token_estimate if compiled else 0,
        )

        # Step 2: 写手 (复用现有 Writer agent)
        on_step(2, "v4: 写作中")
        write_r = self._dispatch(AgentRole.WRITER, project_id, chapter_id,
                                 step=2, extra={"refined_prompt": refined})
        reports.append(write_r)
        if not write_r.ok:
            return self._fail(project_id, chapter_id, reports,
                              f"写作失败: {write_r.error}", t0)
        self._check_cancel()

        # Step 3: 评估 (与旧流程一致)
        on_step(3, "v4: 评估")
        score = self.config.pass_score
        revisions = 0
        ed_r = self._dispatch(AgentRole.EDITOR, project_id, chapter_id, step=3,
                              extra={"content": write_r.data.get("content", "")})
        crit_r = self._dispatch(AgentRole.CRITIC, project_id, chapter_id, step=3,
                                extra={"content": write_r.data.get("content", "")})
        reports.extend([ed_r, crit_r])
        score = self._aggregate_score(ed_r, crit_r)

        # 改稿循环
        while (score < self.config.pass_score
               and revisions < self.config.max_revisions
               and self.config.enable_revision_loop):
            revisions += 1
            on_step(3, f"v4: 改稿第{revisions}轮")
            refine2 = self._build_refine_from_feedback(ed_r, crit_r)
            write_r = self._dispatch(AgentRole.WRITER, project_id, chapter_id,
                                     step=3, extra={"refined_prompt": refine2})
            reports.append(write_r)
            if not write_r.ok:
                break
            ed_r = self._dispatch(AgentRole.EDITOR, project_id, chapter_id, step=3,
                                  extra={"content": write_r.data.get("content", "")})
            crit_r = self._dispatch(AgentRole.CRITIC, project_id, chapter_id, step=3,
                                    extra={"content": write_r.data.get("content", "")})
            reports.extend([ed_r, crit_r])
            score = self._aggregate_score(ed_r, crit_r)

        # Step 4: 落库
        on_step(4, "v4: 落库")
        persist_r = self._dispatch_persist(project_id, chapter_id, write_r, score,
                                           store_as_unit=True)
        reports.append(persist_r)

        # v4: 记录 Decision
        try:
            from app.services.decision_service import record_batch
            if v4_result.signals:
                guide_dicts = [
                    {"guide_id": s.guide_id, "source": s.source, "advice": s.advice,
                     "priority": s.priority, "confidence": s.confidence}
                    for s in v4_result.signals
                ]
                record_batch(unit_id, guide_dicts, project_id=project_id, step_no=0)
        except Exception as e:
            _logger.warning("[orch-v4] Decision 记录失败: %s", e)

        # v4: 影响分析
        try:
            from app.services.story_compiler import analyze_impact
            impact = analyze_impact(unit_id)
            if impact.has_impact:
                _logger.info("[orch-v4] Impact: %d affected units", len(impact.impacted_units))
        except Exception as e:
            _logger.warning("[orch-v4] 影响分析失败: %s", e)

        duration_ms = int((time.time() - t0) * 1000)
        return OrchestratorResult(
            ok=True,
            project_id=project_id,
            chapter_id=chapter_id,
            content=write_r.data.get("text", "") if isinstance(write_r.data, dict) else "",
            score=score,
            revisions=revisions,
            reports=reports,
            refined_prompt=refined,
            retention_adjusted=False,
            duration_ms=duration_ms,
        )

    # ----------------- 内部 ----------------- #

    def _dispatch(self, role: AgentRole, project_id: str, chapter_id: str, *,
                  step: int = 0, extra: Optional[dict] = None) -> Report:
        if self._cancelled:
            raise _OrchCancelled()
        agent = self.helpers.get(role.value)
        if agent is None:
            return Report.fail("orch", role.value, ReportKind.LOG,
                               f"helper {role.value} 未注册")
        task = {
            "id": f"{self._run_id}_s{step}_{role.value}",
            "context": {
                "project_id": project_id,
                "chapter_id": chapter_id,
                **(extra or {}),
            },
        }
        return agent.execute(task)

    def _dispatch_persist(self, project_id: str, chapter_id: str, write_r: Report, score: int,
                          *, store_as_unit: bool = False) -> Report:
        """
        落库 (统一收口).
        写手 Agent 自己不管落库, Orchestrator 统一收口.

        v4.0: store_as_unit=True 时走单元路径 (段落存 unit_paragraph_service,
        Chapter 只由 ChapterExporter.export_from_unit() 产出).
        store_as_unit=False 时走旧路径 (chapter_service.create_draft, 向后兼容).
        """
        from app.services import chapter_service

        content = write_r.data.get("content", "")
        if not content:
            return Report.ok_with(
                agent_id="orch", agent_role=AgentRole.ORCHESTRATOR.value,
                kind=ReportKind.PERSIST, task_id=f"{self._run_id}_s9",
                data={"skipped": True, "reason": "empty content"},
            )

        if store_as_unit:
            # v4.0 单元路径: 段落存 unit_paragraph_service
            try:
                from app.services import unit_paragraph_service as _para_svc
                _para_svc.replace_full_text(chapter_id, project_id, content)
                _logger.info("[v4.0] 段落落库: unit=%s, content=%d chars", chapter_id, len(content))
            except Exception as e:
                _logger.error("[orch] unit_paragraph_service 落库失败: %s", e)
                return Report.fail(
                    agent_id="orch", agent_role=AgentRole.ORCHESTRATOR.value,
                    kind=ReportKind.PERSIST, task_id=f"{self._run_id}_s9",
                    error=f"unit_paragraph_service.replace_full_text 失败: {e}",
                )

            # 一致性扫描 (unit 粒度)
            try:
                from app.services import consistency
                consistency.check_project(project_id, write_log=True)
            except Exception as e:
                _logger.warning("[orch] consistency 扫描失败: %s", e)

            return Report.ok_with(
                agent_id="orch", agent_role=AgentRole.ORCHESTRATOR.value,
                kind=ReportKind.PERSIST, task_id=f"{self._run_id}_s9",
                data={"unit_id": chapter_id, "store_as": "unit", "score": score},
            )

        # ---- 旧路径: chapter_service ----
        try:
            draft = chapter_service.create_draft(chapter_id, content, source="orchestrator")
            chapter_service.set_current_draft(chapter_id, draft["id"])

            # 同步世界状态
            try:
                from app.services import world_sync
                ch = chapter_service.get(chapter_id) or {}
                chapter_no = ch.get("chapter_no", 0)
                if chapter_no and content:
                    world_sync.sync_after_chapter(
                        project_id, chapter_id, chapter_no, content,
                    )
            except Exception as e:
                _logger.warning("[orch] world_sync 失败: %s", e)

            # 一致性扫描
            try:
                from app.services import consistency
                consistency.check_project(project_id, write_log=True)
            except Exception as e:
                _logger.warning("[orch] consistency 扫描失败: %s", e)

            return Report.ok_with(
                agent_id="orch", agent_role=AgentRole.ORCHESTRATOR.value,
                kind=ReportKind.PERSIST, task_id=f"{self._run_id}_s9",
                data={"draft_id": draft["id"], "score": score},
            )
        except Exception as e:
            return Report.fail("orch", AgentRole.ORCHESTRATOR.value, ReportKind.PERSIST,
                               f"落库失败: {e}")

    def _refine(self, *, mem_r: Report, ctx_r: Report, res_r: Report,
                pres_r: Report, ret_r: Report,
                retention: Optional[float] = None,
                extra_block: str = "") -> tuple[str, bool]:
        """
        编排精炼: 把 memory + context_builder + researcher + pressure + retriever
        + (追读率调整) + (v3.6 Guide/Decision 注入) 拼成 writer 用的精炼提示.
        写手只看这一份, 看不到各 Report 的内部 data.
        """
        parts: list[str] = []
        # 1) 格式化上下文 (世界观/角色/伏笔/风格指纹/心智/题材写法)
        if ctx_r.ok and ctx_r.data.get("ctx_formatted"):
            parts.append(ctx_r.data["ctx_formatted"][:2400])
        # 2) 记忆 L1-L4
        if mem_r.ok and mem_r.data.get("text"):
            parts.append("[记忆 L1-L4]\n" + mem_r.data["text"][:2000])
        # 3) 历史/题材资料 (Researcher)
        if res_r.ok and res_r.data.get("snippets"):
            snippets = res_r.data["snippets"]
            topics = res_r.data.get("topics", [])
            header = "[历史/题材资料]"
            if topics:
                header += f" (检索词: {', '.join(topics[:3])})"
            parts.append(f"{header}\n{snippets[:400]}")
        # 4) 压力 + 反规则
        if pres_r.ok:
            zone = pres_r.data.get("zone", "green")
            zone_labels = {
                "green": "舒适区", "yellow": "预警区",
                "orange": "高压区", "red": "危险区",
            }
            zone_label = zone_labels.get(zone, zone)
            hook = pres_r.data.get("can_open_hook", True)
            pressure_val = pres_r.data.get("pressure", 0)
            parts.append(
                f"[叙事压力: {zone} ({zone_label}), 压力值={pressure_val}] "
                + ("可开新钩子" if hook else "⚠ 不宜开新钩子, 优先收束旧线")
            )
            # 反规则
            if pres_r.data.get("anti_rules_text"):
                parts.append("[反规则]\n" + pres_r.data["anti_rules_text"])
        # 5) 检索 (文风+桥段)
        if ret_r.ok and ret_r.data.get("snippets"):
            parts.append("[文风+桥段参考 ~200字, 0 污染]\n" + ret_r.data["snippets"][:600])
        # 5b) 编排知识库 (编排 Agent 专属: 编排技巧/编排范本/指导手册)
        #     作为结构参考注入精炼提示, 让写手按节奏/断章/拼接范本执行
        try:
            from app.knowledge.finder import extract_for_agent
            # 用已拼好的上下文/记忆/资料作为编排 KB 检索 query
            orch_query = ""
            if ctx_r.ok and ctx_r.data.get("ctx_formatted"):
                orch_query += ctx_r.data["ctx_formatted"][:300] + " "
            if res_r.ok and res_r.data.get("snippets"):
                orch_query += res_r.data["snippets"][:200] + " "
            if mem_r.ok and mem_r.data.get("text"):
                orch_query += mem_r.data["text"][:200]
            orch_kb = extract_for_agent("orchestration", orch_query.strip())
            if orch_kb:
                parts.append(
                    "[编排知识库: 节奏/断章/拼接范本, 仅作结构参考]\n" + orch_kb[:800]
                )
        except Exception as e:
            _logger.warning("[orch] 编排知识库检索失败, 跳过: %s", e)
        # 6) 追读率调剧情
        adjusted = False
        if self.config.enable_retention_adjust and retention is not None:
            if retention < self.config.retention_low:
                parts.append(f"[追读率低: {retention:.0%}] 调剧情: 加强情感冲击, 加入即时冲突, 角色反应要外显")
                adjusted = True
            elif retention < self.config.retention_high:
                parts.append(f"[追读率中: {retention:.0%}] 调剧情: 维持当前节奏, 适度悬念铺垫")
        # 7) 反 AI 味 (静态 6 条)
        parts.append(
            "[写作铁律 6 条]\n"
            "1. 写了画面就不用写结论\n"
            "2. 本场情绪基调一致\n"
            "3. 做出来了就不必再说我正在做这个\n"
            "4. 事件冲击力要体现在角色反应上\n"
            "5. 不解释, 不为情绪/动作做心理注解\n"
            "6. 不凑数, 该空就空"
        )
        # v3.6: Guide/Decision 注入
        if extra_block:
            parts.append(extra_block)
        return "\n\n".join(parts), adjusted

    def _build_refine_from_feedback(self, ed_r: Report, crit_r: Report) -> str:
        """从编辑/批评家反馈拼精炼改稿指令."""
        parts: list[str] = ["[改稿指令]"]
        if ed_r.ok:
            issues = ed_r.data.get("issues", [])
            if issues:
                parts.append("修复以下问题:\n" + "\n".join(f"- {i}" for i in issues[:5]))
        if crit_r.ok and crit_r.data.get("style_notes"):
            parts.append("风格调整:\n" + crit_r.data["style_notes"])
        return "\n\n".join(parts)

    def _aggregate_score(self, ed_r: Report, crit_r: Report) -> int:
        """合并 edit + critic 分数. 默认 0-100."""
        scores: list[int] = []
        if ed_r.ok and isinstance(ed_r.data.get("score"), (int, float)):
            scores.append(int(ed_r.data["score"]))
        if crit_r.ok and isinstance(crit_r.data.get("score"), (int, float)):
            scores.append(int(crit_r.data["score"]))
        if not scores:
            return 0
        return sum(scores) // len(scores)

    # ----------------- 因果审查 (设计文档§6) ----------------- #

    def review_causality(self, project_id: str, unit_id: str) -> dict:
        """因果审查: 检查单元的因果衔接.

        检查项:
        1. cause_summary 与前一单元 effect_summary 衔接
        2. 要回收的伏笔是否已埋设
        3. 呈现顺序与因果顺序的一致性
        """
        issues = []

        try:
            from app.services import story_unit_service_v2 as unit_svc
            unit = unit_svc.get(unit_id)
        except Exception as e:
            return {"ok": False, "error": str(e), "issues": []}

        # 1. 检查 cause_summary 与前一单元 effect_summary
        prev_unit = unit_svc.get_prev_unit(unit_id)
        if prev_unit:
            prev_brief = unit_svc.get_brief(prev_unit.id)
            curr_brief = unit_svc.get_brief(unit_id)
            if prev_brief and curr_brief:
                prev_effect = prev_brief.get("effect_summary", "")
                curr_cause = curr_brief.get("cause_summary", "")
                if prev_effect and curr_cause:
                    if not self._summaries_connected(prev_effect, curr_cause):
                        issues.append({
                            "type": "cause_effect_mismatch",
                            "severity": "warning",
                            "message": f"前因总结与上一单元后果不衔接",
                            "prev_effect": prev_effect[:100],
                            "curr_cause": curr_cause[:100],
                        })

        # 2. 伏笔履约检查 (设计 §6)
        issues.extend(self._check_hook_fulfillment(project_id, unit_id, unit_svc))

        # 3. 时间线一致性检查 (设计 §6)
        issues.extend(self._check_timeline_consistency(project_id, unit_id, unit_svc))

        # 4. 连贯性检查 (设计 §4 双时间线)
        try:
            coh = unit_svc.check_coherence(unit_id)
            for iss in coh.get("issues", []):
                issues.append({
                    "type": "coherence_" + iss.get("code", "issue"),
                    "severity": iss.get("level", "info"),
                    "message": iss.get("msg", ""),
                })
        except Exception as e:
            _logger.warning("[orch] check_coherence 失败: %s", e)

        return {
            "ok": True,
            "unit_id": unit_id,
            "issues": issues,
            "issue_count": len(issues),
        }

    def _summaries_connected(self, effect: str, cause: str) -> bool:
        """检查两个摘要是否衔接 (简化版: 关键词重叠)."""
        effect_words = set(effect.replace("，", " ").replace("。", " ").split())
        cause_words = set(cause.replace("，", " ").replace("。", " ").split())
        overlap = effect_words & cause_words
        return len(overlap) >= 2

    def _check_hook_fulfillment(
        self, project_id: str, unit_id: str, unit_svc
    ) -> list:
        """伏笔履约检查 (设计 §6): 本单元计划回收的伏笔是否已在更早单元埋设."""
        issues: list = []
        try:
            brief = unit_svc.get_brief(unit_id) or {}
            to_pay = _safe_json_list(brief.get("hooks_planned_pay"))
            if not to_pay:
                return issues
            units = unit_svc.list_for_project(project_id, order_by="story")
            planted: set = set()
            for u in units:
                if u.id == unit_id:
                    break
                b = unit_svc.get_brief(u.id) or {}
                planted.update(_safe_json_list(b.get("hooks_planned_plant")))
                planted.update(_safe_json_list(b.get("hooks_planned_pay")))
            for h in to_pay:
                if h and h not in planted:
                    issues.append({
                        "type": "hook_unfulfilled",
                        "severity": "warning",
                        "message": f"计划回收的伏笔未在前序单元埋设: {h}",
                    })
        except Exception as e:
            _logger.warning("[orch] _check_hook_fulfillment 失败: %s", e)
        return issues

    def _check_timeline_consistency(
        self, project_id: str, unit_id: str, unit_svc
    ) -> list:
        """时间线一致性检查 (设计 §6): 按呈现顺序, 伏笔是否先于回收被埋设."""
        issues: list = []
        try:
            units = unit_svc.list_for_project(project_id, order_by="present")
            planted: set = set()
            for u in units:
                b = unit_svc.get_brief(u.id) or {}
                planted.update(_safe_json_list(b.get("hooks_planned_plant")))
                to_pay = _safe_json_list(b.get("hooks_planned_pay"))
                for h in to_pay:
                    if h and h not in planted:
                        issues.append({
                            "type": "timeline_hook_misorder",
                            "severity": "info",
                            "message": f"伏笔[{h}]在单元[{u.title}]按呈现顺序先于埋设被回收(可能为合法 flashback)",
                        })
                if u.id == unit_id:
                    break
        except Exception as e:
            _logger.warning("[orch] _check_timeline_consistency 失败: %s", e)
        return issues

    def update_causal_graph(self, project_id: str, unit_id: str, draft_text: str = "") -> dict:
        """写后因果更新.

        更新项:
        1. 提取实际埋设/回收的伏笔
        2. 更新 cause_summary / effect_summary
        3. 更新因果边
        4. 生成出口状态快照
        """
        try:
            from app.services import story_unit_service_v2 as unit_svc

            unit = unit_svc.get(unit_id)
            brief = unit_svc.get_brief(unit_id) or {}

            # 1. 提取实际已埋/已收伏笔 (对照计划列表做确定性匹配, 非 AI)
            hooks_planted = []
            hooks_paid = []
            if draft_text:
                planned_plant = _safe_json_list(getattr(brief, "hooks_planned_plant", "[]"))
                planned_pay = _safe_json_list(getattr(brief, "hooks_planned_pay", "[]"))
                for h in planned_plant:
                    if h and h in draft_text:
                        hooks_planted.append(h)
                for h in planned_pay:
                    if h and h in draft_text:
                        hooks_paid.append(h)
                _logger.info(
                    "[orch] 因果更新: 实际埋设 %d/%d, 实际回收 %d/%d",
                    len(hooks_planted), len(planned_plant),
                    len(hooks_paid), len(planned_pay),
                )

            # 2. 更新 brief (注意: 实际字段名是 hooks_planned_plant/pay)
            updates = {}
            if hooks_planted:
                existing = getattr(brief, "hooks_planned_plant", "[]")
                try:
                    planted_list = json.loads(existing) if isinstance(existing, str) else existing
                except Exception:
                    planted_list = []
                planted_list.extend(hooks_planted)
                updates["hooks_planned_plant"] = json.dumps(planted_list)

            if hooks_paid:
                existing = getattr(brief, "hooks_planned_pay", "[]")
                try:
                    paid_list = json.loads(existing) if isinstance(existing, str) else existing
                except Exception:
                    paid_list = []
                paid_list.extend(hooks_paid)
                updates["hooks_planned_pay"] = json.dumps(paid_list)

            if updates:
                unit_svc.update_brief(unit_id, **updates)

            # 3. 更新因果边 + 因果组 (设计 §3.4 / §3.5)
            try:
                from app.services import unit_causal_service
                prev_unit = unit_svc.get_prev_unit(unit_id)
                if prev_unit:
                    edges = unit_causal_service.get_edges_for_unit(unit_id)
                    has_edge = any(e["from_unit_id"] == prev_unit.id for e in edges)
                    if not has_edge:
                        unit_causal_service.create_edge(
                            project_id, prev_unit.id, unit_id,
                            edge_type="direct",
                            description="自动建立因果边",
                            strength=0.5,
                        )
                # 因果组: 首个单元完成后建默认"主线"组并把单元加入
                groups = unit_causal_service.get_groups_for_project(project_id)
                if groups:
                    gid = groups[0]["id"]
                else:
                    gid = unit_causal_service.create_group(
                        project_id, name="主线", color="#89b4fa",
                        description="单元完成后自动创建的默认剧情线",
                    )["id"]
                unit_causal_service.add_unit_to_group(gid, unit_id)
            except Exception as e:
                _logger.warning("[orch] 因果边/组写入失败: %s", e)

            # 4. 标记完成
            try:
                unit_svc.mark_completed(unit_id)
            except Exception:
                pass

            return {"ok": True, "unit_id": unit_id, "hooks_planted": hooks_planted, "hooks_paid": hooks_paid}

        except Exception as e:
            _logger.warning("update_causal_graph failed: %s", e)
            return {"ok": False, "error": str(e)}

    def _check_cancel(self) -> None:
        if self._cancelled:
            raise _OrchCancelled()

    def _fail(self, project_id: str, chapter_id: str, reports: list, error: str, t0: float) -> OrchestratorResult:
        result = OrchestratorResult(
            ok=False, project_id=project_id, chapter_id=chapter_id,
            reports=reports, error=error,
            duration_ms=int((time.time() - t0) * 1000),
        )
        self.last_result = result
        return result


class _OrchCancelled(Exception):
    """内部取消信号."""
    pass


# ============================================================
# 工厂函数: 构建已激活的将军
# ============================================================

def build_orchestrator(
    ai_engine: Any = None,
    config: Optional[OrchestratorConfig] = None,
) -> Orchestrator:
    """
    构建已激活的将军实例, 所有 6 个辅助 Agent 均注入真实依赖.

    Args:
        ai_engine: AI 引擎实例 (用于 StoryTeller / Editor). None=自动从 IoC 取.
        config: 编排参数. None=默认配置.
    """
    from app.agents.helpers.storyteller import StoryTeller
    from app.agents.helpers.editor import Editor
    from app.agents.helpers.critic import Critic
    from app.agents.helpers.retriever import Retriever
    from app.agents.helpers.memory_keeper import MemoryKeeper
    from app.agents.helpers.pressure_watcher import PressureWatcher

    helpers = {
        AgentRole.WRITER.value: StoryTeller(ai_engine=ai_engine),
        AgentRole.EDITOR.value: Editor(ai_engine=ai_engine),
        AgentRole.CRITIC.value: Critic(),
        AgentRole.RETRIEVER.value: Retriever(),
        AgentRole.MEMORY.value: MemoryKeeper(),
        AgentRole.PRESSURE.value: PressureWatcher(),
    }
    return Orchestrator(helpers=helpers, config=config)
