"""
Wiki 归一化灌库工具 (M4 / WS4)

把 Obsidian 风 wiki (D:/Users/JiangYing/Desktop/wiki) 归一化灌入分层知识库
(app/knowledge/local/<category>/...) 与单元池 (unit_pool)。

功能:
- 归一化: 清理 [[wikilink]] / #tag / > [!callout] / ![[embed]] / 内嵌 HTML /
  折叠重复 H1; 抽首行标题; 解析已有 frontmatter 的 tags/source。
- 目录→category 映射 + agent/doc_type 启发式 + genre 推断。
- 写出带标准 frontmatter 的 .md 到 local/<category>/。
- --unit-mode: 把正文按标题切段, <1000 字段经 unit_pool_service 入池。
- --dry-run 先出报告; --apply 执行; 末尾 rebuild_index() (KB 向量/BM25 重建)。

用法:
  python tools/ingest_wiki.py --dry-run
  python tools/ingest_wiki.py --apply --limit 50
  python tools/ingest_wiki.py --apply --unit-mode --unit-db /tmp/unit_test.db

注意: 全量 2000+ 文件 apply 会触发 rebuild_index (sentence-transformers 嵌入,
可能较慢/需模型)。建议先 --dry-run 看分布, 再小 --limit 验证, 最后全量。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.knowledge import (
    AGENT_ORCHESTRATION, AGENT_WRITING, AGENT_GENERAL,
    DOC_TEMPLATE, DOC_TECHNIQUE, DOC_DIALOGUE, DOC_REFERENCE,
)

# local KB 根目录
LOCAL_KB = ROOT / "app" / "knowledge" / "local"

# 默认 wiki 路径
DEFAULT_WIKI = Path(r"D:/Users/JiangYing/Desktop/wiki")

# 已知题材集合 (用于从文件名/目录推断 genre)
GENRE_SET = {
    "仙侠", "修仙", "玄幻", "武侠", "历史", "古言", "古代言情", "古装",
    "变身", "同人", "年代", "快穿", "悬疑", "悬疑推理", "无限流", "末世",
    "末世生存", "双男主", "奇幻", "兽世", "其他", "都市", "穿书", "系统",
    "西幻", "科幻", "灵异", "游戏", "洪荒", "权谋",
}

# 跳过处理的顶层目录 (代码/视频等非文本素材)
SKIP_TOP_DIRS = {"scripts", "视频教程"}

# 顶层目录 → (category, agent, doc_type)
DIR_MAP = {
    "框架模板": ("编排范本", AGENT_ORCHESTRATION, DOC_TEMPLATE),
    "文风语料": ("写作范本", AGENT_WRITING, DOC_TEMPLATE),
    "人物人设": ("写作技巧", AGENT_WRITING, DOC_TECHNIQUE),
    "场景描写": ("写作技巧", AGENT_WRITING, DOC_TECHNIQUE),
    "剧情桥段": ("桥段", AGENT_ORCHESTRATION, DOC_TEMPLATE),
    "专属素材": ("写作技巧", AGENT_WRITING, DOC_REFERENCE),
    "外部参考小说分析": ("参考", AGENT_GENERAL, DOC_REFERENCE),
    "external_converted": ("参考", AGENT_GENERAL, DOC_REFERENCE),
}


# ────────────────────── 归一化 ──────────────────────

_WIKILINK = re.compile(r"!?\[\[([^\]]+)\]\]")
_TAG = re.compile(r"#(\S+)")            # 无空格的 #token (Obsidian 标签, 非标题)
_CALLOUT = re.compile(r"^\s*>\s*\[![\w-]+\].*$", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"(?m)^\s*>\s?")
_HTML = re.compile(r"<[^>]+>")
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _parse_frontmatter(raw: str):
    """返回 (frontmatter_dict, body). 兼容正常与压行两种 --- 格式。"""
    # 压行格式: ---tags:[..]source:[..]---# title  (split('---',2) 处理)
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body = parts[2]
        else:
            fm_text, body = "", raw
    else:
        m = _FRONTMATTER.match(raw)
        if m:
            fm_text = m.group(1)
            body = raw[m.end():]
        else:
            fm_text, body = "", raw

    fm = {}
    if fm_text:
        tags_m = re.search(r"tags:\s*\[?(.*?)\]?\s*$", fm_text, re.MULTILINE | re.DOTALL)
        if tags_m:
            fm["tags"] = _split_list(tags_m.group(1))
        src_m = re.search(r"source:\s*\[?(.*?)\]?\s*$", fm_text, re.MULTILINE | re.DOTALL)
        if src_m:
            fm["source"] = _split_list(src_m.group(1))
    return fm, body


def _split_list(s: str) -> list:
    if not s:
        return []
    s = s.strip().strip("[]").strip()
    if not s:
        return []
    return [x.strip().strip("\"'") for x in s.split(",") if x.strip()]


def normalize_body(body: str) -> str:
    """清理 Obsidian / 排版噪音, 返回干净正文。"""
    text = body
    # 清理 ![[embed]] 与 [[wikilink|alias]] / [[wikilink]]
    def _link_sub(m):
        inner = m.group(1)
        # ![[...]] 嵌入 → 删除
        if m.group(0).startswith("!"):
            return ""
        # [[a|b]] → b ; [[a]] → a
        return inner.split("|", 1)[1] if "|" in inner else inner
    text = _WIKILINK.sub(_link_sub, text)
    # callout 标记行删除
    text = _CALLOUT.sub("", text)
    # 去除 blockquote 前缀 (> )
    text = _BLOCKQUOTE.sub("", text)
    # 内嵌 HTML
    text = _HTML.sub("", text)
    # Obsidian 标签 (#token, 非标题) 删除 token 但保留周围文字
    text = _TAG.sub(lambda m: "", text)
    # 折叠多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def derive_title(body: str, fallback: str) -> str:
    """从正文取首行标题 (去掉 # 号), 否则用 fallback。"""
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            return line.lstrip("#").strip() or fallback
        # 第一行非空非标题也接受
        return line[:40]
    return fallback


# ────────────────────── 分类 ──────────────────────

def classify(rel_parts: list[str], stem: str, fm_tags: list):
    """rel_parts: wiki 相对路径分段 (如 ['人物人设','仙侠.md'])。
    返回 (category, agent, doc_type, genre)。"""
    top = rel_parts[0] if rel_parts else ""
    if top in DIR_MAP:
        category, agent, doc_type = DIR_MAP[top]
    else:
        category, agent, doc_type = ("参考", AGENT_GENERAL, DOC_REFERENCE)

    # genre 推断
    genre = "通用"
    if top == "专属素材" and len(rel_parts) >= 2:
        genre = rel_parts[1]  # 专属素材/<genre>/...
    elif stem in GENRE_SET:
        genre = stem
    elif fm_tags and fm_tags[0] in GENRE_SET:
        genre = fm_tags[0]

    return category, agent, doc_type, genre


def safe_name(*parts: str) -> str:
    """拼安全文件名 (去非法字符)。"""
    out = []
    for p in parts:
        p = re.sub(r'[\\/:*?"<>|]', "_", p)
        out.append(p)
    return "_".join(out)[:120]


# ────────────────────── 单文件处理 ──────────────────────

def process_file(path: Path, wiki_root: Path, out_root: Path, stats: dict,
                 unit_items: list):
    rel = path.relative_to(wiki_root)
    rel_parts = list(rel.parts)
    stem = path.stem
    raw = path.read_text(encoding="utf-8", errors="ignore")

    fm, body = _parse_frontmatter(raw)
    body = normalize_body(body)
    if not body.strip():
        stats["skipped_empty"] += 1
        return None

    tags = fm.get("tags", [])
    source = fm.get("source", [])
    category, agent, doc_type, genre = classify(rel_parts, stem, tags)

    title = derive_title(body, stem)
    # 补全 genre 到 tags
    all_tags = list(dict.fromkeys([genre] + tags)) if genre != "通用" else list(tags)

    fm_out = (
        "---\n"
        f"agent: {agent}\n"
        f"doc_type: {doc_type}\n"
        f"category: {category}\n"
        f"genre: {genre}\n"
        f"tags: {json.dumps(all_tags, ensure_ascii=False)}\n"
        f"source: {json.dumps(source, ensure_ascii=False)}\n"
        "---\n\n"
        f"# {title}\n\n"
        f"{body}\n"
    )

    out_name = safe_name(rel_parts[0], stem) + ".md"
    out_path = out_root / category / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)

    stats["by_category"][category] = stats["by_category"].get(category, 0) + 1
    stats["by_agent"][agent] = stats["by_agent"].get(agent, 0) + 1
    stats["files"] += 1

    # unit-mode: 按标题切段, 保留 genre + 小标题
    if unit_items is not None:
        for chunk, sub_title in _split_units(body):
            unit_items.append({"text": chunk, "genre": genre, "title": sub_title})

    return out_path, fm_out


