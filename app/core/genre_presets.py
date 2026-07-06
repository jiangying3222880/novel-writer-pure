"""
题材预设 (A1 题材 prompt UI).

定义中文网文常用的题材标签, 用于项目创建 / 设定页多选下拉.
也提供给 prompt_assembler 在 writer prompt 中注入题材提示.

数据分层:
  - GENRE_PRESETS     主题材 16 个 (单选, 大分类: 玄幻/都市/仙侠/...)
  - SUBGENRE_PRESETS  副题材 ~50 个 (多选, 元素标签: 脑洞/爽文/穿越/重生/系统/无限流/...)
  - GENRE_WRITING_GUIDES  题材写法指导 (v3.4 新增: AI病句正反例+写法要点+禁忌)

存储:
  - project.genre         主题材 (单个名字, e.g. "玄幻")
  - project.structure.json 里的 sub_genres  副题材 (列表, 用中文顿号分隔)

层归属: L0 core (纯数据 + 纯函数, 无状态, 无 IO, 无依赖, 所有层都能直接 import).
"""
from __future__ import annotations
from typing import List, Tuple, Dict

# 主题材预设: (id, 显示名, 简介, 风格关键词) — 一本书只选 1 个
GENRE_PRESETS: List[Tuple[str, str, str, List[str]]] = [
    ("xuanhuan", "玄幻", "修炼/血脉/异火/斗气等升级体系", ["修炼等级", "热血", "升级流", "打脸"]),
    ("dushi", "都市", "现代都市职场商战日常", ["现实", "情感", "商战", "职场"]),
    ("xianxia", "仙侠", "飞升成仙/长生/道侣", ["道法", "长生", "剑修", "天道"]),
    ("xiuzhen", "修真", "修真/灵气/丹药/法器", ["筑基", "金丹", "法宝", "灵根"]),
    ("lishi", "历史", "穿越/架空/权谋/王朝", ["朝堂", "权谋", "战争", "典故"]),
    ("junshi", "军事", "军旅/抗战/特种兵", ["战术", "热血", "军魂", "训练"]),
    ("kehuan", "科幻", "星际/赛博/未来/机甲", ["未来", "科技", "AI", "太空"]),
    ("youxi", "游戏", "网游/电竞/全息/数据流", ["游戏", "竞技", "队友", "副本"]),
    ("lingyi", "灵异", "捉鬼/降妖/风水/志怪", ["诡异", "阴阳", "驱鬼", "民俗"]),
    ("xuanyi", "悬疑", "推理/破案/烧脑/反转", ["线索", "真相", "多视角", "伏笔"]),
    ("qingxiaoshuo", "轻小说", "日系/吐槽/日常/校园", ["吐槽", "轻快", "日常", "萌"]),
    ("yanqing", "言情", "爱情/虐恋/甜宠/宫斗", ["情感", "恋爱", "甜", "虐"]),
    ("wuxia", "武侠", "江湖/门派/武功/侠义", ["江湖", "门派", "侠客", "武林"]),
    ("qihuan", "奇幻", "西幻/魔法/精灵/王国", ["魔法", "骑士", "王国", "异世界"]),
    ("erciyuan", "二次元", "动漫风格/系统/脑洞", ["吐槽", "系统", "脑洞", "萌"]),
    ("tongren", "同人", "已有IP衍生/角色再创作", ["致敬", "原作", "人物", "世界"]),
]

# 副题材预设 — 一本书可选 0~N 个, 是元素标签/风格标签
# 与主题材 (大分类) 正交: 不含主题材里的流派名 (玄幻/都市/仙侠/... 等)
# 这些是元素/套路/情感/风格层级的标签, 跟主题材组合形成"风格指纹"
_SUBGENRE_RAW: List[str] = [
    # 套路流派 (元素层, 不与主题材里的流派名重复)
    "穿越", "重生", "系统", "无限流", "末日", "洪荒", "神话",
    "西幻", "剑与魔法",
    "星际", "机甲", "赛博朋克", "末世", "废土", "克苏鲁",
    "升级流", "无敌流", "凡人流", "苟道流", "老六流", "签到流",
    "架空", "古风", "民国", "现代", "未来",
    # 情感向
    "甜文", "虐文", "HE", "BE", "高甜", "先婚后爱",
    "破镜重圆", "追妻", "闪婚", "青梅竹马", "契约婚姻", "相亲",
    "年下", "姐弟", "师徒", "豪门", "宅斗", "宫斗",
    "女强", "女频", "男频", "男强", "大女主", "群像",
    # 元素向
    "脑洞", "爽文", "吐槽", "搞笑", "轻松", "热血", "暗黑",
    "复仇", "退婚", "团宠", "马甲", "神医", "读心",
    "穿书", "快穿", "囤货", "空间", "种田", "经营",
    "争霸", "权谋", "谍战", "刑侦",
    "推理", "惊悚", "恐怖", "玄学",
    "美食", "娱乐", "电竞", "体育", "校园", "职场",
    "求生", "逃生", "灾后",
    "抗战",  # 历史/军事 已是主题材, 这里只留交叉度高的子标签
    "萌宝", "养娃", "家庭", "伦理", "现实", "乡土",
]


