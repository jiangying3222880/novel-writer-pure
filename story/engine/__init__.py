"""
story.engine — StoryEngine Facade.

提供 run_unit() 顶层入口, 串联 State → Guide → Decision → Prompt.
"""
from story.engine.story_engine import StoryEngine

__all__ = ["StoryEngine"]
