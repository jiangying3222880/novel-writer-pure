"""
Phase 1: 全量统计

对每本书提取：
- Author 统计指纹（句长、对白占比、标点密度等）
- 句子模板提取
- Scene 统计

支持：
- 先用 --limit 10 跑通验证
- 全量处理 4396 本书
- 逐本处理，释放内存
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Dict, Any, List

from utils import (
    read_file, parse_book_filename, split_sentences, classify_sentence_length,
    extract_dialogue, split_paragraphs, count_punctuation, calculate_ttr,
    detect_sentence_pattern, clean_text, report_progress,
)


# ============================================================
# 统计单本书
# ============================================================

def analyze_book(file_path: Path) -> Dict[str, Any]:
    """
    分析单本书，提取统计特征。
    
    Returns:
        dict: 统计结果
    """
    try:
        # 解析文件名
        meta = parse_book_filename(file_path.name)
        book_id = meta['book_id']
        book_name = meta['book_name']
        author = meta['author']
        
        # 读取文件
        raw_text = read_file(file_path)
        
        # 清理文本
        text = clean_text(raw_text)
        
        if not text:
            return {
                'book_id': book_id,
                'book_name': book_name,
                'author': author,
                'file_size': file_path.stat().st_size,
                'error': '文件内容为空',
            }
        
        # 分句
        sentences = split_sentences(text)
        
        # 段落
        paragraphs = split_paragraphs(text)
        
        # 对白提取
        dialogue_text, description_text = extract_dialogue(text)
        
        # 标点统计
        punctuation = count_punctuation(text)
        
        # 统计句长分布
        sentence_lengths = [classify_sentence_length(s) for s in sentences]
        short_count = sentence_lengths.count('short')
        medium_count = sentence_lengths.count('medium')
        long_count = sentence_lengths.count('long')
        total_sentences = len(sentences)
        
        # 模式统计
        patterns = [detect_sentence_pattern(s) for s in sentences]
        pattern_counts = {}
        for p in patterns:
            pattern_counts[p] = pattern_counts.get(p, 0) + 1
        
        # 计算比例
        total_chars = len(text)
        dialogue_chars = len(dialogue_text)
        description_chars = len(description_text)
        
        # 词汇丰富度（采样前 10000 字）
        ttr = calculate_ttr(text[:10000])
        
        return {
            'book_id': book_id,
            'book_name': book_name,
            'author': author,
            'file_size': file_path.stat().st_size,
            'total_chars': total_chars,
            'total_sentences': total_sentences,
            'total_paragraphs': len(paragraphs),
            'avg_sentence_len': total_chars / total_sentences if total_sentences > 0 else 0,
            'avg_paragraph_len': total_chars / len(paragraphs) if paragraphs else 0,
            'short_ratio': short_count / total_sentences if total_sentences > 0 else 0,
            'medium_ratio': medium_count / total_sentences if total_sentences > 0 else 0,
            'long_ratio': long_count / total_sentences if total_sentences > 0 else 0,
            'dialogue_ratio': dialogue_chars / total_chars if total_chars > 0 else 0,
            'description_ratio': description_chars / total_chars if total_chars > 0 else 0,
            'inner_monologue_ratio': 0.0,  # 待实现
            'exclamation_density': punctuation['exclamation'] / total_chars if total_chars > 0 else 0,
            'ellipsis_density': punctuation['ellipsis'] / total_chars if total_chars > 0 else 0,
            'question_density': punctuation['question'] / total_chars if total_chars > 0 else 0,
            'vocabulary_richness': ttr,
            'pattern_counts': pattern_counts,
            'error': '',
        }
    
    except Exception as e:
        meta = parse_book_filename(file_path.name)
        return {
            'book_id': meta['book_id'],
            'book_name': meta['book_name'],
            'author': meta['author'],
            'file_size': file_path.stat().st_size,
            'error': str(e),
        }


# ============================================================
# 批量处理
# ============================================================

def process_batch(
    input_dir: Path,
    output_dir: Path,
    limit: int = None,
    skip_errors: bool = True,
) -> None:
    """
    批量处理小说文件。
    
    Args:
        input_dir: 小说文件目录
        output_dir: 输出目录
        limit: 限制处理数量
        skip_errors: 是否跳过错误文件
    """
    # 获取所有 txt 文件
    txt_files = sorted(input_dir.glob('*.txt'))
    
    # 过滤 PDF 文件（可能混入）
    txt_files = [f for f in txt_files if not f.name.lower().endswith('.pdf')]
    
    # 限制数量
    if limit:
        txt_files = txt_files[:limit]
    
    total = len(txt_files)
    start_time = time.time()
    
    print(f"开始处理 {total} 本书...")
    
    # 创建输出文件
    output_dir.mkdir(parents=True, exist_ok=True)
    
    fingerprints_file = output_dir / 'phase1_author_fingerprints.csv'
    patterns_file = output_dir / 'phase1_sentence_patterns.csv'
    log_file = output_dir / 'extraction_log.jsonl'
    errors_file = output_dir / 'errors.jsonl'
    
    # CSV 表头
    fingerprint_fields = [
        'book_id', 'book_name', 'author', 'file_size',
        'total_chars', 'total_sentences', 'total_paragraphs',
        'avg_sentence_len', 'avg_paragraph_len',
        'short_ratio', 'medium_ratio', 'long_ratio',
        'dialogue_ratio', 'description_ratio', 'inner_monologue_ratio',
        'exclamation_density', 'ellipsis_density', 'question_density',
        'vocabulary_richness',
    ]
    
    # 打开文件
    with open(fingerprints_file, 'w', encoding='utf-8', newline='') as f_fp, \
         open(patterns_file, 'w', encoding='utf-8', newline='') as f_pt, \
         open(log_file, 'w', encoding='utf-8') as f_log:
        
        fp_writer = csv.DictWriter(f_fp, fieldnames=fingerprint_fields)
        fp_writer.writeheader()
        
        pt_writer = csv.writer(f_pt)
        pt_writer.writerow(['book_id', 'book_name', 'pattern_type', 'count', 'ratio'])
        
        error_lines = []
        
        for i, file_path in enumerate(txt_files, 1):
            # 进度报告
            if i % 100 == 0 or i == total:
                report_progress(i, total, start_time, log_file)
            
            # 分析
            result = analyze_book(file_path)
            
            # 记录日志
            log_entry = {
                'book_id': result['book_id'],
                'book_name': result['book_name'],
                'file': file_path.name,
                'processed_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                'has_error': bool(result.get('error')),
            }
            f_log.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            
            # 处理错误
            if result.get('error'):
                error_lines.append({
                    'book_id': result['book_id'],
                    'book_name': result['book_name'],
                    'file': file_path.name,
                    'error': result['error'],
                })
                if not skip_errors:
                    continue
            
            # 写入指纹 CSV
            fp_row = {k: result[k] for k in fingerprint_fields}
            fp_writer.writerow(fp_row)
            
            # 写入模式统计
            pattern_counts = result.get('pattern_counts', {})
            total_sentences = result.get('total_sentences', 1)
            for pattern_type, count in pattern_counts.items():
                pt_writer.writerow([
                    result['book_id'],
                    result['book_name'],
                    pattern_type,
                    count,
                    count / total_sentences if total_sentences > 0 else 0,
                ])
        
        # 写入错误日志
        if error_lines:
            with open(errors_file, 'w', encoding='utf-8') as f_err:
                for line in error_lines:
                    f_err.write(json.dumps(line, ensure_ascii=False) + '\n')
    
    elapsed = time.time() - start_time
    print(f"\n处理完成！共 {total} 本，耗时 {elapsed:.1f}s")
    print(f"输出文件:")
    print(f"  - {fingerprints_file}")
    print(f"  - {patterns_file}")
    print(f"  - {log_file}")
    if error_lines:
        print(f"  - {errors_file} ({len(error_lines)} 个错误)")


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Phase 1: 小说全量统计')
    parser.add_argument('--input', type=str, default='F:/AI学习资料/小说/',
                        help='小说文件目录')
    parser.add_argument('--output', type=str, default='D:/novel-writer-pure-v4.0/evidence_data/',
                        help='输出目录')
    parser.add_argument('--limit', type=int, default=None,
                        help='限制处理数量（用于验证）')
    parser.add_argument('--skip-errors', action='store_true', default=True,
                        help='跳过错误文件继续处理')
    
    args = parser.parse_args()
    
    input_dir = Path(args.input)
    output_dir = Path(args.output)
    
    if not input_dir.exists():
        print(f"错误: 输入目录不存在: {input_dir}")
        return
    
    process_batch(input_dir, output_dir, args.limit, args.skip_errors)


if __name__ == '__main__':
    main()
