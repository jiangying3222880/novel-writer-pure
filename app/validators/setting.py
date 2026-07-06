"""
G14 设定验证器 (Setting Validator)
业务场景: 检测章节内容是否符合世界设定.
  - 项目 genre 是 "古代/玄幻" → 不能出现 "汽车/手机/网络/电脑"
  - 项目 genre 是 "现代/都市" → 不能出现 "灵气/飞剑/修真" (除非有特殊说明)
  - 项目 genre 是 "科幻" → 不能出现 "魔法/经脉" 等
  - 项目有 "修真" 类型 → 修为境界需符合: 练气→筑基→金丹→元婴...
  - 项目设定 "无神论" → 不能出现 "神仙/上帝"

设计:
  - 用项目 genre + 项目 worldbuilding 实体 + memory CAT_WORLD_VIEW
  - 黑名单词: 按 genre 分类
  - 命中时 warning

注意: 这是启发式检查, 假阳性可接受 (作者忽略即可)
"""
from __future__ import annotations

import re
from typing import Optional

from app.services import project_service
from .base import (
    BaseValidator, ValidationIssue, ValidatorResult,
    DIM_SETTING, SEV_INFO, SEV_WARNING, SEV_ERROR,
)


# 按 genre 分黑名单 (小说常见题材)
SETTING_BLACKLIST = {
    "古代": ["手机", "电话", "网络", "电脑", "汽车", "飞机", "电视", "微信", "微博",
              "QQ", "互联网", "WiFi", "4G", "5G", "高铁", "地铁", "快递", "外卖",
              "空调", "电梯", "地铁", "股票", "银行"],
    "玄幻": ["手机", "电话", "网络", "电脑", "汽车", "飞机", "电视", "微信", "微博",
              "QQ", "互联网", "WiFi", "4G", "5G", "高铁", "地铁", "快递", "外卖",
              "空调", "电梯", "地铁", "股票", "银行", "科学", "物理", "化学",
              "实验室", "卫星", "导弹", "核弹"],
    "修真": ["手机", "电话", "网络", "电脑", "汽车", "飞机", "电视", "微信", "微博",
              "QQ", "互联网", "WiFi", "4G", "5G", "高铁", "地铁", "快递", "外卖",
              "空调", "电梯", "地铁", "股票", "银行", "科学", "物理", "化学",
              "实验室", "卫星", "导弹", "核弹"],
    "武侠": ["手机", "电话", "网络", "电脑", "汽车", "飞机", "电视", "微信", "微博",
              "QQ", "互联网", "WiFi", "4G", "5G", "高铁", "地铁", "空调"],
    "仙侠": ["手机", "电话", "网络", "电脑", "汽车", "飞机", "电视", "微信", "微博",
              "QQ", "互联网", "WiFi", "4G", "5G", "高铁", "地铁", "快递", "外卖",
              "空调", "电梯", "股票", "银行", "科学", "物理", "化学"],
    "现代": ["灵气", "飞剑", "修真", "法术", "符箓", "内功", "内力", "真气", "结丹", "金丹",
              "筑基", "元婴", "化神", "仙人", "神祇", "妖怪", "灵兽", "御剑", "斗气", "魔法",
              "经脉", "丹田", "灵根", "法器", "法宝"],
    "都市": ["灵气", "飞剑", "修真", "法术", "符箓", "内功", "内力", "真气", "结丹", "金丹",
              "筑基", "元婴", "化神", "仙人", "妖怪", "御剑", "斗气", "魔法", "经脉", "丹田",
              "灵根", "法器", "法宝", "降魔", "除妖"],
    "科幻": ["魔法", "斗气", "内力", "真气", "灵气", "内功", "仙术", "符箓", "法术", "仙人",
              "灵根", "丹田", "经脉", "御剑", "飞剑", "降妖", "除魔", "妖", "仙"],
    "军事": ["魔法", "斗气", "内力", "真气", "灵气", "内功", "仙术", "符箓", "法术", "仙人",
              "灵根", "丹田", "经脉", "御剑", "飞剑", "妖", "仙"],
    "历史": ["手机", "电话", "网络", "电脑", "汽车", "飞机", "电视", "微信", "微博",
              "QQ", "互联网", "WiFi", "4G", "5G", "高铁", "地铁", "空调", "电梯", "快递",
              "外卖", "银行", "股票"],
}

