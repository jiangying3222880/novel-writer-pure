"""
G16 声音验证器 (Voice Validator)
业务场景: 检测角色台词是否符合其 voice_profile (G8 推断结果).
  - 角色 X 的 voice_profile 显示 "话语简短" 但台词长句 ≥ 50 字 → 警告
  - 角色 Y 的 voice_profile 显示 "正式" 但用 "哈哈/嘿/呦" → 警告
  - 角色 Z 的 voice_profile 显示 "用'吾'" 但写 "我" → 警告

设计:
  - 抽角色台词: "..."/'...'/说: .../ 道: ...
  - 检查每句台词的特征 (长度/口语词/自称/句末语气词)
  - 对照 voice_profile 给出建议

与 G8 关系: G16 依赖 G8 推断的 voice_profile (可注入, 也可现场推断)
"""
from __future__ import annotations

import re
from typing import Optional

from .base import (
    BaseValidator, ValidationIssue, ValidatorResult,
    DIM_VOICE, SEV_INFO, SEV_WARNING, SEV_ERROR,
)


# 自称词 (古风/现代)
ARCHAIC_PRONOUNS = ["吾", "我", "余", "在下", "小生", "老朽", "老夫", "本座", "在下", "贫道", "小道", "弟子", "我等", "吾等"]
FORMAL_SELF = ["吾", "余", "在下", "本座"]
CASUAL_SELF = ["我"]
FEMININE_SELF = ["妾身", "奴家", "小女子", "婢子"]
MASCULINE_SELF = ["在下", "小生", "老夫", "老朽", "本座"]

# 句末语气词 (按文体分类)
CASUAL_PARTICLE = ["啊", "呢", "吧", "嘛", "呀", "耶", "咯", "哦", "呵", "哼", "嘿", "哈"]
FORMAL_PARTICLE = ["也", "矣", "哉", "乎", "焉", "耳", "尔", "欸"]
SENTIMENTAL_PARTICLE = ["啊", "呢", "吧"]

# 口语词 (偏现代/轻松)
COLLOQUIAL_WORDS = ["哈哈", "嘿嘿", "呵呵", "哎哟", "哎呀", "嗯嗯", "对对对", "不不不",
                     "我觉得", "我们", "咱们", "哥", "姐", "兄弟", "哥们"]

# 文言词 (偏古代/正式)
LITERARY_WORDS = ["吾", "尔", "汝", "卿", "君", "夫", "然", "盖", "若夫", "是以", "故",
                   "何以", "何为", "安得", "岂", "焉", "哉", "乎", "矣", "也", "欸", "噫",
                   "善", "可", "诺", "谨", "恭", "敬"]


