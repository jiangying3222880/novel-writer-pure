"""
Phase 2: 向量聚类

使用 scikit-learn + TfidfVectorizer 进行聚类分析：
- 作者风格聚类（基于统计特征）
- 叙事模式聚类（基于句子模式）
- 对白风格聚类（基于对白文本）
- 角色 Voice 聚类（基于角色对白特征）

注意：不使用 sentence-transformers，避免 PyTorch 依赖。
"""
from __future__ import annotations

import argparse
import csv
import json
import pickle
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple

import numpy as np
from sklearn.cluster import KMeans, DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score


class TextClusterer:
    """
    文本聚类器。
    """
    
    def __init__(self, n_clusters: int = 8):
        self.n_clusters = n_clusters
        self.vectorizer = TfidfVectorizer(
            tokenizer=self._tokenize,
            stop_words=self._stop_words(),
            max_features=5000,
            ngram_range=(1, 2),
        )
        self.kmeans = KMeans(n_clusters=n_clusters, random_state=42)
        self.pca = PCA(n_components=2)
    
    def _tokenize(self, text: str) -> List[str]:
        """分词（正则实现）"""
        tokens = re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z]+', text)
        stopwords = self._stop_words()
        return [t for t in tokens if t not in stopwords]
    
    def _stop_words(self) -> List[str]:
        """停用词"""
        return list(__import__('utils').STOPWORDS)
    
    def fit_transform(self, texts: List[str]) -> Tuple[np.ndarray, np.ndarray]:
        """
        训练并返回聚类结果和降维坐标。
        
        Returns:
            tuple: (labels, coords)
        """
        X = self.vectorizer.fit_transform(texts)
        labels = self.kmeans.fit_predict(X)
        coords = self.pca.fit_transform(X.toarray())
        return labels, coords
    
    def predict(self, text: str) -> int:
        """预测文本所属类别"""
        X = self.vectorizer.transform([text])
        return self.kmeans.predict(X)[0]
    
    def save(self, path: Path) -> None:
        """保存模型"""
        with open(path, 'wb') as f:
            pickle.dump({
                'vectorizer': self.vectorizer,
                'kmeans': self.kmeans,
                'pca': self.pca,
                'n_clusters': self.n_clusters,
            }, f)
    
    @classmethod
    def load(cls, path: Path) -> 'TextClusterer':
        """加载模型"""
        with open(path, 'rb') as f:
            data = pickle.load(f)
        
        instance = cls(n_clusters=data['n_clusters'])
        instance.vectorizer = data['vectorizer']
        instance.kmeans = data['kmeans']
        instance.pca = data['pca']
        return instance


def cluster_authors(
    fingerprints_file: Path,
    output_dir: Path,
    n_clusters: int = 8,
) -> None:
    """
    基于统计特征进行作者聚类。
    """
    print(f"基于统计特征进行作者聚类...")
    
    features = []
    book_ids = []
    book_names = []
    
    with open(fingerprints_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('error'):
                continue
            
            feat = [
                float(row.get('avg_sentence_len', 0)),
                float(row.get('short_ratio', 0)),
                float(row.get('medium_ratio', 0)),
                float(row.get('long_ratio', 0)),
                float(row.get('dialogue_ratio', 0)),
                float(row.get('description_ratio', 0)),
                float(row.get('exclamation_density', 0)),
                float(row.get('ellipsis_density', 0)),
                float(row.get('question_density', 0)),
                float(row.get('vocabulary_richness', 0)),
            ]
            features.append(feat)
            book_ids.append(row['book_id'])
            book_names.append(row['book_name'])
    
    if not features:
        print("没有有效的指纹数据")
        return
    
    X = np.array(features)
    actual_clusters = max(2, min(n_clusters, len(features) - 1))
    
    kmeans = KMeans(n_clusters=actual_clusters, random_state=42)
    labels = kmeans.fit_predict(X)
    silhouette = silhouette_score(X, labels)
    print(f"轮廓系数: {silhouette:.3f}")
    
    pca = PCA(n_components=2)
    coords = pca.fit_transform(X)
    
    output_file = output_dir / 'phase2_author_clusters.csv'
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['book_id', 'book_name', 'cluster_label', 'pca_x', 'pca_y'])
        for book_id, book_name, label, (x, y) in zip(book_ids, book_names, labels, coords):
            writer.writerow([book_id, book_name, label, x, y])
    
    centers_file = output_dir / 'phase2_cluster_centers.json'
    center_features = [
        'avg_sentence_len', 'short_ratio', 'medium_ratio', 'long_ratio',
        'dialogue_ratio', 'description_ratio', 'exclamation_density',
        'ellipsis_density', 'question_density', 'vocabulary_richness',
    ]
    centers_data = {}
    for i, center in enumerate(kmeans.cluster_centers_):
        centers_data[str(i)] = dict(zip(center_features, center.tolist()))
    
    with open(centers_file, 'w', encoding='utf-8') as f:
        json.dump(centers_data, f, ensure_ascii=False, indent=2)
    
    print(f"作者聚类完成！输出: {output_file}")


