"""
AI 工具 (A6: 完整做)
- JSON 容错 (3 种回退)
- 流式拼接
"""
from __future__ import annotations
import json
import logging
import re
from typing import Optional, Callable, Generator

_logger = logging.getLogger("NovelWriter.ai.utils")


# ────────────────────── JSON 容错 (3 种回退) ──────────────────────

def safe_parse_json(text: str, default=None) -> Optional[dict | list]:
    """
    AI 返回 JSON 残缺时的 3 种回退:
    1. 直接 json.loads
    2. 提取 ```json ... ``` 块
    3. 找第一个 { 或 [ 到最后一个 } 或 ]
    4. 全部失败 -> 返回 default
    """
    if not text:
        return default
    # 1) 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2) 提取 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 3) 找第一个 { 或 [ 到最后一个 } 或 ]
    # 优先 { 开头
    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        candidate = text[start:end]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    if "[" in text and "]" in text:
        start = text.find("[")
        end = text.rfind("]") + 1
        candidate = text[start:end]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    _logger.warning("JSON 容错全部失败: %s", text[:100])
    return default


def extract_json_object(text: str, default: dict = None) -> dict:
    """从文本提取 JSON 对象 (dict)。失败返回 default。"""
    result = safe_parse_json(text, default=default)
    if isinstance(result, dict):
        return result
    return default if default is not None else {}


# ────────────────────── 流式拼接 ──────────────────────

class StreamAssembler:
    """
    流式输出拼接器。
    - SSE 格式 (data: {...})
    - 一边收 chunk, 一边回调
    - 完成后返回完整文本
    """
    def __init__(self, on_chunk: Optional[Callable[[str], None]] = None):
        self.text = ""
        self.thinking = ""
        self.on_chunk = on_chunk

    def feed(self, raw_line: str) -> str:
        """
        喂入 1 行 SSE。
        返回这次新增的文本 (不含 thinking)。
        """
        if not raw_line or not raw_line.startswith("data:"):
            return ""
        data = raw_line[len("data:"):].strip()
        if data == "[DONE]":
            return ""
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            return ""
        delta = self._extract_delta(chunk)
        if delta:
            self.text += delta
            if self.on_chunk:
                try:
                    self.on_chunk(delta)
                except Exception as e:
                    _logger.exception("on_chunk 失败: %s", e)
        return delta

    def _extract_delta(self, chunk: dict) -> str:
        # OpenAI 兼容格式
        if "choices" in chunk:
            choices = chunk["choices"]
            if choices and "delta" in choices[0]:
                delta = choices[0]["delta"]
                if "content" in delta and delta["content"]:
                    return delta["content"]
        # Anthropic 格式
        if chunk.get("type") == "content_block_delta":
            delta = chunk.get("delta", {})
            if delta.get("type") == "text_delta":
                return delta.get("text", "")
        return ""

    def feed_openai_compat(self, line: str) -> str:
        """OpenAI 兼容流 (data: {...})。"""
        return self.feed(line)

    def feed_anthropic(self, event: dict) -> str:
        """
        Anthropic 流式事件。
        事件类型: message_start / content_block_start / content_block_delta / ...
        """
        etype = event.get("type", "")
        if etype == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if text:
                    self.text += text
                    if self.on_chunk:
                        self.on_chunk(text)
                return text
        return ""


# ────────────────────── 工具: 估算 token 数 ──────────────────────

def estimate_tokens(text: str) -> int:
    """
    粗估 token 数。
    - 中文: 1 字 ≈ 1.5 token
    - 英文: 1 词 ≈ 1.3 token
    - 标点: 1 ≈ 0.5 token
    """
    if not text:
        return 0
    # 中文字符
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    # 英文单词
    english = len(re.findall(r"\b[a-zA-Z]+\b", text))
    # 标点
    punct = len(re.findall(r"[^\w\s]", text))
    return int(chinese * 1.5 + english * 1.3 + punct * 0.5)
