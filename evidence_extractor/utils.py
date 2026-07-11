"""
证据提取工具函数

独立模块，不依赖项目其他代码，避免后续冲突。
包含：编码检测、分句、对白提取、书名解析、分词等。
"""
from __future__ import annotations

import re
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


# ============================================================
# 编码检测
# ============================================================

def detect_encoding(file_path: Path) -> str:
    """
    检测文件编码，优先尝试 UTF-8，失败则尝试 GBK。
    
    Returns:
        str: 'utf-8' 或 'gbk'
    """
    encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030']
    
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                f.read(1024)
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    
    return 'utf-8'


def read_file(file_path: Path) -> str:
    """
    读取文件，自动检测编码。
    
    Returns:
        str: 文件内容
    """
    enc = detect_encoding(file_path)
    try:
        with open(file_path, 'r', encoding=enc) as f:
            return f.read()
    except Exception as e:
        raise RuntimeError(f"读取文件失败 {file_path}: {e}") from e


# ============================================================
# 书名解析
# ============================================================

def parse_book_filename(filename: str) -> Dict[str, str]:
    """
    解析小说文件名，提取书名和作者。
    
    支持的格式：
    - 《百炼成仙》（校对版全本）作者：幻雨.txt
    - 《武动乾坤》（精修版全本）作者：天蚕土豆.txt
    - 【快穿】心机美人下蛊日常_7063854455711599624.txt
    - 00后已退休，开局拒绝清冷校花_7319024171596401726.txt
    
    Returns:
        dict: {'book_name': str, 'author': str, 'book_id': str}
    """
    book_name = ""
    author = ""
    
    # 去掉扩展名
    name = filename
    if name.endswith('.txt'):
        name = name[:-4]
    
    # 模式1：《书名》（版本）作者：作者名
    match = re.match(r'《(.+?)》.*作者[：:]\s*([^.]+)', name)
    if match:
        book_name = match.group(1).strip()
        author = match.group(2).strip()
    
    # 模式2：【题材】书名
    if not book_name:
        match = re.match(r'【(.+?)】(.+)', name)
        if match:
            book_name = match.group(2).strip()
    
    # 模式3：书名_数字
    if not book_name:
        match = re.match(r'(.+)_\d+$', name)
        if match:
            book_name = match.group(1).strip()
    
    # 模式4：纯书名
    if not book_name:
        book_name = name.strip()
    
    # 清理书名中的版本信息
    book_name = re.sub(r'[（(].*[）)]', '', book_name).strip()
    
    # 生成确定性 ID
    book_id = hashlib.md5(f"{book_name}_{author}".encode('utf-8')).hexdigest()[:16]
    
    return {
        'book_name': book_name,
        'author': author,
        'book_id': book_id,
    }


# ============================================================
# 分句
# ============================================================

def split_sentences(text: str) -> List[str]:
    """
    按中文标点分句。
    
    分句规则：
    - 按 。！？ 分句
    - 保留标点在句子末尾
    - 过滤空句子
    
    Returns:
        list[str]: 句子列表
    """
    if not text:
        return []
    
    # 按标点分句，但保留标点
    sentences = re.split(r'([。！？！\n\r]+)', text)
    
    # 合并标点到前一句
    result = []
    current = ""
    for part in sentences:
        if part in '。！？！\n\r':
            if current.strip():
                result.append(current.strip() + part)
                current = ""
        else:
            current += part
    
    if current.strip():
        result.append(current.strip())
    
    return result


def classify_sentence_length(sentence: str) -> str:
    """
    按字数分类句子长度。
    
    Returns:
        str: 'short' (<=15字), 'medium' (16-35字), 'long' (>35字)
    """
    # 去掉标点后的字数
    clean = re.sub(r'[。！？，；：、"\"「」（）\s]', '', sentence)
    length = len(clean)
    
    if length <= 15:
        return 'short'
    elif length <= 35:
        return 'medium'
    else:
        return 'long'


# ============================================================
# 对白提取
# ============================================================

