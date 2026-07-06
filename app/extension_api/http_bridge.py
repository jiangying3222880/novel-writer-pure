"""
http_bridge.py - 把 nw.* 暴露为 HTTP REST 端点, 给 VS Code 扩展调用.

启动:
    python -m app.extension_api.http_bridge
    python -m app.extension_api.http_bridge --port 9000

VS Code 扩展端通过 http://localhost:8765 调用核心能力, 1 套 nw.py 双端共享.

设计:
- 使用 Python 内置 http.server (无第三方依赖)
- ThreadingHTTPServer 处理并发 (VS Code WebView 可能并发)
- CORS 放开 (本地 dev, 端口固定)
- 所有端点走 try/except, 失败返回 JSON {ok: false, error: "..."}
- 不接收任意 Python 代码 (安全), 只暴露白名单端点

ADR: docs/decisions/0002-vscode-compatible-api.md
"""
from __future__ import annotations

import argparse
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("nw.http_bridge")

# 默认端口
DEFAULT_PORT = 8765

# nw 单例 (延迟导入, 因为 extension_api 可能初始化较重)
_nw_singleton: Optional[Any] = None
_nw_lock = threading.Lock()


def _get_nw():
    """延迟导入 + 线程安全单例. 注意: `from app.extension_api import nw` 拿到的是
    `nw.py` 模块里那个 _NW() 单例实例本身 (不是模块), 所以直接绑定."""
    global _nw_singleton
    if _nw_singleton is None:
        with _nw_lock:
            if _nw_singleton is None:
                from app.extension_api.nw import nw as _nw_instance
                _nw_singleton = _nw_instance
    return _nw_singleton


# ============================================================================
# 路由表
# ============================================================================

# path -> (method, handler)
# handler 接收 (params: dict, body: dict) -> dict (要 JSON 序列化的结果)


def _route_get_version(_params: dict, _body: dict) -> dict:
    nw = _get_nw()
    return {
        "version": nw.version,
        "commands_count": len(nw.commands.get_commands()),
        "extensions_count": len(nw.extensions.all),
    }


def _route_get_commands(_params: dict, _body: dict) -> dict:
    nw = _get_nw()
    return {"commands": nw.commands.get_commands()}


def _route_execute_command(_params: dict, body: dict) -> dict:
    nw = _get_nw()
    command = body.get("command", "")
    args = body.get("args", [])
    if not command:
        return {"ok": False, "error": "command is required"}
    if not nw.commands.has_command(command):
        return {"ok": False, "error": f"未注册命令: {command}"}
    try:
        result = nw.commands.execute_command(command, *args)
        return {"ok": True, "result": result}
    except Exception as e:
        logger.exception("execute_command failed")
        return {"ok": False, "error": str(e)}


def _route_get_configuration(params: dict, _body: dict) -> dict:
    nw = _get_nw()
    section = params.get("section") or None
    cfg = nw.workspace.get_configuration(section)
    # 把整个 cfg._values 暴露出去 (简化)
    return {
        "section": section or "",
        "values": dict(cfg._values) if hasattr(cfg, "_values") else {},
    }


def _route_get_extensions(_params: dict, _body: dict) -> dict:
    nw = _get_nw()
    return {
        "extensions": [
            {
                "id": ext.id,
                "is_active": ext.is_active,
                "package_json": ext.package_json,
            }
            for ext in nw.extensions.all
        ]
    }


def _route_get_env(_params: dict, _body: dict) -> dict:
    nw = _get_nw()
    return {
        "app_name": nw.env.app_name,
        "app_root": nw.env.app_root,
        "language": nw.env.language,
        "session_id": nw.env.session_id,
        "machine_id": nw.env.machine_id,
        "is_telemetry_enabled": nw.env.is_telemetry_enabled,
    }


def _route_show_info(_params: dict, body: dict) -> dict:
    nw = _get_nw()
    message = body.get("message", "")
    items = body.get("items", [])
    if not message:
        return {"ok": False, "error": "message is required"}
    picked = nw.window.show_information_message(message, *items)
    return {"ok": True, "picked": picked}


def _route_show_warning(_params: dict, body: dict) -> dict:
    nw = _get_nw()
    message = body.get("message", "")
    items = body.get("items", [])
    if not message:
        return {"ok": False, "error": "message is required"}
    picked = nw.window.show_warning_message(message, *items)
    return {"ok": True, "picked": picked}


