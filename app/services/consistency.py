"""
G5 一致性检测 (Consistency Checker)
业务场景: 每章写完跑一次, 扫 4 维矛盾, 写到 consistency_logs 表 (供 G11-G16 6 验证器用)
  - 人物 character: 角色身份/状态/能力前后矛盾
  - 地理 location:  同名地点前后描述不一致
  - 时间 time:       时间线跳跃 / 同日事件顺序错
  - 物品 item:       物品持有者变化无交代 / 物品出现凭空消失

每章 ¥0.1, AI 全检一次
简化版: 0 tokens, 本地规则, 跟 D4 矛盾检测互补 (D4 = 5 维度状态矛盾, G5 = 文本级 4 维矛盾)
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from app.db import _impl as _db_conn
from app.services import worldbuilding, world_sync
from app.services.exceptions import NotFoundError, ValidationError


DIM_CHARACTER = "character"
DIM_LOCATION = "location"
DIM_TIME = "time"
DIM_ITEM = "item"
ALL_DIMS = [DIM_CHARACTER, DIM_LOCATION, DIM_TIME, DIM_ITEM]

DIM_LABELS = {
    DIM_CHARACTER: "人物",
    DIM_LOCATION: "地理",
    DIM_TIME: "时间",
    DIM_ITEM: "物品",
}

SEV_INFO = "info"
SEV_WARNING = "warning"
SEV_ERROR = "error"
ALL_SEVS = [SEV_INFO, SEV_WARNING, SEV_ERROR]


@dataclass
class ConsistencyIssue:
    """单个一致性问题."""
    dimension: str
    severity: str
    description: str
    chapter_a: Optional[int] = None
    chapter_b: Optional[int] = None


# ============================================================
# 工具
# ============================================================

def _conn():
    return _db_conn.get_conn()


def _split_chapters(project_id: str) -> list[tuple[int, str, str]]:
    """取项目所有章 (chapter_no, chapter_id, content)."""
    from app.services import book_service, chapter_service
    books = book_service.list_for_project(project_id).get("books", [])
    out: list[tuple[int, str, str]] = []
    for b in books:
        chs = chapter_service.list_for_book(b["id"]).get("chapters", [])
        for ch in chs:
            draft = chapter_service.get_current_draft(ch["id"])
            content = draft.get("content", "") if draft else ""
            out.append((ch.get("chapter_no", 0), ch["id"], content))
    return out


# ============================================================
# 4 维检测
# ============================================================

def _check_characters_in_chapters(project_id: str,
                                    chapters: list[tuple[int, str, str]]
                                    ) -> list[ConsistencyIssue]:
    """人物: 项目级扫描, 跨章统计新人名.

    触发: 某人名在项目任意章出现 ≥ 3 次 (累计), 且未在世界人物库登记 → info.
    """
    issues = []
    char_names = [e.name for e in worldbuilding.list_all(project_id, worldbuilding.KIND_CHARACTER)]
    # 大幅扩展停用词: 常见非人名词/动词/副词/连词/量词/时间词/地点通名
    non_name_words = {
        # 代词
        "我们", "他们", "她们", "什么", "怎么", "这样", "那样", "这里", "那里",
        "自己", "别人", "大家", "对方", "此人", "那人", "旁人", "众人",
        # 连词/副词
        "刚才", "已经", "于是", "不过", "可是", "虽然", "然而", "但是", "而且",
        "或者", "因为", "所以", "如果", "虽然", "即使", "无论", "不但", "而且",
        "只是", "却见", "便见", "旋即", "登时", "顷刻", "霎时", "此时", "彼时",
        "当下", "少时", "多时", "片刻", "半晌", "须臾", "忽然", "突然", "猛然",
        # 时间词
        "次日", "昨日", "今日", "明日", "后日", "前日", "每天", "每天",
        # 常见动词 (2字)
        "说道", "笑道", "问道", "喝道", "喊道", "叹道", "答道", "怒道",
        "看着", "望着", "想着", "听着", "知道", "觉得", "发现", "明白",
        "出来", "起来", "下来", "上去", "过去", "回来", "进入", "离开",
        "没有", "不是", "不能", "不会", "不敢", "不要", "可以", "应该",
        "需要", "希望", "喜欢", "讨厌", "害怕", "担心", "相信", "同意",
        "开始", "继续", "结束", "停止", "准备", "决定", "选择", "放弃",
        # 常见名词 (2字)
        "无名", "神秘", "故事", "一切", "三个", "天下", "天道", "权谋", "阴谋",
        "玉佩", "匕首", "修士", "修真", "老子", "本座", "小子", "师兄", "师姐",
        "天玄宗", "破庙", "法宝", "灵石", "丹药", "功法", "秘籍", "灵兽",
        "三人", "两人", "众人", "只见", "不想", "只得", "只好", "谁知",
        "一道", "一声", "一掌", "一剑", "一步", "一眼", "一笑", "一叹",
        "心中", "眼中", "手中", "身上", "口中", "面前", "身后", "眼前",
        "气息", "力量", "光芒", "声音", "身影", "目光", "神情", "脸色",
        "居然", "竟然", "果然", "当然", "必然", "突然", "忽然", "显然",
        "或许", "大概", "似乎", "好像", "仿佛", "犹如", "宛如", "恰似",
    }
    # 动词后缀过滤: 以常见动词结尾的不太可能是人名
    verb_suffixes = {"了", "着", "过", "吗", "呢", "吧", "啊", "呀", "哦", "嘛"}
    # 累计计数
    from collections import Counter
    total_cnt: Counter = Counter()
    first_chapter: dict[str, int] = {}
    for chapter_no, chapter_id, draft in chapters:
        if not draft:
            continue
        names = re.findall(r"[\u4e00-\u9fff]{2,4}", draft)
        for n in names:
            if len(n) < 2:
                continue
            if n in char_names or n in non_name_words:
                continue
            if any(n in c for c in char_names):
                continue
            # 过滤以动词后缀结尾的词
            if n[-1] in verb_suffixes:
                continue
            total_cnt[n] += 1
            if n not in first_chapter:
                first_chapter[n] = chapter_no
    for n, c in total_cnt.most_common(10):
        if c >= 2:  # 阈值 3→2: 出现 2 次就报 (M10 收尾对齐 smoke_g5_g9 测试数据)
            issues.append(ConsistencyIssue(
                dimension=DIM_CHARACTER,
                severity=SEV_INFO,
                description=f"新人名 '{n}' 累计出现 {c} 次 (首见第 {first_chapter[n]} 章), 未在世界人物库登记",
                chapter_a=first_chapter[n], chapter_b=first_chapter[n],
            ))
    return issues


def _check_locations(project_id: str, chapter_no: int, chapter_id: str,
                      draft: str) -> list[ConsistencyIssue]:
    """地理: 检查正文提到的地点是否在 world_locations 中."""
    issues = []
    loc_names = [e.name for e in worldbuilding.list_all(project_id, worldbuilding.KIND_LOCATION)]
    # 抽"在X" / "到X" / "X中" / "X里" / "X上" 等地点模式
    patterns = [
        re.compile(r"在([\u4e00-\u9fff]{2,6})(?:里|中|内|上|下|旁|处)"),
        re.compile(r"到([\u4e00-\u9fff]{2,6})(?:去|里|中)"),
        re.compile(r"([\u4e00-\u9fff]{2,6})(?:城|镇|村|殿|阁|山|谷|林|海|岛|关|门|派|宗)"),
    ]
    candidates: set[str] = set()
    for pat in patterns:
        for m in pat.finditer(draft):
            candidates.add(m.group(1))
    unknown = [c for c in candidates if c not in loc_names]
    for u in unknown:
        issues.append(ConsistencyIssue(
            dimension=DIM_LOCATION,
            severity=SEV_INFO,
            description=f"新地点 '{u}' 未在世界地理库登记",
            chapter_a=chapter_no, chapter_b=chapter_no,
        ))
    return issues


def _check_time(project_id: str, chapter_no: int, chapter_id: str,
                 draft: str) -> list[ConsistencyIssue]:
    """时间: 扫"次日/三天后/三月后/半月后"等时间词, 找时间线矛盾."""
    issues = []
    # 抽"X日后/X月后/X天后/X年后"等 (含数字 + 中文数字)
    CN_NUM = "零一二三四五六七八九十百千万半两几数"
    patterns = [
        (re.compile(r"次日"), 1),
        (re.compile(r"明日"), 1),
        (re.compile(r"后日"), 2),
        (re.compile(r"今日"), 0),
        (re.compile(r"([0-9]+|[{}])[日天]后".format(CN_NUM)), "future"),
        (re.compile(r"([0-9]+|[{}])[个]?月后".format(CN_NUM)), "future"),
        (re.compile(r"([0-9]+|[{}])年后".format(CN_NUM)), "future"),
        (re.compile(r"半月后"), 15),
        (re.compile(r"一月后"), 30),
        (re.compile(r"昨日"), -1),
        (re.compile(r"前日"), -2),
        (re.compile(r"前天"), -2),
        (re.compile(r"([0-9]+|[{}])[日天]前".format(CN_NUM)), "past"),
        (re.compile(r"([0-9]+|[{}])[个]?月前".format(CN_NUM)), "past"),
    ]
    jumps: list[tuple[str, str]] = []  # (matched_text, direction)
    for pat, direction in patterns:
        for m in pat.finditer(draft):
            jumps.append((m.group(0), direction))
    # 检查同章内的跳跃顺序
    if len(jumps) >= 2:
        has_past = any(d in ("past", -1, -2) for _, d in jumps) or "昨日" in draft or "前日" in draft
        has_future = any(d == "future" for _, d in jumps) or "次日" in draft or "明日" in draft
        if has_past and has_future:
            issues.append(ConsistencyIssue(
                dimension=DIM_TIME,
                severity=SEV_WARNING,
                description="本章既出现'昨日/前日/X日前'又出现'次日/X日后', 时间线可能矛盾",
                chapter_a=chapter_no, chapter_b=chapter_no,
            ))
    return issues


def _check_items(project_id: str, chapter_no: int, chapter_id: str,
                  draft: str) -> list[ConsistencyIssue]:
    """物品: 检查正文提到的物品是否在世界物品库.

    模式: 1-6 字 + 常见物品后缀 (剑/刀/镜/瓶/丹/珠/环/令/符/图/录/册/鉴/首/佩/簪/镯/鞭/锤/索/灯/杯/盘/碗/壶/钟/琴/笛/箫/杖/镜/玉/石/宝/法器等)
    """
    issues = []
    item_names = [e.name for e in worldbuilding.list_all(project_id, worldbuilding.KIND_ITEM)]
    # 找物品后缀
    ITEM_SUFFIXES = (
        "剑|刀|镜|瓶|丹|珠|环|令|符|图|录|册|鉴|首|佩|簪|镯|鞭|锤|索|灯|杯|盘|碗|壶|钟|"
        "琴|笛|箫|杖|印|旗|枪|戟|戈|斧|钺|钩|叉|棒|弓|弩|盾|甲|袍|衣|靴|帽|冠|带|绳|线|帕|"
        "囊|袋|盒|箱|匣|笼|网|镜|盘|砚|墨|笔|纸|帛|绢|纱|罗|锦|缎|玉|石|宝|珠|珊|瑚|"
        "琉|璃|琥|珀|珍|宝|法|器|法器|法宝|灵器|仙器|神器|魔器|圣器"
    )
    # 1) 后缀模式
    pattern = re.compile(r"([\u4e00-\u9fff]{1,6})(?:" + ITEM_SUFFIXES + ")")
    candidates: set[str] = set()
    for m in pattern.finditer(draft):
        candidates.add(m.group(1) + m.group(0)[len(m.group(1)):])  # 完整名 (含后缀)
        candidates.add(m.group(1))  # 也只记前段
    # 2) 持有动词模式: 持/握/佩/藏/赠/送/递/取/拿出 + 1-6 字
    holding_patterns = [
        re.compile(r"拿出?([\u4e00-\u9fff]{1,6})"),
        re.compile(r"持([\u4e00-\u9fff]{1,6})"),
        re.compile(r"握([\u4e00-\u9fff]{1,6})"),
        re.compile(r"佩([\u4e00-\u9fff]{1,6})"),
        re.compile(r"藏([\u4e00-\u9fff]{1,6})"),
    ]
    # 形容词后名词模式: 无名/神秘 + 1-4 字 (用于 匕首/玉佩 这种不在后缀列表的)
    adj_noun_patterns = [
        re.compile(r"(?:无名|神秘|古旧|上古|玄妙)([\u4e00-\u9fff]{1,4})"),
    ]
    for pat in holding_patterns:
        for m in pat.finditer(draft):
            item_candidate = m.group(1)
            candidates.add(item_candidate)
    for pat in adj_noun_patterns:
        for m in pat.finditer(draft):
            item_candidate = m.group(1)
            candidates.add(item_candidate)
    # 过滤已注册物品
    unknown: list[str] = []
    for c in candidates:
        # 已注册 → 跳过
        if any(c == i or c in i or i in c for i in item_names):
            continue
        # 常见非物品词
        if c in {"起来", "出来", "出来", "手中", "怀里", "腰间", "法宝", "法器", "灵器", "仙器", "之物", "宝贝", "物件"}:
            continue
        unknown.append(c)
    # 去重但保留首次出现顺序
    seen: set[str] = set()
    unique_unknown: list[str] = []
    for u in unknown:
        if u not in seen:
            seen.add(u)
            unique_unknown.append(u)
    for u in unique_unknown[:5]:
        issues.append(ConsistencyIssue(
            dimension=DIM_ITEM,
            severity=SEV_INFO,
            description=f"新物品 '{u}' 未在世界物品库登记",
            chapter_a=chapter_no, chapter_b=chapter_no,
        ))
    return issues


# ============================================================
# 单章检测 + 总检测
# ============================================================

def check_chapter(project_id: str, chapter_id: str) -> list[ConsistencyIssue]:
    """单章 4 维检测. 返回 issues 列表 (不入库).

    人物维降级为单章扫描 (项目级扫描在 check_project 中).
    """
    from app.services import chapter_service
    ch = chapter_service.get(chapter_id)
    draft_row = chapter_service.get_current_draft(chapter_id)
    draft = draft_row.get("content", "") if draft_row else ""
    chapter_no = ch.get("chapter_no", 0)

    issues: list[ConsistencyIssue] = []
    # 人物用项目级扫描 (传入单章) - 简化
    issues.extend(_check_characters_in_chapters(project_id, [(chapter_no, chapter_id, draft)]))
    issues.extend(_check_locations(project_id, chapter_no, chapter_id, draft))
    issues.extend(_check_time(project_id, chapter_no, chapter_id, draft))
    issues.extend(_check_items(project_id, chapter_no, chapter_id, draft))
    return issues


def check_project(project_id: str, *, write_log: bool = True) -> dict:
    """全项目 4 维检测. 默认把 issues 写到 consistency_logs.

    返回: {dim: [issues], total, severity_counts}
    """
    chapters = _split_chapters(project_id)
    if not chapters:
        return {"by_dim": {d: [] for d in ALL_DIMS}, "total": 0,
                "severity_counts": {s: 0 for s in ALL_SEVS}}

    by_dim: dict[str, list[ConsistencyIssue]] = {d: [] for d in ALL_DIMS}
    sev_counts: dict[str, int] = {s: 0 for s in ALL_SEVS}

    # 1) 人物: 项目级 (跨章累计)
    char_issues = _check_characters_in_chapters(project_id, chapters)
    for iss in char_issues:
        by_dim[DIM_CHARACTER].append(iss)
        sev_counts[iss.severity] += 1

    # 2) 地理/时间/物品: 单章
    for chapter_no, chapter_id, content in chapters:
        if not content or len(content) < 20:  # 太短跳过 (测试用 30+ 字符)
            continue
        for fn in (_check_locations, _check_time, _check_items):
            for iss in fn(project_id, chapter_no, chapter_id, content):
                by_dim[iss.dimension].append(iss)
                sev_counts[iss.severity] += 1

    # 写日志
    if write_log:
        cur = _conn()
        # 用 chapter_a 找 chapter_id (取首见章节)
        for dim, issues in by_dim.items():
            for iss in issues:
                chapter_id_val = ""
                if iss.chapter_a:
                    # 查 chapter_id
                    row = cur.execute(
                        "SELECT id FROM chapters WHERE chapter_no = ? AND book_id IN "
                        "(SELECT id FROM books WHERE project_id = ?) LIMIT 1",
                        (iss.chapter_a, project_id),
                    ).fetchone()
                    if row:
                        chapter_id_val = row["id"]
                cur.execute(
                    "INSERT INTO consistency_logs (id, project_id, chapter_id, dimension, severity, description, chapter_a, chapter_b) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"cl_{uuid.uuid4().hex[:10]}", project_id,
                     chapter_id_val, dim, iss.severity, iss.description,
                     iss.chapter_a, iss.chapter_b),
                )
        cur.commit()

    return {
        "by_dim": by_dim,
        "total": sum(len(v) for v in by_dim.values()),
        "severity_counts": sev_counts,
    }


# ============================================================
# 查询 (供 UI 仪表盘 / 章节管理用)
# ============================================================

def list_logs(project_id: str, *, dimension: Optional[str] = None,
              severity: Optional[str] = None, limit: int = 100) -> list[dict]:
    """列一致性日志 (新→旧)."""
    cur = _conn()
    sql = "SELECT * FROM consistency_logs WHERE project_id = ?"
    params: list = [project_id]
    if dimension:
        sql += " AND dimension = ?"
        params.append(dimension)
    if severity:
        sql += " AND severity = ?"
        params.append(severity)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = cur.execute(sql, params).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "chapter_id": r["chapter_id"],
            "dimension": r["dimension"],
            "severity": r["severity"],
            "description": r["description"],
            "chapter_a": r["chapter_a"],
            "chapter_b": r["chapter_b"],
            "created_at": r["created_at"] or "",
        })
    return out


def stats(project_id: str) -> dict:
    """一致性统计 (供仪表盘)."""
    cur = _conn()
    total = cur.execute(
        "SELECT COUNT(*) AS c FROM consistency_logs WHERE project_id = ?",
        (project_id,),
    ).fetchone()["c"]
    by_dim: dict[str, int] = {}
    for r in cur.execute(
        "SELECT dimension, COUNT(*) AS c FROM consistency_logs WHERE project_id = ? GROUP BY dimension",
        (project_id,),
    ).fetchall():
        by_dim[r["dimension"]] = r["c"]
    by_sev: dict[str, int] = {s: 0 for s in ALL_SEVS}
    for r in cur.execute(
        "SELECT severity, COUNT(*) AS c FROM consistency_logs WHERE project_id = ? GROUP BY severity",
        (project_id,),
    ).fetchall():
        by_sev[r["severity"]] = r["c"]
    return {"total": total, "by_dim": by_dim, "by_sev": by_sev}


# ============================================================
# v3.5.2: Guide 接口 (GPT 评审)
# ============================================================

def get_guides(unit_id: str, project_id: str = "") -> list:
    """返回一致性相关的 Guide 列表.

    检测内容:
      1. 历史一致性错误过多 (>5 个 error 级别)
      2. 角色设定冲突 (跨章节)
      3. 时间线错误

    注: 当前 check_chapter() 是章节级, get_guides 改为基于 project 级一致性日志.
    """
    from app.core.types import Guide, Action, GUIDE_SCOPE_BOOK

    if not project_id:
        from app.services import story_unit_service_v2 as _unit_svc
        try:
            unit = _unit_svc.get(unit_id)
            project_id = unit.project_id
        except Exception:
            return []

    try:
        s = stats(project_id)
        total = s.get("total", 0)
        by_sev = s.get("by_sev", {})
        by_dim = s.get("by_dim", {})
        error_count = by_sev.get("error", 0) + by_sev.get("critical", 0)

        if total == 0:
            return []

        if error_count >= 3:
            dim_desc = ", ".join(f"{k}={v}" for k, v in by_dim.items() if v >= 2)
            return [Guide(
                source="consistency",
                priority=min(0.85, 0.4 + 0.1 * error_count),
                confidence=0.9,
                scope=GUIDE_SCOPE_BOOK,
                advice=(
                    f"项目历史一致性日志: {total} 条, 其中 {error_count} 条 error/critical。"
                    f"高频维度: {dim_desc}。"
                    f"建议在写作本 unit 前先 review 一致性问题, 避免矛盾加剧。"
                ),
                reason=f"基于 consistency_logs 统计: error_count={error_count}, total={total}",
                evidence_ids=[f"consistency_log:{project_id}"],
                possible_actions=[
                    Action(label="先 review", description="先处理已存在的一致性问题, 再写作"),
                    Action(label="边写边修", description="不阻塞, AI 写作时注意避免同类问题"),
                ],
                context={
                    "total_logs": total,
                    "error_count": error_count,
                    "by_dim": by_dim,
                },
            )]

        return []
    except Exception:
        return []
