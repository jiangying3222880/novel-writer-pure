"""
项目级 Import / Export 服务 (M3 补完 Phase 2.2 占位).

设计:
  - 导出整个项目 (含 books / chapters / chapter_briefs / agent_memory /
    scene_subtext_cards / world_state_snapshots) 到单个 *.novel.zip 压缩包.
  - zip 内部是 1 个 project.json 文件 (payload) + README.txt (含导出元信息).
  - 同时也打包 项目目录下的所有 JSON (characters.json / worldbuilding.json /
    memory.json / anti_rules.json / etc.) from file_store.
  - 导入时, 自动检测扩展名:
      *.novel.zip / *.zip  → 读 zip 里的 project.json
      *.nwp.json / *.json  → 直接读 (兼容老导出文件)
    创建新 project (新 uuid), 重建关联表, 把老 id 映射到新 id, 恢复 JSON 文件.

注意:
  - 不导出 usage_records (用量统计不该随项目搬迁).
  - 不导出 license/auth 等全局数据.

公开 API:
  - export_project(project_id, output_path) -> Path
  - import_project(input_path) -> str  (返回新 project_id)
  - list_exportable_keys(project_id) -> list[str]  (UI 调试用)
"""
from __future__ import annotations
import json
import logging
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.db import _impl as _db_conn
from app.services import project_service
from app.services.file_store import (
    _get_project_dir,
    SPLITTABLE_KEYS,
)

log = logging.getLogger(__name__)

# 导出文件魔数 + schema 版本 (给将来 schema 兼容用)
EXPORT_MAGIC = "NWP_JSON_V1"
EXPORT_VERSION = 1