class VoiceValidator(BaseValidator):
    """G16 声音验证器: 角色台词 vs voice_profile."""

    dimension = DIM_VOICE
    name = "声音"

    def _do_validate(self, project_id: str, chapter_id: str,
                      content: str, chapter_no: int,
                      context: dict) -> ValidatorResult:
        result = ValidatorResult(dimension=self.dimension)

        if not content or len(content) < 20:
            return result

        # 抽台词
        dialogues = self._extract_dialogues(content)
        if not dialogues:
            return result

        # 加载 voice profiles (从注入或世界人物库推)
        profiles = dict(self._voice_profiles)
        if not profiles:
            profiles = self._infer_profiles_from_world(project_id)

        # 对每个 (角色, 台词) 检查
        for d in dialogues:
            char_name = d["character"]
            text = d["text"]
            char_start = d["char_start"]
            char_end = d["char_end"]

            # 1) 角色无 profile → info
            if char_name and char_name not in profiles:
                # 提一句, 不报错
                continue

            profile = profiles.get(char_name, {})

            # 2) 检查台词长度是否匹配
            issues = self._check_dialogue_length(text, profile, char_name, char_start, char_end, chapter_no)
            result.issues.extend(issues)

            # 3) 检查自称
            issues = self._check_self_pronoun(text, profile, char_name, char_start, char_end, chapter_no)
            result.issues.extend(issues)

            # 4) 检查口语/文言
            issues = self._check_register(text, profile, char_name, char_start, char_end, chapter_no)
            result.issues.extend(issues)

        return result

    # ------------------------------------------------------------------
    def _extract_dialogues(self, content: str) -> list:
        """抽 (角色, 台词, char_start, char_end)."""
        dialogues: list = []

        # 模式 1: 角色名 + 说/道/问/答 + :/+ 台词
        # "林天笑道: ..." or "林天道: \"...\""
        pat1 = re.compile(
            r"([\u4e00-\u9fff]{2,4})(笑道?|说道?|问道?|答道?|叹道?|喝道?|喊道?|答道?|冷笑道?|沉声道?|低声道?|轻声道?|高声道?)[:：]?[\"'""]([^\"'""\n]{2,200})[\"'""]",
        )
        for m in pat1.finditer(content):
            dialogues.append({
                "character": m.group(1),
                "verb": m.group(2),
                "text": m.group(3),
                "char_start": m.start(),
                "char_end": m.end(),
            })

        # 模式 2: "..." + 角色名 + 说 (句末)
        pat2 = re.compile(
            r"[\"'""]([^\"'""\n]{2,200})[\"'""][,，]?[\u4e00-\u9fff]{2,4}说道?",
        )
        for m in pat2.finditer(content):
            text = m.group(1)
            # 找前面/后面是否有角色名 (在 50 字符内)
            ctx_before = content[max(0, m.start()-50):m.start()]
            ctx_after = content[m.end():min(len(content), m.end()+50)]
            char_name = ""
            for ctx in [ctx_before, ctx_after]:
                cm = re.search(r"([\u4e00-\u9fff]{2,4})", ctx)
                if cm:
                    char_name = cm.group(1)
                    break
            if char_name:
                dialogues.append({
                    "character": char_name,
                    "verb": "说",
                    "text": text,
                    "char_start": m.start(),
                    "char_end": m.end(),
                })

        return dialogues

    def _infer_profiles_from_world(self, project_id: str) -> dict:
        """从世界人物库 + 已有对话推断 voice_profile (简化)."""
        try:
            from app.services import worldbuilding
            chars = worldbuilding.list_all(project_id, worldbuilding.KIND_CHARACTER)
            profiles: dict = {}
            for c in chars:
                profiles[c.name] = {
                    "personality": c.personality or "",
                    "role": c.role or "",
                }
            return profiles
        except Exception:
            return {}

    def _check_dialogue_length(self, text: str, profile: dict, char_name: str,
                                  char_start: int, char_end: int,
                                  chapter_no: int) -> list:
        """台词长度 vs profile.personality (若含'寡言'/'简短'则应 < 30 字符)."""
        issues: list = []
        personality = profile.get("personality", "") or ""
        # 简短的关键词
        if any(w in personality for w in ["寡言", "沉默", "简短", "少言", "不爱说话", "惜字如金"]):
            if len(text) > 30:
                issues.append(ValidationIssue(
                    dimension=self.dimension,
                    severity=SEV_INFO,
                    description=f"角色 '{char_name}' 性格偏寡言, 但本章台词 {len(text)} 字符偏长",
                    chapter_no=chapter_no,
                    char_start=char_start,
                    char_end=char_end,
                    suggestion="缩短台词为 10-20 字, 或拆成多句短台词",
                    related=char_name,
                ))
        # 啰嗦的关键词
        if any(w in personality for w in ["啰嗦", "话多", "健谈", "唠叨"]):
            if len(text) < 10:
                issues.append(ValidationIssue(
                    dimension=self.dimension,
                    severity=SEV_INFO,
                    description=f"角色 '{char_name}' 性格偏话多, 但本章台词仅 {len(text)} 字符偏短",
                    chapter_no=chapter_no,
                    char_start=char_start,
                    char_end=char_end,
                    suggestion="考虑补充更多想法/感受, 让台词更长一些",
                    related=char_name,
                ))
        return issues

    def _check_self_pronoun(self, text: str, profile: dict, char_name: str,
                              char_start: int, char_end: int,
                              chapter_no: int) -> list:
        """自称 vs profile.role/personality (古风角色不用'我'用'吾')."""
        issues: list = []
        personality = profile.get("personality", "") or ""
        role = profile.get("role", "") or ""

        # 推断是否古风
        is_archaic = any(w in personality + role for w in
                         ["古风", "古装", "修士", "掌门", "宗主", "长老", "前辈",
                          "老者", "老朽", "少年", "少女", "公子", "姑娘", "侠客",
                          "修真", "修仙", "武者", "剑客"])
        # 推断是否现代
        is_modern = any(w in personality + role for w in
                        ["现代", "都市", "学生", "老师", "医生", "工程师", "程序员"])

        if is_archaic:
            # 用了 "我" 但应该用 "吾" 等
            if "我" in text and "吾" not in text and not any(w in text for w in
                                                              ["我的", "我们", "我想", "我觉得", "我知道", "我是"]):
                # 只在 "我" 单独出现时 (作为自称) 提示
                if re.search(r"\b我\b", text):
                    issues.append(ValidationIssue(
                        dimension=self.dimension,
                        severity=SEV_INFO,
                        description=f"角色 '{char_name}' 古风身份, 台词用 '我' 作自称, 建议用 '吾/在下/本座' 等",
                        chapter_no=chapter_no,
                        char_start=char_start,
                        char_end=char_end,
                        suggestion="将自称'我'替换为'吾'或'在下'等文言自称",
                        related=char_name,
                    ))

        if is_modern:
            # 用了 "吾/在下" 等文言自称
            for w in FORMAL_SELF:
                if w in text and w != "我":
                    issues.append(ValidationIssue(
                        dimension=self.dimension,
                        severity=SEV_INFO,
                        description=f"角色 '{char_name}' 现代身份, 台词用文言自称 '{w}', 建议用 '我'",
                        chapter_no=chapter_no,
                        char_start=char_start,
                        char_end=char_end,
                        suggestion=f"将 '{w}' 替换为 '我'",
                        related=char_name,
                    ))
                    break
        return issues

    def _check_register(self, text: str, profile: dict, char_name: str,
                          char_start: int, char_end: int,
                          chapter_no: int) -> list:
        """语体: 文言词/口语词 vs profile."""
        issues: list = []
        personality = profile.get("personality", "") or ""
        role = profile.get("role", "") or ""
        full = personality + " " + role

        is_archaic = any(w in full for w in ["古风", "古装", "修士", "掌门", "长老", "侠客", "修真"])
        is_casual = any(w in full for w in ["活泼", "开朗", "调皮", "幽默", "搞笑", "现代", "都市", "少年"])

        if is_archaic:
            for w in ["哈哈", "嘿嘿", "呵呵", "哎哟", "哎呀", "嗯嗯", "啊哈"]:
                if w in text:
                    issues.append(ValidationIssue(
                        dimension=self.dimension,
                        severity=SEV_INFO,
                        description=f"古风角色 '{char_name}' 用了现代口语词 '{w}', 与角色设定不符",
                        chapter_no=chapter_no,
                        char_start=char_start,
                        char_end=char_end,
                        suggestion=f"将 '{w}' 替换为文言表达 (如 '善' '可' '甚好')",
                        related=char_name,
                    ))
                    break

        if is_casual:
            for w in ["善", "可", "谨", "恭"]:
                # 单独成词
                if re.search(rf"\b{w}\b", text):
                    issues.append(ValidationIssue(
                        dimension=self.dimension,
                        severity=SEV_INFO,
                        description=f"现代角色 '{char_name}' 用了文言词 '{w}', 与角色设定不符",
                        chapter_no=chapter_no,
                        char_start=char_start,
                        char_end=char_end,
                        suggestion=f"将 '{w}' 替换为现代表达",
                        related=char_name,
                    ))
                    break
        return issues
