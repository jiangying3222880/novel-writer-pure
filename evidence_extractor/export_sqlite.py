"""
将 Phase 1-3 的结果导入 SQLite 数据库

执行顺序：
1. 创建数据库和表结构
2. 导入 Phase 1 统计指纹
3. 导入 Phase 1 句子模板
4. 导入 Phase 2 Voice 原型
5. 导入 Phase 3 Story Pattern
6. 导入角色弧光和章节模板
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, List


SCHEMA = """
CREATE TABLE IF NOT EXISTS author_fingerprints_v2 (
    book_id TEXT PRIMARY KEY,
    book_name TEXT,
    author TEXT,
    file_size INTEGER,
    total_chars INTEGER,
    total_sentences INTEGER,
    total_paragraphs INTEGER,
    avg_sentence_len REAL,
    avg_paragraph_len REAL,
    short_ratio REAL,
    medium_ratio REAL,
    long_ratio REAL,
    dialogue_ratio REAL,
    description_ratio REAL,
    inner_monologue_ratio REAL,
    exclamation_density REAL,
    ellipsis_density REAL,
    question_density REAL,
    vocabulary_richness REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sentence_patterns_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id TEXT,
    book_name TEXT,
    pattern_type TEXT,
    count INTEGER,
    ratio REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES author_fingerprints_v2(book_id)
);

CREATE TABLE IF NOT EXISTS voice_prototypes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prototype_name TEXT,
    avg_sentence_len REAL,
    question_ratio REAL,
    exclamation_ratio REAL,
    slang_ratio REAL,
    emotion_level REAL,
    characteristics TEXT,
    summary TEXT,
    book_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS story_patterns_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_name TEXT,
    pattern_category TEXT,
    description TEXT,
    event_chain TEXT,
    golden_three_chapters TEXT,
    climax_frequency TEXT,
    book_count INTEGER,
    sample_books TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS book_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id TEXT,
    author_cluster INTEGER,
    narrative_cluster INTEGER,
    dialogue_cluster INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES author_fingerprints_v2(book_id)
);

CREATE TABLE IF NOT EXISTS character_arcs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id TEXT,
    character_name TEXT,
    initial_state TEXT,
    key_changes TEXT,
    final_state TEXT,
    growth_type TEXT,
    motivation TEXT,
    conflicts TEXT,
    character_traits TEXT,
    voice_pattern TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES author_fingerprints_v2(book_id)
);

CREATE TABLE IF NOT EXISTS chapter_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id TEXT,
    chapter_index INTEGER,
    template_name TEXT,
    structure TEXT,
    key_elements TEXT,
    emotional_beat TEXT,
    dialogue_ratio REAL,
    description_ratio REAL,
    recommended_genres TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES author_fingerprints_v2(book_id)
);

CREATE TABLE IF NOT EXISTS story_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id TEXT,
    chapter_index INTEGER,
    conflict_type TEXT,
    emotion_arc TEXT,
    rhythm_pattern TEXT,
    scene_structure TEXT,
    key_events TEXT,
    pacing_score REAL,
    tension_score REAL,
    summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES author_fingerprints_v2(book_id)
);
"""


def create_database(db_path: Path) -> sqlite3.Connection:
    """创建数据库和表结构"""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    conn.commit()
    print(f"数据库创建成功: {db_path}")
    return conn


def import_fingerprints(conn: sqlite3.Connection, csv_path: Path) -> int:
    """导入 Phase 1 统计指纹"""
    cursor = conn.cursor()
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            if row.get('error'):
                continue
            
            cursor.execute("""
                INSERT OR REPLACE INTO author_fingerprints_v2 (
                    book_id, book_name, author, file_size, total_chars, total_sentences,
                    total_paragraphs, avg_sentence_len, avg_paragraph_len,
                    short_ratio, medium_ratio, long_ratio,
                    dialogue_ratio, description_ratio, inner_monologue_ratio,
                    exclamation_density, ellipsis_density, question_density,
                    vocabulary_richness
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['book_id'],
                row['book_name'],
                row.get('author', ''),
                int(row.get('file_size', 0)),
                int(row.get('total_chars', 0)),
                int(row.get('total_sentences', 0)),
                int(row.get('total_paragraphs', 0)),
                float(row.get('avg_sentence_len', 0)),
                float(row.get('avg_paragraph_len', 0)),
                float(row.get('short_ratio', 0)),
                float(row.get('medium_ratio', 0)),
                float(row.get('long_ratio', 0)),
                float(row.get('dialogue_ratio', 0)),
                float(row.get('description_ratio', 0)),
                float(row.get('inner_monologue_ratio', 0)),
                float(row.get('exclamation_density', 0)),
                float(row.get('ellipsis_density', 0)),
                float(row.get('question_density', 0)),
                float(row.get('vocabulary_richness', 0)),
            ))
            count += 1
    
    conn.commit()
    print(f"导入指纹: {count} 条")
    return count


