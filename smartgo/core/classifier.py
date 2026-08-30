"""SmartGo Layer1 任务分类器

接收原始任务描述，提取特征，输出任务标签。
"""

import re
from dataclasses import dataclass
from typing import List

from .config import TaskLabel, SmartGoConfig


@dataclass
class TaskFeatures:
    description: str
    estimated_files: int = 1
    estimated_token: int = 5000
    needs_subagents: int = 0
    needs_git_branches: int = 0
    is_research: bool = False
    is_refactor: bool = False
    is_from_scratch: bool = False
    keywords: List[str] = None

    def __post_init__(self):
        if self.keywords is None:
            self.keywords = []


class TaskClassifier:
    """Layer1: 分析任务文本，输出难度标签"""

    # 高危关键词
    DANGER_KEYWORDS = [
        "重构", "refactor", "重写", "rewrite", "从零", "from scratch",
        "整个仓库", "全仓", "migration", "迁移", "架构改造",
    ]

    # 调研排错关键词
    DEBUG_KEYWORDS = [
        "调试", "debug", "排查", "investigate", "为什么", "why does",
        "报错", "error", "失败", "fail", "不工作", "broken",
        "死循环", "infinite loop", "卡住", "stuck", "hang",
    ]

    # 小改动关键词
    TINY_KEYWORDS = [
        "配置", "config", "改个", "fix", "修bug", "typo",
        "改名", "rename", "调参数", "tweak", "一行",
    ]

    # 大型项目关键词
    BIG_KEYWORDS = [
        "新项目", "new project", "新功能", "new feature", "模块",
        "module", "系统", "system", "平台", "platform",
        "多模块", "多文件", "搭建", "build",
    ]

    def __init__(self, config: SmartGoConfig):
        self.config = config

    def classify(self, task_description: str, **kwargs) -> tuple:
        """返回 (TaskLabel, TaskFeatures)"""
        desc_lower = task_description.lower()
        features = TaskFeatures(
            description=task_description,
            estimated_files=kwargs.get("estimated_files", 1),
            estimated_token=kwargs.get("estimated_token", 5000),
            needs_subagents=kwargs.get("needs_subagents", 0),
            needs_git_branches=kwargs.get("needs_git_branches", 0),
            is_research=kwargs.get("is_research", False),
            is_refactor=kwargs.get("is_refactor", False),
            is_from_scratch=kwargs.get("is_from_scratch", False),
        )

        # 关键词匹配
        for kw in self.DANGER_KEYWORDS:
            if kw in desc_lower:
                features.keywords.append(kw)
        for kw in self.DEBUG_KEYWORDS:
            if kw in desc_lower:
                features.keywords.append(kw)
                features.is_research = True
        for kw in self.TINY_KEYWORDS:
            if kw in desc_lower:
                features.keywords.append(kw)
        for kw in self.BIG_KEYWORDS:
            if kw in desc_lower:
                features.keywords.append(kw)

        label = self._determine_label(features)
        return label, features

    def _determine_label(self, features: TaskFeatures) -> TaskLabel:
        # 优先判断高危
        is_danger = (
            features.estimated_token >= self.config.superpowers.danger_task_token
            or features.estimated_files > 30
            or features.is_refactor
            or features.is_from_scratch
            or features.needs_subagents > 4
            or any(kw in features.keywords for kw in ["重构", "refactor", "重写", "整个仓库", "全仓"])
        )
        if is_danger:
            return TaskLabel.DANGER_TASK

        # 调研排错
        if features.is_research:
            return TaskLabel.EXPLORE_DEBUG

        # 大型项目
        if features.estimated_files > 5 or features.estimated_token > 50000:
            return TaskLabel.BIG_PROJECT

        # 普通功能
        if features.estimated_files > 1 or features.estimated_token > 10000:
            return TaskLabel.NORMAL_FEATURE

        # 默认小改动
        return TaskLabel.TINY_FIX

    def format_label_output(self, label: TaskLabel, features: TaskFeatures) -> str:
        return (
            f"[SmartGo 判断：{label.value}] "
            f"预估文件：{features.estimated_files} | "
            f"预估token：~{features.estimated_token} | "
            f"关键词：{features.keywords or '无'}"
        )
