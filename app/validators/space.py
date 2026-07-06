"""
G15 空间验证器 (Space Validator)
业务场景: 检测章节内空间/场景一致性.
  - 空间跳跃: 主角在房间, 突然出现在街上, 中间无移动描写
  - 同场景矛盾: 门朝东/门朝西, 房间大/房间小, 窗朝南/窗朝北
  - 同章同时出现矛盾方位 (前后 200 字符内 "东" 描述同一位置 + "西" 描述同一位置)
  - 多人同位置描写: "他和她" 同一时间同地点做不同事情 (疑似时序错)

设计:
  - 抽方位词: 东/南/西/北/左/右/前/后/上/下 + 同一位置
  - 抽空间移动动词: 走出/进入/飞向/跑到/来到/离开/返回
  - 检测: 移动动词缺失, 但位置词前后矛盾
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Optional

from .base import (
    BaseValidator, ValidationIssue, ValidatorResult,
    DIM_SPACE, SEV_INFO, SEV_WARNING, SEV_ERROR,
)


# 方位词
DIRECTIONS = ["东", "南", "西", "北", "左", "右", "前", "后", "上", "下",
              "东面", "南面", "西面", "北面", "东边", "南边", "西边", "北边",
              "东方", "南方", "西方", "北方", "左侧", "右侧", "左边", "右边",
              "前面", "后面", "上面", "下面"]

# 移动动词 (17 常见)
MOVE_VERBS = ["走", "跑", "飞", "到", "去", "来", "回", "入", "出", "进", "退",
              "踏", "跃", "攀", "爬", "跳", "降", "落", "升", "渡", "穿", "越",
              "抵达", "离开", "返回", "走出", "进入", "飞向", "跑到", "来到",
              "前往", "奔向", "冲向", "赶向", "退向", "逃向", "逃到"]

# 空间跳跃阈值 (字符) - 在 X 字符内位置变化需有移动动词
SPACE_JUMP_THRESHOLD = 300

# 最小章节长度
MIN_CHAPTER_LEN = 30


class SpaceValidator(BaseValidator):
    """G15 空间验证器: 空间/场景/方位一致性."""

    dimension = DIM_SPACE
    name = "空间"

    def _do_validate(self, project_id: str, chapter_id: str,
                      content: str, chapter_no: int,
                      context: dict) -> ValidatorResult:
        result = ValidatorResult(dimension=self.dimension)

        if not content or len(content) < MIN_CHAPTER_LEN:
            return result

        # 1) 空间跳跃检测
        jump_issues = self._check_space_jump(content, chapter_no)
        result.issues.extend(jump_issues)

        # 2) 同场景方位矛盾
        direction_issues = self._check_direction_conflict(content, chapter_no)
        result.issues.extend(direction_issues)

        # 3) 同场景规模矛盾 (大/小/远/近 矛盾)
        size_issues = self._check_size_conflict(content, chapter_no)
        result.issues.extend(size_issues)

        # 4) 未在世界地理库登记的新地点 (info)
        new_loc_issues = self._check_new_locations(project_id, content, chapter_no)
        result.issues.extend(new_loc_issues)

        return result

    # ------------------------------------------------------------------
    def _extract_locations(self, content: str) -> list:
        """抽地点 (在X里/到X去 + 后缀)."""
        locs: list = []
        patterns = [
            re.compile(r"在([\u4e00-\u9fff]{2,6})(?:里|中|内|上|下|旁|处)"),
            re.compile(r"到([\u4e00-\u9fff]{2,6})(?:去|里|中|处)"),
            re.compile(r"([\u4e00-\u9fff]{2,6})(?:城|镇|村|殿|阁|山|谷|林|海|岛|关|门|派|宗|堂|院|府|宫|楼|塔|寺|庙|宫|殿)"),
        ]
        for pat in patterns:
            for m in pat.finditer(content):
                locs.append((m.group(1), m.start(), m.end()))
        return locs

    def _check_space_jump(self, content: str, chapter_no: int) -> list:
        """空间跳跃: 位置 A → 位置 B, 中间无移动动词."""
        issues: list = []
        locs = self._extract_locations(content)
        if len(locs) < 2:
            return issues
        for i in range(len(locs) - 1):
            cur_name, cur_start, cur_end = locs[i]
            nxt_name, nxt_start, nxt_end = locs[i + 1]
            # 同一地点 → 跳过
            if cur_name == nxt_name:
                continue
            # 距离
            gap = nxt_start - cur_end
            if gap > SPACE_JUMP_THRESHOLD:
                continue
            # 中间是否有移动动词
            between = content[cur_end:nxt_start]
            has_move = any(v in between for v in MOVE_VERBS)
            if not has_move:
                # 检查是否在对话内 (对话可跳跃)
                if '"' in between or '"' in between or '"' in between or '"' in between:
                    continue
                # 检查是否 "想起"/"回忆" 等 (回忆/心理可跳跃)
                if any(w in between for w in ["想起", "回忆", "仿佛", "似乎", "梦中", "意识"]):
                    continue
                issues.append(ValidationIssue(
                    dimension=self.dimension,
                    severity=SEV_WARNING,
                    description=f"空间跳跃: '{cur_name}' → '{nxt_name}', 中间 {gap} 字符无移动描写",
                    chapter_no=chapter_no,
                    char_start=cur_end,
                    char_end=nxt_start,
                    suggestion=f"在 '{cur_name}' 和 '{nxt_name}' 之间补一段移动描写 (如 '走出门外', '御剑飞往')",
                    related=f"{cur_name}→{nxt_name}",
                ))
        return issues

    def _check_direction_conflict(self, content: str, chapter_no: int) -> list:
        """方位矛盾: 同一锚点 (前面/后面/左边...) 描述了相反方位."""
        issues: list = []
        # 模式: 锚点 + 方位词
        # 简化: 在 200 字符窗口内, 检测 "门" 同时被 "东面" 和 "西面" 修饰
        for keyword in ["门", "窗", "山", "河", "海", "桥", "塔", "殿", "院", "楼"]:
            positions = [m.start() for m in re.finditer(keyword, content)]
            if len(positions) < 2:
                continue
            # 遍历相邻的 keyword
            for i in range(len(positions) - 1):
                p1 = positions[i]
                p2 = positions[i + 1]
                if p2 - p1 > 200:
                    continue
                # 检查 window
                w1 = content[max(0, p1-30):p1+30]
                w2 = content[max(0, p2-30):p2+30]
                d1 = [d for d in DIRECTIONS if d in w1]
                d2 = [d for d in DIRECTIONS if d in w2]
                # 找矛盾对 (东 vs 西, 南 vs 北, 左 vs 右, 前 vs 后, 上 vs 下)
                opposites = [("东", "西"), ("南", "北"), ("左", "右"), ("前", "后"), ("上", "下"),
                              ("东面", "西面"), ("南面", "北面"), ("左边", "右边"),
                              ("前面", "后面"), ("东边", "西边"), ("南边", "北边"),
                              ("东方", "西方"), ("南方", "北方"), ("左侧", "右侧")]
                found_opposite = None
                for a, b in opposites:
                    if (a in d1 and b in d2) or (b in d1 and a in d2):
                        found_opposite = (a, b)
                        break
                if found_opposite:
                    issues.append(ValidationIssue(
                        dimension=self.dimension,
                        severity=SEV_ERROR,
                        description=f"'{keyword}' 方位矛盾: '{found_opposite[0]}' vs '{found_opposite[1]}' 在 {p2-p1} 字符内同时出现",
                        chapter_no=chapter_no,
                        char_start=min(p1, p2),
                        char_end=max(p1, p2) + len(keyword),
                        suggestion=f"统一 '{keyword}' 的方位为 '{found_opposite[0]}' 或 '{found_opposite[1]}'",
                        related=keyword,
                    ))
        return issues

    def _check_size_conflict(self, content: str, chapter_no: int) -> list:
        """规模矛盾: 同一锚点被描述为大/小/远/近 矛盾."""
        issues: list = []
        size_pairs = [("大", "小"), ("高", "矮"), ("远", "近"), ("长", "短"), ("宽", "窄"),
                      ("巨大", "狭小"), ("宽阔", "狭窄"), ("辽阔", "局促"), ("高耸", "低矮")]
        for keyword in ["房", "屋", "殿", "厅", "院", "城", "山", "谷", "路", "街", "道", "厅"]:
            positions = [m.start() for m in re.finditer(keyword, content)]
            if len(positions) < 2:
                continue
            for i in range(len(positions) - 1):
                p1 = positions[i]
                p2 = positions[i + 1]
                if p2 - p1 > 200:
                    continue
                w1 = content[max(0, p1-30):p1+30]
                w2 = content[max(0, p2-30):p2+30]
                for a, b in size_pairs:
                    if (a in w1 and b in w2) or (b in w1 and a in w2):
                        issues.append(ValidationIssue(
                            dimension=self.dimension,
                            severity=SEV_ERROR,
                            description=f"'{keyword}' 规模矛盾: '{a}' vs '{b}' 在 {p2-p1} 字符内同时出现",
                            chapter_no=chapter_no,
                            char_start=min(p1, p2),
                            char_end=max(p1, p2) + len(keyword),
                            suggestion=f"统一 '{keyword}' 的规模描述",
                            related=keyword,
                        ))
        return issues

    def _check_new_locations(self, project_id: str, content: str,
                                chapter_no: int) -> list:
        """未在世界地理库登记的新地点 (info)."""
        issues: list = []
        world_locs = self._load_world_locations(project_id)
        if not world_locs:
            return issues
        locs = self._extract_locations(content)
        reported: set = set()
        for name, start, end in locs:
            if name in reported:
                continue
            if any(name == w or name in w or w in name for w in world_locs):
                continue
            # 过滤非地点词
            if name in {"起来", "出来", "手中", "怀里", "腰间", "心里", "眼里", "嘴里"}:
                continue
            reported.add(name)
            issues.append(ValidationIssue(
                dimension=self.dimension,
                severity=SEV_INFO,
                description=f"新地点 '{name}' 未在世界地理库登记",
                chapter_no=chapter_no,
                char_start=start,
                char_end=end,
                suggestion=f"在'世界设定'中添加 '{name}' 的描述, 或确认是否临时地点",
                related=name,
            ))
        return issues
