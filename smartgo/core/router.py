"""SmartGo Layer2 执行模式调度层

根据任务标签自动选择执行模式，处理 Superpowers 激活逻辑。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .config import (
    TaskLabel, ExecutionMode, RunMode, SmartGoConfig,
)
from .classifier import TaskFeatures


class SuperpowersDecision(Enum):
    NOT_NEEDED = "未需要"
    ELIGIBLE = "符合条件，可开启"
    DOWNGRADED_BUDGET = "自动降级：超出预算"
    DOWNGRADED_DANGER = "自动降级：高危任务"
    PENDING_USER_CONFIRM = "等待用户确认"
    FORCED_ON = "用户强制开启"


@dataclass
class RoutingResult:
    execution_mode: ExecutionMode
    superpowers: SuperpowersDecision
    ponytail_level: str
    needs_user_confirm: bool = False
    confirm_reason: str = ""
    estimated_token: int = 0


class ModeRouter:
    """Layer2: 根据任务标签路由到对应执行模式"""

    LABEL_TO_MODE = {
        TaskLabel.TINY_FIX: ExecutionMode.REACT,
        TaskLabel.NORMAL_FEATURE: ExecutionMode.PLAN_EXECUTE,
        TaskLabel.BIG_PROJECT: ExecutionMode.PLAN_EXECUTE_REFLECTION,
        TaskLabel.DANGER_TASK: ExecutionMode.PLAN_EXECUTE_REFLECTION,
        TaskLabel.EXPLORE_DEBUG: ExecutionMode.PLAN_EXECUTE_REFLECTION,
    }

    LABEL_TO_PONYTAIL = {
        TaskLabel.TINY_FIX: "full",
        TaskLabel.NORMAL_FEATURE: "lite",
        TaskLabel.BIG_PROJECT: "off",
        TaskLabel.DANGER_TASK: "off",
        TaskLabel.EXPLORE_DEBUG: "lite",
    }

    def __init__(self, config: SmartGoConfig):
        self.config = config

    def route(
        self,
        label: TaskLabel,
        features: TaskFeatures,
        force_mode: Optional[str] = None,
        force_superpowers: bool = False,
    ) -> RoutingResult:
        # 用户强制覆盖
        if force_mode == "fast":
            mode = ExecutionMode.REACT
            ponytail = "full"
        else:
            mode = self.LABEL_TO_MODE.get(label, ExecutionMode.REACT)
            ponytail = self.LABEL_TO_PONYTAIL.get(label, "lite")

        # Superpowers 决策
        sp_decision, needs_confirm = self._decide_superpowers(
            label, features, force_superpowers
        )

        confirm_reason = ""
        if needs_confirm:
            confirm_reason = (
                f"命中高危任务 danger_task，"
                f"run_mode={self.config.run_mode.value}，需要用户确认"
            )

        return RoutingResult(
            execution_mode=mode,
            superpowers=sp_decision,
            ponytail_level=ponytail,
            needs_user_confirm=needs_confirm,
            confirm_reason=confirm_reason,
            estimated_token=features.estimated_token,
        )

    def _decide_superpowers(
        self,
        label: TaskLabel,
        features: TaskFeatures,
        force: bool,
    ) -> tuple:
        """返回 (SuperpowersDecision, needs_user_confirm)"""
        if force:
            return SuperpowersDecision.FORCED_ON, False

        if label == TaskLabel.TINY_FIX:
            return SuperpowersDecision.NOT_NEEDED, False

        if label == TaskLabel.NORMAL_FEATURE:
            return SuperpowersDecision.NOT_NEEDED, False

        if label == TaskLabel.EXPLORE_DEBUG:
            return SuperpowersDecision.NOT_NEEDED, False

        if label == TaskLabel.BIG_PROJECT:
            if features.estimated_token <= self.config.superpowers.auto_open_token:
                return SuperpowersDecision.ELIGIBLE, False
            else:
                return SuperpowersDecision.DOWNGRADED_BUDGET, False

        if label == TaskLabel.DANGER_TASK:
            if self.config.run_mode == RunMode.STRICT_AUTO:
                return SuperpowersDecision.DOWNGRADED_DANGER, False
            elif self.config.run_mode == RunMode.SAFE_AUTO:
                return SuperpowersDecision.PENDING_USER_CONFIRM, True
            elif self.config.run_mode == RunMode.SEMI:
                return SuperpowersDecision.PENDING_USER_CONFIRM, True

        return SuperpowersDecision.NOT_NEEDED, False

    def format_routing_output(self, result: RoutingResult) -> str:
        parts = [
            f"[SmartGo 路由] 执行模式：{result.execution_mode.value}",
            f"Superpowers：{result.superpowers.value}",
            f"Ponytail：{result.ponytail_level}",
        ]
        if result.needs_user_confirm:
            parts.append(f"⚠️ 需要用户确认：{result.confirm_reason}")
        return " | ".join(parts)