# 项目目录里要一并打包的 JSON 文件 (按 file_store 惯例命名)
_PROJECT_JSON_KEYS = [
    "characters",
    "worldbuilding",
    "memory",
    "anti_rules",
    "outline",
    "framework",
    "prompts",
    "feedback",
    "facts",
    "timepoints",
    "evidence_chain",
    "factions",
    "graph_cache",
    "scene_drafts",
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ===================================================================== #
# 1. 导出
# ===================================================================== #

def export_project(project_id: str, output_path: Path) -> Path:
    """把项目导出到 output_path (*.novel.zip).

    V4.0-P2 改: 之前导出为裸的 *.nwp.json, 现在改为 *.novel.zip 压缩包,
    内部含 1 个 project.json (payload) + README.txt (元信息).

    Returns:
        实际写入路径 (output_path 可能是用户选的目录, 我们会自动加文件名).
    """
    project = project_service.get(project_id)  # NotFoundError if missing

    output_path = Path(output_path)
    if output_path.is_dir() or output_path.suffix == "":
        # 选了目录 → 用项目名 + 时间戳 自动命名
        safe_name = "".join(
            c for c in (project.get("name") or "project")
            if c.isalnum() or c in (" ", "_", "-")
        ).strip().replace(" ", "_") or "project"
        output_path = output_path / f"{safe_name}_{_now()[:10]}.novel.zip"
    else:
        # 用户给了文件名, 但后缀不是 .zip → 自动补
        if not output_path.suffix.lower() == ".zip":
            output_path = output_path.with_suffix(".novel.zip")

    payload: dict[str, Any] = {
        "_magic": EXPORT_MAGIC,
        "_version": EXPORT_VERSION,
        "_exported_at": _now(),
        "_app": "Novel Writer Pure v4",
        "project": project,
        "books": [],
        "chapters": [],
        "chapter_briefs": [],
        "agent_memory": [],
        "scene_subtext_cards": [],
        "world_state_snapshots": [],
        "project_files": {},  # JSON 键 -> 内容
    }

    with _db_conn.connection() as db:
        # 1) books
        rows = db.execute(
            "SELECT * FROM books WHERE project_id = ?", (project_id,)
        ).fetchall()
        payload["books"] = [dict(r) for r in rows]
        book_ids = [r["id"] for r in rows]

        # 2) chapters + 关联子表
        if book_ids:
            placeholders = ",".join("?" for _ in book_ids)
            rows = db.execute(
                f"SELECT * FROM chapters WHERE book_id IN ({placeholders})",
                book_ids,
            ).fetchall()
            payload["chapters"] = [dict(r) for r in rows]
            chapter_ids = [r["id"] for r in rows]

            if chapter_ids:
                placeholders = ",".join("?" for _ in chapter_ids)
                rows = db.execute(
                    f"SELECT * FROM chapter_briefs WHERE chapter_id IN ({placeholders})",
                    chapter_ids,
                ).fetchall()
                payload["chapter_briefs"] = [dict(r) for r in rows]

                rows = db.execute(
                    f"SELECT * FROM agent_memory WHERE chapter_id IN ({placeholders})",
                    chapter_ids,
                ).fetchall()
                payload["agent_memory"] = [dict(r) for r in rows]

                rows = db.execute(
                    f"SELECT * FROM scene_subtext_cards WHERE chapter_id IN ({placeholders})",
                    chapter_ids,
                ).fetchall()
                payload["scene_subtext_cards"] = [dict(r) for r in rows]

        # 3) world_state_snapshots (按 project_id 走)
        rows = db.execute(
            "SELECT * FROM world_state_snapshots WHERE project_id = ?", (project_id,)
        ).fetchall()
        payload["world_state_snapshots"] = [dict(r) for r in rows]

    # 4) 项目目录下的 JSON 文件
    project_dir = _get_project_dir(project_id)
    for key in _PROJECT_JSON_KEYS:
        # file 模式
        f = project_dir / f"{key}.json"
        if f.exists():
            try:
                payload["project_files"][key] = json.loads(f.read_text(encoding="utf-8"))
                continue
            except Exception as e:
                log.warning(f"[export] 读 {key}.json 失败: {e}")
        # 目录 (large-project) 模式
        d = project_dir / key
        if d.is_dir():
            files: dict[str, Any] = {}
            for sub in d.rglob("*.json"):
                rel = str(sub.relative_to(d))
                try:
                    files[rel] = json.loads(sub.read_text(encoding="utf-8"))
                except Exception as e:
                    log.warning(f"[export] 读 {d.name}/{rel} 失败: {e}")
            if files:
                payload["project_files"][key] = {"__dir_mode__": True, "files": files}

    # 5) 写入 zip
    output_path.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    readme_text = (
        f"Novel Writer Pure v4 - Project Export\n"
        f"----------------------------------------\n"
        f"Exported at : {payload['_exported_at']}\n"
        f"Schema      : {EXPORT_MAGIC} (v{EXPORT_VERSION})\n"
        f"Project     : {project.get('name')!r} (id={project_id[:8]}...)\n"
        f"Books       : {len(payload['books'])}\n"
        f"Chapters    : {len(payload['chapters'])}\n"
        f"Memory      : {len(payload['agent_memory'])}\n"
        f"Subtext     : {len(payload['scene_subtext_cards'])}\n"
        f"----------------------------------------\n"
        f"Re-import via: Novel Writer Pure v4 → 项目管理 → 导入项目\n"
    )
    # ZIP_DEFLATED 压缩; ZIP_STORED 更快但更大. JSON 文本压缩收益大, 用 DEFLATED.
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json_text)
        zf.writestr("README.txt", readme_text)
    log.info(f"[export_project] {project_id} -> {output_path} ({output_path.stat().st_size} bytes)")
    return output_path


# ===================================================================== #
# 1.5 共享: 读取 payload (zip 或 json)
# ===================================================================== #