def _split_units(body: str) -> list:
    """按 #/##/### 标题切段, 返回 [(正文, 小标题)] (50~1000 字)。"""
    parts = re.split(r"(?m)^#{1,3}\s+(.+)$", body)
    out = []
    # parts[0] = 首个标题前的序言
    if len(parts) >= 1 and parts[0].strip() and 50 <= len(parts[0].strip()) <= 1000:
        out.append((parts[0].strip(), "片段"))
    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        chunk = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if 50 <= len(chunk) <= 1000:
            out.append((chunk, heading[:20]))
    return out


# ────────────────────── 主流程 ──────────────────────

def iter_wiki_files(wiki_root: Path, include_extra: bool, top_filter: str = ""):
    for path in sorted(wiki_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in (".md", ".txt"):
            continue
        rel_parts = path.relative_to(wiki_root).parts
        top = rel_parts[0] if rel_parts else ""
        if top in SKIP_TOP_DIRS:
            continue
        if top_filter and top != top_filter:
            continue
        yield path


def _setup_unit_db(db_path: Path):
    """为单元池目标库建 schema + 跑迁移 (用于 --unit-db 指向临时/新库)。"""
    import app.app_paths as _ap
    _ap.sqlite_path = lambda: str(db_path)
    from app.db import connection, migrator
    connection.init(db_path)
    conn = connection.get_conn()
    schema_sql = (ROOT / "app" / "db" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    migrator.run_migrations()


def main():
    ap = argparse.ArgumentParser(description="Wiki 归一化灌库 (M4)")
    ap.add_argument("--wiki", default=str(DEFAULT_WIKI), help="wiki 根目录")
    ap.add_argument("--out", default=str(LOCAL_KB), help="输出 KB 根 (默认 app/knowledge/local)")
    ap.add_argument("--dry-run", action="store_true", help="只报告不写入 (默认)")
    ap.add_argument("--apply", action="store_true", help="执行写入")
    ap.add_argument("--unit-mode", action="store_true", help="同时把正文切段入单元池")
    ap.add_argument("--unit-db", default=None, help="单元池目标 DB (默认用 app 默认库)")
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 个文件")
    ap.add_argument("--no-rebuild", action="store_true", help="apply 后不重建 KB 索引")
    ap.add_argument("--include-extra", action="store_true", help="也处理 external_converted/scripts/视频教程")
    ap.add_argument("--top", default="", help="只处理指定顶层目录 (如 人物人设), 便于分目录验证")
    args = ap.parse_args()

    dry_run = not args.apply
    wiki_root = Path(args.wiki)
    out_root = Path(args.out)

    if not wiki_root.exists():
        print(f"[ERROR] wiki 路径不存在: {wiki_root}")
        return 2

    print("=" * 64)
    print("Wiki 归一化灌库 (M4)")
    print("=" * 64)
    print(f"wiki : {wiki_root}")
    print(f"out  : {out_root}")
    print(f"mode : {'DRY-RUN' if dry_run else 'APPLY'}"
          f"{' + unit-mode' if args.unit_mode else ''}")

    stats = {"files": 0, "skipped_empty": 0, "by_category": {}, "by_agent": {}}
    unit_items: list = [] if args.unit_mode else None

    written = 0
    for path in iter_wiki_files(wiki_root, args.include_extra, args.top):
        if args.limit and stats["files"] >= args.limit:
            break
        res = process_file(path, wiki_root, out_root, stats, unit_items)
        if res is None:
            continue
        out_path, fm_out = res
        if not dry_run:
            out_path.write_text(fm_out, encoding="utf-8")
            written += 1

    print(f"\n[统计] 处理文件: {stats['files']}  跳过空: {stats['skipped_empty']}  "
          f"写入: {written}")
    print("[按 category]:")
    for k, v in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print("[按 agent]:")
    for k, v in sorted(stats["by_agent"].items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    if args.unit_mode:
        from collections import Counter
        gcount = Counter(it["genre"] for it in unit_items)
        print(f"[单元池分段]: 共 {len(unit_items)} 段 按 genre: {dict(gcount)}")

    if dry_run:
        print("\n[DRY-RUN] 未写入任何文件。加 --apply 执行。")
        return 0

    # ── 单元池导入 ──
    if args.unit_mode and unit_items:
        print(f"\n[单元池] 导入 {len(unit_items)} 段 (按 genre 分组) ...")
        from app.db import connection, migrator
        from app.services import unit_pool_service as ups
        if args.unit_db:
            # 指向临时/新库: 完整建 schema + 迁移
            _setup_unit_db(Path(args.unit_db))
        else:
            # 默认 app DB: schema 已建, 直接补迁移
            try:
                migrator.run_migrations()
            except Exception as e:
                print(f"  [WARN] run_migrations: {e}")
        # 按 genre 分组批量导入, 保留各自小标题
        by_genre: dict = {}
        for it in unit_items:
            by_genre.setdefault(it["genre"], []).append(it)
        total_created = 0
        for g, items in sorted(by_genre.items()):
            texts = [x["text"] for x in items]
            titles = [x["title"] for x in items]
            created = ups.bulk_import(texts, genre=g, source="wiki", titles=titles)
            total_created += len(created)
        print(f"  单元池新增 {total_created} 条 (当前总量 {ups.count()})")

    # ── KB 索引重建 ──
    if not args.no_rebuild:
        print("\n[索引] rebuild_index() ...")
        try:
            from app.knowledge.finder import rebuild_index
            rebuild_index()
            print("  索引重建完成")
        except Exception as e:
            print(f"  [WARN] rebuild_index 失败: {e}")

    print("\n[完成]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