def extract_character_dialogues(text: str) -> Dict[str, List[str]]:
    """
    提取文本中每个角色的对白。
    
    从原始文本中直接提取 "角色名说：..." 格式的对白。
    
    Returns:
        dict: {角色名: [对白列表]}
    """
    if not text:
        return {}
    
    character_dialogues = {}
    lines = text.split('\n')
    
    current_character = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        match = re.search(r'([\u4e00-\u9fff]{2,4})\s*(说|说道|问|答|叹|吼|喊|叫|怒道|冷声道|低声道|心想|暗想|说道)\s*[：:]', line)
        if match:
            char_name = match.group(1)
            if len(char_name) >= 2 and len(char_name) <= 4:
                current_character = char_name
        
        if current_character and len(line) > 5:
            dialogue_part = line
            
            if current_character not in character_dialogues:
                character_dialogues[current_character] = []
            
            if len(character_dialogues[current_character]) < 50:
                character_dialogues[current_character].append(dialogue_part)
    
    filtered = {k: v for k, v in character_dialogues.items() if len(v) >= 3}
    return filtered


def analyze_character_voice(dialogues: List[str]) -> Dict[str, float]:
    """
    分析角色的 Voice 特征。
    
    Args:
        dialogues: 角色的对白列表
    
    Returns:
        dict: Voice 特征
    """
    if not dialogues:
        return {
            'avg_sentence_len': 0,
            'question_ratio': 0,
            'exclamation_ratio': 0,
            'slang_ratio': 0,
            'emotion_level': 0,
        }
    
    all_text = '\n'.join(dialogues)
    
    sentences = re.split(r'[。！？.!?]', all_text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if not sentences:
        return {
            'avg_sentence_len': 0,
            'question_ratio': 0,
            'exclamation_ratio': 0,
            'slang_ratio': 0,
            'emotion_level': 0,
        }
    
    avg_sentence_len = sum(len(s) for s in sentences) / len(sentences)
    
    total_chars = len(all_text)
    question_count = all_text.count('？') + all_text.count('?')
    exclamation_count = all_text.count('！') + all_text.count('!')
    
    question_ratio = question_count / max(total_chars, 1)
    exclamation_ratio = exclamation_count / max(total_chars, 1)
    
    slang_keywords = ['卧槽', '尼玛', '靠', '切', '哼', '啊哈', '哟', '嘛', '呗', '呢']
    slang_count = sum(all_text.count(kw) for kw in slang_keywords)
    slang_ratio = slang_count / max(total_chars, 1)
    
    emotion_keywords = ['哈哈', '呵呵', '呜呜', '哭', '笑', '愤怒', '激动', '惊讶', '悲伤', '开心']
    emotion_count = sum(all_text.count(kw) for kw in emotion_keywords)
    emotion_level = emotion_count / max(total_chars, 1)
    
    return {
        'avg_sentence_len': round(avg_sentence_len, 2),
        'question_ratio': round(question_ratio, 4),
        'exclamation_ratio': round(exclamation_ratio, 4),
        'slang_ratio': round(slang_ratio, 4),
        'emotion_level': round(emotion_level, 4),
    }


def cluster_character_voices(
    input_dir: Path,
    output_dir: Path,
    n_clusters: int = 10,
    sample_size: int = 500,
) -> None:
    """
    基于角色对白进行 Voice 聚类。
    
    执行指南要求：
    1. 提取所有 "角色名说：..." 的对白
    2. 按角色聚合
    3. 对每个角色计算：平均句长、反问句比例、感叹句比例、口语/俚语比例、情绪强度
    4. 用 K-Means 聚成 5-10 个 Voice 原型
    """
    print(f"基于角色对白进行 Voice 聚类...")
    
    from utils import read_file, parse_book_filename, clean_text
    
    txt_files = sorted(input_dir.glob('*.txt'))
    txt_files = [f for f in txt_files if not f.name.lower().endswith('.pdf')]
    
    if sample_size and len(txt_files) > sample_size:
        import random
        random.seed(42)
        txt_files = random.sample(txt_files, sample_size)
    
    all_characters = []
    character_features = []
    
    for file_path in txt_files:
        try:
            meta = parse_book_filename(file_path.name)
            raw_text = read_file(file_path)
            text = clean_text(raw_text)
            
            char_dialogues = extract_character_dialogues(text)
            
            for char_name, dialogues in char_dialogues.items():
                if len(dialogues) >= 5 and len(char_name) >= 2:
                    voice_features = analyze_character_voice(dialogues)
                    all_characters.append({
                        'character_name': char_name,
                        'book_id': meta['book_id'],
                        'book_name': meta['book_name'],
                        **voice_features,
                    })
                    character_features.append([
                        voice_features['avg_sentence_len'],
                        voice_features['question_ratio'],
                        voice_features['exclamation_ratio'],
                        voice_features['slang_ratio'],
                        voice_features['emotion_level'],
                    ])
        
        except Exception as e:
            print(f"跳过 {file_path.name}: {e}")
    
    if not character_features:
        print("没有有效的角色对白数据")
        return
    
    print(f"共提取 {len(all_characters)} 个角色的对白")
    
    X = np.array(character_features)
    actual_clusters = max(2, min(n_clusters, len(character_features) - 1))
    
    kmeans = KMeans(n_clusters=actual_clusters, random_state=42)
    labels = kmeans.fit_predict(X)
    
    silhouette = silhouette_score(X, labels)
    print(f"Voice 聚类轮廓系数: {silhouette:.3f}")
    
    pca = PCA(n_components=2)
    coords = pca.fit_transform(X)
    
    prototype_names = [
        '冰山型', '热血型', '睿智型', '腹黑型', '呆萌型',
        '高冷型', '豪爽型', '温柔型', '神秘型', '活泼型',
    ]
    
    for i, character in enumerate(all_characters):
        character['cluster_label'] = int(labels[i])
        character['prototype_name'] = prototype_names[labels[i] % len(prototype_names)]
        character['pca_x'] = float(coords[i][0])
        character['pca_y'] = float(coords[i][1])
    
    output_file = output_dir / 'phase2_voice_prototypes.csv'
    fieldnames = [
        'character_name', 'book_id', 'book_name', 'cluster_label', 'prototype_name',
        'avg_sentence_len', 'question_ratio', 'exclamation_ratio',
        'slang_ratio', 'emotion_level', 'pca_x', 'pca_y',
    ]
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_characters)
    
    centers_file = output_dir / 'phase2_voice_cluster_centers.json'
    center_features = ['avg_sentence_len', 'question_ratio', 'exclamation_ratio', 'slang_ratio', 'emotion_level']
    centers_data = {}
    for i, center in enumerate(kmeans.cluster_centers_):
        center_dict = dict(zip(center_features, center.tolist()))
        center_dict['prototype_name'] = prototype_names[i % len(prototype_names)]
        
        characteristics = []
        if center[0] < 15:
            characteristics.append('话少')
        elif center[0] > 40:
            characteristics.append('话多')
        
        if center[1] > 0.01:
            characteristics.append('反问多')
        if center[2] > 0.01:
            characteristics.append('感叹多')
        if center[3] > 0.005:
            characteristics.append('口语化')
        if center[4] > 0.005:
            characteristics.append('情绪丰富')
        
        if not characteristics:
            characteristics = ['中性']
        
        center_dict['characteristics'] = characteristics
        center_dict['summary'] = f"{prototype_names[i % len(prototype_names)]}: {'，'.join(characteristics)}"
        
        centers_data[str(i)] = center_dict
    
    with open(centers_file, 'w', encoding='utf-8') as f:
        json.dump(centers_data, f, ensure_ascii=False, indent=2)
    
    model_file = output_dir / 'phase2_voice_clusterer.pkl'
    with open(model_file, 'wb') as f:
        pickle.dump({
            'kmeans': kmeans,
            'pca': pca,
            'prototype_names': prototype_names,
        }, f)
    
    print(f"角色 Voice 聚类完成！输出: {output_file}, {centers_file}, {model_file}")


