"""
Conversation service - three-step guided conversation for novel setting
generation. The state lives in process memory (single-process app, fine
for desktop usage). State is keyed by conversation_id (UUID).
"""
from __future__ import annotations
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional

from app.services.exceptions import NotFoundError, ValidationError

log = logging.getLogger(__name__)


class ConversationStep(str, Enum):
    INIT = "init"
    STEP1_DONE = "step1_done"
    STEP2_DONE = "step2_done"
    STEP3_DONE = "step3_done"


@dataclass
class ConversationState:
    conversation_id: str
    project_id: Optional[str] = None
    step: ConversationStep = ConversationStep.INIT
    inspiration: Optional[str] = None
    follow_up_questions: Optional[str] = None
    follow_up_answers: Optional[str] = None
    generated_setting: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["step"] = self.step.value
        return d


# In-memory store. Phase 3 can persist these to SQLite if needed.
_conversations: dict[str, ConversationState] = {}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _touch(state: ConversationState) -> None:
    state.updated_at = _now()


# ----- Lifecycle -----

def new_conversation(project_id: Optional[str] = None) -> ConversationState:
    """Start a brand new conversation. Returns the state."""
    conv_id = str(uuid.uuid4())
    state = ConversationState(conv_id, project_id)
    _conversations[conv_id] = state
    return state


def get_conversation(conversation_id: str) -> ConversationState:
    if conversation_id not in _conversations:
        raise NotFoundError("Conversation", conversation_id)
    return _conversations[conversation_id]


# ----- Step transitions -----

def submit_step1(conversation_id: str, inspiration: str) -> ConversationState:
    state = get_conversation(conversation_id)
    if state.step != ConversationStep.INIT:
        raise ValidationError(
            f"Invalid step. Current: {state.step.value}, expected: init"
        )
    state.inspiration = inspiration
    state.follow_up_questions = None
    state.step = ConversationStep.STEP1_DONE
    _touch(state)
    return state


def submit_step2(conversation_id: str, answers: str) -> ConversationState:
    state = get_conversation(conversation_id)
    if state.step != ConversationStep.STEP1_DONE:
        raise ValidationError(
            f"Invalid step. Current: {state.step.value}, expected: step1_done"
        )
    state.follow_up_answers = answers
    state.step = ConversationStep.STEP2_DONE
    _touch(state)
    return state


def submit_step3(conversation_id: str, generated_setting: str) -> ConversationState:
    state = get_conversation(conversation_id)
    if state.step != ConversationStep.STEP2_DONE:
        raise ValidationError(
            f"Invalid step. Current: {state.step.value}, expected: step2_done"
        )
    state.generated_setting = generated_setting
    state.step = ConversationStep.STEP3_DONE
    _touch(state)
    return state


# ----- Prompt templates -----

STEP1_SYSTEM_PROMPT = """你是一位资深的小说策划编辑，擅长帮助作者从一个模糊的灵感出发，提出有针对性的追问来完善小说设定。

你的任务是根据用户提供的灵感/想法，提出3-5个关键的追问问题，帮助明确：
1. 世界观设定（时代背景、力量体系、社会结构）
2. 主角设定（身份、性格、目标、困境）
3. 核心冲突（主要矛盾、反派/阻碍力量）
4. 故事类型和风格（热血、轻松、暗黑、文艺等）
5. 目标读者和平台（起点、晋江、番茄等）

请直接输出问题，不要多余的开场白。每个问题一行，编号列出。"""

STEP2_SYSTEM_PROMPT = """你是一位资深的小说策划编辑。现在你已经有了作者的灵感描述和追问回答。

请根据这些信息，为作者生成一份完整的小说初始设定文档，包括：

## 格式要求
1. **书名建议**（3个备选）
2. **一句话简介**（30字以内）
3. **世界观概述**（200-300字）
4. **主角设定**（姓名/身份/性格/目标/困境，各50-100字）
5. **核心冲突**（100-200字）
6. **力量/社会体系**（如有，200-300字）
7. **故事线大纲**（开篇/发展/高潮/结局，各100字）
8. **风格定位**（类型/基调/节奏/字数目标）

请用清晰的Markdown格式输出。"""


# ----- LLM 调用 (V4.0-P4-新: 真正接通 AI, 之前 service 只存状态) -----

