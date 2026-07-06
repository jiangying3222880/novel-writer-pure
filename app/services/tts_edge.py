"""
H7 TTS 语音合成服务 (原插件, 已固化).

功能: 章节转语音 (TTS).
- mock 模式 (默认): 生成 ".wav" 占位文件, 记录文本长度
- 真实模式 (留接口): 调 edge-tts / azure 等 (后续接入)
- 落盘: 项目 / tts / chapter_<id>.txt (保存脚本), chapter_<id>.wav (音频)

公开 API:
  - synthesize_chapter(chapter_id) -> TTSResult
  - synthesize_text(text, out_path) -> TTSResult
  - get_audio_path(chapter_id) -> Path | None
  - list_synthesized(project_id) -> list[dict]

数据: 简单存文件系统 (tts/ 目录). 不存 DB (避免 schema 膨胀).
"""
from __future__ import annotations

import json
import logging
import os
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from app.services import project_service, chapter_service, ServiceError

_logger = logging.getLogger("NovelWriter.plugin.tts_edge")


# --------------------------------------------------------------------- #
# 数据类
# --------------------------------------------------------------------- #

@dataclass
class TTSResult:
    """TTS 合成结果."""
    chapter_id: str
    text_len: int
    out_path: str
    duration_sec: float
    voice: str
    engine: str           # "mock" / "edge" / ...
    created_at: str

    def to_dict(self) -> dict:
        return {
            "chapter_id": self.chapter_id,
            "text_len": self.text_len,
            "out_path": self.out_path,
            "duration_sec": self.duration_sec,
            "voice": self.voice,
            "engine": self.engine,
            "created_at": self.created_at,
        }


# --------------------------------------------------------------------- #
# 插件实现
# --------------------------------------------------------------------- #

class TTSEdgePlugin:
    """
    H7 章节 TTS 服务 (mock).

    模式:
      - mock (默认): 写 .wav header + 0 长度, 记录文本, 估算 duration = chars/4
      - edge: 调 edge-tts (后续接)
    """
    # 默认参数
    DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
    DEFAULT_RATE = "+0%"
    SAMPLE_RATE = 24000

    # ─────────────── 公开 API ───────────────

    def synthesize_chapter(
        self,
        chapter_id: str,
        *,
        voice: Optional[str] = None,
        engine: str = "mock",
    ) -> TTSResult:
        """合成一章的 TTS."""
        # 拿 chapter + 关联 project
        from app.db import _impl as _db_conn
        with _db_conn.connection() as db:
            row = db.execute(
                "SELECT c.*, b.project_id FROM chapters c "
                "JOIN books b ON c.book_id=b.id WHERE c.id=?",
                (chapter_id,),
            ).fetchone()
        if not row:
            raise ServiceError(f"找不到 chapter: {chapter_id}")
        ch = dict(row)
        # 优先: final > draft > 最新 chapter_drafts > scene_context > title
        text = (ch.get("final") or ch.get("draft") or "")
        if not text:
            with _db_conn.connection() as db:
                d_row = db.execute(
                    "SELECT content FROM chapter_drafts WHERE chapter_id=? "
                    "ORDER BY version_no DESC LIMIT 1",
                    (chapter_id,),
                ).fetchone()
            if d_row:
                text = d_row["content"] or ""
        if not text:
            text = ch.get("scene_context") or ""
        if not text:
            ch_title = ch.get("title") or ("章节 %s" % ch.get("chapter_no"))
            text = "(%s 无内容)" % ch_title

        out_dir = self._tts_dir(ch["project_id"])
        out_path = out_dir / f"chapter_{chapter_id}.wav"
        return self.synthesize_text(
            text, str(out_path), voice=voice, engine=engine, chapter_id=chapter_id,
        )

    def synthesize_text(
        self,
        text: str,
        out_path: str,
        *,
        voice: Optional[str] = None,
        engine: str = "mock",
        chapter_id: str = "",
    ) -> TTSResult:
        """合成一段文本到文件."""
        if engine == "mock":
            return self._mock_synth(text, out_path, voice=voice, chapter_id=chapter_id)
        elif engine == "edge":
            return self._edge_synth(text, out_path, voice=voice, chapter_id=chapter_id)
        else:
            raise ValueError(f"未知 engine: {engine} (合法: mock / edge)")

    def get_audio_path(self, chapter_id: str, project_id: str) -> Optional[str]:
        p = self._tts_dir(project_id) / f"chapter_{chapter_id}.wav"
        return str(p) if p.exists() else None

    def list_synthesized(self, project_id: str) -> List[dict]:
        """列出项目下所有已合成的章节 .wav 元信息."""
        tts_dir = self._tts_dir(project_id)
        if not tts_dir.exists():
            return []
        out = []
        for p in sorted(tts_dir.glob("chapter_*.wav")):
            try:
                stat = p.stat()
                chapter_id = p.stem.replace("chapter_", "")
                out.append({
                    "chapter_id": chapter_id,
                    "path": str(p),
                    "size_bytes": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                })
            except Exception:
                continue
        return out

    # ─────────────── 内部 ───────────────

    def _tts_dir(self, project_id: str) -> Path:
        from app.services.file_store import _get_project_dir
        proj_dir = Path(_get_project_dir(project_id))
        tts_dir = proj_dir / "tts"
        tts_dir.mkdir(parents=True, exist_ok=True)
        return tts_dir

    def _mock_synth(
        self, text: str, out_path: str, voice: Optional[str], chapter_id: str,
    ) -> TTSResult:
        """Mock 模式: 写最小 WAV header, 估算时长."""
        voice = voice or self.DEFAULT_VOICE
        n = max(1, len(text))
        # 估算: 中文 ~4 字/秒
        duration = n / 4.0
        # 写一个空 wav (header + 0 字节数据)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(out_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.SAMPLE_RATE)
            # 写 0 帧 (空 wav, 但 header 完整, 大多数播放器可识别)
            w.writeframes(b"")
        # 写一个 sidecar json (供后续读取)
        meta_path = Path(out_path).with_suffix(".json")
        meta = {
            "chapter_id": chapter_id,
            "text_len": n,
            "duration_sec": duration,
            "voice": voice,
            "engine": "mock",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        return TTSResult(
            chapter_id=chapter_id,
            text_len=n,
            out_path=out_path,
            duration_sec=duration,
            voice=voice,
            engine="mock",
            created_at=meta["created_at"],
        )

    def _edge_synth(
        self, text: str, out_path: str, voice: Optional[str], chapter_id: str,
    ) -> TTSResult:
        """真实 edge-tts 模式. 依赖外部 edge-tts 包."""
        try:
            import asyncio
            import edge_tts  # type: ignore
        except ImportError:
            raise ImportError("请先 pip install edge-tts")
        voice = voice or self.DEFAULT_VOICE

        async def _run() -> None:
            comm = edge_tts.Communicate(text, voice=voice, rate=self.DEFAULT_RATE)
            await comm.save(out_path)

        asyncio.run(_run())
        n = len(text)
        duration = n / 4.0
        meta = {
            "chapter_id": chapter_id,
            "text_len": n,
            "duration_sec": duration,
            "voice": voice,
            "engine": "edge",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        Path(out_path).with_suffix(".json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return TTSResult(
            chapter_id=chapter_id,
            text_len=n,
            out_path=out_path,
            duration_sec=duration,
            voice=voice,
            engine="edge",
            created_at=meta["created_at"],
        )
