"""SmartGo Layer3 安全防护层

全局轮次上限、子任务轮次上限、Token 预算监控、死循环检测。
所有模式强制生效，不可关闭。
"""

import hashlib
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .config import SmartGoConfig, RunMode


@dataclass
class SafetyState:
    global_round: int = 0
    subtask_round: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    action_hashes: List[str] = field(default_factory=list)
    terminated: bool = False
    terminate_reason: str = ""


class SafetyViolationType:
    GLOBAL_ROUND_LIMIT = "全局轮次上限"
    SUBTASK_ROUND_LIMIT = "子任务轮次上限"
    TOKEN_BUDGET = "token预算超限"
    LOOP_DETECTED = "死循环检测"


class SafetyGuard:
    """Layer3: 强制安全防护，防卡死防死循环"""

    def __init__(self, config: SmartGoConfig):
        self.config = config
        self.state = SafetyState()

    def begin_subtask(self):
        """开始一个新的子任务，重置子任务轮次计数"""
        self.state.subtask_round = 0

    def record_round(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        action_signature: str = "",
    ) -> Tuple[bool, str]:
        """记录一轮执行，返回 (是否允许继续, 原因)

        每轮调用一次。返回 (False, reason) 表示需要终止/暂停。
        """
        if self.state.terminated:
            return False, self.state.terminate_reason

        self.state.global_round += 1
        self.state.subtask_round += 1
        self.state.total_input_tokens += input_tokens
        self.state.total_output_tokens += output_tokens
        self.state.total_tokens = (
            self.state.total_input_tokens + self.state.total_output_tokens
        )

        # 全局轮次上限
        if self.state.global_round >= self.config.safety.max_all_round:
            return self._terminate(SafetyViolationType.GLOBAL_ROUND_LIMIT)

        # 子任务轮次上限
        if self.state.subtask_round >= self.config.safety.max_one_subtask_round:
            return self._terminate(SafetyViolationType.SUBTASK_ROUND_LIMIT)

        # Token 预算监控
        budget = self.config.safety.token_max_budget
        if self.state.total_tokens >= budget:
            return self._terminate(SafetyViolationType.TOKEN_BUDGET)

        # 死循环检测
        if action_signature:
            action_hash = hashlib.md5(action_signature.encode()).hexdigest()
            self.state.action_hashes.append(action_hash)
            if self._detect_loop():
                return self._terminate(SafetyViolationType.LOOP_DETECTED)

        # 预算告警（80%）
        if self.state.total_tokens >= budget * 0.8:
            return True, f"[SmartGo 安全告警] token预算已达{int(self.state.total_tokens/budget*100)}%，逼近上限"

        return True, ""

    def _detect_loop(self) -> bool:
        """检测最近 N 轮的 action hash 是否高度重复"""
        window = self.config.safety.loop_detection_window
        hashes = self.state.action_hashes[-window:]
        if len(hashes) < window:
            return False

        # 统计最近窗口内不同 hash 的数量
        unique = len(set(hashes))
        similarity = 1.0 - (unique - 1) / max(len(hashes) - 1, 1)
        return similarity >= self.config.safety.loop_similarity_threshold

    def _terminate(self, reason: str) -> Tuple[bool, str]:
        """终止任务，根据 run_mode 返回不同行为"""
        self.state.terminated = True
        self.state.terminate_reason = reason

        if self.config.run_mode == RunMode.SEMI:
            # semi 模式：返回需要询问用户
            return False, f"[SmartGo 安全保护] 触发：{reason}，等待用户确认是否继续"
        else:
            # strict_auto / safe_auto：直接终止
            return False, f"[SmartGo 安全保护] 任务终止：{reason}"

    def get_progress_snapshot(self, total_subtasks: int = 0, completed_subtasks: int = 0) -> str:
        """输出进度快照"""
        budget = self.config.safety.token_max_budget
        token_pct = int(self.state.total_tokens / budget * 100) if budget > 0 else 0
        subtask_info = ""
        if total_subtasks > 0:
            subtask_info = f" | 进度：{completed_subtasks}/{total_subtasks}子任务完成"
        return (
            f"[SmartGo 安全快照] 轮次{self.state.global_round}/{self.config.safety.max_all_round} "
            f"| token消耗{self.state.total_tokens}/{budget}({token_pct}%)"
            f"{subtask_info}"
        )

    def reset(self):
        """重置全部状态（新任务开始时调用）"""
        self.state = SafetyState()