def import_sentence_patterns(conn: sqlite3.Connection, csv_path: Path) -> int:
    """导入 Phase 1 句子模板"""
    cursor = conn.cursor()
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            cursor.execute("""
                INSERT INTO sentence_patterns_v2 (
                    book_id, book_name, pattern_type, count, ratio
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                row['book_id'],
                row['book_name'],
                row['pattern_type'],
                int(row.get('count', 0)),
                float(row.get('ratio', 0)),
            ))
            count += 1
    
    conn.commit()
    print(f"导入句子模式: {count} 条")
    return count


def import_clusters(conn: sqlite3.Connection, output_dir: Path) -> int:
    """导入 Phase 2 聚类结果"""
    cursor = conn.cursor()
    
    author_clusters = {}
    author_path = output_dir / 'phase2_author_clusters.csv'
    if author_path.exists():
        with open(author_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                author_clusters[row['book_id']] = int(row['cluster_label'])
    
    narrative_clusters = {}
    narrative_path = output_dir / 'phase2_narrative_clusters.csv'
    if narrative_path.exists():
        with open(narrative_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                narrative_clusters[row['book_id']] = int(row['cluster_label'])
    
    dialogue_clusters = {}
    dialogue_path = output_dir / 'phase2_dialogue_clusters.csv'
    if dialogue_path.exists():
        with open(dialogue_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                dialogue_clusters[row['book_id']] = int(row['cluster_label'])
    
    count = 0
    for book_id in author_clusters:
        cursor.execute("""
            INSERT INTO book_clusters (
                book_id, author_cluster, narrative_cluster, dialogue_cluster
            ) VALUES (?, ?, ?, ?)
        """, (
            book_id,
            author_clusters.get(book_id, -1),
            narrative_clusters.get(book_id, -1),
            dialogue_clusters.get(book_id, -1),
        ))
        count += 1
    
    conn.commit()
    print(f"导入聚类结果: {count} 条")
    return count


def import_voice_prototypes(conn: sqlite3.Connection, output_dir: Path) -> int:
    """导入 Phase 2 Voice 原型"""
    cursor = conn.cursor()
    
    centers_path = output_dir / 'phase2_voice_cluster_centers.json'
    if centers_path.exists():
        with open(centers_path, 'r', encoding='utf-8') as f:
            centers = json.load(f)
        
        count = 0
        for cluster_id, features in centers.items():
            cursor.execute("""
                INSERT INTO voice_prototypes (
                    prototype_name, avg_sentence_len, question_ratio,
                    exclamation_ratio, slang_ratio, emotion_level,
                    characteristics, summary, book_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                features.get('prototype_name', f"prototype_{cluster_id}"),
                features.get('avg_sentence_len', 0),
                features.get('question_ratio', 0),
                features.get('exclamation_ratio', 0),
                features.get('slang_ratio', 0),
                features.get('emotion_level', 0),
                json.dumps(features.get('characteristics', [])),
                features.get('summary', f"聚类中心 {cluster_id}"),
                0,
            ))
            count += 1
        
        conn.commit()
        print(f"导入 Voice 原型: {count} 条")
        return count
    
    print("跳过 Voice 原型导入（文件不存在）")
    return 0


