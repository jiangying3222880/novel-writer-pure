"""
ProjectContext — 统一项目状态守护者（单一事实源）。

职责：
  - 统一管理 current_project 数据的内存状态
  - 提供统一的 save_to_disk() 落盘入口
  - 不替代现有数据库，只在现有 set_project 通道上加一层缓存

用法（在 main_window.py 中）：
  self.context = ProjectContext()
  # 加载项目时
  self.context.load(project_path, raw_project_data)
  # 切页时
  page.context = self.context  # 注入引用
  # 落盘时
  self.context.save_to_disk()
"""

from __future__ import annotations
import json
import logging
import os

logger = logging.getLogger(__name__)


class ProjectContext:
    """项目状态数据守护者 (单一事实源)。

    封装现有的 current_project dict，仅负责统一的内存状态管理与持久化落盘。
    所有 Page 共享同一个实例，切换页面时无需额外同步。
    """

    def __init__(self) -> None:
        # 项目工作目录路径
        self.project_path: str = ""
        # 核心数据 dict（按领域分类，兼容现有 project dict 的全部字段）
        self.data: dict = {
            "meta": {},           # 书名、作者、基本元数据
            "settings": {},       # 设定、背景、世界观
            "outline": {},        # 大纲结构（卷、章节树）
            "characters": [],     # 角色卡列表
            "current_content": "",  # 当前编辑器正文缓存
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load(self, project_path: str = "",
             raw_project_data: dict | None = None) -> None:
        """加载项目时调用，灌入现有 project 数据。

        Args:
            project_path: 项目文件路径
            raw_project_data: project_service 返回的 dict（可选）
        """
        self.project_path = project_path
        if raw_project_data:
            # 合并：保留现有分类 key，同时保存原始字段
            for k, v in raw_project_data.items():
                if k in self.data and isinstance(self.data[k], dict) and isinstance(v, dict):
                    self.data[k].update(v)
                elif k in self.data and isinstance(self.data[k], list) and isinstance(v, list):
                    self.data[k].extend(v)
                else:
                    self.data[k] = v

        # 尝试从本地 project_state.json 恢复
        if project_path:
            state_file = os.path.join(project_path, "project_state.json")
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        file_data: dict = json.load(f)
                    self.data.update(file_data)
                    logger.info("成功从本地恢复项目状态: %s", state_file)
                except Exception as exc:
                    logger.warning("读取本地 project_state.json 失败: %s", exc)

    def save_to_disk(self) -> bool:
        """强迫性落盘入口。不管哪个 Page 触发，最终统一由这里落库。

        Returns:
            True 表示落盘成功，False 表示失败
        """
        if not self.project_path:
            logger.warning("未检测到有效的 project_path，放弃自动落盘")
            return False

        try:
            os.makedirs(self.project_path, exist_ok=True)
            state_file = os.path.join(self.project_path, "project_state.json")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
            logger.info("项目数据已统一落盘: %s", state_file)
            return True
        except Exception as exc:
            logger.error("统一落盘时发生错误: %s", exc)
            return False

    def update_field(self, key: str, value) -> None:
        """Page 离开时调用，同步内存数据到中央缓存。

        Args:
            key: 字段名（如 'current_content'）
            value: 字段值
        """
        self.data[key] = value

    def get_current_project(self) -> dict | None:
        """获取当前项目完整数据（兼容旧 set_project API）。

        Returns:
            项目 dict，或 None 如果没有加载
        """
        if not self.project_path:
            return None
        return self.data