def _dedup_preserve_order(items: List[str]) -> List[str]:
    """去重, 保序 (Set 会打乱顺序, 副题材用 list 是为了 UI 排版稳定)."""
    seen: set = set()
    out: List[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


SUBGENRE_PRESETS: List[str] = _dedup_preserve_order(_SUBGENRE_RAW)

# 平台预设 (e.g. 起点 / 番茄 / 七猫 / 公众号)
PLATFORM_PRESETS: List[str] = [
    "起点中文网",
    "番茄小说",
    "七猫小说",
    "晋江文学城",
    "纵横中文网",
    "飞卢小说网",
    "刺猬猫",
    "微信公众号",
    "其他",
]


# ────────────────────── 题材写法指导 (v3.4 新增) ──────────────────────

# 5大题材的写法指导: AI病句正反例 + 写法要点 + 禁忌
# 用于 prompt_assembler 注入, 让AI写得更符合题材特色
GENRE_WRITING_GUIDES: Dict[str, Dict] = {
    "玄幻": {
        "ai_sick_sentences": {
            "bad": "他非常强大，实力极其恐怖。",
            "good": "他周身灵气翻涌，筑基期的威压如山岳般沉重。",
            "reason": "玄幻讲究具体等级和画面感，避免泛化的'非常''极其'",
        },
        "writing_tips": [
            "等级体系要具体: 练气/筑基/金丹/元婴，不要只说'很强'",
            "战斗场面要有画面感: 灵气颜色、法宝光芒、招式名称",
            "升级节奏要快: 3-5章一个小境界，10-15章一个大境界",
            "打脸要爽快: 反派嘲讽→主角爆发→围观震惊，三段式",
        ],
        "taboos": [
            "不要写主角犹豫不决超过2章",
            "不要写无意义的日常超过3章",
            "不要让反派活过5章还不死",
            "不要写主角主动退让、圣母心",
        ],
    },
    "都市": {
        "ai_sick_sentences": {
            "bad": "他十分优秀，能力特别强。",
            "good": "他三句话拿下千万订单，会议室里没人敢对视。",
            "reason": "都市讲究具体场景和数据，避免空洞的形容词",
        },
        "writing_tips": [
            "场景要真实: 办公室、咖啡厅、高档小区，要有代入感",
            "对话要接地气: 少用书面语，多用口语、网络用语",
            "节奏要紧凑: 每章都要有冲突或反转",
            "情感线要细腻: 暧昧期要拉长，不要太快确定关系",
        ],
        "taboos": [
            "不要写主角一开始就无敌",
            "不要写无脑倒贴的女主",
            "不要写主角靠运气成功",
            "不要写脱离现实的夸张情节",
        ],
    },
    "仙侠": {
        "ai_sick_sentences": {
            "bad": "他的剑法非常厉害，令人震惊。",
            "good": "一剑斩出，九天雷动，方圆百里化为焦土。",
            "reason": "仙侠讲究意境和画面感，要有仙气和道韵",
        },
        "writing_tips": [
            "要有仙气: 道法自然、天人合一的意境",
            "战斗要有意境: 不是单纯的招式对轰，要有道的理解",
            "修炼要有感悟: 突破不只是灵力积累，更是对道的领悟",
            "人物要有风骨: 修仙者要有超脱世俗的气质",
        ],
        "taboos": [
            "不要写成低配玄幻，失去仙侠特色",
            "不要写太多世俗争斗，要有超脱感",
            "不要写主角贪财好色，要有修道之心",
            "不要写无脑升级，要有对道的思考",
        ],
    },
    "悬疑": {
        "ai_sick_sentences": {
            "bad": "这个案件非常复杂，让人想不通。",
            "good": "死者左手戴着婚戒，右手却有新茧，妻子说他已经三年没工作。",
            "reason": "悬疑讲究细节和逻辑，要用具体线索推动推理",
        },
        "writing_tips": [
            "伏笔要早埋: 第1章的细节要在第10章回收",
            "线索要分散: 不要把所有证据堆在一起",
            "推理要有逻辑: 每个结论都要有证据支撑",
            "反转要合理: 不要为反转而反转，要有铺垫",
        ],
        "taboos": [
            "不要写主角开挂，靠直觉破案",
            "不要写线索突然出现，没有铺垫",
            "不要写反派智商下线",
            "不要写结局烂尾，伏笔不回收",
        ],
    },
    "言情": {
        "ai_sick_sentences": {
            "bad": "他非常帅气，她十分美丽，两人很相爱。",
            "good": "他低头看她，眼底有化不开的温柔，她心跳漏了一拍。",
            "reason": "言情讲究情感细腻和互动细节，避免空洞的描述",
        },
        "writing_tips": [
            "情感要细腻: 心理描写要到位，让读者共情",
            "互动要甜: 眼神、动作、对话都要有CP感",
            "节奏要慢: 暧昧期要拉长，不要急着确定关系",
            "冲突要虐: 误会、分离、重逢，要有情感起伏",
        ],
        "taboos": [
            "不要写无脑甜，没有冲突",
            "不要写男主油腻，女主傻白甜",
            "不要写太快确定关系，没有暧昧期",
            "不要写狗血误会，沟通能解决的事拖10章",
        ],
    },
}


def list_genres() -> List[dict]:
    """返回所有题材预设 (id, name, desc, keywords) 列表. 供 UI 下拉使用."""
    return [
        {"id": gid, "name": name, "desc": desc, "keywords": keywords}
        for gid, name, desc, keywords in GENRE_PRESETS
    ]


def list_genre_names() -> List[str]:
    """返回题材名称列表 (顺序与预设一致). 供 UI 简单多选用."""
    return [name for _gid, name, _desc, _kw in GENRE_PRESETS]


def list_platforms() -> List[str]:
    """返回平台预设名列表."""
    return list(PLATFORM_PRESETS)


def parse_genre_string(genre: str | None) -> List[str]:
    """解析 project.genre 字符串. 支持逗号 / 中文顿号 分隔. 返回去重后的题材名列表."""
    if not genre:
        return []
    # 兼容中英文逗号、顿号
    s = genre.replace("、", ",").replace("，", ",")
    parts = [p.strip() for p in s.split(",") if p.strip()]
    # 去重保序
    seen: set = set()
    out: List[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def serialize_genres(genres: List[str]) -> str:
    """题材列表 -> 字符串. 用中文顿号分隔, 避免与字段内文本混淆."""
    cleaned = [g.strip() for g in genres if g and g.strip()]
    return "、".join(cleaned)


def genre_to_keywords(genre_str: str | None) -> List[str]:
    """由 genre 字符串反查所有匹配预设的 keywords 集合, 供 prompt_assembler 注入."""
    if not genre_str:
        return []
    selected = set(parse_genre_string(genre_str))
    keywords: List[str] = []
    seen: set = set()
    for _gid, name, _desc, kw in GENRE_PRESETS:
        if name in selected:
            for k in kw:
                if k not in seen:
                    seen.add(k)
                    keywords.append(k)
    return keywords


def list_subgenre_names() -> List[str]:
    """副题材显示名列表 (顺序与预设一致). 供 UI 多选用."""
    return list(SUBGENRE_PRESETS)


def parse_subgenre_string(s: str | None) -> List[str]:
    """解析副题材字符串. 支持逗号 / 中文顿号 分隔. 返回去重后的副题材名列表."""
    if not s:
        return []
    norm = s.replace("、", ",").replace("，", ",").replace(" ", ",")
    parts = [p.strip() for p in norm.split(",") if p.strip()]
    # 过滤掉不在 SUBGENRE_PRESETS 里的 (防止历史脏数据)
    valid: List[str] = []
    seen: set = set()
    valid_set = set(SUBGENRE_PRESETS)
    for p in parts:
        if p in valid_set and p not in seen:
            seen.add(p)
            valid.append(p)
    return valid


def serialize_subgenres(items: List[str] | None) -> str:
    """副题材列表 -> 字符串. 用中文顿号分隔 (与题材一致风格)."""
    if not items:
        return ""
    cleaned = [g.strip() for g in items if g and g.strip()]
    return "、".join(cleaned)


def genre_id_to_name(gid: str | None) -> str | None:
    """题材 id -> 显示名. 找不到返回 None."""
    if not gid:
        return None
    for _g, name, _d, _kw in GENRE_PRESETS:
        if _g == gid:
            return name
    return None


def genre_name_to_id(name: str | None) -> str | None:
    """题材显示名 -> id. 找不到返回 None."""
    if not name:
        return None
    for _g, n, _d, _kw in GENRE_PRESETS:
        if n == name:
            return _g
    return None
