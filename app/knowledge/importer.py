"""
C1 知识导入 (txt + md → local)
- 文件上传 (.txt / .md) → 自动写到 local/{category}/
- 文本粘贴 → 同上
- 可选 AI 补全 (category / genre / tags / summary)
- 写规范 frontmatter (与 builtin 风格一致)
- 支持批量 + 进度回调
- 写完后 BM25/向量索引失效, 调用方需 rebuild

依赖: app.knowledge (读/解析), app.ai.engine (AI 分类)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from app.knowledge import (
    LOCAL_DIR,
    PRESET_CATEGORIES,
    SOURCE_LOCAL,
    get_category_dir,
    # 内部 helper, 复用解析逻辑
    _parse_frontmatter,  # type: ignore
    _read_text,  # type: ignore
)

_logger = logging.getLogger("NovelWriter.knowledge.importer")

# ────────────────────── 常量 ──────────────────────

MAX_FILE_BYTES = 1 * 1024 * 1024    # 1 MB (单文件上限, 防误传小说整本)
MAX_CONTENT_CHARS = 200_000         # 20 万字 (内存里保这么多, 超了截断)
AI_PREVIEW_CHARS = 1500             # 喂 AI 的预览长度
MIN_CONTENT_FOR_AI = 30             # 内容过短时跳过 AI
DEFAULT_GENRE = "通用"

VALID_CATEGORIES = set(PRESET_CATEGORIES)
VALID_EXTENSIONS = {".txt", ".md"}

# 题材白名单 (AI 给建议时约束, 防瞎给)
GENRE_WHITELIST = (
    "仙侠", "古言", "都市", "悬疑", "科幻",
    "玄幻", "武侠", "历史", "军事", "游戏",
    "体育", "校园", "灵异", "同人", "通用",
)


# ────────────────────── 数据类 ──────────────────────

@dataclass
class ImportSuggestion:
    """AI 给的分类建议 (或用户手动指定)。"""
    category: str = "文风语料"
    genre: str = DEFAULT_GENRE
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0          # 0-1, AI 自评

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImportResult:
    """导入结果。"""
    success: bool = False
    path: Optional[Path] = None
    error: str = ""
    category: str = ""                 # 最终写入的 category (来自 suggestion 或 fallback)
    genre: str = ""                    # 最终写入的 genre
    suggestion: Optional[ImportSuggestion] = None
    content_chars: int = 0
    ai_used: bool = False
    renamed: bool = False             # True = 同名文件已存在, 加 _2/_3 后缀
    skipped: bool = False             # True = 文件已存在, 跳过
    reason: str = ""                  # skipped/失败原因

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "path": str(self.path) if self.path else None,
            "error": self.error,
            "category": self.category,
            "genre": self.genre,
            "skipped": self.skipped,
            "reason": self.reason,
            "suggestion": self.suggestion.to_dict() if self.suggestion else None,
            "content_chars": self.content_chars,
            "ai_used": self.ai_used,
            "renamed": self.renamed,
        }


# ────────────────────── 工具函数 ──────────────────────

_VALID_NAME_RE = re.compile(r"[^\w\u4e00-\u9fff\-]+", re.UNICODE)


def _sanitize_name(name: str, max_len: int = 60) -> str:
    """
    清洗文件名, 移除非法字符。
    - 保留中英文/数字/下划线/连字符
    - 折叠连续下划线
    - 截断到 max_len
    """
    if not name:
        return f"import_{uuid.uuid4().hex[:6]}"
    name = name.strip()
    name = _VALID_NAME_RE.sub("_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        return f"import_{uuid.uuid4().hex[:6]}"
    return name[:max_len]


def _build_filename(genre: str, stem: str) -> str:
    """
    生成文件名: {genre}_{stem}.md
    样例: 仙侠_文风参考.md
    """
    g = _sanitize_name(genre or DEFAULT_GENRE, max_len=20)
    s = _sanitize_name(stem, max_len=40)
    return f"{g}_{s}.md"


def _unique_path(category_dir: Path, filename: str) -> tuple[Path, bool]:
    """
    若目标文件已存在, 在后缀加 _2 / _3 ... 直到不冲突。
    返回 (path, renamed)。
    """
    target = category_dir / filename
    if not target.exists():
        return target, False
    stem = target.stem
    suffix = target.suffix
    n = 2
    while True:
        cand = category_dir / f"{stem}_{n}{suffix}"
        if not cand.exists():
            return cand, True
        n += 1
        if n > 999:
            raise RuntimeError(f"找可用文件名失败 (>999 重名): {filename}")


def _validate_category(cat: str) -> str:
    """校验分类, 不合法抛 ValueError。"""
    if cat not in VALID_CATEGORIES:
        raise ValueError(f"未知分类: {cat!r} (合法: {sorted(VALID_CATEGORIES)})")
    return cat


def _build_frontmatter(meta: dict) -> str:
    """
    构造 frontmatter (与 builtin 风格一致)。
    - genre: string
    - tags: list (空时不写)
    - source: import
    - imported_at: ISO
    """
    lines = ["---"]
    for k, v in meta.items():
        if k == "tags" and isinstance(v, list):
            if not v:
                continue
            tags_str = ", ".join(str(t).strip() for t in v if t)
            lines.append(f"tags: [{tags_str}]")
        elif v is None or v == "":
            continue
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")  # 空行分隔
    return "\n".join(lines)


def _make_meta_dict(suggestion: ImportSuggestion) -> dict:
    """根据 suggestion 构造写入用的 meta。"""
    return {
        "genre": suggestion.genre or DEFAULT_GENRE,
        "tags": suggestion.tags or [],
        "source": "import",
        "imported_at": datetime.now().isoformat(timespec="seconds"),
    }


# ────────────────────── AI 分类 ──────────────────────

_CATEGORY_DESC = {
    "文风语料": "参考写作风格/语感/句式的素材 (含示例段落)",
    "桥段":     "常见套路/情节模板/故事弧",
    "人物人设": "人物模板/性格/背景设定",
    "场景描写": "场景模板/环境描写/氛围",
    "框架模板": "故事结构/叙事框架/世界观架构",
}


def _build_ai_prompt(content_preview: str) -> list[dict]:
    """构造分类用的 prompt。"""
    cat_options = "\n".join(f"- {k}: {v}" for k, v in _CATEGORY_DESC.items())
    genre_options = "、".join(GENRE_WHITELIST)
    system = (
        "你是小说写作辅助, 负责给一段素材做分类打标。\n"
        "严格按 JSON 输出, 不要任何额外文字或解释。\n\n"
        f"## 5 个分类 (category 必选其一):\n{cat_options}\n\n"
        f"## 题材 (genre 从下述选一个, 不确定用'{DEFAULT_GENRE}'):\n{genre_options}\n\n"
        "## 输出字段:\n"
        "- category: 上述 5 选 1\n"
        "- genre: 上述题材列表选 1\n"
        "- tags: 2-5 个关键词, 数组\n"
        "- summary: 1-2 句中文描述内容, 50 字内\n"
        "- confidence: 0-1 浮点, 你对分类的确信度\n"
    )
    user = f"素材内容 (前 {len(content_preview)} 字):\n\n{content_preview}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _parse_ai_response(text: str) -> ImportSuggestion:
    """解析 AI 返回, 失败返回默认。"""
    from app.ai.utils import safe_parse_json
    data = safe_parse_json(text, default={})
    if not isinstance(data, dict):
        data = {}
    cat = str(data.get("category", "文风语料")).strip()
    if cat not in VALID_CATEGORIES:
        cat = "文风语料"
    genre = str(data.get("genre", DEFAULT_GENRE)).strip() or DEFAULT_GENRE
    if genre not in GENRE_WHITELIST:
        genre = DEFAULT_GENRE
    tags_raw = data.get("tags", [])
    if isinstance(tags_raw, str):
        tags_raw = [t.strip() for t in re.split(r"[,，、\s]+", tags_raw) if t.strip()]
    elif not isinstance(tags_raw, list):
        tags_raw = []
    tags = [str(t).strip() for t in tags_raw if str(t).strip()][:8]
    summary = str(data.get("summary", "")).strip()[:200]
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))
    return ImportSuggestion(
        category=cat, genre=genre, tags=tags,
        summary=summary, confidence=confidence,
    )


def ai_classify(
    content: str,
    *,
    content_preview_chars: int = AI_PREVIEW_CHARS,
) -> ImportSuggestion:
    """
    调 AI 给一段素材分类 (category/genre/tags/summary)。
    - 只用前 content_preview_chars 字喂 AI (省 token)
    - 内容过短 (< MIN_CONTENT_FOR_AI) 直接返回默认
    - AI 失败返回默认
    """
    if not content or len(content.strip()) < MIN_CONTENT_FOR_AI:
        return ImportSuggestion()
    preview = content.strip()[:content_preview_chars]
    try:
        from app.ai.engine import get_engine
        engine = get_engine()
        messages = _build_ai_prompt(preview)
        result = engine.chat(
            messages,
            task="knowledge_classify",
            temperature=0.2,    # 分类要稳
            max_tokens=400,
            use_fallback=True,
        )
        return _parse_ai_response(result.content)
    except Exception as e:
        _logger.warning("AI 分类失败, 用默认: %s", e)
        return ImportSuggestion()


# ────────────────────── 核心入口 ──────────────────────

def _read_source(path: Path) -> str:
    """读源文件, 容错编码。"""
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(
            f"文件过大: {path.stat().st_size} bytes (上限 {MAX_FILE_BYTES})"
        )
    return _read_text(path)


def _resolve_suggestion(
    content: str,
    *,
    category: Optional[str],
    genre: Optional[str],
    tags: Optional[list[str]],
    summary: Optional[str],
    use_ai: bool,
) -> tuple[ImportSuggestion, bool]:
    """
    决定最终 suggestion 和 ai_used。
    - 用户提供的字段优先
    - use_ai=True 且有缺失字段, 调 AI 补全
    - 都不提供 → 全默认
    """
    has_user = any([category, genre, tags, summary])
    suggestion = ImportSuggestion(
        category=category or "文风语料",
        genre=genre or DEFAULT_GENRE,
        tags=list(tags) if tags else [],
        summary=summary or "",
    )
    ai_used = False

    if not has_user and not use_ai:
        return suggestion, False
    if not use_ai:
        # 用户已提供, 不用 AI
        return suggestion, False

    # 调 AI 补缺失
    ai_sug = ai_classify(content)
    ai_used = True
    if not category:
        suggestion.category = ai_sug.category
    if not genre:
        suggestion.genre = ai_sug.genre
    if not tags:
        suggestion.tags = ai_sug.tags
    if not summary:
        suggestion.summary = ai_sug.summary
    return suggestion, ai_used


def import_file(
    path: str | Path,
    *,
    category: Optional[str] = None,
    genre: Optional[str] = None,
    tags: Optional[list[str]] = None,
    summary: Optional[str] = None,
    use_ai: bool = True,
    overwrite: bool = False,
) -> ImportResult:
    """
    主入口: 导入一个文件 (.txt / .md) → local/{category}/。
    - 必传: path
    - 可选: category / genre / tags / summary (覆盖 AI 建议)
    - use_ai=True 时对未提供字段调 AI 补全
    - overwrite=False 时若目标已存在, 加后缀 (_2 / _3 ...)

    返回 ImportResult (含写入路径 / AI 是否调用 / 内容字数)
    """
    src = Path(path)
    if src.suffix.lower() not in VALID_EXTENSIONS:
        return ImportResult(
            success=False,
            error=f"不支持的文件类型: {src.suffix} (支持: {sorted(VALID_EXTENSIONS)})",
        )

    try:
        content = _read_source(src)
    except (FileNotFoundError, ValueError, OSError) as e:
        return ImportResult(success=False, error=f"读文件失败: {e}")

    # 截断
    content = content[:MAX_CONTENT_CHARS]

    # 解析已有 frontmatter (若 .md 且有)
    existing_meta, content_no_fm = _parse_frontmatter(content)
    body = content_no_fm.strip() or content.strip()
    if not body:
        return ImportResult(success=False, error="文件内容为空")

    suggestion, ai_used = _resolve_suggestion(
        body, category=category, genre=genre, tags=tags, summary=summary, use_ai=use_ai,
    )

    # 若原文件有 frontmatter 且用户没传, 沿用原值 (仅 genre/tags)
    if not genre and existing_meta.get("genre"):
        suggestion.genre = str(existing_meta["genre"])
    if not tags and existing_meta.get("tags"):
        old_tags = existing_meta["tags"]
        if isinstance(old_tags, list):
            suggestion.tags = [str(t) for t in old_tags]

    # 校验分类
    try:
        _validate_category(suggestion.category)
    except ValueError as e:
        return ImportResult(success=False, error=str(e), suggestion=suggestion)

    # 写文件
    cat_dir = get_category_dir(suggestion.category, SOURCE_LOCAL)
    cat_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    filename = _build_filename(suggestion.genre, stem)
    if overwrite:
        target = cat_dir / filename
        renamed = False
    else:
        target, renamed = _unique_path(cat_dir, filename)

    meta = _make_meta_dict(suggestion)
    fm = _build_frontmatter(meta)
    final = f"{fm}\n{body.strip()}\n"
    target.write_text(final, encoding="utf-8")

    _logger.info(
        "导入成功: %s → %s (AI=%s, %d 字, renamed=%s)",
        src.name, target.name, ai_used, len(body), renamed,
    )
    return ImportResult(
        success=True, path=target, category=suggestion.category, genre=suggestion.genre,
        suggestion=suggestion,
        content_chars=len(body), ai_used=ai_used, renamed=renamed,
    )


def import_text(
    content: str,
    name: str,
    *,
    category: Optional[str] = None,
    genre: Optional[str] = None,
    tags: Optional[list[str]] = None,
    summary: Optional[str] = None,
    use_ai: bool = True,
    overwrite: bool = False,
) -> ImportResult:
    """
    主入口: 导入一段文本 (粘贴/拖入场景)。
    - content: 文本内容
    - name: 文件名 (不含扩展名), 会被 sanitize
    - 其他参数同 import_file
    """
    if not content or not content.strip():
        return ImportResult(success=False, error="内容为空")

    body = content[:MAX_CONTENT_CHARS].strip()
    stem = _sanitize_name(name or "pasted")

    suggestion, ai_used = _resolve_suggestion(
        body, category=category, genre=genre, tags=tags, summary=summary, use_ai=use_ai,
    )
    try:
        _validate_category(suggestion.category)
    except ValueError as e:
        return ImportResult(success=False, error=str(e), suggestion=suggestion)

    cat_dir = get_category_dir(suggestion.category, SOURCE_LOCAL)
    cat_dir.mkdir(parents=True, exist_ok=True)
    filename = _build_filename(suggestion.genre, stem)
    if overwrite:
        target = cat_dir / filename
        renamed = False
    else:
        target, renamed = _unique_path(cat_dir, filename)

    meta = _make_meta_dict(suggestion)
    fm = _build_frontmatter(meta)
    final = f"{fm}\n{body}\n"
    target.write_text(final, encoding="utf-8")

    _logger.info(
        "文本导入成功: %s → %s (AI=%s, %d 字, renamed=%s)",
        name, target.name, ai_used, len(body), renamed,
    )
    return ImportResult(
        success=True, path=target, suggestion=suggestion,
        content_chars=len(body), ai_used=ai_used, renamed=renamed,
    )


def batch_import(
    paths: list[Path],
    *,
    use_ai: bool = True,
    on_progress: Optional[Callable[[int, int, ImportResult], None]] = None,
) -> list[ImportResult]:
    """
    批量导入。
    - on_progress(i, total, result): 进度回调 (1-based i)
    """
    results: list[ImportResult] = []
    total = len(paths)
    for i, p in enumerate(paths, 1):
        r = import_file(p, use_ai=use_ai)
        results.append(r)
        if on_progress:
            try:
                on_progress(i, total, r)
            except Exception as e:
                _logger.warning("on_progress 回调失败: %s", e)
    return results


def delete_local_doc(path: str | Path) -> bool:
    """
    删除 local/ 下的一个文件。
    - 必须在 LOCAL_DIR 下 (防误删 builtin)
    - 删除后 BM25/向量索引失效, 调用方需 rebuild
    """
    p = Path(path).resolve()
    local_root = LOCAL_DIR.resolve()
    try:
        p.relative_to(local_root)
    except ValueError:
        raise ValueError(f"不在 local/ 目录下, 拒绝删除: {p}")
    if not p.exists():
        return False
    p.unlink()
    _logger.info("已删除 local doc: %s", p)
    return True


def list_local(category: Optional[str] = None) -> list[Path]:
    """
    列出 local/ 下的所有文件 (或某分类下)。
    - 包含 README.md (UI 可展示)
    """
    if category:
        d = LOCAL_DIR / category
        if not d.exists():
            return []
        return sorted(d.glob("*.md"))
    out: list[Path] = []
    for cat in PRESET_CATEGORIES:
        out.extend(list_local(cat))
    return out


# ────────────────────── 便捷入口 (UI 端调用) ──────────────────────

def suggest_only(content: str) -> ImportSuggestion:
    """
    只调 AI 给建议, 不写文件。
    UI 场景: 用户上传 → 后端给建议 → UI 展示 + 用户编辑 → 确认后调 import_file/import_text。
    """
    return ai_classify(content)


# 导出
__all__ = [
    "ImportSuggestion",
    "ImportResult",
    "ai_classify",
    "suggest_only",
    "import_file",
    "import_text",
    "batch_import",
    "delete_local_doc",
    "list_local",
    "MAX_FILE_BYTES",
    "MAX_CONTENT_CHARS",
    "AI_PREVIEW_CHARS",
    "MIN_CONTENT_FOR_AI",
    "DEFAULT_GENRE",
    "GENRE_WHITELIST",
    "VALID_CATEGORIES",
    "VALID_EXTENSIONS",
]