def cluster_dialogue_patterns(
    input_dir: Path,
    output_dir: Path,
    n_clusters: int = 10,
    sample_size: int = 100,
) -> None:
    """
    基于对白文本进行聚类。
    """
    print(f"基于对白文本进行聚类...")
    
    from utils import read_file, parse_book_filename, extract_dialogue, clean_text
    
    txt_files = sorted(input_dir.glob('*.txt'))
    txt_files = [f for f in txt_files if not f.name.lower().endswith('.pdf')]
    
    if sample_size and len(txt_files) > sample_size:
        import random
        random.seed(42)
        txt_files = random.sample(txt_files, sample_size)
    
    dialogue_texts = []
    book_ids = []
    book_names = []
    
    for file_path in txt_files:
        try:
            meta = parse_book_filename(file_path.name)
            raw_text = read_file(file_path)
            text = clean_text(raw_text)
            dialogue_text, _ = extract_dialogue(text)
            
            if dialogue_text and len(dialogue_text) > 100:
                dialogue_texts.append(dialogue_text[:5000])
                book_ids.append(meta['book_id'])
                book_names.append(meta['book_name'])
        except Exception as e:
            print(f"跳过 {file_path.name}: {e}")
    
    if not dialogue_texts:
        print("没有有效的对白数据")
        return
    
    print(f"共 {len(dialogue_texts)} 本书有对白数据")
    
    actual_clusters = max(2, min(n_clusters, len(dialogue_texts) - 1))
    
    clusterer = TextClusterer(n_clusters=actual_clusters)
    labels, coords = clusterer.fit_transform(dialogue_texts)
    
    X = clusterer.vectorizer.transform(dialogue_texts)
    silhouette = silhouette_score(X, labels)
    print(f"对白聚类轮廓系数: {silhouette:.3f}")
    
    output_file = output_dir / 'phase2_dialogue_clusters.csv'
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['book_id', 'book_name', 'cluster_label', 'pca_x', 'pca_y'])
        for book_id, book_name, label, (x, y) in zip(book_ids, book_names, labels, coords):
            writer.writerow([book_id, book_name, label, x, y])
    
    model_file = output_dir / 'phase2_dialogue_clusterer.pkl'
    clusterer.save(model_file)
    
    print(f"对白聚类完成！输出: {output_file}, {model_file}")


