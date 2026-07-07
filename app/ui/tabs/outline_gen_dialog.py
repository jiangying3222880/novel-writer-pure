"""
H1 AI 大纲生成 UI (章节生成 tab 旁边 / 弹窗).

提供 3 版本 A/B/C 大纲的可视化对比 + 一键选定 + 导出到 chapter_brief.

UI 结构:
  - 上: 工具栏 (生成按钮 + 章数 spin + 风格选择)
  - 中: 3 列 (A / B / C) QPlainTextEdit 并排显示
  - 下: 选定按钮 + 选定后自动写入 chapter_brief.core_events
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict

from PySide6.QtCore import Qt, QObject, QThread, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QCheckBox,
    QPlainTextEdit,
    QPushButton,
    QLabel,
    QGroupBox,
    QProgressBar,
    QDialog,
    QDialogButtonBox,
)

from app.services import (
    project_service,
    book_service,
    chapter_service,
    setting_service,
    outline_service,
    genre_presets,
    ServiceError,
)
from app.db import _impl as _db_conn
from app.ui.widgets import Dialogs
from app.ui.widgets._number_input import NumberInput

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# 数据类 (原 ai_outline_gen_plugin, 已内联)
# --------------------------------------------------------------------- #

@dataclass
class OutlineDraft:
    """单版本大纲草稿."""
    version: str               # A / B / C
    outline: str
    core_events: str = ""
    emotion_arc: str = ""
    word_target: int = 3000
    fallback: bool = False     # 是否由模板生成 (LLM 不可用时)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "outline": self.outline,
            "core_events": self.core_events,
            "emotion_arc": self.emotion_arc,
            "word_target": self.word_target,
            "fallback": self.fallback,
        }


@dataclass
class OutlineResult:
    """一章的 3 版本生成结果."""
    chapter_id: str
    chapter_no: int
    title: str
    drafts: Dict[str, OutlineDraft]  # version -> draft

    def to_dict(self) -> dict:
        return {
            "chapter_id": self.chapter_id,
            "chapter_no": self.chapter_no,
            "title": self.title,
            "drafts": {k: v.to_dict() for k, v in self.drafts.items()},
        }


# --------------------------------------------------------------------- #
# 提示模板
# --------------------------------------------------------------------- #

VERSION_PROMPTS = {
    "A": (
        "风格 A - 平稳线:\n"
        "  沿用本章既定方向, 低冲突, 强化日常 / 情感 / 角色互动.\n"
        "  节奏平稳, 适合章节开头或过渡段.\n"
        "  重点: 角色细腻描写, 日常事件, 关系推进."
    ),
    "B": (
        "风格 B - 上升线:\n"
        "  推进主线, 加大冲突, 推动剧情整体前进.\n"
        "  节奏紧凑, 适合章节中段或高潮段.\n"
        "  重点: 矛盾升级, 信息揭露, 关键决策."
    ),
    "C": (
        "风格 C - 翻转线:\n"
        "  引入意外 / 反转, 颠覆已有假设或预期.\n"
        "  节奏强烈, 适合章节末尾或转折点.\n"
        "  重点: 认知颠覆, 隐藏信息曝光, 立场反转."
    ),
}

FALLBACK_TEMPLATES = {
    "A": (
        "{title} (平稳线)\n"
        "场景: 主角在熟悉环境内, 处理日常事务 / 与配角互动.\n"
        "事件: 一个小的但有意义的细节展开, 引出背景或关系.\n"
        "情绪: 平静 → 好奇 → 温暖 / 忧虑.\n"
        "结尾: 留一个小伏笔, 为后续章节铺垫."
    ),
    "B": (
        "{title} (上升线)\n"
        "场景: 主角面对外部压力 / 内部冲突, 主动出击.\n"
        "事件: 主线推进, 一个关键决策 / 一次重要交锋.\n"
        "情绪: 紧张 → 决心 → 突破 / 受挫.\n"
        "结尾: 留下悬念, 推动下一章."
    ),
    "C": (
        "{title} (翻转线)\n"
        "场景: 看似平静, 实际暗藏关键线索.\n"
        "事件: 一个意外揭示, 颠覆已有认知, 引出新的疑问.\n"
        "情绪: 困惑 → 震惊 → 重新评估.\n"
        "结尾: 留大悬念 / 反转冲击."
    ),
}


# --------------------------------------------------------------------- #
# 内部辅助函数 (原插件逻辑)
# --------------------------------------------------------------------- #

def _build_prompt(chapter_no, title, project, version, word_target, world, characters):
    genre = project.get("genre") or "通用"
    keywords = genre_presets.genre_to_keywords(genre)
    kw_line = "、".join(keywords[:6]) if keywords else ""
    return f"""你是资深网文大纲编辑. 为一本{genre}小说设计第 {chapter_no} 章的【{version} 版本】大纲.