def extract_dialogue(text: str) -> Tuple[str, str]:
    """
    提取对白内容。
    
    支持多种引号格式：
    - 中文弯引号："" ""
    - 中文直角引号：「」
    - 英文双引号：""
    - 英文单引号：''
    
    Returns:
        tuple: (dialogue_text, description_text)
    """
    if not text:
        return "", ""
    
    dialogue_parts = []
    
    # 中文弯引号 ""..."" (U+201C 和 U+201D)
    for match in re.finditer(r'\u201c([^\u201d]+)\u201d', text):
        dialogue_parts.append(match.group(1))
    
    # 中文直角引号 「...」
    for match in re.finditer(r'「([^」]+)」', text):
        dialogue_parts.append(match.group(1))
    
    # 中文直角引号 『...』
    for match in re.finditer(r'『([^』]+)』', text):
        dialogue_parts.append(match.group(1))
    
    # 英文双引号 "..."
    for match in re.finditer(r'"([^"]+)"', text):
        dialogue_parts.append(match.group(1))
    
    # 英文单引号 '...'
    for match in re.finditer(r"'([^']+)'", text):
        dialogue_parts.append(match.group(1))
    
    dialogue_text = ''.join(dialogue_parts)
    
    # 移除对白后的文本作为描写
    description_text = re.sub(r'\u201c[^\u201d]+\u201d', '', text)
    description_text = re.sub(r'「[^」]+」', '', description_text)
    description_text = re.sub(r'『[^』]+』', '', description_text)
    description_text = re.sub(r'"[^"]+"', '', description_text)
    description_text = re.sub(r"'[^']+'", '', description_text)
    
    return dialogue_text, description_text


# ============================================================
# 段落分割
# ============================================================

def split_paragraphs(text: str) -> List[str]:
    """
    按换行分割段落。
    
    中文小说通常用单换行分段，需要：
    - 按单个换行符分割
    - 过滤过短行（<2字的可能是分隔线或空行）
    - 将连续短行合并为段落
    
    Returns:
        list[str]: 段落列表
    """
    if not text:
        return []
    
    # 按单个换行符分割
    lines = text.split('\n')
    
    # 过滤空行和过短行，合并连续短行
    paragraphs = []
    current_paragraph = []
    
    for line in lines:
        line = line.strip()
        
        # 跳过空行
        if not line:
            if current_paragraph:
                paragraphs.append(''.join(current_paragraph))
                current_paragraph = []
            continue
        
        # 跳过分隔线（纯符号行）
        if re.match(r'^[=*#-~—\\s]+$', line):
            if current_paragraph:
                paragraphs.append(''.join(current_paragraph))
                current_paragraph = []
            continue
        
        # 短行（<20字）可能是段落的一部分，合并
        if len(line) < 20 and current_paragraph:
            current_paragraph.append(line)
        else:
            if current_paragraph:
                paragraphs.append(''.join(current_paragraph))
            current_paragraph = [line]
    
    if current_paragraph:
        paragraphs.append(''.join(current_paragraph))
    
    return paragraphs


# ============================================================
# 标点密度统计
# ============================================================

def count_punctuation(text: str) -> Dict[str, int]:
    """
    统计标点符号出现次数。
    
    Returns:
        dict: {'exclamation': int, 'ellipsis': int, 'question': int}
    """
    counts = {
        'exclamation': text.count('！') + text.count('!'),
        'ellipsis': text.count('…') + text.count('...'),
        'question': text.count('？') + text.count('?'),
        'comma': text.count('，') + text.count(','),
        'period': text.count('。') + text.count('.'),
    }
    return counts


# ============================================================
# 分词（基于正则，不依赖 jieba）
# ============================================================

STOPWORDS_ZH = frozenset("""
的 了 在 是 我 有 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看
好 自己 这 那 能 好 多 么 就 像 从 们 我 你 他 她 它 这 那 哪 几 谁 什么
怎么 怎样 如何 为什么 因为 所以 但是 然而 虽然 即使 如果 要是 只有 只要
就 才 都 也 还 又 再 更 最 太 非常 十分 特别 很 挺 比较 稍微 一点儿
可以 能够 会 愿意 应该 值得 敢于 要 想 希望 打算 计划 准备 开始 继续
完成 结束 停止 放弃 坚持 努力 尝试 学习 工作 生活 爱情 友情 亲情 金钱
权力 地位 名声 财富 健康 幸福 快乐 悲伤 痛苦 愤怒 恐惧 焦虑 希望 绝望
人生 命运 机遇 挑战 困难 挫折 成功 失败 成长 进步 退步 变化 不变
时间 空间 过去 现在 未来 昨天 今天 明天 小时 分钟 秒 年 月 日 星期
春夏秋冬 早晚 昼夜 黄昏 黎明 午夜 正午 凌晨 傍晚 深夜 凌晨 清晨
东西南北 前后左右 上下内外 中间旁边 远近高低 大小长短 宽窄粗细 厚薄软硬
轻重快慢 强弱冷热 明暗快慢 好坏美丑 真假虚实 新旧多少 有无难易 生死存亡
爱恨情仇 善恶美丑 是非对错 正邪黑白 好坏优劣 成败得失 进退攻守 生死存亡
""" .split())

