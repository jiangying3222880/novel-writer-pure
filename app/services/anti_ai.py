"""
E2 6 大去 AI 味检查器 (v3_engine 第 2 步)
- 检查项 6 个 (基于"AI 写作 vs 真人写作"常见差距)
- 每个 check 是纯函数, 输入: (text, ctx) → Issue 列表
- Issue 含: kind / severity / location / suggestion
- 不调 AI, 不依赖外部, 完全本地可跑

6 项:
  1. SENTENCE_PATTERN  句式模板去重 (连续同结构)
  2. DIALOGUE_VOICE    对话个性化 (口吻区分)
  3. PACING_BREATH     节奏呼吸 (长短句交替)
  4. RHETORIC_MOD      修辞适度 (形容词/副词密度)
  5. POV_CONSIST       视角一致
  6. INFO_GAP          信息差控制 (避免上帝视角)

v3.4 新增: 三遍法 + 误杀防护
  - Pass1: 去泛化 (去"非常""极其"等泛化词)
  - Pass2: 去书面化 (去过于书面化的表达)
  - Pass3: 回自然感 (恢复自然的口语化表达)
  - 误杀防护: 角色化表达/对话特例/功能豁免不改
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

_logger = logging.getLogger("NovelWriter.services.anti_ai")


# ────────────────────── 严重度 ──────────────────────

class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    BLOCK = "block"  # 阻断生成


SEVERITY_ORDER = {Severity.INFO: 0, Severity.WARN: 1, Severity.BLOCK: 2}


# ────────────────────── 检查类型 ──────────────────────

class CheckKind(str, Enum):
    SENTENCE_PATTERN = "sentence_pattern"
    DIALOGUE_VOICE = "dialogue_voice"
    PACING_BREATH = "pacing_breath"
    RHETORIC_MOD = "rhetoric_mod"
    POV_CONSIST = "pov_consist"
    INFO_GAP = "info_gap"
    # v3.4 新增: 三遍法检查类型
    PASS1_GENERALIZATION = "pass1_generalization"  # 去泛化
    PASS2_WRITTEN_STYLE = "pass2_written_style"    # 去书面化
    PASS3_NATURAL = "pass3_natural"                # 回自然感
    # v4.1 新增: 对标 story-deslop 7-Gate 体系
    TOXIC_PATTERNS = "toxic_patterns"              # Gate A/B: 高危句式 (不是A而是B/万能状语/表情模板)
    EXPLANATION_VOICE = "explanation_voice"        # Gate G: 解释腔/上帝视角/安排感
    ENDING_SUBLIMATION = "ending_sublimation"      # Gate F: 结尾升华/总结体
    EXCESS_MODIFIERS = "excess_modifiers"          # Gate B/C: 修饰词清扫/弱化副词滥用


CHECK_LABELS = {
    CheckKind.SENTENCE_PATTERN: "句式去重",
    CheckKind.DIALOGUE_VOICE: "对话个性",
    CheckKind.PACING_BREATH: "节奏呼吸",
    CheckKind.RHETORIC_MOD: "修辞适度",
    CheckKind.POV_CONSIST: "视角一致",
    CheckKind.INFO_GAP: "信息差",
    CheckKind.PASS1_GENERALIZATION: "去泛化",
    CheckKind.PASS2_WRITTEN_STYLE: "去书面化",
    CheckKind.PASS3_NATURAL: "回自然感",
    CheckKind.TOXIC_PATTERNS: "高危句式",
    CheckKind.EXPLANATION_VOICE: "解释腔",
    CheckKind.ENDING_SUBLIMATION: "结尾升华",
    CheckKind.EXCESS_MODIFIERS: "修饰冗余",
}


# ────────────────────── Issue 数据类 ──────────────────────

@dataclass
class Issue:
    kind: str
    label: str
    severity: str
    location: str            # 章节内位置 (e.g., "p3.s2" 表示第 3 段第 2 句)
    snippet: str = ""        # 问题原文片段 (限长)
    suggestion: str = ""     # 建议
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "severity": self.severity,
            "location": self.location,
            "snippet": self.snippet,
            "suggestion": self.suggestion,
            "detail": self.detail,
        }


# ────────────────────── 通用工具 ──────────────────────

_SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?\.])")
_PARA_SPLIT_RE = re.compile(r"\n\s*\n")


def _split_paragraphs(text: str) -> list[str]:
    """按空行分段。"""
    return [p.strip() for p in _PARA_SPLIT_RE.split(text.strip()) if p.strip()]


def _split_sentences(paragraph: str) -> list[str]:
    """段落拆句 (中英文标点都支持)。"""
    parts = _SENT_SPLIT_RE.split(paragraph)
    return [s.strip() for s in parts if s and s.strip()]


def _truncate(s: str, n: int = 30) -> str:
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


# ────────────────────── 误杀防护 (v3.4 新增) ──────────────────────

# 角色化表达: 这些表达即使看起来"AI味"，但在角色对话/内心独白中是合理的
_ROLE_EXPRESSIONS = [
    r"「.*?」",  # 对话内容
    r"\".*?\"",  # 对话内容
    r"心想[：:]?.+?[。！？]",  # 内心独白
    r"暗想[：:]?.+?[。！？]",
    r"心中.*?[。！？]",
]

# 功能豁免: 某些场景下特定表达是合理的
_FUNCTIONAL_CONTEXTS = [
    "心理描写",  # 心理描写中的情感词可以多一些
    "环境渲染",  # 环境描写中的形容词可以多一些
    "回忆片段",  # 回忆中的书面化表达可以接受
]

# 文学性表达豁免: 这些模式在文学创作中是合理的，不应被标记
_LITERARY_EXPRESSIONS = [
    r"不禁.*?(?:笑|哭|叹|愣|惊)",  # "不禁笑起来"等情感反应
    r"心中(?:充满|涌起|升起|泛起)",  # 心理描写
    r"眼中(?:闪烁|流露|透出)",  # 眼神描写
    r"声音(?:在|回荡|响起)",  # 声音描写
    r"气息(?:扑面而来|弥漫)",  # 氛围描写
    # v4.1 新增: 文学修辞豁免 — "仿佛梦一般/宛如仙境似的" 是常见文学表达
    r"仿佛[^，。！？]{1,8}(?:一般|似的|般)",
    r"宛如[^，。！？]{1,8}(?:似的|般)",
    r"犹如[^，。！？]{1,8}(?:般|似的)",
]


def _is_in_dialogue(text: str, pos: int) -> bool:
    """检查某个位置是否在对话中。"""
    # 简单判断: 前后是否有引号
    before = text[:pos]
    after = text[pos:]
    # 计算前面未闭合的引号数
    open_quotes = before.count("「") - before.count("」")
    open_quotes += before.count('"') - before.count('"')
    return open_quotes > 0


def _is_in_thought(text: str, pos: int) -> bool:
    """检查某个位置是否在心理描写中。"""
    # 检查前后是否有心理描写标记
    before = text[max(0, pos-20):pos]
    after = text[pos:min(len(text), pos+20)]
    thought_markers = ["心想", "暗想", "心中", "心里", "思忖", "琢磨"]
    return any(marker in before or marker in after for marker in thought_markers)


def _is_in_environment(text: str, pos: int) -> bool:
    """检查某个位置是否在环境描写中。"""
    # 检查前后是否有环境描写标记
    before = text[max(0, pos-30):pos]
    after = text[pos:min(len(text), pos+30)]
    env_markers = ["天空", "大地", "阳光", "月光", "风", "雨", "树", "花", "景色", "氛围"]
    return any(marker in before or marker in after for marker in env_markers)


def _is_literary_expression(text: str, pos: int) -> bool:
    """检查某个位置是否是文学性表达（应豁免）。"""
    # 检查是否匹配文学性表达模式
    context = text[max(0, pos-10):min(len(text), pos+20)]
    return any(re.search(pattern, context) for pattern in _LITERARY_EXPRESSIONS)


def _should_skip_check(text: str, pos: int, context_type: str = "") -> bool:
    """
    判断是否应该跳过检查 (误杀防护)。
    - context_type: "dialogue" | "thought" | "narration" | "environment" | ""
    """
    # 对话中的表达通常不改
    if context_type in ("dialogue", "thought"):
        return True
    # 检查是否在引号内（对话）
    if _is_in_dialogue(text, pos):
        return True
    # 检查是否在心理描写中
    if _is_in_thought(text, pos):
        return True
    # 检查是否在环境描写中
    if _is_in_environment(text, pos):
        return True
    # 检查是否是文学性表达
    if _is_literary_expression(text, pos):
        return True
    return False


# ────────────────────── 三遍法检查 (v3.4 新增) ──────────────────────

# Pass1: 去泛化 — 只保留AI味重的程度副词
_GENERALIZATION_WORDS = [
    "非常", "极其", "十分", "格外", "异常", "特别地", "无比", "分外",
]

# Pass2: 去书面化 — 修复有问题的模式
_WRITTEN_STYLE_PATTERNS = [
    # 原有: 文言腔模式
    (r"仿佛[^，。！？]{2,10}一般", "像...一样"),
    (r"宛如[^，。！？]{2,10}似的", "像...似的"),
    (r"犹如[^，。！？]{2,10}般", "像...般"),
    (r"令人[^，。！？]{2,8}不已", "让人...极了"),
    # v4.1 新增: 书面语连词 (对照 anti-ai-writing.md 模式6)
    (r"于是乎[^，。！？]{2,20}", "于是/接着"),
    (r"与此同时[^，。！？]{2,20}", "同时/这时"),
    (r"从而[^，。！？]{2,20}", "就"),
    (r"因而[^，。！？]{2,20}", "所以"),
    (r"诚然[^，。！？]{2,20}", "确实"),
    # v4.1 新增: 论文体 (对照 anti-ai-writing.md 模式5)
    (r"不难看出[^，。！？]{0,20}", "很明显"),
    (r"由此可见[^，。！？]{0,20}", "看得出来"),
    (r"事实上[^，。！？]{0,20}", "其实"),
    (r"综上所述[^，。！？]{0,20}", "总的来说"),
    # v4.1 新增: 意义膨胀 (对照 anti-ai-writing.md 模式3)
    (r"意义深远", "…"),
    (r"前所未有", "…"),
    (r"可谓[^，。！？]{2,10}", "…"),
]

# Pass3: 回自然感 — 修复过于宽泛的模式
_UNNATURAL_PATTERNS = [
    # 原有
    (r"他的心中充满了[^，。！？]{2,8}", "他心里..."),
    (r"她的眼中闪烁着[^，。！？]{2,8}", "她眼里..."),
    # v4.1 新增: 不自然表达
    (r"他的目光如[^，。！？]{2,6}", "他盯着..."),
    (r"她的目光[^，。！？]{0,3}深邃", "她看着..."),
    (r"心中(?:一(?:动|震|紧|酸|软|凛)|不由得)", "改成身体反应"),
    (r"心(?:中|里|底)(?:暗想|暗道|默念)", "改成动作或删"),
    (r"不由得[^，。！？]{1,8}", "删掉'不由得'"),
    (r"下意识地[^，。！？]{1,10}", "删掉'下意识地'"),
    # v4.1 新增: 过度完美句式
    (r"完美地[^，。！？]{2,10}", "'完美地...'→直接写结果"),
    (r"恰到好处[^，。！？]{0,8}", "删掉'恰到好处'"),
]


def check_pass1_generalization(text: str) -> list[Issue]:
    """
    Pass1: 去泛化 — 检测过于泛化的程度副词。
    这些词缺乏具体感, 是AI写作的典型特征。
    """
    issues: list[Issue] = []
    paragraphs = _split_paragraphs(text)
    for pi, para in enumerate(paragraphs, 1):
        for word in _GENERALIZATION_WORDS:
            # 找到所有出现位置
            start = 0
            while True:
                pos = para.find(word, start)
                if pos == -1:
                    break
                # 误杀防护: 检查是否在对话中
                if not _should_skip_check(para, pos, "narration"):
                    issues.append(Issue(
                        kind=CheckKind.PASS1_GENERALIZATION,
                        label=CHECK_LABELS[CheckKind.PASS1_GENERALIZATION],
                        severity=Severity.INFO,
                        location=f"p{pi}",
                        snippet=_truncate(para[max(0, pos-5):pos+len(word)+5], 30),
                        suggestion=f"'{word}' 太泛, 建议换成具体描述或删掉",
                        detail={"word": word, "pass": 1},
                    ))
                start = pos + len(word)
    return issues


def check_pass2_written_style(text: str) -> list[Issue]:
    """
    Pass2: 去书面化 — 检测过于书面化的表达模式。
    这些表达在口语中不自然, 是AI写作的典型特征。
    """
    issues: list[Issue] = []
    paragraphs = _split_paragraphs(text)
    for pi, para in enumerate(paragraphs, 1):
        for pattern, suggestion in _WRITTEN_STYLE_PATTERNS:
            if suggestion is None:
                continue  # 跳过保留的表达
            for m in re.finditer(pattern, para):
                pos = m.start()
                # 误杀防护
                if not _should_skip_check(para, pos, "narration"):
                    issues.append(Issue(
                        kind=CheckKind.PASS2_WRITTEN_STYLE,
                        label=CHECK_LABELS[CheckKind.PASS2_WRITTEN_STYLE],
                        severity=Severity.INFO,
                        location=f"p{pi}",
                        snippet=_truncate(m.group(0), 30),
                        suggestion=f"太书面, 建议: {suggestion.replace('.*', '...')}",
                        detail={"pattern": pattern, "pass": 2},
                    ))
    return issues


def check_pass3_natural(text: str) -> list[Issue]:
    """
    Pass3: 回自然感 — 检测不自然的表达模式。
    这些表达在真人写作中较少出现, 是AI写作的典型特征。
    """
    issues: list[Issue] = []
    paragraphs = _split_paragraphs(text)
    for pi, para in enumerate(paragraphs, 1):
        for pattern, suggestion in _UNNATURAL_PATTERNS:
            for m in re.finditer(pattern, para):
                pos = m.start()
                # 误杀防护
                if not _should_skip_check(para, pos, "narration"):
                    issues.append(Issue(
                        kind=CheckKind.PASS3_NATURAL,
                        label=CHECK_LABELS[CheckKind.PASS3_NATURAL],
                        severity=Severity.INFO,
                        location=f"p{pi}",
                        snippet=_truncate(m.group(0), 30),
                        suggestion=f"不够自然, 建议: {suggestion.replace('.*', '...')}",
                        detail={"pattern": pattern, "pass": 3},
                    ))
    return issues


# ────────────────────── 原有6项检查 ──────────────────────

# 简单句式模板: 按"主语 + 谓语起始 2 字"分类
def _sentence_pattern(sent: str) -> str:
    """提取句式模板 (头 4 字符归一化)。"""
    s = sent.strip()
    if not s:
        return ""
    # 去掉前导标点
    s = re.sub(r"^[，。！？,.!?\s\"'\"']+", "", s)
    return s[:4]


def check_sentence_pattern(text: str) -> list[Issue]:
    """
    检测连续 3 句以上用同一句式模板 (典型 AI 病)。
    """
    issues: list[Issue] = []
    paragraphs = _split_paragraphs(text)
    for pi, para in enumerate(paragraphs, 1):
        sents = _split_sentences(para)
        if len(sents) < 3:
            continue
        # 滑动窗口: 连续 3 句同模板
        prev_patterns: list[tuple[int, str, str]] = []  # (sent_idx, pattern, sent)
        for si, sent in enumerate(sents, 1):
            pat = _sentence_pattern(sent)
            if not pat:
                continue
            if prev_patterns and prev_patterns[-1][1] == pat:
                prev_patterns.append((si, pat, sent))
            else:
                # 窗口结束, 检查长度
                if len(prev_patterns) >= 3:
                    first_si, first_pat, first_sent = prev_patterns[0]
                    last_si, _, _ = prev_patterns[-1]
                    issues.append(Issue(
                        kind=CheckKind.SENTENCE_PATTERN,
                        label=CHECK_LABELS[CheckKind.SENTENCE_PATTERN],
                        severity=Severity.WARN,
                        location=f"p{pi}.s{first_si}-{last_si}",
                        snippet=_truncate(first_sent),
                        suggestion=f"连续 {len(prev_patterns)} 句同句式 '{first_pat}...', 建议换 1-2 句的起手",
                        detail={"count": len(prev_patterns), "pattern": first_pat},
                    ))
                prev_patterns = [(si, pat, sent)]
        # 收尾
        if len(prev_patterns) >= 3:
            first_si, first_pat, first_sent = prev_patterns[0]
            last_si, _, _ = prev_patterns[-1]
            issues.append(Issue(
                kind=CheckKind.SENTENCE_PATTERN,
                label=CHECK_LABELS[CheckKind.SENTENCE_PATTERN],
                severity=Severity.WARN,
                location=f"p{pi}.s{first_si}-{last_si}",
                snippet=_truncate(first_sent),
                suggestion=f"连续 {len(prev_patterns)} 句同句式 '{first_pat}...', 建议换 1-2 句的起手",
                detail={"count": len(prev_patterns), "pattern": first_pat},
            ))
    return issues


# ────────────────────── 2. 对话个性化 ──────────────────────

# 简单角色识别: 「XXX说」/ "XXX said"
_SPEAKER_RE = re.compile(r"[「\"](.+?)[」\"]\s*说[,:，：]?|[「\"](.+?)[」\"]\s*道[,:，：]?")


def _extract_dialogues(text: str) -> list[tuple[str, str, str]]:
    """
    提取对话: 返回 (speaker, line, paragraph_idx_str)。
    - 简单规则: "..." 或 「...」 配前面的角色名
    - 用非贪婪 + 句末标点截断, 避免吃多句
    """
    out: list[tuple[str, str, str]] = []
    paragraphs = _split_paragraphs(text)
    for pi, para in enumerate(paragraphs, 1):
        # 形式 1: "XXX说:" + 「...」  (限定到 "」" 结束)
        for m in re.finditer(
            r"([\u4e00-\u9fa5\w]{1,6})(?:说|道|答|问|笑|叹|怒喝|低声道|沉声道)[：:]?\s*[「\"](.+?)[」\"]",
            para,
        ):
            out.append((m.group(1), m.group(2), f"p{pi}"))
        # 形式 2: "XXX说" + 一段到句末
        for m in re.finditer(
            r"([\u4e00-\u9fa5\w]{1,6})(?:说|道|答|问|笑|叹|怒喝|低声道|沉声道)[：:，,]?\s*"
            r"([\u4e00-\u9fa5\w\s,，]{2,40}?)(?:[。！？!?]|$)",
            para,
        ):
            out.append((m.group(1), m.group(2).strip(), f"p{pi}"))
    return out


def check_dialogue_voice(text: str) -> list[Issue]:
    """
    检测对话个性化问题。
    - 同一角色多段对话长度/语气词重复
    """
    issues: list[Issue] = []
    dialogues = _extract_dialogues(text)
    if len(dialogues) < 3:
        return issues
    # 按角色分组
    by_speaker: dict[str, list[tuple[str, str]]] = {}
    for sp, line, loc in dialogues:
        by_speaker.setdefault(sp, []).append((line, loc))
    for sp, items in by_speaker.items():
        if len(items) < 3:
            continue
        # 检查每句长度是否过于一致 (差 < 2 字)
        lens = [len(line) for line, _ in items]
        avg = sum(lens) / len(lens)
        if max(lens) - min(lens) < 2 and avg >= 3:
            issues.append(Issue(
                kind=CheckKind.DIALOGUE_VOICE,
                label=CHECK_LABELS[CheckKind.DIALOGUE_VOICE],
                severity=Severity.WARN,
                location=items[0][1],
                snippet=_truncate(items[0][0]),
                suggestion=f"角色 '{sp}' {len(items)} 段对话长度过于一致 (~{avg:.0f} 字), 建议长短交替",
                detail={"speaker": sp, "count": len(items), "avg_len": avg},
            ))
        # 检查语气词堆叠
        all_lines = "".join(line for line, _ in items)
        for filler in ["啊", "呢", "吧", "哦", "嗯", "呀"]:
            cnt = all_lines.count(filler)
            if cnt >= 4:
                issues.append(Issue(
                    kind=CheckKind.DIALOGUE_VOICE,
                    label=CHECK_LABELS[CheckKind.DIALOGUE_VOICE],
                    severity=Severity.INFO,
                    location=items[0][1],
                    snippet=_truncate(items[0][0]),
                    suggestion=f"角色 '{sp}' 对话中 '{filler}' 出现 {cnt} 次, 偏多",
                    detail={"speaker": sp, "filler": filler, "count": cnt},
                ))
    return issues


# ────────────────────── 3. 节奏呼吸 ──────────────────────

def check_pacing_breath(text: str) -> list[Issue]:
    """
    节奏: 整段若是连续长句 (>= 30 字) 或连续短句 (<= 5 字), 提示。
    """
    issues: list[Issue] = []
    paragraphs = _split_paragraphs(text)
    for pi, para in enumerate(paragraphs, 1):
        sents = _split_sentences(para)
        if len(sents) < 4:
            continue
        lens = [len(s) for s in sents]
        # 4 句以上全部 >= 30
        if all(l >= 30 for l in lens):
            issues.append(Issue(
                kind=CheckKind.PACING_BREATH,
                label=CHECK_LABELS[CheckKind.PACING_BREATH],
                severity=Severity.WARN,
                location=f"p{pi}",
                snippet=_truncate(para),
                suggestion=f"本段 {len(sents)} 句全是长句, 建议插入 1-2 短句断节奏",
                detail={"avg_len": sum(lens) // len(lens), "all_long": True},
            ))
        # 4 句以上全部 <= 5
        elif all(l <= 5 for l in lens):
            issues.append(Issue(
                kind=CheckKind.PACING_BREATH,
                label=CHECK_LABELS[CheckKind.PACING_BREATH],
                severity=Severity.WARN,
                location=f"p{pi}",
                snippet=_truncate(para),
                suggestion=f"本段 {len(sents)} 句全是短句, 显得急促, 建议混合中长句",
                detail={"avg_len": sum(lens) // len(lens), "all_short": True},
            ))
    return issues


# ────────────────────── 4. 修辞适度 ──────────────────────

# 修辞密度检测词表 (与 Pass1 去泛化词表完全独立，避免重复标记)
_RHETORIC_ADV = [
    "惊人地", "不可思议地", "令人窒息地", "前所未有地",
    "出乎意料地", "难以置信地", "匪夷所思地",
]
_RHETORIC_ADJ = [
    "绝美", "完美无瑕", "惊为天人", "倾国倾城", "风华绝代", "惊艳绝伦",
    "美得令人窒息", "绝世", "无与伦比", "完美",
]


def check_rhetoric_mod(text: str) -> list[Issue]:
    """
    修辞密度: 形容词/副词密度过高 = AI 味。
    """
    issues: list[Issue] = []
    paragraphs = _split_paragraphs(text)
    for pi, para in enumerate(paragraphs, 1):
        adv_count = sum(para.count(w) for w in _RHETORIC_ADV)
        adj_count = sum(para.count(w) for w in _RHETORIC_ADJ)
        total_rhet = adv_count + adj_count
        # 段落 > 100 字时, 修辞词 >= 3 触发 WARN
        if len(para) >= 100 and total_rhet >= 3:
            snippet = _truncate(para, 50)
            issues.append(Issue(
                kind=CheckKind.RHETORIC_MOD,
                label=CHECK_LABELS[CheckKind.RHETORIC_MOD],
                severity=Severity.WARN,
                location=f"p{pi}",
                snippet=snippet,
                suggestion=f"本段 {len(para)} 字内含 {total_rhet} 个修辞词, 偏多, 建议减 1-2 个",
                detail={"adv": adv_count, "adj": adj_count, "total": total_rhet, "para_len": len(para)},
            ))
    return issues


# ────────────────────── 5. 视角一致 ──────────────────────

# 典型第一人称 / 第三人称 标记
_FIRST_PERSON = ["我", "我们", "我的", "我们的"]
_THIRD_HE = ["他", "他的", "他自己"]
_THIRD_SHE = ["她", "她的", "她自己"]


def _detect_pov(text: str) -> str:
    """
    简单判断主视角: 一/三 (男/女)。
    """
    first = sum(text.count(w) for w in _FIRST_PERSON)
    he = sum(text.count(w) for w in _THIRD_HE)
    she = sum(text.count(w) for w in _THIRD_SHE)
    third_total = he + she
    # 简单规则
    if first > third_total * 1.5:
        return "first"
    if he > she * 1.5:
        return "third_he"
    if she > he * 1.5:
        return "third_she"
    return "third_mixed" if third_total > 0 else "unknown"


def check_pov_consist(text: str, *, expected_pov: str = "") -> list[Issue]:
    """
    视角一致: 段落间 POV 不漂移。
    - expected_pov="" → 自动检测主视角, 再检查段落
    """
    issues: list[Issue] = []
    paragraphs = _split_paragraphs(text)
    if len(paragraphs) < 2:
        return issues
    if not expected_pov:
        expected_pov = _detect_pov(text)
    if expected_pov in ("unknown", "third_mixed"):
        return issues
    # 检查每段
    for pi, para in enumerate(paragraphs, 1):
        para_pov = _detect_pov(para)
        if para_pov == "unknown":
            continue
        if para_pov != expected_pov and para_pov != "third_mixed":
            # 检测到他段以另一 POV 为主
            first = sum(para.count(w) for w in _FIRST_PERSON)
            third = sum(para.count(w) for w in _THIRD_HE + _THIRD_SHE)
            # 出现 1+ 个 POV 词即视为漂移信号
            if first >= 1 or third >= 1:
                issues.append(Issue(
                    kind=CheckKind.POV_CONSIST,
                    label=CHECK_LABELS[CheckKind.POV_CONSIST],
                    severity=Severity.WARN,
                    location=f"p{pi}",
                    snippet=_truncate(para),
                    suggestion=f"本段 POV 漂移 (检测 {para_pov}, 全文主 POV {expected_pov})",
                    detail={"para_pov": para_pov, "expected_pov": expected_pov,
                            "first": first, "third": third},
                ))
    return issues


# ────────────────────── 6. 信息差 ──────────────────────

# 内心独白标记 (中文里典型是"心想"/"暗想"/"心里想")
_INTERNAL_THOUGHT = ["心想", "暗想", "心里想", "心里暗道", "心中暗道", "心中想道"]


def check_info_gap(text: str) -> list[Issue]:
    """
    信息差: 过多"心想"会剥夺读者揣测空间。
    - 每段 >= 3 处"心想"类, 触发 WARN
    """
    issues: list[Issue] = []
    paragraphs = _split_paragraphs(text)
    for pi, para in enumerate(paragraphs, 1):
        cnt = sum(para.count(w) for w in _INTERNAL_THOUGHT)
        if cnt >= 3:
            issues.append(Issue(
                kind=CheckKind.INFO_GAP,
                label=CHECK_LABELS[CheckKind.INFO_GAP],
                severity=Severity.WARN,
                location=f"p{pi}",
                snippet=_truncate(para),
                suggestion=f"本段出现 {cnt} 处'心想/暗想', 偏多, 建议保留 1-2 处, 其他改用行为暗示",
                detail={"count": cnt},
            ))
    return issues


# ────────────────────── Gate A/B: 高危句式检测 (v4.1 新增) ──────────────────────

# 对照 story-deslop banned-words.md:
# ★★★★★ "不是A，（而）是B" — 出现即 BLOCK
# ★★★★ "，带着……" 万能状语
# ★★★★ "声音不大，却带着……" AI 声音描写
# ★★★  眼中闪过/嘴角勾起/心中涌起 — AI 表情模板
_TOXIC_NOT_IS_PATTERN = re.compile(r"不是[^，。！？!?]{0,30}(?:而是|，而是|是[^吗吧嘛])")
_TOXIC_DAIZHE_PATTERN = re.compile(r"[，,]\s*带着[^，。！？!?\n]{2,30}")
_TOXIC_VOICE_PATTERN = re.compile(r"声音不大[，,]?\s*却带着[^。！？!?\n]{2,30}")
_TOXIC_EXPRESSION_PATTERNS = [
    (re.compile(r"眼中闪过[^，。！？!?\n]{1,15}"), "眼中闪过…", Severity.WARN),
    (re.compile(r"嘴角勾起[^，。！？!?\n]{0,10}"), "嘴角勾起…", Severity.WARN),
    (re.compile(r"心中涌起[^，。！？!?\n]{1,15}"), "心中涌起…", Severity.WARN),
    (re.compile(r"心头一震"), "心头一震", Severity.WARN),
    (re.compile(r"瞳孔(?:微缩|猛地收缩|骤然收缩)"), "瞳孔微缩…", Severity.WARN),
    (re.compile(r"深吸一口气"), "深吸一口气", Severity.INFO),
    (re.compile(r"不禁[^，。！？]{0,20}(?:笑|哭|叹|愣|惊)"), "不禁…", Severity.INFO),
    (re.compile(r"深深地看了[^。！？]{1,10}"), "深深地看了…", Severity.WARN),
]


def check_toxic_patterns(text: str) -> list[Issue]:
    """
    Gate A/B: 检测最毒 AI 句式 — 对标 story-deslop 7-Gate 体系。
    
    - Gate A (BLOCK): "不是A，而是B" — 最高危
    - Gate B (WARN): 万能状语 / AI 声音描写 / AI 表情模板
    """
    issues: list[Issue] = []
    paragraphs = _split_paragraphs(text)
    
    for pi, para in enumerate(paragraphs, 1):
        # Gate A: "不是A，而是B" — BLOCK 级别
        for m in _TOXIC_NOT_IS_PATTERN.finditer(para):
            pos = m.start()
            if not _should_skip_check(para, pos):
                # 排除 "是不是" 疑问句
                snippet = m.group(0)
                if "是不是" in snippet[:4]:
                    continue
                issues.append(Issue(
                    kind=CheckKind.TOXIC_PATTERNS,
                    label=CHECK_LABELS[CheckKind.TOXIC_PATTERNS],
                    severity=Severity.BLOCK,
                    location=f"p{pi}",
                    snippet=_truncate(snippet, 50),
                    suggestion="最毒AI句式: 删掉否定铺垫，直接写后项，或改成动作/细节呈现",
                    detail={"pattern": "not-is-comparison", "gate": "A"},
                ))
        
        # Gate B: "，带着……" 万能状语
        for m in _TOXIC_DAIZHE_PATTERN.finditer(para):
            pos = m.start()
            if not _should_skip_check(para, pos):
                snippet = m.group(0)
                # 排除合理表达: "带着孩子/带着行李/带着钱" 等实体携带
                if re.search(r"带着(?:孩子|行李|钱|东西|包|伞|钥匙|手机)", snippet):
                    continue
                # 排除动作串联: "带着...走/跑/冲/跳"
                if re.search(r"带着[^，。！？]{0,15}(?:走|跑|冲|跳|离开|进去|出来)", snippet):
                    continue
                issues.append(Issue(
                    kind=CheckKind.TOXIC_PATTERNS,
                    label=CHECK_LABELS[CheckKind.TOXIC_PATTERNS],
                    severity=Severity.WARN,
                    location=f"p{pi}",
                    snippet=_truncate(snippet, 40),
                    suggestion="万能状语: 用独立短句或具体动作替代",
                    detail={"pattern": "daizhe-adverbial", "gate": "B"},
                ))
        
        # Gate B: "声音不大，却带着……" AI 声音描写
        for m in _TOXIC_VOICE_PATTERN.finditer(para):
            pos = m.start()
            if not _should_skip_check(para, pos):
                issues.append(Issue(
                    kind=CheckKind.TOXIC_PATTERNS,
                    label=CHECK_LABELS[CheckKind.TOXIC_PATTERNS],
                    severity=Severity.WARN,
                    location=f"p{pi}",
                    snippet=_truncate(m.group(0), 40),
                    suggestion="AI声音模板: 直接写声音特征或动作，不要用'声音不大却带着...'",
                    detail={"pattern": "voice-not-loud", "gate": "B"},
                ))
        
        # Gate B: AI 表情模板
        for pattern_re, pattern_name, severity in _TOXIC_EXPRESSION_PATTERNS:
            for m in pattern_re.finditer(para):
                pos = m.start()
                if not _should_skip_check(para, pos):
                    suggestions = {
                        "眼中闪过…": "用行为展示: '他垂下眼' / '他移开视线'",
                        "嘴角勾起…": "用简洁动作: '他笑了一下' / '他翘了下嘴'",
                        "心中涌起…": "用身体反应: '胸口发热' / '鼻头一酸'",
                        "心头一震": "用具体动作替代",
                        "瞳孔微缩…": "用行为替代: '他愣了一下' / '他停住脚步'",
                        "深吸一口气": "90%无意义，建议删除或替换为具体动作",
                        "不禁…": "删除'不禁'，直接写动作",
                        "深深地看了…": "简化为'看了他一眼'或直接删",
                    }
                    issues.append(Issue(
                        kind=CheckKind.TOXIC_PATTERNS,
                        label=CHECK_LABELS[CheckKind.TOXIC_PATTERNS],
                        severity=severity,
                        location=f"p{pi}",
                        snippet=_truncate(m.group(0), 30),
                        suggestion=suggestions.get(pattern_name, "AI模板化表达，建议用具体描写替代"),
                        detail={"pattern": pattern_name, "gate": "B"},
                    ))
    
    return issues


# ────────────────────── Gate G: 解释腔/上帝视角/安排感 (v4.1 新增) ──────────────────────

# 对照 story-deslop Gate G + anti-ai-writing.md 模式8
_EXPLANATION_CAUSAL = [
    (re.compile(r"之所以[^，。！？]{2,40}是因为"), "解释因果"),
    (re.compile(r"原来[^，。！？]{0,5}(?:是|这|那|一切)"), "原来…"),
    (re.compile(r"这意味着"), "这意味着"),
]
_EXPLANATION_GOD_VIEW = [
    (re.compile(r"她不知道的是"), "她不知道的是"),
    (re.compile(r"他(?:并)?不知道[^，。！？]{0,10}(?:的是)?"), "他不知道…"),
    (re.compile(r"殊不知"), "殊不知"),
    (re.compile(r"多年以后"), "多年以后"),
    (re.compile(r"仿佛预示"), "仿佛预示"),
    (re.compile(r"冥冥之中"), "冥冥之中"),
]
_EXPLANATION_JUDGE = [
    (re.compile(r"演得真好"), "替读者定性"),
    (re.compile(r"(?:他|她)就是这样[^，。！？]{2,10}的人"), "替角色总结"),
    (re.compile(r"关切得恰到好处"), "评判性副词"),
    (re.compile(r"笑得恰如其分"), "评判性副词"),
    (re.compile(r"不多不少"), "评判性副词"),
    (re.compile(r"(?:那点笑|那份笑|那点紧张).{0,5}(?:看[得在]分明|看得清楚)"), "剧透式点破"),
    (re.compile(r"(?:谁|任何人).{0,5}(?:看得出|看得出来|都能看出)"), "剧透式点破"),
    (re.compile(r"像在宣判[^。！？]{2,20}"), "定性比喻"),
    (re.compile(r"像看一件[^。！？]{2,10}"), "定性比喻"),
]


def check_explanation_voice(text: str) -> list[Issue]:
    """
    Gate G: 检测解释腔/上帝视角/安排感。
    叙述者跳出角色当下去解释、剧透、总结、定性，读者闻到"作者在场"。
    """
    issues: list[Issue] = []
    paragraphs = _split_paragraphs(text)
    
    for pi, para in enumerate(paragraphs, 1):
        # 解释因果
        for pattern_re, pattern_name in _EXPLANATION_CAUSAL:
            for m in pattern_re.finditer(para):
                pos = m.start()
                if not _should_skip_check(para, pos, "narration"):
                    issues.append(Issue(
                        kind=CheckKind.EXPLANATION_VOICE,
                        label=CHECK_LABELS[CheckKind.EXPLANATION_VOICE],
                        severity=Severity.WARN,
                        location=f"p{pi}",
                        snippet=_truncate(m.group(0), 40),
                        suggestion=f"解释腔[{pattern_name}]: 删除因果解释，让读者从动作/对话里自己拼",
                        detail={"pattern": pattern_name, "gate": "G", "subtype": "causal"},
                    ))
        
        # 上帝视角剧透
        for pattern_re, pattern_name in _EXPLANATION_GOD_VIEW:
            for m in pattern_re.finditer(para):
                pos = m.start()
                if not _should_skip_check(para, pos):
                    issues.append(Issue(
                        kind=CheckKind.EXPLANATION_VOICE,
                        label=CHECK_LABELS[CheckKind.EXPLANATION_VOICE],
                        severity=Severity.WARN,
                        location=f"p{pi}",
                        snippet=_truncate(m.group(0), 40),
                        suggestion=f"上帝视角[{pattern_name}]: 删除，只写角色此刻知道的",
                        detail={"pattern": pattern_name, "gate": "G", "subtype": "god_view"},
                    ))
        
        # 替读者定性/总结
        for pattern_re, pattern_name in _EXPLANATION_JUDGE:
            for m in pattern_re.finditer(para):
                pos = m.start()
                if not _should_skip_check(para, pos):
                    issues.append(Issue(
                        kind=CheckKind.EXPLANATION_VOICE,
                        label=CHECK_LABELS[CheckKind.EXPLANATION_VOICE],
                        severity=Severity.WARN,
                        location=f"p{pi}",
                        snippet=_truncate(m.group(0), 40),
                        suggestion=f"安排感[{pattern_name}]: 删除评判，只摆动作/神态/台词让读者自己判",
                        detail={"pattern": pattern_name, "gate": "G", "subtype": "judge"},
                    ))
    
    return issues


# ────────────────────── Gate F: 结尾升华检测 (v4.1 新增) ──────────────────────

# 对照故事-deslop Gate F + anti-ai-writing.md 章末总结体
_SUBLIMATION_PATTERNS = [
    (re.compile(r"(?:他|她|这)终于明白[^。！？]{0,30}"), "终于明白"),
    (re.compile(r"(?:他|她)(?:这才)?意识到[^。！？]{0,30}"), "意识到"),
    (re.compile(r"此刻[，,]\s*(?:他|她)[^。！？]{2,30}"), "此刻…"),
    (re.compile(r"这一(?:刻|夜|刻起)[，,]?\s*[^。！？]{2,30}"), "这一刻/夜…"),
    (re.compile(r"一切[^，。！？]{0,5}(?:都|又|也)[^。！？]{2,25}"), "一切…都…"),
    (re.compile(r"这就是[^。！？]{2,25}"), "这就是…"),
    (re.compile(r"岁月如[^。！？]{2,15}"), "岁月如…"),
    (re.compile(r"从今以后"), "从今以后"),
    (re.compile(r"人生就是这样"), "人生就是这样"),
    (re.compile(r"注定[^。！？]{2,20}"), "注定…"),
    (re.compile(r"命运[^的]{0,5}(?:的)?(?:齿轮|的安排|弄人)"), "命运的齿轮…"),
]


def check_ending_sublimation(text: str) -> list[Issue]:
    """
    Gate F: 检测结尾升华/总结/预告体。
    只检查最后 3 段 (尾段检测)，避免全文误判。
    """
    issues: list[Issue] = []
    paragraphs = _split_paragraphs(text)
    if len(paragraphs) < 1:
        return issues
    
    # 只检查最后 3 段 (结尾区域)
    tail_paragraphs = paragraphs[-3:]
    start_pi = len(paragraphs) - len(tail_paragraphs) + 1
    
    for offset, para in enumerate(tail_paragraphs):
        pi = start_pi + offset
        for pattern_re, pattern_name in _SUBLIMATION_PATTERNS:
            for m in pattern_re.finditer(para):
                pos = m.start()
                if not _should_skip_check(para, pos, "narration"):
                    issues.append(Issue(
                        kind=CheckKind.ENDING_SUBLIMATION,
                        label=CHECK_LABELS[CheckKind.ENDING_SUBLIMATION],
                        severity=Severity.WARN,
                        location=f"p{pi}",
                        snippet=_truncate(m.group(0), 40),
                        suggestion=f"结尾升华[{pattern_name}]: 删除总结/升华/预告，用动作或留白收尾",
                        detail={"pattern": pattern_name, "gate": "F", "is_tail": True},
                    ))
    
    return issues


# ────────────────────── Gate B/C: 修饰词清扫 (v4.1 新增) ──────────────────────

# 弱化副词: 每千字超过阈值即 AI 指纹
_WEAK_ADVERBS = ["微微", "淡淡", "缓缓", "轻轻", "默默", "浅浅", "慢慢"]
# 装饰性形容词冗余
_EXCESS_ADJ_PATTERNS = [
    (re.compile(r"([\u4e00-\u9fa5]{1,4})的\1"), "形容词重复修饰"),  # "美丽的美人"
    (re.compile(r"[\u4e00-\u9fa5]{1,3}色的[\u4e00-\u9fa5]{1,4}"), "颜色+物品冗余"),  # "白色的药片"
]
# 指示代词/量词冗余
_EXCESS_DETERMINERS = [
    (re.compile(r"(?:手里|手上|身边|面前|眼前)(?:的)?(?:那|这)(?:个|截|根|把|条|张)"), "指示代词冗余"),
    (re.compile(r"多年前的|多年前那"), "时间冗余修饰"),
    (re.compile(r"飞驰的|疾驰的"), "定语冗余"),
]
# 含义重复
_SEMANTIC_REPEAT_PATTERNS = [
    (re.compile(r"(?:兴高采烈|开开心心|高高兴兴)地[^。！？]{1,6}(?:笑|跑|跳|走|说)"), "形容词+动作重复"),
    (re.compile(r"非常(?:重要的|关键的)[^，。！？]{2,8}"), "近义词堆叠"),
]


def check_excess_modifiers(text: str) -> list[Issue]:
    """
    Gate B/C: 检测修饰词清扫 — 弱化副词滥用、形容词冗余、指示代词堆砌。
    
    弱化副词词表来自 story-deslop banned-words.md 模式2。
    每千字阈值: 3 个弱化副词 = AI 签名。
    """
    issues: list[Issue] = []
    paragraphs = _split_paragraphs(text)
    total_chars = sum(len(p) for p in paragraphs)
    if total_chars == 0:
        return issues
    
    # 全局弱化副词计数 (按千字阈值)
    total_weak = sum(text.count(w) for w in _WEAK_ADVERBS)
    per_k = total_weak * 1000 / total_chars if total_chars > 0 else 0
    
    if per_k > 3:
        issues.append(Issue(
            kind=CheckKind.EXCESS_MODIFIERS,
            label=CHECK_LABELS[CheckKind.EXCESS_MODIFIERS],
            severity=Severity.WARN,
            location="global",
            snippet=f"全文 {total_weak} 个弱化副词 ({per_k:.1f}/千字)",
            suggestion=f"弱化副词密度过高 (阈值 ≤3/千字): {', '.join(_WEAK_ADVERBS)}，建议删减一半",
            detail={"total": total_weak, "per_k": per_k, "threshold": 3, "words": _WEAK_ADVERBS},
        ))
    
    # 逐段检查其他修饰冗余
    for pi, para in enumerate(paragraphs, 1):
        # 装饰性形容词冗余
        for pattern_re, pattern_name in _EXCESS_ADJ_PATTERNS:
            for m in pattern_re.finditer(para):
                issues.append(Issue(
                    kind=CheckKind.EXCESS_MODIFIERS,
                    label=CHECK_LABELS[CheckKind.EXCESS_MODIFIERS],
                    severity=Severity.INFO,
                    location=f"p{pi}",
                    snippet=_truncate(m.group(0), 25),
                    suggestion=f"{pattern_name}: 删除多余修饰词",
                    detail={"pattern": pattern_name},
                ))
        
        # 指示代词/量词冗余
        for pattern_re, pattern_name in _EXCESS_DETERMINERS:
            for m in pattern_re.finditer(para):
                issues.append(Issue(
                    kind=CheckKind.EXCESS_MODIFIERS,
                    label=CHECK_LABELS[CheckKind.EXCESS_MODIFIERS],
                    severity=Severity.INFO,
                    location=f"p{pi}",
                    snippet=_truncate(m.group(0), 25),
                    suggestion=f"{pattern_name}: '手里那截链子'→'链子'，'白色的药片'→'药片'",
                    detail={"pattern": pattern_name},
                ))
        
        # 含义重复
        for pattern_re, pattern_name in _SEMANTIC_REPEAT_PATTERNS:
            for m in pattern_re.finditer(para):
                issues.append(Issue(
                    kind=CheckKind.EXCESS_MODIFIERS,
                    label=CHECK_LABELS[CheckKind.EXCESS_MODIFIERS],
                    severity=Severity.INFO,
                    location=f"p{pi}",
                    snippet=_truncate(m.group(0), 25),
                    suggestion=f"语义重复[{pattern_name}]: 只留一个最合适的",
                    detail={"pattern": pattern_name},
                ))
    
    return issues

def _get_all_checks() -> list[Callable[..., list[Issue]]]:
    """懒构造 (避开 import-order 问题)."""
    return [
        # v4.1 新增: Gate A/B 高危句式 — 最高优先级，先跑
        check_toxic_patterns,
        # 原有6项
        check_sentence_pattern,
        check_dialogue_voice,
        check_pacing_breath,
        check_rhetoric_mod,
        check_pov_consist,
        check_info_gap,
        # v3.4 新增: 三遍法
        check_pass1_generalization,
        check_pass2_written_style,
        check_pass3_natural,
        # v4.1 新增: Gate F/G + 修饰词清扫
        check_explanation_voice,
        check_ending_sublimation,
        check_excess_modifiers,
    ]


def run_all(text: str, *, expected_pov: str = "", enable_three_pass: bool = True,
            enable_gate_checks: bool = True) -> list[Issue]:
    """
    跑全部检查, 返回所有 Issue 列表.
    
    Args:
        text: 待检查文本
        expected_pov: 预期视角
        enable_three_pass: 是否启用三遍法检查 (默认True)
        enable_gate_checks: 是否启用 Gate A/B/F/G 高级检查 (默认True)
    """
    issues: list[Issue] = []
    for fn in _get_all_checks():
        try:
            # 三遍法检查可选
            if not enable_three_pass and fn in (
                check_pass1_generalization, check_pass2_written_style, check_pass3_natural,
            ):
                continue
            # Gate 检查可选
            if not enable_gate_checks and fn in (
                check_toxic_patterns, check_explanation_voice,
                check_ending_sublimation, check_excess_modifiers,
            ):
                continue
            if fn is check_pov_consist:
                issues.extend(fn(text, expected_pov=expected_pov))
            else:
                issues.extend(fn(text))
        except Exception as e:
            _logger.warning("检查 %s 出错: %s", fn.__name__, e)
    # 按 severity 降序
    issues.sort(key=lambda i: -SEVERITY_ORDER.get(i.severity, 0))
    return issues


def summary(issues: list[Issue]) -> dict:
    """汇总: 按 kind / severity 计数。"""
    by_kind: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for i in issues:
        by_kind[i.kind] = by_kind.get(i.kind, 0) + 1
        by_sev[i.severity] = by_sev.get(i.severity, 0) + 1
    return {
        "total": len(issues),
        "by_kind": by_kind,
        "by_severity": by_sev,
        "has_block": any(i.severity == Severity.BLOCK for i in issues),
    }


def format_report(issues: list[Issue], *, max_items: int = 20) -> str:
    """把 Issue 列表格式化成可读报告。"""
    if not issues:
        return "✅ 去AI味检查: 无问题"
    s = summary(issues)
    
    # 统计三遍法问题数
    three_pass_count = sum(1 for i in issues if i.kind in (
        CheckKind.PASS1_GENERALIZATION, CheckKind.PASS2_WRITTEN_STYLE, CheckKind.PASS3_NATURAL,
    ))
    # v4.1: 统计 Gate 问题数
    gate_count = sum(1 for i in issues if i.kind in (
        CheckKind.TOXIC_PATTERNS, CheckKind.EXPLANATION_VOICE,
        CheckKind.ENDING_SUBLIMATION, CheckKind.EXCESS_MODIFIERS,
    ))
    # 统计 BLOCK 数量
    block_count = sum(1 for i in issues if i.severity == Severity.BLOCK)
    
    lines = [
        f"⚠️ 去AI味检查: 共 {s['total']} 条问题",
        f"  按严重度: {s['by_severity']}",
        f"  按类型:   {s['by_kind']}",
    ]
    if block_count > 0:
        lines.append(f"  🛑 阻断级: {block_count} 条 (必须修复)")
    if gate_count > 0:
        lines.append(f"  Gate 检查: {gate_count} 条")
    if three_pass_count > 0:
        lines.append(f"  三遍法: {three_pass_count} 条")
    lines.append("")
    
    for i, issue in enumerate(issues[:max_items], 1):
        sev_icon = {"info": "ℹ️", "warn": "⚠️", "block": "🛑"}.get(issue.severity, "?")
        pass_tag = ""
        gate_tag = ""
        if issue.kind == CheckKind.PASS1_GENERALIZATION:
            pass_tag = " [Pass1]"
        elif issue.kind == CheckKind.PASS2_WRITTEN_STYLE:
            pass_tag = " [Pass2]"
        elif issue.kind == CheckKind.PASS3_NATURAL:
            pass_tag = " [Pass3]"
        elif issue.kind == CheckKind.TOXIC_PATTERNS:
            gate_tag = " [Gate A/B]"
        elif issue.kind == CheckKind.EXPLANATION_VOICE:
            gate_tag = " [Gate G]"
        elif issue.kind == CheckKind.ENDING_SUBLIMATION:
            gate_tag = " [Gate F]"
        elif issue.kind == CheckKind.EXCESS_MODIFIERS:
            gate_tag = " [Gate B/C]"
        lines.append(f"  {i}. {sev_icon}{pass_tag}{gate_tag} [{issue.label}] @ {issue.location}")
        if issue.snippet:
            lines.append(f"     原文: {issue.snippet}")
        if issue.suggestion:
            lines.append(f"     建议: {issue.suggestion}")
    if len(issues) > max_items:
        lines.append(f"  ... 还有 {len(issues) - max_items} 条未显示")
    return "\n".join(lines)


# 导出
__all__ = [
    "Severity", "SEVERITY_ORDER",
    "CheckKind", "CHECK_LABELS",
    "Issue",
    "check_sentence_pattern", "check_dialogue_voice", "check_pacing_breath",
    "check_rhetoric_mod", "check_pov_consist", "check_info_gap",
    "check_pass1_generalization", "check_pass2_written_style", "check_pass3_natural",
    "check_toxic_patterns", "check_explanation_voice",
    "check_ending_sublimation", "check_excess_modifiers",
    "run_all", "summary", "format_report",
    "_detect_pov", "_should_skip_check",  # 给测试用
]