题材: {genre}
{('风格关键词: ' + kw_line) if kw_line else ''}
{VERSION_PROMPTS.get(version, '')}

章名: {title}
目标字数: ~{word_target} 字

# 项目世界观 (截取)
{world[:600] if world else '(无)'}

# 已有角色 (截取)
{characters[:500] if characters else '(无)'}

# 输出要求 (严格 JSON, 不要任何其他文本)
{{
  "outline": "本章 200-300 字大纲 (含场景 / 事件 / 情绪变化)",
  "core_events": "核心事件 1-2 句",
  "emotion_arc": "情绪弧线 (起 → 承 → 转 → 合)"
}}
"""


def _try_llm_call(prompt, *, step="outline_gen"):
    """尝试调 LLM, 失败返回 None."""
    try:
        from app.ai.engine import AIEngine
        engine = AIEngine.instance()
        resp = engine.chat(
            [{"role": "user", "content": prompt}],
            task=step,
            temperature=0.7,
            max_tokens=600,
        )
    except Exception as e:
        log.warning("LLM 调用失败, 走 fallback: %s", e)
        return None
    content = (resp.content or "").strip()
    content = content.strip("`").strip()
    if content.startswith("json"):
        content = content[4:].strip()
    s = content.find("{")
    e = content.rfind("}")
    if s < 0 or e < 0 or e <= s:
        log.warning("LLM 输出无 JSON 结构: %r", content[:120])
        return None
    try:
        return json.loads(content[s:e + 1])
    except json.JSONDecodeError as ex:
        log.warning("LLM 输出 JSON 解析失败: %s", ex)
        return None


def _fallback_draft(chapter_no, title, version, word_target):
    tpl = FALLBACK_TEMPLATES[version]
    return OutlineDraft(
        version=version,
        outline=tpl.format(title=title or f"第 {chapter_no} 章"),
        core_events=f"({version} 版) 本章核心事件待人工补充",
        emotion_arc="起 → 承 → 转 → 合",
        word_target=word_target,
        fallback=True,
    )


def _ensure_default_book(project_id):
    books = book_service.list_for_project(project_id).get("books", [])
    if books:
        return sorted(books, key=lambda b: b.get("volume_no", 0))[0]
    return book_service.create(project_id, volume_no=1, title="默认卷")


def _world_to_str(world):
    if not world:
        return ""
    if isinstance(world, dict):
        return "\n".join(f"{k}: {str(v)[:200]}" for k, v in list(world.items())[:8])
    if isinstance(world, list):
        return "\n".join(str(x)[:200] for x in world[:8])
    return str(world)


def _chars_to_str(chars):
    if not chars:
        return ""
    if isinstance(chars, list):
        out = []
        for c in chars[:8]:
            if isinstance(c, dict):
                out.append(f"【{c.get('name', '?')}】{c.get('traits', c.get('personality', ''))}")
            else:
                out.append(str(c))
        return "\n".join(out)
    if isinstance(chars, dict):
        out = []
        for k, v in list(chars.items())[:8]:
            if isinstance(v, dict):
                out.append(f"【{k}】{v.get('traits', v.get('personality', ''))}")
            else:
                out.append(f"【{k}】{v}")
        return "\n".join(out)
    return str(chars)


def _ensure_chapters(book_id, num):
    with _db_conn.connection() as db:
        rows = db.execute(
            "SELECT * FROM chapters WHERE book_id=? ORDER BY chapter_no LIMIT ?",
            (book_id, num),
        ).fetchall()
    existing = [dict(r) for r in rows]
    for i in range(len(existing) + 1, num + 1):
        ch = chapter_service.create(book_id, chapter_no=i, title=f"第 {i} 章")
        existing.append(ch)
    return existing[:num]


def generate_outlines(project_id, num_chapters=10, *, word_target=3000, use_llm=True):
    """为项目前 N 章生成 3 版本大纲。"""
    if not (1 <= num_chapters <= 10):
        raise ValueError(f"num_chapters 必须在 1-10 (实际 {num_chapters})")
    proj = project_service.get(project_id)
    world = setting_service.get_setting(project_id, "worldbuilding").get("data") or {}
    chars = setting_service.get_setting(project_id, "characters").get("data") or {}
    world_text = _world_to_str(world)
    chars_text = _chars_to_str(chars)
    book = _ensure_default_book(project_id)
    chapters = _ensure_chapters(book["id"], num_chapters)
    results = []
    for ch in chapters:
        ch_no = ch.get("chapter_no", 0)
        ch_title = ch.get("title") or f"第 {ch_no} 章"
        drafts = {}
        for ver in ("A", "B", "C"):
            prompt = _build_prompt(ch_no, ch_title, proj, ver, word_target, world_text, chars_text)
            draft = None
            if use_llm:
                parsed = _try_llm_call(prompt, step=f"outline_{ver}")
                if parsed:
                    draft = OutlineDraft(
                        version=ver,
                        outline=str(parsed.get("outline", "")).strip(),
                        core_events=str(parsed.get("core_events", "")).strip(),
                        emotion_arc=str(parsed.get("emotion_arc", "")).strip(),
                        word_target=word_target,
                        fallback=False,
                    )
            if draft is None:
                draft = _fallback_draft(ch_no, ch_title, ver, word_target)
            outline_service.save_outline(
                ch["id"], ver, draft.outline,
                core_events=draft.core_events,
                emotion_arc=draft.emotion_arc,
                word_target=draft.word_target,
            )
            drafts[ver] = draft
        results.append(OutlineResult(
            chapter_id=ch["id"],
            chapter_no=ch_no,
            title=ch_title,
            drafts=drafts,
        ))
    return results


# --------------------------------------------------------------------- #
# Worker: 把 generate_outlines 装进 QThread
# --------------------------------------------------------------------- #

class OutlineGenWorker(QObject):
    finished_ok = Signal(list)         # list[OutlineResult]
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, project_id: str, num: int, use_llm: bool) -> None:
        super().__init__()
        self.project_id = project_id
        self.num = num
        self.use_llm = use_llm

    def run(self) -> None:
        try:
            self.progress.emit(f"正在生成前 {self.num} 章大纲…")
            results = generate_outlines(
                self.project_id, num_chapters=self.num, use_llm=self.use_llm,
            )
            self.progress.emit("生成完毕")
            self.finished_ok.emit(results)
        except Exception as e:
            log.exception("OutlineGenWorker failed")
            self.failed.emit(str(e))


# --------------------------------------------------------------------- #
# 主体: OutlineGenDialog
# --------------------------------------------------------------------- #

class OutlineGenDialog(QDialog):
    """H1 AI 大纲生成对话框."""

    def __init__(self, project: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle(f"AI 大纲生成 — {project.get('name', '')}")
        self.resize(1100, 700)
        self._build_ui()
        # 加载已有大纲 (如有)
        self._load_existing()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # 工具栏
        bar = QHBoxLayout()
        bar.addWidget(QLabel("章节数:"))
        self.spn_num = NumberInput(lo=1, hi=10, default=10)
        bar.addWidget(self.spn_num)
        self.chk_use_llm = QCheckBox("使用 LLM (未勾选走模板)")
        self.chk_use_llm.setChecked(False)  # 默认安全: 模板模式
        bar.addWidget(self.chk_use_llm)
        self.btn_gen = QPushButton("🚀 生成 / 重新生成")
        self.btn_gen.clicked.connect(self._on_generate)
        bar.addWidget(self.btn_gen)
        self.btn_select = QPushButton("✅ 标记为选定")
        self.btn_select.clicked.connect(self._on_select)
        self.btn_select.setEnabled(False)
        bar.addWidget(self.btn_select)
        bar.addStretch(1)
        outer.addLayout(bar)

        # 状态条
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        outer.addWidget(self.progress)
        self.status_label = QLabel("就绪")
        outer.addWidget(self.status_label)

        # 3 列大纲
        cols = QHBoxLayout()
        self.edits: dict[str, QPlainTextEdit] = {}
        self.titles: dict[str, QLabel] = {}
        for ver, color, desc in [
            ("A", "#16a34a", "平稳线 - 日常 / 情感"),
            ("B", "#2563eb", "上升线 - 主线 / 冲突"),
            ("C", "#d97706", "翻转线 - 意外 / 反转"),
        ]:
            box = QGroupBox(f"版本 {ver}  ({desc})")
            v = QVBoxLayout(box)
            t = QLabel("(未生成)")
            t.setObjectName(f"title_{ver}")
            t.setStyleSheet(f"color: {color}; font-weight: bold;")
            v.addWidget(t)
            e = QPlainTextEdit()
            e.setReadOnly(True)
            e.setPlaceholderText(f"版本 {ver} 大纲将显示在这里…")
            v.addWidget(e, 1)
            cols.addWidget(box, 1)
            self.edits[ver] = e
            self.titles[ver] = t
        outer.addLayout(cols, 1)

        # 关闭按钮
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.reject)
        outer.addWidget(btn_box)

    def _load_existing(self) -> None:
        """加载已有的所有 chapter 的大纲 (取前 N 章的最后一个状态)."""
        # 找项目下的 chapter
        from app.services import book_service
        books = book_service.list_for_project(self.project["id"]).get("books", [])
        if not books:
            return
        # 取前 N 章 (按 chapter_no)
        with _db_conn.connection() as db:
            rows = db.execute(
                "SELECT * FROM chapters WHERE book_id IN ({}) "
                "ORDER BY chapter_no LIMIT ?".format(
                    ",".join("?" * len(books))
                ),
                (*[b["id"] for b in books], self.spn_num.value()),
            ).fetchall()
        for r in rows:
            ch = dict(r)
            outs = outline_service.list_outlines(ch["id"])
            for o in outs:
                ver = o["version"]
                tag = " ⭐" if o.get("selected") else ""
                self.titles[ver].setText(
                    f"第 {ch.get('chapter_no', '?')} 章 {ch.get('title', '')} ({ver}){tag}"
                )
                if not self.edits[ver].toPlainText():
                    self.edits[ver].setPlainText(
                        f"─── 第 {ch.get('chapter_no', '?')} 章 ───\n{o['outline']}"
                    )
                else:
                    self.edits[ver].append(
                        f"\n─── 第 {ch.get('chapter_no', '?')} 章 ───\n{o['outline']}"
                    )
        # 如有数据, 启用 select
        has_data = any(self.edits[v].toPlainText() for v in ("A", "B", "C"))
        self.btn_select.setEnabled(has_data)

    def _on_generate(self) -> None:
        if not self.project:
            return
        # 清空
        for v in ("A", "B", "C"):
            self.edits[v].clear()
            self.titles[v].setText("(生成中…)")
        self.btn_gen.setEnabled(False)
        self.btn_select.setEnabled(False)
        self.progress.setVisible(True)

        # 直接调用内联的 generate_outlines
        self._thread = QThread(self)
        self._worker = OutlineGenWorker(
            self.project["id"], self.spn_num.value(), self.chk_use_llm.isChecked()
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.progress.connect(self.status_label.setText)
        self._thread.start()

    def _on_finished(self, results: list) -> None:
        self._cleanup_thread()
        for r in results:
            for ver, draft in r.drafts.items():
                tag = " [fallback]" if draft.fallback else ""
                self.titles[ver].setText(
                    f"第 {r.chapter_no} 章 {r.title} ({ver}){tag}"
                )
                self.edits[ver].appendPlainText(
                    f"─── 第 {r.chapter_no} 章 ───\n{draft.outline}"
                )
        self.status_label.setText(f"生成完毕: {len(results)} 章 × 3 版本")
        self.progress.setVisible(False)
        self.btn_gen.setEnabled(True)
        self.btn_select.setEnabled(True)

    def _on_failed(self, msg: str) -> None:
        self._cleanup_thread()
        Dialogs.warning("生成失败", msg, parent=self)
        self.status_label.setText(f"失败: {msg}")
        self.progress.setVisible(False)
        self.btn_gen.setEnabled(True)

    def _on_select(self) -> None:
        """对当前 3 列 (A/B/C) 各自标记 '已选' (这里简化为全部都保存到对应 chapter).
        实际选版流程: 在章节编辑 tab 看单章的 A/B/C, 选定一个.
        """
        Dialogs.info(
            "提示",
            "本对话框是批量查看. 如要选定单章版本, 请到「章节编辑」tab 选定.\n"
            "生成的大纲已保存到 chapter_outlines 表, 选定后会写入 chapter_brief.",
            parent=self,
        )

    def _cleanup_thread(self) -> None:
        try:
            if self._thread and self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(2000)
        except Exception:
            pass
        self._thread = None
        self._worker = None