STOPWORDS_EN = frozenset("""
a an the is are was were be been being have has had do does did will would shall should
can could may might must need dare ought to of in on at by for with from as into about
and or but if then else when while until than this that these those it its they them
""" .split())

STOPWORDS_PUNCT = frozenset([
    '，', '。', '！', '？', '、', '；', '：', '"', "'",
    '（', '）', '(', ')', '【', '】', '《', '》',
    '…', '—', '·', '-', '——', '/', '\n', '\r', '\t',
    '.', ',', '!', '?', ';', ':', '"', "'",
    '[', ']', '{', '}', '<', '>', '\\', ' ',
])

STOPWORDS = STOPWORDS_ZH | STOPWORDS_PUNCT | STOPWORDS_EN

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z]+|\d+", re.UNICODE)


def tokenize(text: str) -> List[str]:
    """
    分词（纯正则实现，不依赖 jieba）。
    
    Returns:
        list[str]: 词列表
    """
    if not text:
        return []
    
    text = text.lower()
    raw = _TOKEN_RE.findall(text)
    
    out = []
    for t in raw:
        t = t.strip()
        if not t or t in STOPWORDS:
            continue
        if all(c in STOPWORDS_PUNCT for c in t):
            continue
        if len(t) == 1 and not _TOKEN_RE.match(t):
            continue
        out.append(t)
    
    return out


def calculate_ttr(text: str) -> float:
    """
    计算词汇丰富度（Type-Token Ratio）。
    
    Returns:
        float: 0-1 之间的值
    """
    tokens = tokenize(text)
    if not tokens:
        return 0.0
    types = set(tokens)
    return len(types) / len(tokens)


# ============================================================
# 句子模式识别
# ============================================================

def detect_sentence_pattern(sentence: str) -> str:
    """
    识别句子结构模式。
    
    Returns:
        str: 模式名称，如 'action_pause', 'scene_memory', 'dialogue_tension'
    """
    sentence_lower = sentence.lower()
    
    # 连续短对白（角色说：...）
    if re.search(r'[“"]([^”"]+)[”"]', sentence_lower):
        return 'dialogue'
    
    # 动作+停顿
    if len(sentence) <= 15 and re.search(r'[。！？]$', sentence):
        return 'action_short'
    
    # 环境描写（包含感官词）
    sensory_words = ['看见', '听到', '闻到', '感觉', '触摸', '声音', '颜色', '光线', '温度']
    if any(kw in sentence for kw in sensory_words):
        return 'sensory_description'
    
    # 情绪表达
    emotion_words = ['突然', '终于', '不禁', '忍不住', '眼泪', '笑了', '哭了', '愤怒', '悲伤']
    if any(kw in sentence for kw in emotion_words):
        return 'emotion_expression'
    
    # 内心独白
    if re.search(r'想[：:]', sentence_lower):
        return 'inner_monologue'
    
    return 'narrative'


# ============================================================
# 文本清理
# ============================================================

def clean_text(text: str) -> str:
    """
    清理文本：移除广告、版权声明等。
    
    Returns:
        str: 清理后的文本
    """
    if not text:
        return ""
    
    # 移除常见广告
    patterns = [
        r'本站.*首发',
        r'请记住本书首发域名',
        r'手机版阅读网址',
        r'全文字阅读',
        r'无弹窗阅读',
        r'最新网址',
        r'本章已完成',
        r'本章未完，请点击下一页继续阅读',
        r'^\s*[=*#-]{10,}\s*$',  # 分割线
    ]
    
    for pattern in patterns:
        text = re.sub(pattern, '', text, flags=re.MULTILINE)
    
    # 移除多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


# ============================================================
# 进度报告
# ============================================================

def report_progress(current: int, total: int, start_time: float, log_file: Optional[Path] = None) -> None:
    """
    输出进度报告。
    
    Args:
        current: 当前处理数
        total: 总数
        start_time: 开始时间（time.time()）
        log_file: 日志文件路径
    """
    import time
    
    elapsed = time.time() - start_time
    progress = (current / total) * 100
    eta = elapsed / current * (total - current) if current > 0 else 0
    
    msg = f"进度: {current}/{total} ({progress:.1f}%) | 已用: {elapsed:.1f}s | 预计剩余: {eta:.1f}s"
    print(msg)
    
    if log_file:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n")
