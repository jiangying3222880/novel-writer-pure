"""
G11 道具验证器 (Props Validator)
业务场景: 跨章追踪道具的 持有/位置/状态, 检测:
  - 凭空出现: 道具在某章首次被使用/出现, 之前从未被介绍
  - 凭空消失: 道具在某章被使用, 之后章节不再出现 (可能被遗弃/转移/销毁无交代)
  - 持有者矛盾: 道具在某章被 X 持有, 之后章被 Y 持有但无转移描写
  - 状态矛盾: 道具在某章被描述为完好, 之后章被描述为破碎/消失但无描写

设计:
  - 跨章状态: {item_name: {first_seen_chapter, last_seen_chapter, last_state, holders: []}}
  - 单章扫描: 抽道具 + 持有动词 + 状态形容词
  - 状态形容词: 完好/破碎/缺损/裂开/有裂痕/已毁/消失/不见/沾血/燃起/发光/完整/崭新/崭新如初/锈迹斑斑
  - 持有动词: 持有/握/拿/佩/藏/赠/送/递/交给/夺/抢/丢失/遗失/找回/寻得

与 G5 item 维的区别:
  - G5 = 单章内新物品检测 (info 级)
  - G11 = 跨章道具生命周期追踪 (warning/error 级)
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from .base import (
    BaseValidator, ValidationIssue, ValidatorResult,
    DIM_PROPS, SEV_INFO, SEV_WARNING, SEV_ERROR,
)


# 物品后缀 (同 G5 consistency.py)
ITEM_SUFFIXES = (
    "剑|刀|镜|瓶|丹|珠|环|令|符|图|录|册|鉴|首|佩|簪|镯|鞭|锤|索|灯|杯|盘|碗|壶|钟|"
    "琴|笛|箫|杖|印|旗|枪|戟|戈|斧|钺|钩|叉|棒|弓|弩|盾|甲|袍|衣|靴|帽|冠|带|绳|线|帕|"
    "囊|袋|盒|箱|匣|笼|网|砚|墨|笔|纸|帛|绢|纱|罗|锦|缎|玉|石|宝|珊|瑚|"
    "琉|璃|琥|珀|珍|法器|法宝|灵器|仙器|神器|魔器|圣器"
)

# 持有动词 (10 常见)
HOLDING_VERBS = ["持有", "握着", "拿着", "佩着", "藏着", "佩戴", "握紧", "取出", "掏出", "拾起"]
TRANSFER_VERBS = ["赠", "送", "递", "交给", "传给", "托付", "转交", "交给"]
TAKE_VERBS = ["夺", "抢", "拿走", "夺走", "抢走", "收走", "收缴"]
LOSE_VERBS = ["丢失", "遗失", "不见", "消失", "丢下", "扔下", "弃置", "丢弃", "毁去", "销毁", "毁掉", "打碎", "砸碎", "弄碎"]
FIND_VERBS = ["找回", "寻得", "寻回", "找到", "捡到"]

# 状态形容词 (道具状态)
STATE_ADJECTIVES_BROKEN = ["破碎", "已碎", "碎裂", "裂开", "有裂痕", "残破", "已毁", "毁坏", "裂痕", "残缺"]
STATE_ADJECTIVES_INTACT = ["完好", "完整", "崭新", "崭新如初", "毫无损伤", "完好如初", "依旧完好"]
STATE_ADJECTIVES_MAGIC = ["发光", "闪烁", "灼热", "微凉", "炽热", "沾血", "染血", "染尘", "蒙尘"]

ALL_STATES = STATE_ADJECTIVES_BROKEN + STATE_ADJECTIVES_INTACT + STATE_ADJECTIVES_MAGIC


class PropsValidator(BaseValidator):
    """G11 道具验证器: 跨章追踪道具生命周期."""

    dimension = DIM_PROPS
    name = "道具"

    def _do_validate(self, project_id: str, chapter_id: str,
                      content: str, chapter_no: int,
                      context: dict) -> ValidatorResult:
        result = ValidatorResult(dimension=self.dimension)

        if not content or len(content) < 20:
            return result

        # 加载跨章历史 + 世界物品库
        history = self._load_chapter_history(project_id, chapter_no - 1) if chapter_no > 1 else []
        world_items = self._load_world_items(project_id)

        # 单章抽道具 + 状态
        chapter_items = self._extract_chapter_items(content, chapter_no, world_items)

        # 跨章追踪
        if history and chapter_items:
            state = self._build_state_from_history(history, world_items)
            cross_issues = self._check_cross_chapter(state, chapter_no, chapter_items, content)
            result.issues.extend(cross_issues)

        # 单章内矛盾 (本章前后状态变化无描写)
        intra_issues = self._check_intra_chapter(content, chapter_no, chapter_items)
        result.issues.extend(intra_issues)

        return result

    # ------------------------------------------------------------------
    # 抽取
    # ------------------------------------------------------------------
    def _extract_chapter_items(self, content: str, chapter_no: int,
                                world_items: list) -> list:
        """单章抽出: 道具名 + 持有/转移/状态 + 位置."""
        items: list = []  # [(item_name, verb, state_adj, char_start, char_end, line)]

        # 1) 道具后缀模式: 1-6 字 + 后缀
        pat = re.compile(r"([\u4e00-\u9fff]{1,6})(?:" + ITEM_SUFFIXES + ")")
        for m in pat.finditer(content):
            name = m.group(0)
            if any(name == w or name in w or w in name for w in world_items):
                items.append({"name": name, "verb": "", "state": "", "char_start": m.start(), "char_end": m.end()})

        # 2) 持有动词模式
        for verb in HOLDING_VERBS + TRANSFER_VERBS + TAKE_VERBS + LOSE_VERBS + FIND_VERBS:
            vp = re.compile(verb + r"([\u4e00-\u9fff]{1,6}(?:" + ITEM_SUFFIXES + ")?)")
            for m in vp.finditer(content):
                items.append({
                    "name": m.group(1),
                    "verb": verb,
                    "state": "",
                    "char_start": m.start(),
                    "char_end": m.end(),
                })

        # 3) 状态形容词: 找 adj, 然后前后 10 字符内找 item+suffix
        for adj in ALL_STATES:
            for m in re.finditer(adj, content):
                adj_start = m.start()
                # 前 10 字符内找最近一个 item+suffix
                window_before = content[max(0, adj_start - 10):adj_start]
                # 在 window_before 中找最长 item+suffix
                item_match = None
                for mm in re.finditer(r"[\u4e00-\u9fff]{1,6}(?:" + ITEM_SUFFIXES + ")", window_before):
                    item_match = mm
                if item_match:
                    # adj 在 item 之后 (正常语序: 玉佩 完好)
                    item_full = item_match.group(0)
                    char_start = adj_start - len(item_full)
                    items.append({
                        "name": item_full,
                        "verb": "",
                        "state": adj,
                        "char_start": char_start,
                        "char_end": adj_start + len(adj),
                    })
                else:
                    # adj 在 item 之前 (倒装: 完好的 玉佩)
                    window_after = content[adj_start + len(adj):adj_start + len(adj) + 10]
                    item_match2 = None
                    for mm in re.finditer(r"[\u4e00-\u9fff]{1,6}(?:" + ITEM_SUFFIXES + ")", window_after):
                        item_match2 = mm
                        break
                    if item_match2:
                        item_full = item_match2.group(0)
                        items.append({
                            "name": item_full,
                            "verb": "",
                            "state": adj,
                            "char_start": adj_start,
                            "char_end": adj_start + len(adj) + len(item_full),
                        })

        # 去重 (同位置同道具)
        seen: set = set()
        unique = []
        for it in items:
            k = (it["name"], it["char_start"])
            if k in seen:
                continue
            seen.add(k)
            unique.append(it)
        return unique

    def _build_state_from_history(self, history: list, world_items: list) -> dict:
        """构建跨章道具状态: {item_name: {first, last, last_state, is_intact}}."""
        state: dict = {}
        for chapter_no, chapter_id, content in history:
            if not content:
                continue
            items = self._extract_chapter_items(content, chapter_no, world_items)
            for it in items:
                name = it["name"]
                if name not in state:
                    state[name] = {
                        "first": chapter_no,
                        "last": chapter_no,
                        "mentions": [],
                        "last_state": "",
                        "destroyed": False,
                    }
                st = state[name]
                st["last"] = chapter_no
                st["mentions"].append(chapter_no)
                if it["state"] in STATE_ADJECTIVES_BROKEN:
                    st["last_state"] = "broken"
                    if it["verb"] in LOSE_VERBS or "碎" in it["state"] or "毁" in it["state"]:
                        st["destroyed"] = True
                elif it["state"] in STATE_ADJECTIVES_INTACT:
                    st["last_state"] = "intact"
                if it["state"]:
                    st["last_state"] = it["state"]
        return state

    def _check_cross_chapter(self, state: dict, chapter_no: int,
                                chapter_items: list, content: str) -> list:
        """跨章检查: 凭空出现/状态矛盾/已毁物品再出现."""
        issues: list = []
        for it in chapter_items:
            name = it["name"]
            if name not in state:
                # 凭空出现 (无 first_seen, 但有 last_state 直接完整) - 不算
                continue
            prev = state[name]
            # 1) 状态矛盾: 之前已破碎/销毁, 本章又完整出现
            if prev.get("destroyed") and it["state"] in STATE_ADJECTIVES_INTACT:
                issues.append(ValidationIssue(
                    dimension=self.dimension,
                    severity=SEV_ERROR,
                    description=f"道具 '{name}' 已在第 {prev['last']} 章被销毁/丢失, 本章又以完好状态出现, 状态矛盾",
                    chapter_no=chapter_no,
                    char_start=it["char_start"],
                    char_end=it["char_end"],
                    suggestion=f"需补写 '{name}' 重新获得的经过, 或修改本章描写为 '残破/有裂痕' 等",
                    related=name,
                ))
            # 2) 凭空消失: 之前在 prev['last'] 章出现, 之后 ≥ 3 章未出现 (本章又突然出现)
            gap = chapter_no - prev["last"]
            if gap >= 3 and not prev.get("destroyed"):
                # 检查本章是否解释获得
                if not any(v in content[max(0, it["char_start"]-100):it["char_end"]+50]
                           for v in FIND_VERBS + TRANSFER_VERBS):
                    issues.append(ValidationIssue(
                        dimension=self.dimension,
                        severity=SEV_WARNING,
                        description=f"道具 '{name}' 在第 {prev['last']} 章后消失 {gap} 章, 本章又出现但未交代来源",
                        chapter_no=chapter_no,
                        char_start=it["char_start"],
                        char_end=it["char_end"],
                        suggestion=f"补写 '{name}' 重新获得的经过, 或确认是否在第 {prev['last']+1}~{chapter_no-1} 章被销毁/转移",
                        related=name,
                    ))
        return issues

    def _check_intra_chapter(self, content: str, chapter_no: int,
                                chapter_items: list) -> list:
        """单章内矛盾: 同一道具先完好后破碎, 中间无损坏描写."""
        issues: list = []
        # 按道具名分组
        by_name: dict = defaultdict(list)
        for it in chapter_items:
            by_name[it["name"]].append(it)
        for name, items in by_name.items():
            if len(items) < 2:
                continue
            items.sort(key=lambda x: x["char_start"])
            # 检查完好 → 破碎
            for i in range(len(items) - 1):
                cur = items[i]
                nxt = items[i + 1]
                if cur["state"] in STATE_ADJECTIVES_INTACT and nxt["state"] in STATE_ADJECTIVES_BROKEN:
                    # 中间是否有 LOSE_VERB
                    between = content[cur["char_end"]:nxt["char_start"]]
                    if not any(v in between for v in LOSE_VERBS + ["打", "击", "砸", "裂", "断", "碰"]):
                        issues.append(ValidationIssue(
                            dimension=self.dimension,
                            severity=SEV_INFO,
                            description=f"道具 '{name}' 在本章从完好突变为破碎, 中间缺少损坏过程描写",
                            chapter_no=chapter_no,
                            char_start=nxt["char_start"],
                            char_end=nxt["char_end"],
                            suggestion="补写一段损坏过程 (如战斗/失手/被攻击) 再描写破碎状态",
                            related=name,
                        ))
        return issues
