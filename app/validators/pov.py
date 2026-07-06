"""
G12 视角验证器 (POV Validator)
业务场景: 检测单章内视角是否一致.
  - 第一人称 (我) 出现, 又出现第三人称 (他/她) 描述自己 → 视角漂移
  - 第二人称 (你) 突然出现 (除自传/特殊文体)
  - 内心独白与外部观察混淆 (同一段既用 "我心里想" 又用 "从外面看, 他...")

设计:
  - 默认假设: 第三人称限制视角 (有限全知/单一 POV)
  - 抽第一人称代词 (我/我们/我的/我们的)
  - 抽第二人称代词 (你/你们/你的)
  - 抽第三人称代词 (他/她/他们/她们/他的/她的/他们的/她们的)
  - 警告: 同一章混合 I/You
  - 错误: 同一段同一主体既用 I 又用 third-person refer to self

与 G5 character 维的区别:
  - G5 = 跨章人名出现
  - G12 = 单章视角漂移 (人称代词层面)
"""
from __future__ import annotations

import re

from .base import (
    BaseValidator, ValidationIssue, ValidatorResult,
    DIM_POV, SEV_INFO, SEV_WARNING, SEV_ERROR,
)


# 第一人称代词
FIRST_PERSON = ["我", "我们", "我的", "我们的", "我自己"]
# 第二人称代词
SECOND_PERSON = ["你", "你们", "你的", "你们的", "你自己"]
# 第三人称代词
THIRD_PERSON = ["他", "她", "他们", "她们", "他的", "她的", "他们的", "她们的", "他们自己"]

# 段内允许的代词 (硬约束: 同一段不能同时出现 1st 和 3rd 指代自己)
# 用段内分块 (\n\n 或 \n) 来分析
PARA_SPLIT = re.compile(r"\n\s*\n")


class POVValidator(BaseValidator):
    """G12 视角验证器: 人称代词一致性."""

    dimension = DIM_POV
    name = "视角"

    def _do_validate(self, project_id: str, chapter_id: str,
                      content: str, chapter_no: int,
                      context: dict) -> ValidatorResult:
        result = ValidatorResult(dimension=self.dimension)

        if not content or len(content) < 20:
            return result

        # 1) 全文视角检测
        counts = self._count_persons(content)
        n_first = counts["first"]
        n_second = counts["second"]
        n_third = counts["third"]

        # 2) 混合 I+You 警告 (第二人称是小说禁区, 出现几乎都是错误)
        if n_second >= 2 and n_first >= 5:
            issues_sy = self._find_mixed_paragraphs(content, "first+second")
            for char_start, char_end, text in issues_sy:
                result.issues.append(ValidationIssue(
                    dimension=self.dimension,
                    severity=SEV_WARNING,
                    description=f"本章同时出现大量第一人称({n_first})和第二人称({n_second}), 视角混乱",
                    chapter_no=chapter_no,
                    char_start=char_start,
                    char_end=char_end,
                    suggestion="统一为第一人称或第三人称, 删除'你'或'我'",
                    related="first+second",
                ))

        # 3) 单段内混合 I+III (自己又用他/她)
        mixed_self = self._find_mixed_paragraphs(content, "first+third_self")
        for char_start, char_end, text in mixed_self:
            result.issues.append(ValidationIssue(
                dimension=self.dimension,
                severity=SEV_ERROR,
                description="本段第一人称'我'和第三人称'他/她'混用, 视角漂移",
                chapter_no=chapter_no,
                char_start=char_start,
                char_end=char_end,
                suggestion="将'他/她'统一为'我', 或将整段改为纯第三人称",
                related="first+third_self",
            ))

        # 4) 章首尾视角不一致 (开头 I, 结尾 III 描述同一主体)
        # 简化: 章首 200 字符 vs 章尾 200 字符
        head = content[:200]
        tail = content[-200:] if len(content) > 200 else ""
        if head and tail:
            h_first = any(p in head for p in ["我", "我们"])
            t_third = any(p in tail for p in ["他", "她", "他们"])
            t_first = any(p in tail for p in ["我", "我们"])
            if h_first and t_third and not t_first:
                result.issues.append(ValidationIssue(
                    dimension=self.dimension,
                    severity=SEV_WARNING,
                    description="章首以第一人称'我'叙述, 章尾转为第三人称'他/她'描述同一主体",
                    chapter_no=chapter_no,
                    char_start=max(0, len(content) - 200),
                    char_end=len(content),
                    suggestion="检查章尾是否需改为'我', 或在视角转换处补一句过渡 (如'我仿佛看到了另一个自己')",
                    related="head_tail_mismatch",
                ))

        return result

    # ------------------------------------------------------------------
    def _count_persons(self, content: str) -> dict:
        """数人称代词出现次数."""
        # 用 regex 匹配词边界
        first = sum(len(re.findall(rf"\b{p}\b", content)) if False else content.count(p)
                    for p in FIRST_PERSON)
        # 上面是错的, 改用字符级 + 简单去重
        # 用 count 简单实现, 不做完整分词
        def _count(patterns, text):
            total = 0
            for p in patterns:
                # 避免 "我的" 被 "我" + "的" 双计数
                # 用滑动: 出现 1 次计 1
                total += text.count(p)
            return total
        return {
            "first": _count(FIRST_PERSON, content),
            "second": _count(SECOND_PERSON, content),
            "third": _count(THIRD_PERSON, content),
        }

    def _find_mixed_paragraphs(self, content: str, kind: str) -> list:
        """找混合视角的段落. 返回 [(char_start, char_end, text)]."""
        out: list = []
        offset = 0
        for para in PARA_SPLIT.split(content):
            if len(para) < 5:
                offset += len(para) + 2  # \n\n
                continue
            char_start = offset
            char_end = offset + len(para)
            offset = char_end + 2
            if kind == "first+second":
                has_first = any(p in para for p in ["我", "我们"])
                has_second = any(p in para for p in ["你", "你们"])
                if has_first and has_second:
                    out.append((char_start, char_end, para))
            elif kind == "first+third_self":
                # 第一人称 + 第三人称, 但需要排除正常引用 ("我说: '他的眼睛'")
                has_first = any(p in para for p in ["我", "我们"])
                has_third = any(p in para for p in ["他", "她"])
                # 简化: 同时有且段长 < 200, 警告
                if has_first and has_third and len(para) < 200:
                    out.append((char_start, char_end, para))
        return out
