"""
证据提取器主入口

用法：
    python run_extractor.py --phase all           # 运行所有阶段
    python run_extractor.py --phase 1             # 仅运行 Phase 1
    python run_extractor.py --phase 1 --limit 10  # 运行 Phase 1，限制 10 本书
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_phase1(input_dir: str, output_dir: str, limit: int = None) -> None:
    """运行 Phase 1: 全量统计"""
    cmd = [sys.executable, 'phase1_statistics.py']
    cmd.extend(['--input', input_dir])
    cmd.extend(['--output', output_dir])
    if limit:
        cmd.extend(['--limit', str(limit)])
    
    subprocess.run(cmd, check=True)


def run_phase2(input_dir: str, output_dir: str, n_clusters: int = 8) -> None:
    """运行 Phase 2: 向量聚类"""
    cmd = [sys.executable, 'phase2_clustering.py']
    cmd.extend(['--input', input_dir])
    cmd.extend(['--output', output_dir])
    cmd.extend(['--n-clusters', str(n_clusters)])
    
    subprocess.run(cmd, check=True)


def run_phase3(input_dir: str, output_dir: str, limit: int = None) -> None:
    """运行 Phase 3: LLM 蒸馏"""
    cmd = [sys.executable, 'phase3_distillation.py']
    cmd.extend(['--input', input_dir])
    cmd.extend(['--output', output_dir])
    if limit:
        cmd.extend(['--limit', str(limit)])
    
    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser(description='证据提取器')
    parser.add_argument('--phase', type=str, choices=['1', '2', '3', 'all'],
                        default='all', help='运行阶段')
    parser.add_argument('--input', type=str, default='F:/AI学习资料/小说/',
                        help='小说文件目录')
    parser.add_argument('--output', type=str, default='D:/novel-writer-pure-v4.0/evidence_data/',
                        help='输出目录')
    parser.add_argument('--limit', type=int, default=None,
                        help='限制处理数量（用于验证）')
    parser.add_argument('--n-clusters', type=int, default=8,
                        help='Phase 2 聚类数量')
    
    args = parser.parse_args()
    
    # 切换到脚本目录
    script_dir = Path(__file__).parent
    original_cwd = Path.cwd()
    try:
        import os
        os.chdir(script_dir)
        
        print(f"=== 证据提取器 ===")
        print(f"输入目录: {args.input}")
        print(f"输出目录: {args.output}")
        print(f"运行阶段: {args.phase}")
        if args.limit:
            print(f"限制数量: {args.limit}")
        print()
        
        if args.phase in ['1', 'all']:
            print("--- 运行 Phase 1: 全量统计 ---")
            run_phase1(args.input, args.output, args.limit)
            print()
        
        if args.phase in ['2', 'all']:
            print("--- 运行 Phase 2: 向量聚类 ---")
            run_phase2(args.input, args.output, args.n_clusters)
            print()
        
        if args.phase in ['3', 'all']:
            print("--- 运行 Phase 3: LLM 蒸馏 ---")
            run_phase3(args.input, args.output, args.limit)
            print()
        
        print("=== 所有阶段完成 ===")
    
    finally:
        os.chdir(original_cwd)


if __name__ == '__main__':
    main()
