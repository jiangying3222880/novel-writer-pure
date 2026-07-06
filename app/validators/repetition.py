"""
G13 重复验证器 (Repetition Validator)
业务场景: 检测章节内重复的字/词/短语/段落, 提升可读性.
  - 4 字以上短语重复 ≥ 3 次
  - 句子重复 ≥ 2 次
  - 段落完全相同 ≥ 2 次
  - 高频词 (top5) 占比 > 8% (说明作者卡词)

设计:
  - N-gram 检测: 中文按字 2-gram / 3-gram / 4-gram
  - 段落去重: 用 set of trimmed lines
  - 频率统计: Counter

与 G5 的区别:
  - G5 = 4 维语义矛盾
  - G13 = 文本重复度 (质量改进, 不是矛盾)
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from .base import (
    BaseValidator, ValidationIssue, ValidatorResult,
    DIM_REPETITION, SEV_INFO, SEV_WARNING, SEV_ERROR,
)


# 中文 2/3/4 gram 阈值
NGRAM_THRESHOLDS = {
    2: 8,   # 2 字短语重复 ≥ 8 次
    3: 5,   # 3 字短语重复 ≥ 5 次
    4: 3,   # 4 字短语重复 ≥ 3 次
}

# 句子重复阈值 (2 句完全相同就警告)
SENTENCE_REPEAT_THRESHOLD = 2

# 段落重复阈值
PARA_REPEAT_THRESHOLD = 2

# 高频词占比阈值
TOP_WORD_RATIO = 0.08

# 最小章节长度 (低于此跳过, 避免过短章节产生噪声)
MIN_CHAPTER_LEN = 30


class RepetitionValidator(BaseValidator):
    """G13 重复验证器: 短语/句子/段落重复 + 高频词占比."""

    dimension = DIM_REPETITION
    name = "重复"

    def _do_validate(self, project_id: str, chapter_id: str,
                      content: str, chapter_no: int,
                      context: dict) -> ValidatorResult:
        result = ValidatorResult(dimension=self.dimension)

        if not content or len(content) < MIN_CHAPTER_LEN:
            return result

        # 去标点 (保留中文字符)
        text = re.sub(r"[^\u4e00-\u9fff]", "", content)

        # 1) N-gram 重复 (2/3/4 字)
        for n in (2, 3, 4):
            issues = self._check_ngram(text, content, n, chapter_no)
            result.issues.extend(issues)

        # 2) 句子重复
        sentence_issues = self._check_sentences(content, chapter_no)
        result.issues.extend(sentence_issues)

        # 3) 段落重复
        para_issues = self._check_paragraphs(content, chapter_no)
        result.issues.extend(para_issues)

        # 4) 高频词占比
        top_word_issues = self._check_top_words(text, content, chapter_no)
        result.issues.extend(top_word_issues)

        return result

    # ------------------------------------------------------------------
    def _check_ngram(self, text: str, content: str, n: int,
                      chapter_no: int) -> list:
        """N-gram 重复检测."""
        issues: list = []
        min_len = n * NGRAM_THRESHOLDS[n]
        if len(text) < min_len:
            return issues
        # 生成 n-gram
        grams = [text[i:i+n] for i in range(len(text) - n + 1)]
        cnt = Counter(grams)
        threshold = NGRAM_THRESHOLDS[n]
        # 过滤常见短语 (常用成语/连接词) - 只在 gram 完全等于常见短语时过滤
        # 注意: 之前是 any(p in gram) 太宽, 会把 "心中充满期待" 这种有意义的也过滤掉
        common_phrases = {"的", "了", "是", "在", "有", "和", "与", "或", "及", "之",
                          "而是", "并不", "并没有", "一个", "这个", "那个", "什么",
                          "怎么", "这样", "那样", "这里", "那里", "我们", "他们",
                          "她们", "什么", "可能", "或许", "似乎", "仿佛", "如同"}
        # 完全匹配过滤: gram 本身就是常见短语
        reported: set = set()
        for gram, c in cnt.most_common(20):
            if c < threshold:
                break
            # 只过滤 完全等于 常见短语 的, 不要子串过滤
            if gram in common_phrases:
                continue
            if gram in reported:
                continue
            reported.add(gram)
            # 找首次出现位置
            pos = content.find(gram)
            # 严重度: c >= threshold*2 = ERROR (严重重复), >= threshold = WARNING (达到阈值)
            if c >= threshold * 2:
                sev = SEV_ERROR
            elif c >= threshold:
                sev = SEV_WARNING
            else:
                sev = SEV_INFO
            issues.append(ValidationIssue(
                dimension=self.dimension,
                severity=sev,
                description=f"{n} 字短语 '{gram}' 出现 {c} 次 (≥ {threshold}), 重复度过高",
                chapter_no=chapter_no,
                char_start=pos if pos >= 0 else None,
                char_end=(pos + n) if pos >= 0 else None,
                suggestion=f"考虑替换部分 '{gram}' 为同义词或简化",
                related=gram,
            ))
        return issues

    def _check_sentences(self, content: str, chapter_no: int) -> list:
        """句子重复: 完整句子重复 ≥ 2 次."""
        issues: list = []
        # 切句 (支持中英文句末标点 + 换行)
        sents = re.split(r"[。！？.!?\n]+", content)
        sents = [s.strip() for s in sents if len(s.strip()) >= 10]
        cnt = Counter(sents)
        reported: set = set()
        for s, c in cnt.most_common(5):
            if c < SENTENCE_REPEAT_THRESHOLD:
                break
            if s in reported:
                continue
            reported.add(s)
            pos = content.find(s)
            issues.append(ValidationIssue(
                dimension=self.dimension,
                severity=SEV_ERROR,
                description=f"句子重复 {c} 次: '{s[:50]}{'...' if len(s) > 50 else ''}'",
                chapter_no=chapter_no,
                char_start=pos if pos >= 0 else None,
                char_end=(pos + len(s)) if pos >= 0 else None,
                suggestion="删除或重写重复句子, 保留一处即可",
                related=s[:30],
            ))
        return issues

    def _check_paragraphs(self, content: str, chapter_no: int) -> list:
        """段落重复: 完全相同段落 ≥ 2 次."""
        issues: list = []
        # 支持 \n\n 和单 \n
        paras = re.split(r"\n\s*\n|\n", content)
        paras = [p.strip() for p in paras if len(p.strip()) >= 30]
        cnt = Counter(paras)
        reported: set = set()
        for p, c in cnt.most_common(3):
            if c < PARA_REPEAT_THRESHOLD:
                break
            if p in reported:
                continue
            reported.add(p)
            pos = content.find(p)
            issues.append(ValidationIssue(
                dimension=self.dimension,
                severity=SEV_ERROR,
                description=f"段落完全重复 {c} 次 (长度 {len(p)} 字符)",
                chapter_no=chapter_no,
                char_start=pos if pos >= 0 else None,
                char_end=(pos + len(p)) if pos >= 0 else None,
                suggestion="删除重复段落, 保留一处即可",
                related=p[:30],
            ))
        return issues

    def _check_top_words(self, text: str, content: str, chapter_no: int) -> list:
        """高频词占比: top5 词 / 总字数 > 8%."""
        issues: list = []
        if len(text) < 50:
            return issues
        # 单字
        words = list(text)
        cnt = Counter(words)
        top5 = cnt.most_common(5)
        # 排除常用字
        common_chars = {"的", "了", "是", "在", "有", "和", "我", "你", "他", "她", "它", "们",
                        "中", "上", "下", "不", "也", "都", "就", "要", "说", "对", "看", "把",
                        "那", "这", "里", "么", "来", "去", "到", "会", "能", "为", "与", "及",
                        "之", "以", "于", "从", "向", "由", "而", "但", "却", "或", "如", "若",
                        "虽", "所", "其", "则", "乃", "即", "曾", "已", "未", "将", "方", "正"}
        meaningful_top = [(w, c) for w, c in top5 if w not in common_chars]
        if not meaningful_top:
            return issues
        # top1 有意义词的占比
        top1_word, top1_count = meaningful_top[0]
        ratio = top1_count / len(words)
        if ratio > TOP_WORD_RATIO:
            pos = content.find(top1_word)
            issues.append(ValidationIssue(
                dimension=self.dimension,
                severity=SEV_INFO,
                description=f"高频字 '{top1_word}' 出现 {top1_count} 次, 占比 {ratio*100:.1f}% (>{TOP_WORD_RATIO*100:.0f}%), 建议替换部分为同义词",
                chapter_no=chapter_no,
                char_start=pos if pos >= 0 else None,
                char_end=(pos + 1) if pos >= 0 else None,
                suggestion=f"考虑用其他动词/名词替换部分 '{top1_word}'",
                related=top1_word,
            ))
        return issues