def _route_show_error(_params: dict, body: dict) -> dict:
    nw = _get_nw()
    message = body.get("message", "")
    items = body.get("items", [])
    if not message:
        return {"ok": False, "error": "message is required"}
    picked = nw.window.show_error_message(message, *items)
    return {"ok": True, "picked": picked}


def _route_show_input(_params: dict, body: dict) -> dict:
    nw = _get_nw()
    options = body.get("options") or {}
    value = nw.window.show_input_box(options)
    return {"ok": True, "value": value}


def _route_clipboard_write(_params: dict, body: dict) -> dict:
    nw = _get_nw()
    text = body.get("text", "")
    nw.env.clipboard_write(text)
    return {"ok": True}


def _route_clipboard_read(_params: dict, _body: dict) -> dict:
    nw = _get_nw()
    return {"ok": True, "text": nw.env.clipboard_read()}


def _route_open_external(_params: dict, body: dict) -> dict:
    nw = _get_nw()
    target = body.get("target", "")
    if not target:
        return {"ok": False, "error": "target is required"}
    ok = nw.env.open_external(target)
    return {"ok": ok}


# ────────────────────── TTS 章节朗读 (M8) ──────────────────────


def _ensure_bridge_db() -> None:
    """TTS 路由需要 DB, 第一次调时 init_db (与 CLI 共享同一文件)."""
    from app.db import _impl as _db_conn
    _db_conn.init_db()


def _route_tts_synth(_params: dict, body: dict) -> dict:
    """POST /tts/synth - 合成章节 TTS.
    body: {chapter_id, engine?, voice?, dry_run?}
    """
    try:
        _ensure_bridge_db()
    except Exception as e:
        return {"ok": False, "error": f"db init failed: {e}"}

    from app.services.tts_edge import TTSEdgePlugin

    chapter_id = body.get("chapter_id", "")
    if not chapter_id:
        return {"ok": False, "error": "chapter_id is required"}
    engine = (body.get("engine") or "mock").lower()
    if engine not in ("mock", "edge"):
        return {"ok": False, "error": f"engine must be mock/edge (got {engine})"}
    if body.get("dry_run"):
        return {
            "ok": True,
            "dry_run": True,
            "chapter_id": chapter_id,
            "engine": engine,
            "voice": body.get("voice") or "zh-CN-XiaoxiaoNeural",
        }

    plugin = TTSEdgePlugin()
    try:
        result = plugin.synthesize_chapter(
            chapter_id, voice=body.get("voice"), engine=engine,
        )
    except ImportError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("tts synth failed: %s", chapter_id)
        return {"ok": False, "error": str(e)}
    return {"ok": True, **result.to_dict()}


def _route_tts_list(params: dict, _body: dict) -> dict:
    """GET /tts/list?project_id=<id> - 列出项目下已合成的 TTS."""
    try:
        _ensure_bridge_db()
    except Exception as e:
        return {"ok": False, "error": f"db init failed: {e}"}
    
    pid = params.get("project_id", "")
    if not pid:
        return {"ok": False, "error": "project_id query param is required"}
    from app.services.tts_edge import TTSEdgePlugin
    plugin = TTSEdgePlugin()
    files = plugin.list_synthesized(pid)
    return {"ok": True, "project_id": pid, "files": files, "count": len(files)}


def _route_tts_show(params: dict, _body: dict) -> dict:
    """GET /tts/show?chapter_id=<id> - 查章节 TTS 音频 + sidecar meta."""
    try:
        _ensure_bridge_db()
    except Exception as e:
        return {"ok": False, "error": f"db init failed: {e}"}
    
    cid = params.get("chapter_id", "")
    if not cid:
        return {"ok": False, "error": "chapter_id query param is required"}

    from app.services import chapter_service, book_service
    from app.services.tts_edge import TTSEdgePlugin
    try:
        ch = chapter_service.get(cid)
    except Exception as e:
        return {"ok": False, "error": f"chapter not found: {e}"}
    b = book_service.get(ch["book_id"])
    pid = b["project_id"]

    plugin = TTSEdgePlugin()
    ap = plugin.get_audio_path(cid, pid)
    if ap is None:
        return {"ok": True, "chapter_id": cid, "project_id": pid, "audio_path": None}

    import json as _json
    from pathlib import Path as _P
    meta_path = _P(ap).with_suffix(".json")
    meta: dict = {}
    if meta_path.exists():
        try:
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "ok": True,
        "chapter_id": cid,
        "project_id": pid,
        "audio_path": ap,
        "meta": meta,
    }


