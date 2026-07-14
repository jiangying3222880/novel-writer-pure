"""
设定/大纲导入导出服务 (V4.0-P4-新)

解决: 用户反馈「小说设定页缺导入按钮」 — 之前只能手填 JSON, 不方便.
现在支持:
  1) 导入设定 (setting_service.set_setting 的 key):
     - 支持 key: worldbuilding / characters / anti_rules / style_fingerprint
                  / plot_outline / chapter_outline / volume_outline / ...
     - 文件格式: .json (整个就是 setting data) / .md (按 ## 章节切分)
  2) 导入大纲 (chapter_service 大纲 / outline):
     - 文件格式: .json (chapter list) / .md (按 ## 第N章 切分)

用法:
    from app.services import setting_io
    setting_io.import_setting(project_id, "worldbuilding", "/path/to/file.md")
    setting_io.import_outlines(project_id, "/path/to/chapters.json")
"""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# 设定 key 白名单 (写 setting_service)
SETTING_KEYS = {
    "worldbuilding",
    "characters",
    "hooks",
    "anti_rules",
    "style_fingerprint",
    "plot_outline",
    "chapter_outline",
    "volume_outline",
    "foreshadowing",
    "voice_profiles",
    "notes",
    "creation_conversation",
}


def _read_file_text(path: Path) -> str:
    """读文件文本, 失败抛 RuntimeError."""
    if not path.exists():
        raise RuntimeError(f"文件不存在: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # 兜底: GBK
        return path.read_text(encoding="gbk", errors="ignore")


def _parse_md_sections(text: str) -> list[tuple[str, str]]:
    """把 Markdown 按 ##/### 切分成 (title, body) 列表.

    例:
        # 大纲
        ## 第 1 章
        内容1
        ## 第 2 章
        内容2
    → [("大纲", ""), ("第 1 章", "内容1"), ("第 2 章", "内容2")]
    """
    # 规范化换行符
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    out: list[tuple[str, str]] = []
    cur_title: Optional[str] = None
    cur_body: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            if cur_title is not None:
                out.append((cur_title, "\n".join(cur_body).strip()))
            cur_title = m.group(2).strip()
            cur_body = []
        else:
            if cur_title is not None:
                cur_body.append(line)
    if cur_title is not None:
        out.append((cur_title, "\n".join(cur_body).strip()))
    return out


def _cn_num_to_int(cn_str: str) -> int:
    """中文数字转阿拉伯数字.
    
    支持: 零一二三四五六七八九十百千万
    例如: "二十一" → 21, "一百二十三" → 123, "十二" → 12, "一百零一" → 101
    """
    cn_map = {"零":0, "一":1, "二":2, "三":3, "四":4, "五":5, 
              "六":6, "七":7, "八":8, "九":9}
    unit_map = {"十":10, "百":100, "千":1000, "万":10000}
    
    total = 0
    current = 0
    
    for ch in cn_str:
        if ch in cn_map:
            current = cn_map[ch]
        elif ch in unit_map:
            unit = unit_map[ch]
            if current == 0 and unit == 10:
                # 处理"十二"这种情况(十前面没有数字，默认为1)
                current = 1
            if current == 0 and ch == "零":
                # 零作为占位符，不改变 current
                continue
            total += current * unit
            current = 0
        elif ch == "零":
            # 零作为占位符
            continue
    
    # 加上最后的个位数
    total += current
    
    return total if total > 0 else 1


def _parse_character_block(name: str, body: str) -> dict:
    """从角色描述块中提取结构化字段.

    支持的格式:
      - 键值对行: 「身份: 主角」「性别: 男」「身份：主角」
      - 列表项: 「- 身份：主角」
      - 其余文本作为 description
    """
    identity = ""
    gender = ""
    desc_lines: list[str] = []

    key_patterns = {
        "identity": ["身份", "角色身份", "定位", "身份定位"],
        "gender": ["性别"],
        "name": ["姓名", "名字"],
    }

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            desc_lines.append("")
            continue
        matched = False
        clean_line = line.lstrip("-*•").strip()
        for field, keys in key_patterns.items():
            for k in keys:
                for sep in [":", "：", "=", "＝"]:
                    prefix = f"{k}{sep}"
                    if clean_line.startswith(prefix):
                        val = clean_line[len(prefix):].strip()
                        if field == "identity":
                            identity = val
                        elif field == "gender":
                            gender = val
                        elif field == "name" and val:
                            name = val
                        matched = True
                        break
                if matched:
                    break
            if matched:
                break
        if not matched:
            desc_lines.append(line)

    description = "\n".join(desc_lines).strip()

    char = {
        "name": name,
        "identity": identity,
        "gender": gender,
        "description": description,
    }
    return char


def _md_text_to_setting_data(text: str, key: str) -> Any:
    """把 Markdown 转成 setting_service 期待的 data 格式.

    - worldbuilding / plot_outline 等长文: 返回 str (整段文本)
    - characters: 尝试按 ## 姓名 切分, 返回 list[{name, desc}]
    - anti_rules: 返回 list[str] (每行一条, 空行/标题过滤)
    """
    sections = _parse_md_sections(text)
    if key in ("worldbuilding", "plot_outline", "style_fingerprint",
               "voice_profiles", "foreshadowing", "notes", "volume_outline"):
        # 整体作为单段文本返回
        if not sections:
            return text.strip()
        # 取第一个 #/## 后的整文 (去掉最外层 H1 标题)
        if len(sections) == 1:
            return sections[0][1] or text
        # 多段: 拼接
        parts = []
        for t, b in sections:
            if b:
                parts.append(f"## {t}\n\n{b}")
        return "\n\n".join(parts) if parts else text
    if key == "characters":
        out_chars: list[dict] = []
        for t, b in sections:
            if not b or len(b.strip()) < 10:
                continue
            char = _parse_character_block(t, b)
            out_chars.append(char)
        return out_chars
    if key == "anti_rules":
        # 每行一条规则
        rules: list[str] = []
        for t, b in sections:
            for ln in b.splitlines():
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    rules.append(ln)
        return rules
    return text


def import_setting(project_id: str, key: str, file_path: str | Path) -> dict:
    """导入设定 → setting_service.set_setting.

    Args:
        project_id: 目标项目 id
        key: 设定 key (必须在 SETTING_KEYS 中)
        file_path: 用户选的 .md / .json 文件

    Returns:
        {"key": ..., "size_chars": N, "format": "md" | "json"}

    Raises:
        ValueError: key 不在白名单
        RuntimeError: 读文件失败
    """
    if key not in SETTING_KEYS:
        raise ValueError(f"key {key!r} 不在白名单; 允许: {sorted(SETTING_KEYS)}")
    p = Path(file_path)
    if not p.exists():
        raise RuntimeError(f"文件不存在: {p}")
    if p.suffix.lower() == ".json":
        # JSON: 直接 parse
        try:
            data = json.loads(_read_file_text(p))
        except Exception as e:
            raise RuntimeError(f"JSON 解析失败: {e}") from e
    else:
        # MD / 其他: 当文本
        text = _read_file_text(p)
        data = _md_text_to_setting_data(text, key)
    # 写 setting_service
    from app.services.setting_service import set_setting
    set_setting(project_id, key, data)
    # 估算字符数 (用于返回)
    if isinstance(data, str):
        size = len(data)
    elif isinstance(data, list):
        size = sum(len(json.dumps(x, ensure_ascii=False)) for x in data)
    else:
        size = len(json.dumps(data, ensure_ascii=False))
    return {"key": key, "size_chars": size, "format": p.suffix.lower().lstrip(".") or "md"}


def import_outlines(project_id: str, file_path: str | Path,
                   create_missing: bool = True) -> dict:
    """导入大纲 (按章节分).

    文件格式:
      - JSON: list[{"chapter_no": int, "title": str, "outline": str}]
              或 {chapters: [...]}
              或 {volumes: [{volume_no, title, chapters: [...]}]}
      - MD:   ## 第 N 卷 / ### 第 N 章 标题 \\n 描述

    Args:
        project_id: 项目ID
        file_path: 大纲文件路径
        create_missing: 是否自动创建缺失的分卷和章节 (默认 True)

    Returns:
        导入结果统计
    """
    p = Path(file_path)
    if not p.exists():
        raise RuntimeError(f"文件不存在: {p}")
    text = _read_file_text(p)

    volumes: list[dict] = []  # [{volume_no, title, chapters: [{chapter_no, title, outline}]}]

    if p.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except Exception as e:
            raise RuntimeError(f"JSON 解析失败: {e}") from e

        if isinstance(data, dict) and "volumes" in data:
            volumes = []
            for idx, v in enumerate(data["volumes"]):
                vol_no = v.get("volume_no") or idx + 1
                vol_title = v.get("title", "")
                chapters = v.get("chapters", [])
                vol_chapters = []
                for c in chapters:
                    vol_chapters.append({
                        "chapter_no": c.get("chapter_no"),
                        "title": c.get("title", ""),
                        "outline": c.get("outline") or c.get("desc") or "",
                    })
                volumes.append({
                    "volume_no": vol_no,
                    "title": vol_title,
                    "chapters": vol_chapters,
                })
        elif isinstance(data, dict) and "chapters" in data:
            chapters_list = list(data["chapters"])
            volumes = [{
                "volume_no": 1,
                "title": "第一卷",
                "chapters": [
                    {
                        "chapter_no": c.get("chapter_no"),
                        "title": c.get("title", ""),
                        "outline": c.get("outline") or c.get("desc") or "",
                    }
                    for c in chapters_list
                ],
            }]
        elif isinstance(data, list):
            volumes = [{
                "volume_no": 1,
                "title": "第一卷",
                "chapters": [
                    {
                        "chapter_no": c.get("chapter_no"),
                        "title": c.get("title", ""),
                        "outline": c.get("outline") or c.get("desc") or "",
                    }
                    for c in data
                ],
            }]
        else:
            raise RuntimeError("JSON 格式不正确")
    else:
        sections = _parse_md_sections(text)
        current_vol_no = 1
        current_vol_title = "第一卷"
        current_chapters: list[dict] = []
        volumes = []

        vol_pattern = re.compile(
            r"第\s*(\d+|[一二三四五六七八九十百千万零]+)\s*卷[\s、:：\-—\.]*(.*)"
        )
        chap_pattern = re.compile(
            r"第\s*(\d+|[一二三四五六七八九十百千万零]+)\s*(?:章|节|话)[\s、:：\-—\.]*(.*)"
        )

        def _parse_num(num_str: str) -> int:
            if num_str.isdigit():
                return int(num_str)
            n = _cn_num_to_int(num_str)
            return n if n > 0 else 0

        chap_counter = 0
        for title, body in sections:
            vol_m = vol_pattern.match(title)
            chap_m = chap_pattern.match(title)

            if vol_m:
                if current_chapters:
                    volumes.append({
                        "volume_no": current_vol_no,
                        "title": current_vol_title,
                        "chapters": current_chapters,
                    })
                num_str = vol_m.group(1)
                vol_no = _parse_num(num_str)
                if vol_no == 0:
                    vol_no = len(volumes) + 1
                current_vol_no = vol_no
                current_vol_title = vol_m.group(2).strip() or title
                current_chapters = []
                chap_counter = 0
            elif chap_m:
                num_str = chap_m.group(1)
                chap_no = _parse_num(num_str)
                if chap_no == 0:
                    chap_counter += 1
                    chap_no = chap_counter
                chap_title = chap_m.group(2).strip() or title
                current_chapters.append({
                    "chapter_no": chap_no,
                    "title": chap_title,
                    "outline": body,
                })
            else:
                if current_chapters:
                    current_chapters[-1]["outline"] += "\n" + body
                    current_chapters[-1]["outline"] = current_chapters[-1]["outline"].strip()

        if current_chapters:
            volumes.append({
                "volume_no": current_vol_no,
                "title": current_vol_title,
                "chapters": current_chapters,
            })

    if not volumes:
        return {"imported": 0, "format": p.suffix.lower().lstrip(".")}

    from app.services import book_service, chapter_service, outline_service

    total_imported = 0
    created_volumes = 0
    created_chapters = 0

    try:
        existing_books = book_service.list_for_project(project_id).get("books", [])
        book_index: dict[int, str] = {}  # volume_no → book_id
        for b in existing_books:
            book_index[int(b.get("volume_no") or 0)] = b.get("id")

        for vol in volumes:
            vol_no = int(vol.get("volume_no") or 0)
            vol_title = vol.get("title", "")
            vol_chapters = vol.get("chapters", [])

            if not vol_chapters:
                continue

            book_id = book_index.get(vol_no)
            if not book_id:
                if create_missing:
                    new_book = book_service.create(
                        project_id=project_id,
                        volume_no=vol_no,
                        title=vol_title,
                    )
                    book_id = new_book["id"]
                    book_index[vol_no] = book_id
                    created_volumes += 1
                else:
                    continue

            chap_index: dict[int, str] = {}
            existing_chaps = chapter_service.list_for_book(book_id).get("chapters", [])
            for c in existing_chaps:
                chap_index[int(c.get("chapter_no") or 0)] = c.get("id")

            for ch in vol_chapters:
                chap_no = int(ch.get("chapter_no") or 0)
                chap_title = ch.get("title", "")
                outline_text = (ch.get("outline") or "").strip()

                if chap_no <= 0:
                    continue

                chapter_id = chap_index.get(chap_no)
                if not chapter_id:
                    if create_missing:
                        new_chap = chapter_service.create(
                            book_id=book_id,
                            chapter_no=chap_no,
                            title=chap_title,
                        )
                        chapter_id = new_chap["id"]
                        chap_index[chap_no] = chapter_id
                        created_chapters += 1
                    else:
                        continue

                if outline_text:
                    try:
                        outline_service.save_outline(
                            chapter_id, "A", outline=outline_text
                        )
                    except Exception as e:
                        log.warning("save outline for chapter %s failed: %s", chapter_id, e)

                total_imported += 1

    except Exception as e:
        log.error("import_outlines failed: %s", e)
        raise

    return {
        "imported": total_imported,
        "created_volumes": created_volumes,
        "created_chapters": created_chapters,
        "format": p.suffix.lower().lstrip(".") or "md",
    }


def list_importable_keys() -> list[str]:
    return sorted(SETTING_KEYS)


# --------------------------------------------------------------------- #
# V4.0-P4-新: 自动识别导入文件属于哪个 key
# --------------------------------------------------------------------- #

# 识别提示词: 文件名 / H1 标题里出现这些词 → 命中对应 key
_FILENAME_HINTS: dict[str, list[str]] = {
    "characters":       ["角色", "人物", "character", "char"],
    "worldbuilding":    ["世界观", "世界", "world", "世界观设定", "设定"],
    "anti_rules":       ["反规则", "禁忌", "规则", "rule", "anti"],
    "style_fingerprint":["风格", "文风", "style", "fingerprint", "语气"],
    "plot_outline":     ["大纲", "主线", "总纲", "outline", "plot"],
    "chapter_outline":  ["章节大纲", "章纲", "chapter_outline"],
    "volume_outline":   ["分卷", "卷纲", "卷大纲", "volume"],
    "foreshadowing":    ["伏笔", "foreshadow", "hook", "悬念"],
    "voice_profiles":   ["声音", "声纹", "voice", "口吻", "语调"],
    "notes":            ["笔记", "备注", "note", "memo"],
}

# JSON 结构提示: 顶层 keys 出现这些 → 命中对应 key
_JSON_KEY_HINTS: dict[str, list[str]] = {
    "characters":    ["characters", "roles", "人物", "角色", "cast"],
    "worldbuilding": ["worldbuilding", "world", "世界观", "设定", "locations"],
    "anti_rules":    ["anti_rules", "rules", "规则", "禁忌", "taboos"],
    "style_fingerprint": ["style", "fingerprint", "风格", "文风"],
    "plot_outline":  ["plot", "outline", "大纲", "主线"],
    "chapter_outline": ["chapters", "chapter_outline", "章纲"],
    "volume_outline":  ["volumes", "volume_outline", "卷"],
    "foreshadowing": ["foreshadowing", "hooks", "伏笔", "悬念"],
    "voice_profiles": ["voice_profiles", "voice", "voices", "声音", "声纹"],
}


def _extract_frontmatter(text: str) -> tuple[dict, str]:
    """提取 Markdown 文件开头的 YAML frontmatter.

    返回: (frontmatter_dict, body_text)
    如果没有 frontmatter, 返回 ({}, text)
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if not text.startswith('---\n'):
        return {}, text
    # 找第二个 ---
    end_idx = text.find('\n---\n', 4)
    if end_idx == -1:
        return {}, text
    fm_text = text[4:end_idx]
    body = text[end_idx + 5:]
    # 简单解析 YAML (只解析顶层 key, 不依赖 pyyaml)
    fm: dict[str, str] = {}
    current_key = None
    for line in fm_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        # key: value 格式
        if ':' in stripped and not stripped.startswith('-') and not stripped.startswith(' '):
            parts = stripped.split(':', 1)
            key = parts[0].strip()
            val = parts[1].strip().strip('"').strip("'")
            fm[key] = val
            current_key = key
    return fm, body


def detect_setting_key(path: str | Path, *, peek_chars: int = 4000) -> dict:
    """自动识别导入文件属于哪个设定 key.

    V4.0-P4-新: 用户反馈「导入设定时为什么不是自动分析」, 之前要手动从
    QInputDialog 里选 key, 现在加了内容嗅探:
      1) 文件名 hint  (如 「角色.md」 → characters)
      2) JSON 顶层 keys  (如 `{"characters": [...]}` → characters)
      3) MD 标题层级  (如 `## 第 N 章` → chapter_outline, `## 姓名` → characters)
      4) 行结构 hint  (如 短行 → anti_rules, 大段叙事 → worldbuilding)
      5) 兜底: 第一个 SETTING_KEYS (alphabetical)

    Args:
        path: 文件路径
        peek_chars: 嗅探最多读多少字符 (避免大文件卡顿)

    Returns:
        {"key": str, "confidence": float (0-1), "reasons": list[str],
         "alternatives": list[(key, score)]}
    """
    p = Path(path)
    if not p.exists():
        return {"key": "worldbuilding", "confidence": 0.0,
                "reasons": [f"文件不存在: {p}"], "alternatives": []}

    # 1) 文件名 hint (按 hint 长度降序, 长的更具体, 优先命中)
    name = p.stem.lower()
    name_scores: dict[str, float] = {}
    name_reasons: list[str] = []
    # 收集所有 (key, hint) 候选, 按 hint 长度降序
    candidates: list[tuple[str, str, int]] = []
    for k, hints in _FILENAME_HINTS.items():
        for h in hints:
            candidates.append((k, h, len(h)))
    candidates.sort(key=lambda x: -x[2])  # 长 hint 先
    matched_keys: set[str] = set()
    for k, h, hl in candidates:
        if k in matched_keys:
            continue
        if h.lower() in name:
            name_scores[k] = name_scores.get(k, 0) + 0.45
            name_reasons.append(f"文件名含「{h}」→ {k}")
            matched_keys.add(k)

    # 2) 读前几行
    try:
        text = _read_file_text(p)
    except Exception as e:
        return {"key": "worldbuilding", "confidence": 0.0,
                "reasons": [f"读文件失败: {e}"], "alternatives": []}
    text_peek = text[:peek_chars]

    # 2.5) YAML frontmatter 检测 (inkos / obsidian 风格)
    fm_scores: dict[str, float] = {}
    fm_reasons: list[str] = []
    fm, body_after_fm = _extract_frontmatter(text_peek)
    if fm:
        fm_keys_lower = {k.lower(): v for k, v in fm.items()}
        # protagonist + personalityLock + behavioralConstraints → plot_outline / worldbuilding
        if "protagonist" in fm_keys_lower or "主角" in fm_keys_lower:
            fm_scores["plot_outline"] = fm_scores.get("plot_outline", 0) + 0.4
            fm_reasons.append("frontmatter 含 protagonist → plot_outline")
        if "genreLock" in fm or "genre_lock" in fm_keys_lower or "类型" in fm_keys_lower:
            fm_scores["worldbuilding"] = fm_scores.get("worldbuilding", 0) + 0.3
            fm_reasons.append("frontmatter 含 genreLock → worldbuilding")
        if "prohibitions" in fm_keys_lower or "禁忌" in fm_keys_lower or "禁止" in fm_keys_lower:
            fm_scores["anti_rules"] = fm_scores.get("anti_rules", 0) + 0.35
            fm_reasons.append("frontmatter 含 prohibitions → anti_rules")
        if "style_guide" in fm_keys_lower or "文风" in fm_keys_lower or "风格" in fm_keys_lower:
            fm_scores["style_fingerprint"] = fm_scores.get("style_fingerprint", 0) + 0.4
            fm_reasons.append("frontmatter 含 style → style_fingerprint")
        # 如果 frontmatter 里有角色字段
        if "characters" in fm_keys_lower or "角色" in fm_keys_lower or "cast" in fm_keys_lower:
            fm_scores["characters"] = fm_scores.get("characters", 0) + 0.3
            fm_reasons.append("frontmatter 含 characters → characters")
        # 有 frontmatter 且内容多 → 更可能是 plot_outline / worldbuilding
        if len(fm) >= 5:
            fm_scores["plot_outline"] = fm_scores.get("plot_outline", 0) + 0.2
            fm_reasons.append(f"frontmatter 有 {len(fm)} 个字段 → plot_outline")

    # 3) JSON 解析
    json_scores: dict[str, float] = {}
    json_reasons: list[str] = []
    if p.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except Exception:
            data = None
        if data is not None:
            # 顶层 key 命中
            if isinstance(data, dict):
                top_keys = list(data.keys())
                for tk in top_keys:
                    tkl = tk.lower()
                    for k, hints in _JSON_KEY_HINTS.items():
                        if any(h.lower() in tkl for h in hints):
                            json_scores[k] = json_scores.get(k, 0) + 0.5
                            json_reasons.append(f"JSON 顶层 key「{tk}」→ {k}")
                # 嵌套 dict 里有 list (常见 characters 模式)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, list) and v and isinstance(v[0], dict):
                            if "name" in v[0] and ("desc" in v[0] or "description" in v[0] or "role" in v[0]):
                                json_scores["characters"] = json_scores.get("characters", 0) + 0.4
                                json_reasons.append("list[dict] 元素含 name+desc → characters")
            elif isinstance(data, list):
                if data and isinstance(data[0], dict):
                    keys0 = set(data[0].keys())
                    if "name" in keys0 and ("desc" in keys0 or "description" in keys0):
                        json_scores["characters"] = json_scores.get("characters", 0) + 0.6
                        json_reasons.append("list[dict] 顶层结构 → characters")
                    elif "rule" in keys0 or "text" in keys0:
                        json_scores["anti_rules"] = json_scores.get("anti_rules", 0) + 0.4
                        json_reasons.append("list[dict] 含 rule/text → anti_rules")
                elif data and isinstance(data[0], str):
                    # list[str] → 反规则 (每行一条)
                    json_scores["anti_rules"] = json_scores.get("anti_rules", 0) + 0.5
                    json_reasons.append("list[str] 顶层 → anti_rules")

    # 4) MD 标题 hint
    md_scores: dict[str, float] = {}
    md_reasons: list[str] = []
    sections = _parse_md_sections(text_peek) if text_peek.strip() else []
    if sections:
        titles = [t for t, _ in sections]
        # 「第 N 章」出现多次 → chapter_outline; 「第 N 卷」 → volume_outline
        # 支持阿拉伯数字和中文数字
        chap_re = re.compile(r"第\s*(\d+|[一二三四五六七八九十百千万零]+)\s*章")
        vol_re = re.compile(r"第\s*(\d+|[一二三四五六七八九十百千万零]+)\s*卷")
        chap_n = sum(1 for t in titles if chap_re.search(t))
        vol_n = sum(1 for t in titles if vol_re.search(t))
        if chap_n >= 2:
            md_scores["chapter_outline"] = md_scores.get("chapter_outline", 0) + 0.55
            md_reasons.append(f"{chap_n} 个「第 N 章」标题 → chapter_outline")
        if vol_n >= 1:
            md_scores["volume_outline"] = md_scores.get("volume_outline", 0) + 0.45
            md_reasons.append(f"{vol_n} 个「第 N 卷」标题 → volume_outline")
        # H1 大纲 / 总纲
        h1 = titles[0] if titles else ""
        for k, hints in _FILENAME_HINTS.items():
            if k in md_scores:
                continue
            for h in hints:
                if h.lower() in h1.lower():
                    md_scores[k] = md_scores.get(k, 0) + 0.35
                    md_reasons.append(f"H1 标题「{h1}」含「{h}」→ {k}")
                    break
        # 多段都是姓名 + 短描述 → characters
        if not (chap_n or vol_n):
            short_bodies = [(t, b) for t, b in sections if b and len(b) < 200]
            if len(short_bodies) >= 2 and all(len(t) <= 20 for t, _ in short_bodies):
                md_scores["characters"] = md_scores.get("characters", 0) + 0.4
                md_reasons.append(f"{len(short_bodies)} 段短描述 (疑似角色) → characters")
            elif len(sections) == 1 and len(sections[0][1]) > 500:
                # 单段长文 → worldbuilding
                md_scores["worldbuilding"] = md_scores.get("worldbuilding", 0) + 0.25
                md_reasons.append("单段长文 → worldbuilding")
            elif len(sections) > 4:
                # 多段且不命中其它 → plot_outline
                md_scores["plot_outline"] = md_scores.get("plot_outline", 0) + 0.25
                md_reasons.append("多段结构 → plot_outline")

    # 5) 汇总 (各路分数相加, 上限 1.0)
    all_keys = set(SETTING_KEYS)
    final: dict[str, float] = {}
    reasons: list[str] = []
    for src_scores, src_reasons in (
        (name_scores, name_reasons),
        (fm_scores, fm_reasons),
        (json_scores, json_reasons),
        (md_scores, md_reasons),
    ):
        for k, v in src_scores.items():
            if k in all_keys:
                final[k] = min(1.0, final.get(k, 0) + v)
        reasons.extend(src_reasons)

    # 排序
    sorted_keys = sorted(final.items(), key=lambda x: -x[1])
    if sorted_keys:
        best_key, best_score = sorted_keys[0]
    else:
        best_key, best_score = "worldbuilding", 0.0
        reasons.append("未命中任何 hint, 兜底用 worldbuilding")

    return {
        "key": best_key,
        "confidence": round(best_score, 2),
        "reasons": reasons,
        "alternatives": [(k, round(v, 2)) for k, v in sorted_keys[1:4]],
    }
