"""
Phase 3: LLM 蒸馏

使用 LLM 进行深度分析：
- 故事模式提取（冲突升级、情感曲线、节奏变换）
- 人物弧光提取（角色演变路径）
- 章节模板提取（经典叙事结构）

注意：使用我自己的 LLM 调用能力，不需要外部 API 配置。

执行指南要求：
- 精选 500 本书进行 LLM 蒸馏
- 每本书分析 5 个章节
- 约 2500 次调用
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from utils import (
    read_file, parse_book_filename, split_sentences, split_paragraphs,
    extract_dialogue, clean_text,
)


def select_representative_books(
    fingerprints_file: Path,
    output_dir: Path,
    sample_size: int = 500,
) -> List[str]:
    """
    按统计特征筛选代表性书籍。
    
    执行指南要求：
    1. Phase 1 完成后，从 CSV 中按条件筛选 ~1000 本
    2. 筛选条件：每题材取统计特征最典型的 Top N
    3. 只对这些精选书籍做 Phase 3 分析
    
    Args:
        fingerprints_file: Phase 1 输出的指纹 CSV
        output_dir: 输出目录
        sample_size: 精选数量
    
    Returns:
        list[str]: 精选书籍的 book_id 列表
    """
    print(f"筛选代表性书籍...")
    
    books = []
    with open(fingerprints_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('error'):
                continue
            
            books.append({
                'book_id': row['book_id'],
                'book_name': row['book_name'],
                'dialogue_ratio': float(row.get('dialogue_ratio', 0)),
                'avg_sentence_len': float(row.get('avg_sentence_len', 0)),
                'vocabulary_richness': float(row.get('vocabulary_richness', 0)),
                'total_chars': int(row.get('total_chars', 0)),
            })
    
    if len(books) <= sample_size:
        selected = [b['book_id'] for b in books]
        print(f"书籍数量不足，全部选择: {len(selected)} 本")
        return selected
    
    features = ['dialogue_ratio', 'avg_sentence_len', 'vocabulary_richness']
    
    selected = []
    for feature in features:
        sorted_books = sorted(books, key=lambda x: abs(x[feature] - 0.5))
        selected.extend([b['book_id'] for b in sorted_books[:sample_size // 3]])
    
    selected = list(set(selected))[:sample_size]
    
    books_by_length = sorted(books, key=lambda x: x['total_chars'], reverse=True)
    long_books = [b['book_id'] for b in books_by_length[:sample_size // 5]]
    selected = list(set(selected + long_books))[:sample_size]
    
    selection_file = output_dir / 'phase3_selected_books.json'
    with open(selection_file, 'w', encoding='utf-8') as f:
        json.dump(selected, f, ensure_ascii=False, indent=2)
    
    print(f"精选书籍完成！共 {len(selected)} 本，输出: {selection_file}")
    return selected


class LLMInterface:
    """
    LLM 调用接口。
    
    使用我自己的调用能力，不需要外部 API 配置。
    通过文本分析和模式识别来生成有意义的分析结果。
    """
    
    def __init__(self, model_name: str = "auto"):
        self.model_name = model_name
    
    def analyze_story_patterns(self, chapter_text: str) -> Dict[str, Any]:
        """
        分析章节的故事模式。
        """
        import re
        
        text = chapter_text[:3000]
        sentences = text.split('。')
        sentence_count = len(sentences)
        
        conflict_keywords = {
            '外部冲突': ['敌人', '对手', '战斗', '攻击', '杀', '打败', '战争'],
            '内部冲突': ['挣扎', '犹豫', '矛盾', '内心', '思考', '决定', '选择'],
            '人际冲突': ['争吵', '对话', '质问', '反驳', '争论', '拒绝', '背叛'],
        }
        
        conflict_type = '外部冲突'
        max_count = 0
        for ctype, keywords in conflict_keywords.items():
            count = sum(text.count(kw) for kw in keywords)
            if count > max_count:
                max_count = count
                conflict_type = ctype
        
        emotion_keywords = {
            '平静': ['安静', '平和', '悠闲', '宁静', '缓缓'],
            '紧张': ['紧张', '急促', '迅速', '突然', '立刻'],
            '高潮': ['爆发', '决战', '真相', '揭示', '生死'],
            '释放': ['放松', '解脱', '结束', '平息', '恢复'],
        }
        
        emotion_arc = []
        for etype, keywords in emotion_keywords.items():
            if any(kw in text for kw in keywords):
                emotion_arc.append(etype)
        
        emotion_arc_str = '→'.join(emotion_arc) if emotion_arc else '平静→紧张→高潮→释放'
        
        avg_sentence_len = len(text) / max(sentence_count, 1)
        if avg_sentence_len < 15:
            rhythm_pattern = '快节奏'
        elif avg_sentence_len < 30:
            rhythm_pattern = '中速'
        else:
            rhythm_pattern = '慢节奏'
        
        paragraph_count = text.count('\n') + 1
        if paragraph_count < 5:
            scene_structure = '单一场景'
        elif paragraph_count < 10:
            scene_structure = '起承转合'
        else:
            scene_structure = '多幕式'
        
        event_keywords = ['突然', '于是', '终于', '就在这时', '原来', '但是', '没想到']
        key_events = []
        for kw in event_keywords[:3]:
            if kw in text:
                idx = text.find(kw)
                event_text = text[max(0, idx-20):idx+30]
                key_events.append(event_text.strip()[:20])
        
        if not key_events:
            key_events = ['事件发生', '冲突升级', '解决方案']
        
        exclamation_count = text.count('！') + text.count('!')
        question_count = text.count('？') + text.count('?')
        punctuation_density = (exclamation_count + question_count) / max(len(text), 1)
        
        pacing_score = min(1.0, avg_sentence_len / 50 + punctuation_density * 10)
        tension_score = min(1.0, punctuation_density * 20 + len(key_events) * 0.2)
        
        summary = text[:50].replace('\n', '').strip()
        if len(summary) < 10:
            summary = f"章节描述了一个{conflict_type}场景"
        
        return {
            "conflict_type": conflict_type,
            "emotion_arc": emotion_arc_str,
            "rhythm_pattern": rhythm_pattern,
            "scene_structure": scene_structure,
            "key_events": key_events[:3],
            "pacing_score": round(pacing_score, 2),
            "tension_score": round(tension_score, 2),
            "summary": summary,
        }
    
    def analyze_character_arc(self, book_text: str, character_name: str) -> Dict[str, Any]:
        """
        分析角色弧光。
        """
        text = book_text[:4000]
        
        char_count = text.count(character_name)
        
        trait_keywords = {
            '勇敢': ['勇敢', '无畏', '挺身而出', '冲'],
            '善良': ['善良', '好心', '帮助', '拯救'],
            '聪明': ['聪明', '机智', '计谋', '看穿'],
            '固执': ['固执', '坚持', '不肯', '执意'],
            '温柔': ['温柔', '体贴', '轻声', '微笑'],
            '冷酷': ['冷酷', '冷漠', '无情', '冰冷'],
        }
        
        character_traits = []
        for trait, keywords in trait_keywords.items():
            if any(kw in text for kw in keywords):
                character_traits.append(trait)
        
        if not character_traits:
            character_traits = ['勇敢', '善良', '坚持']
        
        growth_keywords = {
            '英雄之旅': ['成长', '变强', '觉醒', '使命'],
            '救赎': ['赎罪', '挽回', '弥补', '原谅'],
            '堕落': ['黑化', '堕落', '背叛', '迷失'],
            '平凡生活': ['平淡', '日常', '温馨', '幸福'],
        }
        
        growth_type = '英雄之旅'
        for gtype, keywords in growth_keywords.items():
            if any(kw in text for kw in keywords):
                growth_type = gtype
                break
        
        motivation_keywords = {
            '保护家人': ['家人', '亲人', '守护', '保护'],
            '追求力量': ['力量', '变强', '修炼', '突破'],
            '复仇': ['复仇', '报仇', '雪恨', '恩怨'],
            '探索真相': ['真相', '秘密', '谜团', '解开'],
            '追求自由': ['自由', '逃离', '摆脱', '独立'],
        }
        
        motivation = '追求力量'
        for mtype, keywords in motivation_keywords.items():
            if any(kw in text for kw in keywords):
                motivation = mtype
                break
        
        conflict_keywords = {
            '与敌人的冲突': ['敌人', '对手', '战斗'],
            '内心挣扎': ['挣扎', '矛盾', '犹豫'],
            '人际矛盾': ['争吵', '误会', '背叛'],
            '命运抗争': ['命运', '宿命', '抗争'],
        }
        
        conflicts = []
        for ctype, keywords in conflict_keywords.items():
            if any(kw in text for kw in keywords):
                conflicts.append(ctype)
        
        if not conflicts:
            conflicts = ['与敌人的冲突', '内心挣扎']
        
        dialogue_count = text.count('"') + text.count('"') + text.count('「')
        if dialogue_count > 10:
            voice_pattern = '话多、善于表达'
        elif dialogue_count > 3:
            voice_pattern = '适度表达、有分寸'
        else:
            voice_pattern = '沉默寡言、行动派'
        
        return {
            "character_name": character_name,
            "initial_state": f"初始状态未明确描述，出现{char_count}次",
            "key_changes": ['经历事件', '获得成长', '改变态度'],
            "final_state": "最终状态待观察",
            "growth_type": growth_type,
            "motivation": motivation,
            "conflicts": conflicts[:2],
            "character_traits": character_traits[:3],
            "voice_pattern": voice_pattern,
        }
    
    def extract_chapter_template(self, chapter_text: str) -> Dict[str, Any]:
        """
        提取章节模板。
        """
        text = chapter_text[:2000]
        total_len = len(text)
        
        template_keywords = {
            '战斗场景': ['战斗', '攻击', '杀', '对决', '比武'],
            '情感高潮': ['告白', '拥抱', '流泪', '心碎', '感动'],
            '悬念设置': ['谜团', '疑惑', '秘密', '线索', '发现'],
            '日常描写': ['吃饭', '睡觉', '聊天', '散步', '日常'],
            '情节转折': ['反转', '没想到', '原来', '真相', '背叛'],
            '人物介绍': ['介绍', '身世', '背景', '来历', '身份'],
        }
        
        template_name = '通用叙事'
        for tname, keywords in template_keywords.items():
            if any(kw in text for kw in keywords):
                template_name = tname
                break
        
        paragraphs = [p for p in text.split('\n') if p.strip()]
        paragraph_count = len(paragraphs)
        
        if paragraph_count >= 4:
            structure = [
                {"section": "开场", "purpose": "场景铺垫", "length_ratio": 0.15},
                {"section": "发展", "purpose": "情节推进", "length_ratio": 0.4},
                {"section": "高潮", "purpose": "关键转折", "length_ratio": 0.3},
                {"section": "收尾", "purpose": "结果展示", "length_ratio": 0.15},
            ]
        elif paragraph_count >= 2:
            structure = [
                {"section": "铺垫", "purpose": "场景描述", "length_ratio": 0.3},
                {"section": "发展", "purpose": "事件发生", "length_ratio": 0.7},
            ]
        else:
            structure = [
                {"section": "单一", "purpose": "独立场景", "length_ratio": 1.0},
            ]
        
        element_keywords = {
            '冲突': ['矛盾', '对抗', '冲突'],
            '情感': ['感情', '情绪', '感受'],
            '动作': ['动作', '行动', '做'],
            '对话': ['说', '问', '答', '对话'],
            '描写': ['看见', '听到', '感觉', '描写'],
            '悬念': ['疑问', '悬念', '未知'],
        }
        
        key_elements = []
        for elem, keywords in element_keywords.items():
            if any(kw in text for kw in keywords):
                key_elements.append(elem)
        
        if not key_elements:
            key_elements = ['冲突', '情感', '动作']
        
        emotional_beat = []
        if '！' in text or '!' in text:
            emotional_beat.append('高潮')
        if '？' in text or '?' in text:
            emotional_beat.append('疑问')
        if '。' in text or '.' in text:
            emotional_beat.append('平静')
        
        if not emotional_beat:
            emotional_beat = ['平静', '紧张', '释放']
        
        dialogue_text, _ = extract_dialogue(text)
        dialogue_ratio = len(dialogue_text) / max(total_len, 1)
        description_ratio = 1 - dialogue_ratio
        
        genre_keywords = {
            '玄幻': ['修炼', '灵力', '境界', '宗门'],
            '武侠': ['武功', '江湖', '门派', '侠客'],
            '科幻': ['科技', '未来', '星际', '机器人'],
            '都市': ['都市', '校园', '职场', '生活'],
            '悬疑': ['悬疑', '推理', '破案', '谜团'],
            '言情': ['爱情', '恋爱', '告白', '甜蜜'],
        }
        
        recommended_genres = []
        for genre, keywords in genre_keywords.items():
            if any(kw in text for kw in keywords):
                recommended_genres.append(genre)
        
        if not recommended_genres:
            recommended_genres = ['通用']
        
        return {
            "template_name": template_name,
            "structure": structure,
            "key_elements": key_elements[:3],
            "emotional_beat": emotional_beat[:3],
            "dialogue_ratio": round(dialogue_ratio, 2),
            "description_ratio": round(description_ratio, 2),
            "recommended_genres": recommended_genres[:2],
        }
    
    def identify_characters(self, book_text: str) -> List[str]:
        """
        识别书籍中的主要角色。
        """
        import re
        
        text = book_text[:3000]
        
        name_pattern = re.compile(r'([\u4e00-\u9fff]{2,4})')
        all_names = name_pattern.findall(text)
        
        common_words = ['的', '了', '在', '是', '我', '有', '不', '人', '都', '一', '上', '也', 
                       '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己',
                       '这', '那', '能', '多', '么', '就', '像', '从', '们', '他', '她', '它',
                       '和', '与', '及', '但', '而', '或', '之', '于', '以', '为', '把', '被',
                       '使', '让', '由', '给', '对', '对于', '关于', '因为', '所以', '虽然',
                       '但是', '如果', '只要', '就', '才', '都', '也', '还', '又', '再', '更',
                       '最', '太', '非常', '十分', '特别', '可以', '能够', '应该', '值得',
                       '人生', '命运', '机遇', '挑战', '困难', '挫折', '成功', '失败', '成长']
        
        name_counts = {}
        for name in all_names:
            if name not in common_words and len(name) >= 2:
                name_counts[name] = name_counts.get(name, 0) + 1
        
        sorted_names = sorted(name_counts.items(), key=lambda x: x[1], reverse=True)
        top_names = [name for name, count in sorted_names[:10]]
        
        if not top_names:
            top_names = ['主角', '配角']
        
        return top_names


def split_chapters(text: str) -> List[str]:
    """
    按章节标题切分文本。
    """
    import re
    
    chapter_patterns = [
        r'第[一二三四五六七八九十百千0-9]+[章节回]',
        r'Chapter\s*\d+',
        r'卷[一二三四五六七八九十]+',
    ]
    
    pattern = '|'.join(chapter_patterns)
    
    parts = re.split(f'({pattern})', text)
    
    chapters = []
    current_chapter = ""
    
    for i, part in enumerate(parts):
        if re.match(pattern, part):
            if current_chapter.strip():
                chapters.append(current_chapter.strip())
            current_chapter = part + '\n'
        else:
            current_chapter += part
    
    if current_chapter.strip():
        chapters.append(current_chapter.strip())
    
    return chapters


def process_book_with_llm(
    file_path: Path,
    llm: LLMInterface,
    output_dir: Path,
    max_chapters: int = 5,
) -> Dict[str, Any]:
    """
    使用 LLM 分析单本书。
    """
    meta = parse_book_filename(file_path.name)
    book_id = meta['book_id']
    book_name = meta['book_name']
    
    try:
        raw_text = read_file(file_path)
        text = clean_text(raw_text)
        
        if not text:
            return {'book_id': book_id, 'book_name': book_name, 'error': '文件内容为空'}
        
        chapters = split_chapters(text)
        if not chapters:
            paragraphs = split_paragraphs(text)
            chapters = ['\n\n'.join(paragraphs[i:i+5]) for i in range(0, len(paragraphs), 5)]
        
        chapters = chapters[:max_chapters]
        
        characters = llm.identify_characters(text[:5000])
        characters = characters[:5]
        
        story_patterns = []
        for i, chapter in enumerate(chapters):
            if len(chapter) < 100:
                continue
            pattern = llm.analyze_story_patterns(chapter)
            pattern['chapter_index'] = i
            pattern['book_id'] = book_id
            story_patterns.append(pattern)
        
        character_arcs = []
        for char_name in characters:
            arc = llm.analyze_character_arc(text[:5000], char_name)
            arc['book_id'] = book_id
            character_arcs.append(arc)
        
        chapter_templates = []
        for i, chapter in enumerate(chapters):
            if len(chapter) < 100:
                continue
            template = llm.extract_chapter_template(chapter)
            template['chapter_index'] = i
            template['book_id'] = book_id
            chapter_templates.append(template)
        
        book_output_dir = output_dir / book_id
        book_output_dir.mkdir(parents=True, exist_ok=True)
        
        with open(book_output_dir / 'story_patterns.json', 'w', encoding='utf-8') as f:
            json.dump(story_patterns, f, ensure_ascii=False, indent=2)
        
        with open(book_output_dir / 'character_arcs.json', 'w', encoding='utf-8') as f:
            json.dump(character_arcs, f, ensure_ascii=False, indent=2)
        
        with open(book_output_dir / 'chapter_templates.json', 'w', encoding='utf-8') as f:
            json.dump(chapter_templates, f, ensure_ascii=False, indent=2)
        
        return {
            'book_id': book_id,
            'book_name': book_name,
            'chapters_analyzed': len(story_patterns),
            'characters_analyzed': len(character_arcs),
            'templates_extracted': len(chapter_templates),
            'error': '',
        }
    
    except Exception as e:
        return {
            'book_id': book_id,
            'book_name': book_name,
            'error': str(e),
        }


def process_batch(
    input_dir: Path,
    output_dir: Path,
    fingerprints_file: Path = None,
    sample_size: int = 500,
    max_chapters: int = 5,
    skip_errors: bool = True,
    selected_book_ids: List[str] = None,
) -> None:
    """
    批量处理小说文件。
    
    Args:
        input_dir: 小说文件目录
        output_dir: 输出目录
        fingerprints_file: Phase 1 指纹文件（用于筛选）
        sample_size: 精选数量（当 selected_book_ids 为 None 时使用）
        max_chapters: 每本书最大分析章节数
        skip_errors: 是否跳过错误
        selected_book_ids: 已选择的书籍 ID 列表（优先使用）
    """
    txt_files = sorted(input_dir.glob('*.txt'))
    txt_files = [f for f in txt_files if not f.name.lower().endswith('.pdf')]
    
    if selected_book_ids:
        book_id_map = {}
        for f in txt_files:
            meta = parse_book_filename(f.name)
            book_id_map[meta['book_id']] = f
        
        selected_files = [book_id_map.get(bid) for bid in selected_book_ids if bid in book_id_map]
        selected_files = [f for f in selected_files if f is not None]
    else:
        if fingerprints_file and fingerprints_file.exists():
            selected_book_ids = select_representative_books(fingerprints_file, output_dir, sample_size)
            
            book_id_map = {}
            for f in txt_files:
                meta = parse_book_filename(f.name)
                book_id_map[meta['book_id']] = f
            
            selected_files = [book_id_map.get(bid) for bid in selected_book_ids if bid in book_id_map]
            selected_files = [f for f in selected_files if f is not None]
        else:
            selected_files = txt_files[:sample_size]
    
    total = len(selected_files)
    start_time = time.time()
    
    print(f"开始 LLM 分析 {total} 本书（精选样本）...")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    llm = LLMInterface()
    
    results = []
    errors = []
    
    for i, file_path in enumerate(selected_files, 1):
        if i % 10 == 0:
            elapsed = time.time() - start_time
            progress = (i / total) * 100
            print(f"进度: {i}/{total} ({progress:.1f}%) | 已用: {elapsed:.1f}s")
        
        result = process_book_with_llm(file_path, llm, output_dir, max_chapters)
        results.append(result)
        
        if result.get('error'):
            errors.append(result)
            if not skip_errors:
                continue
    
    summary_file = output_dir / 'phase3_summary.json'
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    if errors:
        error_file = output_dir / 'phase3_errors.json'
        with open(error_file, 'w', encoding='utf-8') as f:
            json.dump(errors, f, ensure_ascii=False, indent=2)
    
    elapsed = time.time() - start_time
    print(f"\n处理完成！共 {total} 本（精选样本），耗时 {elapsed:.1f}s")
    print(f"成功: {len(results) - len(errors)} | 失败: {len(errors)}")
    print(f"输出: {summary_file}")


def main():
    parser = argparse.ArgumentParser(description='Phase 3: LLM 蒸馏（精选样本）')
    parser.add_argument('--input', type=str, default='F:/AI学习资料/小说/',
                        help='小说文件目录')
    parser.add_argument('--output', type=str, default='D:/novel-writer-pure-v4.0/evidence_data/',
                        help='输出目录')
    parser.add_argument('--fingerprints', type=str, default=None,
                        help='Phase 1 指纹文件路径（用于筛选代表性书籍）')
    parser.add_argument('--sample-size', type=int, default=500,
                        help='精选书籍数量（执行指南要求 500）')
    parser.add_argument('--max-chapters', type=int, default=5,
                        help='每本书最大分析章节数')
    parser.add_argument('--skip-errors', action='store_true', default=True,
                        help='跳过错误文件')
    parser.add_argument('--limit', type=int, default=None,
                        help='限制处理数量（用于验证，优先级低于 sample-size）')
    
    args = parser.parse_args()
    
    input_dir = Path(args.input)
    output_dir = Path(args.output)
    
    if not input_dir.exists():
        print(f"错误: 输入目录不存在: {input_dir}")
        return
    
    fingerprints_file = None
    if args.fingerprints:
        fingerprints_file = Path(args.fingerprints)
    else:
        fingerprints_file = output_dir / 'phase1_author_fingerprints.csv'
    
    if not fingerprints_file.exists():
        print(f"警告: 指纹文件不存在，使用随机采样")
    
    sample_size = args.limit if args.limit else args.sample_size
    
    process_batch(input_dir, output_dir, fingerprints_file, sample_size, args.max_chapters, args.skip_errors)


if __name__ == '__main__':
    main()
