"""
单元池素材入库脚本

将 extracted_units.jsonl 导入单元池数据库。
在项目主机上运行: python import_units.py extracted_units.jsonl
"""
import json
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db._impl import init as db_init
from app.app_paths import sqlite_path

def import_units(jsonl_path: str):
    """从 JSONL 文件导入单元到数据库."""
    from app.services.unit_pool_service import create

    count = 0
    errors = 0

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                unit = json.loads(line)
                create(
                    title=unit["title"],
                    content=unit["content"],
                    genre=unit.get("genre", "通用"),
                    scene_type=unit.get("scene_type", ""),
                    emotion=unit.get("emotion", ""),
                    tags=unit.get("tags", []),
                    source="web_extract",
                )
                count += 1
                if count % 50 == 0:
                    print(f"已导入 {count} 条...")
            except (json.JSONDecodeError, KeyError) as e:
                errors += 1
                print(f"第 {line_num} 行错误: {e}")
            except Exception as e:
                errors += 1
                print(f"第 {line_num} 行入库失败: {e}")

    print(f"\n完成: 成功 {count} 条, 失败 {errors} 条")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python import_units.py <extracted_units.jsonl>")
        sys.exit(1)

    db_init(str(sqlite_path()))
    import_units(sys.argv[1])