# 修为境界顺序 (修真类检测境界倒序)
CULTIVATION_LEVELS = [
    "练气", "筑基", "结丹", "金丹", "元婴", "化神", "炼虚", "合体", "大乘", "渡劫",
]


class SettingValidator(BaseValidator):
    """G14 设定验证器: 世界规则一致性."""

    dimension = DIM_SETTING
    name = "设定"

    def _do_validate(self, project_id: str, chapter_id: str,
                      content: str, chapter_no: int,
                      context: dict) -> ValidatorResult:
        result = ValidatorResult(dimension=self.dimension)

        if not content or len(content) < 20:
            return result

        # 1) genre 黑名单检查
        try:
            p = project_service.get(project_id)
            genre = p.get("genre", "") if p else ""
        except Exception:
            genre = ""
        if genre and genre in SETTING_BLACKLIST:
            blacklist = SETTING_BLACKLIST[genre]
            issues = self._check_blacklist(content, blacklist, genre, chapter_no)
            result.issues.extend(issues)

        # 2) 修真类: 境界倒序检测
        if genre in ("修真", "玄幻", "仙侠"):
            issues = self._check_cultivation_order(content, chapter_no)
            result.issues.extend(issues)

        # 3) 项目级自定义黑名单 (从 world_settings 注入, key 为 "blacklist" 时是逗号分隔字符串)
        world_settings = self._load_world_settings(project_id)
        if self._world_settings:
            world_settings.update(self._world_settings)
        custom_blacklist_str = world_settings.get("blacklist", "") or ""
        if custom_blacklist_str:
            custom_blacklist = [w.strip() for w in custom_blacklist_str.split(",") if w.strip()]
            if custom_blacklist:
                issues = self._check_blacklist(content, custom_blacklist, "自定义", chapter_no)
                result.issues.extend(issues)

        return result

    # ------------------------------------------------------------------
    def _check_blacklist(self, content: str, blacklist: list,
                           genre: str, chapter_no: int) -> list:
        """黑名单词检测."""
        issues: list = []
        reported: set = set()
        for word in blacklist:
            if word in content and word not in reported:
                reported.add(word)
                pos = content.find(word)
                issues.append(ValidationIssue(
                    dimension=self.dimension,
                    severity=SEV_WARNING,
                    description=f"'{word}' 不符合本作品 '{genre}' 题材设定",
                    chapter_no=chapter_no,
                    char_start=pos,
                    char_end=pos + len(word),
                    suggestion=f"检查'{word}'是否需要替换为符合 '{genre}' 题材的表述",
                    related=word,
                ))
        return issues

    def _check_cultivation_order(self, content: str, chapter_no: int) -> list:
        """修真类: 检测境界倒序 (如'元婴'出现比'筑基'早 + 主角筑基前就使用元婴能力)."""
        issues: list = []
        # 找本章出现的所有境界
        found_levels: list = []  # [(name, position, level_index)]
        for i, lvl in enumerate(CULTIVATION_LEVELS):
            for m in re.finditer(lvl, content):
                found_levels.append((lvl, m.start(), i))
        if len(found_levels) < 2:
            return issues
        # 检测: 同一段中, 高境界出现在低境界之前
        # 简化: 全文按 position 排序, 检查相邻两个是否倒序
        found_levels.sort(key=lambda x: x[1])
        reported: set = set()
        for i in range(len(found_levels) - 1):
            cur = found_levels[i]
            nxt = found_levels[i + 1]
            if cur[2] > nxt[2]:  # 倒序
                # 距离太近 (≤ 100 字符) 才算问题
                if nxt[1] - cur[1] <= 200:
                    key = (cur[0], nxt[0])
                    if key in reported:
                        continue
                    reported.add(key)
                    issues.append(ValidationIssue(
                        dimension=self.dimension,
                        severity=SEV_INFO,
                        description=f"境界 '{cur[0]}' (高级) 出现在 '{nxt[0]}' (低级) 之前, 顺序可能有问题",
                        chapter_no=chapter_no,
                        char_start=cur[1],
                        char_end=cur[1] + len(cur[0]),
                        suggestion="检查境界描述是否符合修真体系顺序",
                        related=f"{cur[0]}→{nxt[0]}",
                    ))
        return issues