def _load_payload(input_path: Path) -> dict[str, Any]:
    """从 zip 或 json 读出 payload dict.

    V4.0-P2 新: 新导出文件是 *.novel.zip, 老导出文件是 *.nwp.json.
    导入时自动按扩展名 + 文件内容识别.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(str(input_path))

    suffix = input_path.suffix.lower()
    if suffix == ".zip" or input_path.name.lower().endswith(".novel.zip"):
        # 新格式: zip 压缩包
        try:
            with zipfile.ZipFile(input_path, "r") as zf:
                # 优先读 project.json, 兼容其它约定 (nwp.json / data.json)
                candidate_names = ["project.json", "nwp.json", "data.json", "payload.json"]
                member_name: Optional[str] = None
                for name in candidate_names:
                    if name in zf.namelist():
                        member_name = name
                        break
                if not member_name:
                    # 没找到约定的, 找 zip 里第 1 个 .json
                    for name in zf.namelist():
                        if name.lower().endswith(".json"):
                            member_name = name
                            break
                if not member_name:
                    raise ValueError("zip 压缩包内找不到 project.json")
                with zf.open(member_name) as f:
                    payload = json.loads(f.read().decode("utf-8"))
        except zipfile.BadZipFile as e:
            raise ValueError(f"不是有效的 zip 文件: {e}") from e
    else:
        # 老格式: 裸 JSON
        try:
            payload = json.loads(input_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"导出文件 JSON 解析失败: {e}") from e

    if payload.get("_magic") != EXPORT_MAGIC:
        raise ValueError(f"不是有效的 Novel Writer 导出文件 (magic={payload.get('_magic')!r})")
    if payload.get("_version", 0) > EXPORT_VERSION:
        raise ValueError(
            f"导出文件版本过新 (v{payload['_version']}), 当前仅支持 v{EXPORT_VERSION} 及以下"
        )
    return payload


# ===================================================================== #
# 2. 导入
# ===================================================================== #

def import_project(input_path: Path) -> str:
    """从 *.novel.zip 或老式 *.nwp.json 恢复项目, 返回新 project_id.

    V4.0-P2 改: 用 _load_payload 自动适配 zip / json 两种格式.

    行为:
      - 创建新 project (新 uuid, 保留 name/book_title/genre/platform/word_target).
      - 重建 books / chapters (新 uuid, 维护老 id -> 新 id 映射).
      - 用新 id 重建 chapter_briefs / agent_memory / scene_subtext_cards / world_state_snapshots.
      - 恢复项目目录下的 JSON 文件 (characters / worldbuilding / ...).
    """
    payload = _load_payload(input_path)

    src_project = payload.get("project") or {}
    # 1) 创建新 project
    new_pid = project_service.create(
        name=src_project.get("name") or "Imported Project",
        book_title=src_project.get("book_title"),
        genre=src_project.get("genre"),
        platform=src_project.get("platform"),
        word_target=int(src_project.get("word_target") or 200000),
        # V4.0-P2 修复: import 路径不预先创建 book, 而是下面从 payload 重建.
        # 之前默认 create_books=True 会自动创建 1 个 book, 跟下面的 for 循环重复.
        create_books=False,
    )["id"]

    # 2) 维护老 book_id -> 新 book_id 映射
    book_id_map: dict[str, str] = {}
    chapter_id_map: dict[str, str] = {}
    for b in payload.get("books", []):
        new_bid = str(uuid.uuid4())
        book_id_map[b["id"]] = new_bid
        with _db_conn.transaction() as db:
            db.execute(
                """INSERT INTO books
                   (id, project_id, volume_no, title, synopsis, target_chapters, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_bid, new_pid,
                    b.get("volume_no") or 1,
                    b.get("title"),
                    b.get("synopsis"),
                    b.get("target_chapters") or 100,
                    b.get("created_at") or _now(),
                ),
            )

    # 3) chapters
    for c in payload.get("chapters", []):
        new_cid = str(uuid.uuid4())
        chapter_id_map[c["id"]] = new_cid
        new_bid = book_id_map.get(c["book_id"])
        if not new_bid:
            log.warning(f"[import] chapter {c['id']} 找不到对应 book, 跳过")
            continue
        with _db_conn.transaction() as db:
            db.execute(
                """INSERT INTO chapters
                   (id, book_id, chapter_no, status, title, scene_context,
                    draft, final, critique, checkpoint, word_count,
                    review_flag, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_cid, new_bid,
                    c.get("chapter_no") or 1,
                    c.get("status") or "draft",
                    c.get("title"),
                    c.get("scene_context"),
                    c.get("draft"),
                    c.get("final"),
                    c.get("critique"),
                    c.get("checkpoint"),
                    c.get("word_count") or 0,
                    c.get("review_flag") or "pending",
                    c.get("created_at") or _now(),
                    c.get("updated_at") or _now(),
                ),
            )

    # 4) chapter_briefs
    for row in payload.get("chapter_briefs", []):
        new_cid = chapter_id_map.get(row.get("chapter_id"))
        if not new_cid:
            continue
        with _db_conn.transaction() as db:
            db.execute(
                """INSERT INTO chapter_briefs
                   (id, chapter_id, brief, core_events, emotion_arc, volume_no, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), new_cid,
                    row.get("brief"),
                    row.get("core_events"),
                    row.get("emotion_arc"),
                    row.get("volume_no"),
                    row.get("created_at") or _now(),
                ),
            )

    # 5) agent_memory
    for row in payload.get("agent_memory", []):
        new_cid = chapter_id_map.get(row.get("chapter_id"))
        if not new_cid:
            continue
        with _db_conn.transaction() as db:
            db.execute(
                """INSERT INTO agent_memory
                   (id, chapter_id, tier, entity_type, entity_name, content,
                    token_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), new_cid,
                    row.get("tier"),
                    row.get("entity_type"),
                    row.get("entity_name"),
                    row.get("content") or "",
                    row.get("token_count") or 0,
                    row.get("created_at") or _now(),
                    row.get("updated_at") or _now(),
                ),
            )

    # 6) scene_subtext_cards
    for row in payload.get("scene_subtext_cards", []):
        new_cid = chapter_id_map.get(row.get("chapter_id"))
        if not new_cid:
            continue
        with _db_conn.transaction() as db:
            db.execute(
                """INSERT INTO scene_subtext_cards
                   (id, chapter_id, surface_event, true_intent, lie, truth,
                    physical_anchor, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), new_cid,
                    row.get("surface_event"),
                    row.get("true_intent"),
                    row.get("lie"),
                    row.get("truth"),
                    row.get("physical_anchor"),
                    row.get("created_at") or _now(),
                ),
            )

    # 7) world_state_snapshots (用新 project_id)
    for row in payload.get("world_state_snapshots", []):
        with _db_conn.transaction() as db:
            db.execute(
                """INSERT OR REPLACE INTO world_state_snapshots
                   (id, project_id, chapter_no, entity_name, entity_kind,
                    state_value, changes_delta, source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), new_pid,
                    row.get("chapter_no"),
                    row.get("entity_name"),
                    row.get("entity_kind"),
                    row.get("state_value"),
                    row.get("changes_delta"),
                    row.get("source") or "imported",
                    row.get("created_at") or _now(),
                ),
            )

    # 8) 恢复项目目录下的 JSON 文件
    project_dir = _get_project_dir(new_pid)
    for key, data in (payload.get("project_files") or {}).items():
        try:
            if isinstance(data, dict) and data.get("__dir_mode__"):
                # 目录模式
                d = project_dir / key
                d.mkdir(parents=True, exist_ok=True)
                for rel, content in (data.get("files") or {}).items():
                    fp = d / rel
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.write_text(
                        json.dumps(content, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            else:
                fp = project_dir / f"{key}.json"
                fp.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except Exception as e:
            log.warning(f"[import] 恢复 {key} 失败: {e}")

    log.info(f"[import_project] {input_path} -> {new_pid}")
    return new_pid


# ===================================================================== #
# 3. 调试辅助
# ===================================================================== #

def list_exportable_keys(project_id: str) -> list[str]:
    """列出该项目下 file_store 里所有可导出的 JSON key (UI 调试用)."""
    project_dir = _get_project_dir(project_id)
    found: list[str] = []
    for key in _PROJECT_JSON_KEYS:
        if (project_dir / f"{key}.json").exists() or (project_dir / key).is_dir():
            found.append(key)
    return found