def cluster_narrative_patterns(
    patterns_file: Path,
    output_dir: Path,
    n_clusters: int = 8,
) -> None:
    """
    基于句子模式分布进行聚类。
    """
    print(f"基于句子模式进行聚类...")
    
    pattern_data = {}
    
    with open(patterns_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            book_id = row['book_id']
            if book_id not in pattern_data:
                pattern_data[book_id] = {
                    'book_name': row['book_name'],
                    'patterns': {},
                }
            pattern_data[book_id]['patterns'][row['pattern_type']] = float(row['ratio'])
    
    if not pattern_data:
        print("没有有效的模式数据")
        return
    
    all_patterns = set()
    for data in pattern_data.values():
        all_patterns.update(data['patterns'].keys())
    all_patterns = sorted(list(all_patterns))
    
    features = []
    book_ids = []
    book_names = []
    
    for book_id, data in pattern_data.items():
        feat = [data['patterns'].get(p, 0) for p in all_patterns]
        features.append(feat)
        book_ids.append(book_id)
        book_names.append(data['book_name'])
    
    X = np.array(features)
    actual_clusters = max(2, min(n_clusters, len(features) - 1))
    kmeans = KMeans(n_clusters=actual_clusters, random_state=42)
    labels = kmeans.fit_predict(X)
    
    silhouette = silhouette_score(X, labels)
    print(f"叙事模式聚类轮廓系数: {silhouette:.3f}")
    
    pca = PCA(n_components=2)
    coords = pca.fit_transform(X)
    
    output_file = output_dir / 'phase2_narrative_clusters.csv'
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['book_id', 'book_name', 'cluster_label', 'pca_x', 'pca_y'])
        for book_id, book_name, label, (x, y) in zip(book_ids, book_names, labels, coords):
            writer.writerow([book_id, book_name, label, x, y])
    
    print(f"叙事模式聚类完成！输出: {output_file}")


def main():
    parser = argparse.ArgumentParser(description='Phase 2: 向量聚类')
    parser.add_argument('--input', type=str, default='F:/AI学习资料/小说/',
                        help='小说文件目录')
    parser.add_argument('--output', type=str, default='D:/novel-writer-pure-v4.0/evidence_data/',
                        help='输出目录')
    parser.add_argument('--n-clusters', type=int, default=8,
                        help='聚类数量')
    parser.add_argument('--mode', type=str, choices=['author', 'dialogue', 'narrative', 'voice', 'all'],
                        default='all', help='聚类模式')
    parser.add_argument('--sample-size', type=int, default=500,
                        help='采样数量（用于对白和Voice聚类）')
    
    args = parser.parse_args()
    
    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    fingerprints_file = output_dir / 'phase1_author_fingerprints.csv'
    patterns_file = output_dir / 'phase1_sentence_patterns.csv'
    
    if args.mode in ['author', 'all']:
        if fingerprints_file.exists():
            cluster_authors(fingerprints_file, output_dir, args.n_clusters)
        else:
            print(f"警告: {fingerprints_file} 不存在，请先运行 Phase 1")
    
    if args.mode in ['narrative', 'all']:
        if patterns_file.exists():
            cluster_narrative_patterns(patterns_file, output_dir, args.n_clusters)
        else:
            print(f"警告: {patterns_file} 不存在，请先运行 Phase 1")
    
    if args.mode in ['dialogue', 'all']:
        cluster_dialogue_patterns(input_dir, output_dir, args.n_clusters, args.sample_size)
    
    if args.mode in ['voice', 'all']:
        cluster_character_voices(input_dir, output_dir, args.n_clusters, args.sample_size)


if __name__ == '__main__':
    main()