def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """调 LLM 拿回答. 失败时降级到 mock.

    V4.0-P4-新: 之前 service 留了 system_prompt 但没接通, 现在接上. 用法:
      _call_llm(STEP1_SYSTEM_PROMPT, "灵感: ...") → str (AI 回答)

    降级策略:
      - import router.real_client 失败 → mock
      - 调用异常 (无 model / 无 key / 超时) → mock
    """
    try:
        # 1) 尝试真模型
        from app.services.router.real_client import create_real_client
        client = create_real_client()
        if client:
            # 构造 messages: system prompt 作为 system role 消息前置
            msgs = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            result = client.chat(
                messages=msgs,
                temperature=0.7,
                max_tokens=2000,
            )
            content = result.content if hasattr(result, 'content') else str(result)
            if content and content.strip():
                return content.strip()
    except Exception as e:
        log.warning("LLM call failed, fallback to mock: %s", e)
    # 2) mock fallback
    return _mock_llm(system_prompt, user_prompt)


def _mock_llm(system_prompt: str, user_prompt: str) -> str:
    """无 LLM 时的兜底: 根据 system_prompt 类型返回模板回答.

    注意: mock 会 sleep 1.0-1.5 秒, 让 UI 的等待页有足够时间展示,
    否则毫秒级完成用户看不到任何过程。
    """
    import time, random
    time.sleep(random.uniform(1.0, 1.5))
    if "3-5个关键的追问问题" in system_prompt or "提出3-5" in system_prompt:
        # step1: 返回固定追问
        return (
            "1. 你想写什么题材 / 类型的小说？（如 玄幻 / 都市 / 仙侠 / 科幻 / 言情）\n"
            "2. 主角是什么样的人？身份/性格/目标分别是什么？\n"
            "3. 这个故事的核心矛盾 / 反派是谁？\n"
            "4. 故事发生在什么时代 / 世界？（现代都市 / 异世界 / 古代架空 / 未来星际）\n"
            "5. 目标读者和发布平台是？（起点 / 番茄 / 晋江 / 七猫 等）\n"
        )
    # step2: 返回模板设定 (用用户灵感做项目名/简介)
    seed = user_prompt[:200].replace("\n", " ").strip() or "我的新小说"
    book_title_a = seed.split("。")[0][:10] or "新世界"
    return (
        f"## 1. 书名建议\n1. 《{book_title_a}》\n2. 《纪元》\n3. 《破晓》\n\n"
        f"## 2. 一句话简介\n一个关于{seed[:30]}的故事。\n\n"
        f"## 3. 世界观概述\n这是一个架空的奇幻世界, 存在多种力量体系, 主角在这个世界中逐渐成长。\n\n"
        f"## 4. 主角设定\n姓名: 陆沉\n身份: 普通少年 / 隐藏身份\n性格: 坚毅 / 善良\n目标: 寻找真相 / 保护重要的人\n困境: 资源匮乏 / 被追杀\n\n"
        f"## 5. 核心冲突\n主角发现世界的真相, 与传统秩序产生根本冲突, 必须做出选择。\n\n"
        f"## 6. 力量 / 社会体系\n境界划分: 入门 / 精进 / 大师 / 宗师 / 传说\n\n"
        f"## 7. 故事线大纲\n开篇: 主角平凡生活被打破\n发展: 进入修炼之路, 遇到同伴\n高潮: 与反派决战\n结局: 完成使命, 找到归属\n\n"
        f"## 8. 风格定位\n类型: 玄幻 / 升级流\n基调: 热血 / 友情\n节奏: 中等偏快\n字数目标: 200-300 万字\n"
    )


def run_step1(conversation_id: str, inspiration: str) -> ConversationState:
    """V4.0-P4-新: step1 = 用户给灵感 → AI 追问.

    先调 submit_step1 存灵感, 再调 LLM 拿追问, 存到 follow_up_questions.
    """
    state = submit_step1(conversation_id, inspiration)
    user_prompt = f"用户灵感: {inspiration}\n\n请按 system 提示, 直接列出 3-5 个追问问题."
    questions = _call_llm(STEP1_SYSTEM_PROMPT, user_prompt)
    state.follow_up_questions = questions
    _touch(state)
    return state


def run_step2(conversation_id: str, answers: str) -> ConversationState:
    """V4.0-P4-新: step2 = 用户回答追问 → AI 生成完整设定.

    流程:
      1) submit_step2(answers) → state.step = STEP2_DONE
      2) 调 LLM 拿生成设定
      3) submit_step3(generated_setting) → state.step = STEP3_DONE
    """
    submit_step2(conversation_id, answers)
    state = get_conversation(conversation_id)
    user_prompt = (
        f"用户灵感: {state.inspiration or ''}\n\n"
        f"追问回答: {answers}\n\n"
        f"请按 system 提示, 生成完整小说初始设定 Markdown."
    )
    setting = _call_llm(STEP2_SYSTEM_PROMPT, user_prompt)
    return submit_step3(conversation_id, setting)