# ────────────────────── M9-B 一键出版 ──────────────────────


def _route_export_formats(_params: dict, _body: dict) -> dict:
    """GET /export/formats - 列出支持的导出格式 + 封面模板."""
    try:
        from app.services.exporter import SUPPORTED_FORMATS
    except Exception as e:
        return {"ok": False, "error": f"exporter unavailable: {e}"}
    return {
        "ok": True,
        "formats": list(SUPPORTED_FORMATS),
        "cover_templates": ["default", "minimal", "wuxia", "romance", "scifi"],
    }


def _route_export_book(_params: dict, body: dict) -> dict:
    """POST /export/book - 一键导出.

    body: {
        "project_id": "uuid",
        "book_id": "uuid" (optional),
        "format": "epub|docx|md|txt",
        "output_path": "..." (optional, default ./exports/),
        "with_cover": true,
        "cover_template": "default"
    }
    """
    try:
        from app.services.exporter import BookExporter, SUPPORTED_FORMATS
    except Exception as e:
        return {"ok": False, "error": f"exporter unavailable: {e}"}

    pid = body.get("project_id", "")
    if not pid:
        return {"ok": False, "error": "project_id is required"}
    fmt = (body.get("format") or "epub").lower()
    if fmt not in SUPPORTED_FORMATS:
        return {"ok": False, "error": f"format must be one of {SUPPORTED_FORMATS}"}

    bid = body.get("book_id")
    output = body.get("output_path")
    if not output:
        from pathlib import Path
        exports_dir = Path("exports")
        exports_dir.mkdir(parents=True, exist_ok=True)
        suffix = f".{fmt}"
        key = (pid[:8] + ("_" + bid[:8] if bid else "_all"))
        output = str(exports_dir / f"{key}{suffix}")

    try:
        exporter = BookExporter(pid, bid)
        result = exporter.export(
            fmt, output,
            with_cover=bool(body.get("with_cover", True)),
            cover_template=body.get("cover_template", "default"),
        )
        return {
            "ok": True,
            "output_path": result.output_path,
            "format": result.format,
            "chapter_count": result.chapter_count,
            "file_size": result.file_size,
            "cover_path": result.cover_path,
            "duration_ms": result.duration_ms,
            "metadata": result.metadata,
        }
    except Exception as e:
        logger.exception("export book failed: project=%s book=%s", pid, bid)
        return {"ok": False, "error": str(e)}


def _route_export_cover(_params: dict, body: dict) -> dict:
    """POST /export/cover - 单生成封面.

    body: {
        "title": "...", "author": "...",
        "template": "default|minimal|wuxia|romance|scifi",
        "output_path": "..." (optional)
    }
    """
    try:
        from app.services.exporter import CoverGenerator, CoverRequest
    except Exception as e:
        return {"ok": False, "error": f"exporter unavailable: {e}"}

    tpl = body.get("template", "default")
    valid_templates = ("default", "minimal", "wuxia", "romance", "scifi")
    if tpl not in valid_templates:
        return {"ok": False, "error": f"template must be one of {valid_templates}"}

    req = CoverRequest(
        template=tpl,
        project_name=body.get("title", "未命名"),
        author_name=body.get("author", "佚名"),
    )
    from pathlib import Path
    out = body.get("output_path")
    out_path = Path(out) if out else Path(f"cover_{tpl}.png")
    try:
        gen = CoverGenerator()
        res = gen.render(req, out_path)
    except Exception as e:
        logger.exception("cover render failed")
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "path": res.path,
        "width": res.width,
        "height": res.height,
        "format": res.format,
        "template": res.template,
    }


# ────────────────────── M9-C License + Feature Gate ──────────────────────