def import_story_patterns(conn: sqlite3.Connection, output_dir: Path) -> int:
    """导入 Phase 3 Story Pattern"""
    cursor = conn.cursor()
    
    # 从每本书的 story_patterns.json 提取
    book_dirs = [d for d in output_dir.iterdir() if d.is_dir()]
    
    pattern_counts = {}
    patterns_data = []
    
    for book_dir in book_dirs:
        story_path = book_dir / 'story_patterns.json'
        if not story_path.exists():
            continue
        
        try:
            with open(story_path, 'r', encoding='utf-8') as f:
                patterns = json.load(f)
            
            for pattern in patterns:
                conflict_type = pattern.get('conflict_type', 'unknown')
                if conflict_type not in pattern_counts:
                    pattern_counts[conflict_type] = {'count': 0, 'books': []}
                pattern_counts[conflict_type]['count'] += 1
                pattern_counts[conflict_type]['books'].append(book_dir.name)
        except Exception as e:
            continue
    
    count = 0
    for pattern_name, data in pattern_counts.items():
        cursor.execute("""
            INSERT INTO story_patterns_v2 (
                pattern_name, pattern_category, description,
                event_chain, golden_three_chapters, climax_frequency,
                book_count, sample_books
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pattern_name,
            'conflict',
            f"{pattern_name} 类型的故事模式",
            json.dumps([]),
            '',
            '',
            data['count'],
            json.dumps(data['books'][:10]),
        ))
        count += 1
    
    conn.commit()
    print(f"导入 Story Pattern: {count} 条")
    return count


def import_character_arcs(conn: sqlite3.Connection, output_dir: Path) -> int:
    """导入 Phase 3 角色弧光"""
    cursor = conn.cursor()
    
    book_dirs = [d for d in output_dir.iterdir() if d.is_dir()]
    count = 0
    
    for book_dir in book_dirs:
        arcs_path = book_dir / 'character_arcs.json'
        if not arcs_path.exists():
            continue
        
        try:
            with open(arcs_path, 'r', encoding='utf-8') as f:
                arcs = json.load(f)
            
            for arc in arcs:
                cursor.execute("""
                    INSERT INTO character_arcs (
                        book_id, character_name, initial_state, key_changes,
                        final_state, growth_type, motivation, conflicts,
                        character_traits, voice_pattern
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    book_dir.name,
                    arc.get('character_name', ''),
                    arc.get('initial_state', ''),
                    json.dumps(arc.get('key_changes', [])),
                    arc.get('final_state', ''),
                    arc.get('growth_type', ''),
                    arc.get('motivation', ''),
                    json.dumps(arc.get('conflicts', [])),
                    json.dumps(arc.get('character_traits', [])),
                    arc.get('voice_pattern', ''),
                ))
                count += 1
        except Exception as e:
            continue
    
    conn.commit()
    print(f"导入角色弧光: {count} 条")
    return count


def import_chapter_templates(conn: sqlite3.Connection, output_dir: Path) -> int:
    """导入 Phase 3 章节模板"""
    cursor = conn.cursor()
    
    book_dirs = [d for d in output_dir.iterdir() if d.is_dir()]
    count = 0
    
    for book_dir in book_dirs:
        templates_path = book_dir / 'chapter_templates.json'
        if not templates_path.exists():
            continue
        
        try:
            with open(templates_path, 'r', encoding='utf-8') as f:
                templates = json.load(f)
            
            for template in templates:
                cursor.execute("""
                    INSERT INTO chapter_templates (
                        book_id, chapter_index, template_name, structure,
                        key_elements, emotional_beat, dialogue_ratio,
                        description_ratio, recommended_genres
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    book_dir.name,
                    template.get('chapter_index', 0),
                    template.get('template_name', ''),
                    json.dumps(template.get('structure', [])),
                    json.dumps(template.get('key_elements', [])),
                    json.dumps(template.get('emotional_beat', [])),
                    template.get('dialogue_ratio', 0),
                    template.get('description_ratio', 0),
                    json.dumps(template.get('recommended_genres', [])),
                ))
                count += 1
        except Exception as e:
            continue
    
    conn.commit()
    print(f"导入章节模板: {count} 条")
    return count


def import_story_analysis(conn: sqlite3.Connection, output_dir: Path) -> int:
    """导入 Phase 3 故事分析"""
    cursor = conn.cursor()
    
    book_dirs = [d for d in output_dir.iterdir() if d.is_dir()]
    count = 0
    
    for book_dir in book_dirs:
        story_path = book_dir / 'story_patterns.json'
        if not story_path.exists():
            continue
        
        try:
            with open(story_path, 'r', encoding='utf-8') as f:
                patterns = json.load(f)
            
            for pattern in patterns:
                cursor.execute("""
                    INSERT INTO story_analysis (
                        book_id, chapter_index, conflict_type, emotion_arc,
                        rhythm_pattern, scene_structure, key_events,
                        pacing_score, tension_score, summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    book_dir.name,
                    pattern.get('chapter_index', 0),
                    pattern.get('conflict_type', ''),
                    pattern.get('emotion_arc', ''),
                    pattern.get('rhythm_pattern', ''),
                    pattern.get('scene_structure', ''),
                    json.dumps(pattern.get('key_events', [])),
                    pattern.get('pacing_score', 0),
                    pattern.get('tension_score', 0),
                    pattern.get('summary', ''),
                ))
                count += 1
        except Exception as e:
            continue
    
    conn.commit()
    print(f"导入故事分析: {count} 条")
    return count


def verify_database(conn: sqlite3.Connection) -> None:
    """验证数据库数据"""
    cursor = conn.cursor()
    
    tables = [
        ('author_fingerprints_v2', '指纹'),
        ('sentence_patterns_v2', '句子模式'),
        ('book_clusters', '聚类结果'),
        ('voice_prototypes', 'Voice 原型'),
        ('story_patterns_v2', 'Story Pattern'),
        ('character_arcs', '角色弧光'),
        ('chapter_templates', '章节模板'),
        ('story_analysis', '故事分析'),
    ]
    
    print("\n=== 数据库验证 ===")
    for table, label in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"{label}: {count} 条")


def main():
    parser = argparse.ArgumentParser(description='将提取结果导入 SQLite')
    parser.add_argument('--input', type=str, default='D:/novel-writer-pure-v4.0/evidence_data/',
                        help='输入目录（包含 CSV 和 JSON 文件）')
    parser.add_argument('--output', type=str, default='D:/novel-writer-pure-v4.0/evidence_data/evidence.db',
                        help='输出数据库路径')
    
    args = parser.parse_args()
    
    input_dir = Path(args.input)
    db_path = Path(args.output)
    
    if not input_dir.exists():
        print(f"错误: 输入目录不存在: {input_dir}")
        return
    
    # 创建数据库
    conn = create_database(db_path)
    
    # 导入数据
    print("\n=== 开始导入数据 ===")
    
    # Phase 1
    fingerprints_path = input_dir / 'phase1_author_fingerprints.csv'
    if fingerprints_path.exists():
        import_fingerprints(conn, fingerprints_path)
    else:
        print("跳过指纹导入（文件不存在）")
    
    patterns_path = input_dir / 'phase1_sentence_patterns.csv'
    if patterns_path.exists():
        import_sentence_patterns(conn, patterns_path)
    else:
        print("跳过句子模式导入（文件不存在）")
    
    # Phase 2
    import_clusters(conn, input_dir)
    import_voice_prototypes(conn, input_dir)
    
    # Phase 3
    import_story_patterns(conn, input_dir)
    import_character_arcs(conn, input_dir)
    import_chapter_templates(conn, input_dir)
    import_story_analysis(conn, input_dir)
    
    # 验证
    verify_database(conn)
    
    conn.close()
    print(f"\n数据库导入完成！")
    print(f"路径: {db_path}")


if __name__ == '__main__':
    main()