def _route_license_status(_params: dict, _body: dict) -> dict:
    """GET /license/status - 查 license + tier + 功能."""
    try:
        from app.services.license import get_license, get_machine_code
        from app.services.feature_gate import get_tier, list_features
    except Exception as e:
        return {"ok": False, "error": f"license service unavailable: {e}"}
    info = get_license()
    tier = get_tier()
    machine = get_machine_code()
    return {
        "ok": True,
        "license": {
            "status": info.status.value,
            "version": info.version,
            "machine_code": info.machine_code or machine,
            "expire_date": info.expire_date,
            "remaining_days": info.remaining_days,
            "activated_at": info.activated_at,
            "error_msg": info.error_msg,
        },
        "tier": tier.value,
        "features": [
            {
                "feature_id": fid, "name": finfo.name,
                "required_tier": finfo.tier.value, "unlocked": unlocked,
                "category": finfo.category,
            }
            for fid, finfo, unlocked in list_features()
        ],
    }


def _route_license_activate(_params: dict, body: dict) -> dict:
    """POST /license/activate - body.key = 'NV-XXXX-...'."""
    try:
        from app.services.license import activate, LicenseStatus
    except Exception as e:
        return {"ok": False, "error": f"license service unavailable: {e}"}
    key = body.get("key", "").strip()
    if not key:
        return {"ok": False, "error": "key is required"}
    info = activate(key)
    return {
        "ok": info.status == LicenseStatus.PREMIUM and not info.error_msg,
        "status": info.status.value,
        "version": info.version,
        "machine_code": info.machine_code,
        "expire_date": info.expire_date,
        "remaining_days": info.remaining_days,
        "error_msg": info.error_msg,
    }


def _route_license_deactivate(_params: dict, _body: dict) -> dict:
    """POST /license/deactivate - 清 key."""
    try:
        from app.services.license import deactivate
    except Exception as e:
        return {"ok": False, "error": f"license service unavailable: {e}"}
    info = deactivate()
    return {
        "ok": True,
        "status": info.status.value,
        "version": info.version,
    }


def _route_license_machine(_params: dict, _body: dict) -> dict:
    """GET /license/machine - 查本机机器码."""
    try:
        from app.services.license import get_machine_code
    except Exception as e:
        return {"ok": False, "error": f"license service unavailable: {e}"}
    return {"ok": True, "machine_code": get_machine_code()}


def _route_feature_list(_params: dict, _body: dict) -> dict:
    """GET /feature/list - 列出所有功能 + 解锁状态."""
    try:
        from app.services.feature_gate import list_features, get_tier
    except Exception as e:
        return {"ok": False, "error": f"feature_gate unavailable: {e}"}
    tier = get_tier()
    return {
        "ok": True,
        "tier": tier.value,
        "features": [
            {
                "feature_id": fid, "name": finfo.name,
                "required_tier": finfo.tier.value, "unlocked": unlocked,
                "category": finfo.category, "description": finfo.description,
            }
            for fid, finfo, unlocked in list_features()
        ],
    }


def _route_feature_check(params: dict, _body: dict) -> dict:
    """GET /feature/check?feature_id=ai.critic - 查单个功能."""
    try:
        from app.services.feature_gate import (
            check_feature, get_feature_info, required_tier, get_tier,
        )
    except Exception as e:
        return {"ok": False, "error": f"feature_gate unavailable: {e}"}
    fid = params.get("feature_id", "")
    if not fid:
        return {"ok": False, "error": "feature_id query param is required"}
    unlocked = check_feature(fid)
    info = get_feature_info(fid)
    if info is None:
        return {"ok": False, "error": f"unknown feature_id: {fid}"}
    return {
        "ok": True,
        "feature_id": fid,
        "unlocked": unlocked,
        "required_tier": required_tier(fid).value,
        "actual_tier": get_tier().value,
        "info": {
            "name": info.name, "description": info.description,
            "category": info.category,
        },
    }


# 路由表: (method, path_pattern) -> handler
# path_pattern 用 {name} 表示 query param 提取
RouteKey = Tuple[str, str]
_ROUTES: Dict[RouteKey, Callable[[dict, dict], dict]] = {
    ("GET", "/health"): lambda p, b: {"ok": True, "service": "novel-writer-bridge"},
    ("GET", "/version"): _route_get_version,
    ("GET", "/commands"): _route_get_commands,
    ("POST", "/commands/execute"): _route_execute_command,
    ("GET", "/workspace/configuration"): _route_get_configuration,
    ("GET", "/extensions"): _route_get_extensions,
    ("GET", "/env"): _route_get_env,
    ("POST", "/window/show_info"): _route_show_info,
    ("POST", "/window/show_warning"): _route_show_warning,
    ("POST", "/window/show_error"): _route_show_error,
    ("POST", "/window/show_input"): _route_show_input,
    ("POST", "/env/clipboard/write"): _route_clipboard_write,
    ("GET", "/env/clipboard/read"): _route_clipboard_read,
    ("POST", "/env/open_external"): _route_open_external,
    # M8 章节 TTS
    ("POST", "/tts/synth"): _route_tts_synth,
    ("GET", "/tts/list"): _route_tts_list,
    ("GET", "/tts/show"): _route_tts_show,
    # M9-B 一键出版
    ("GET", "/export/formats"): _route_export_formats,
    ("POST", "/export/book"): _route_export_book,
    ("POST", "/export/cover"): _route_export_cover,
    # M9-C License + Feature Gate
    ("GET", "/license/status"): _route_license_status,
    ("POST", "/license/activate"): _route_license_activate,
    ("POST", "/license/deactivate"): _route_license_deactivate,
    ("GET", "/license/machine"): _route_license_machine,
    ("GET", "/feature/list"): _route_feature_list,
    ("GET", "/feature/check"): _route_feature_check,
}


# ============================================================================
# HTTP handler
# ============================================================================


def _parse_query(url: str) -> Tuple[str, dict]:
    """分离 path 和 query params."""
    if "?" not in url:
        return url, {}
    path, qs = url.split("?", 1)
    params: dict = {}
    for pair in qs.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            from urllib.parse import unquote
            params[unquote(k)] = unquote(v)
    return path, params


class _BridgeHandler(BaseHTTPRequestHandler):
    """HTTP handler: 路由表驱动 + JSON 响应 + CORS 开放."""

    # 静默 BaseHTTPRequestHandler 默认 access log
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.info("[bridge] " + format, *args)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            logger.warning("invalid JSON body: %s", e)
            return {}

    def _dispatch(self, method: str) -> None:
        path, params = _parse_query(self.path)
        key = (method, path)
        handler = _ROUTES.get(key)
        if handler is None:
            # 兜底: 404
            self._send_json(404, {"ok": False, "error": f"no route for {method} {path}"})
            return
        try:
            body = self._read_body() if method == "POST" else {}
            result = handler(params, body)
            self._send_json(200, result)
        except Exception as e:
            logger.exception("handler error: %s %s", method, path)
            self._send_json(500, {"ok": False, "error": str(e)})

    def do_OPTIONS(self) -> None:  # noqa: N802
        # CORS 预检
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")


# ============================================================================
# 启动入口
# ============================================================================


def start_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """启动 HTTP bridge. 返回 server 对象 (测试用)."""
    server = ThreadingHTTPServer((host, port), _BridgeHandler)
    logger.info("novel-writer HTTP bridge listening on http://%s:%s", host, port)
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="novel-writer HTTP bridge for VS Code extension")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port (default {DEFAULT_PORT})")
    parser.add_argument("--log-level", default="INFO", help="logging level (default INFO)")
    parser.add_argument(
        "--dialogs",
        choices=("headless", "pyside6", "none"),
        default="headless",
        help="dialogs adapter (default headless; pyside6 needs QApplication; none = raise on dialogs)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # 注入弹窗实现 (默认 headless, 适合 VS Code 端核心进程)
    if args.dialogs == "headless":
        from app.adapters.headless.dialogs_impl import install as _install_dialogs
        _install_dialogs()
        logger.info("dialogs adapter: headless (no GUI)")
    elif args.dialogs == "pyside6":
        try:
            from app.adapters.pyside6.dialogs_impl import install as _install_dialogs
            _install_dialogs()
            logger.info("dialogs adapter: pyside6 (QApplication required)")
        except Exception as e:
            logger.warning("pyside6 dialogs install failed: %s; fallback to headless", e)
            from app.adapters.headless.dialogs_impl import install as _install_dialogs
            _install_dialogs()
    else:
        logger.info("dialogs adapter: none (calls will raise)")

    server = start_server(args.host, args.port)
    logger.info("route table: %d endpoints", len(_ROUTES))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
