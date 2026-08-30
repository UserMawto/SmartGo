"""SmartGo Layer5 贯穿式观测日志层

独立运行、贯穿所有环节的持续观测层。
从 Layer1 到 Layer4 每一步都在持续采集数据、按配置粒度实时输出。
统计模块只输出信息，绝不干预执行逻辑。
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .config import SmartGoConfig, LogLevel


# 估算系数参考（仅供内部计算，不对外作为计费）
# 所有【预估节省】输出必须标注：【参考估算，非精确计费】
SAVINGS_COEFFICIENTS = {
    # Ponytail 代码精简节省系数：基于输出 token 的比例估算
    "ponytail_full": (0.75, 0.90),   # full 模式：节省 75%-90% 输出 token
    "ponytail_lite": (0.30, 0.50),   # lite 模式：节省 30%-50% 输出 token
    "ponytail_off": (0.0, 0.0),      # off 模式：无节省

    # 模式自适应节省系数：避免错误启用重型 Superpowers 流程
    "mode_avoid_superpowers": (0.60, 0.80),  # 小任务避免开Superpowers节省

    # 安全拦截节省系数：拦截死循环无效轮次
    "safety_intercept_loop": (0.80, 0.95),   # 拦截死循环避免的消耗
}

DISCLAIMER = "【参考估算，非精确计费】"


@dataclass
class TelemetryRecord:
    timestamp: str
    layer: str
    event: str
    input_tokens: int = 0
    output_tokens: int = 0
    cumulative_input: int = 0
    cumulative_output: int = 0
    estimated_saved: int = 0
    cumulative_saved: int = 0
    extra_info: str = ""


class TelemetryLogger:
    """Layer5: 贯穿全程的观测日志"""

    def __init__(self, config: SmartGoConfig):
        self.config = config
        self.records: List[TelemetryRecord] = []
        self.total_input: int = 0
        self.total_output: int = 0
        self.saved_ponytail: int = 0
        self.saved_mode: int = 0
        self.saved_safety: int = 0
        self.safety_triggers: List[str] = []
        self._enabled = config.log_level != LogLevel.OFF
        self._file_handle = None
        if config.telemetry.save_log_to_file and config.telemetry.log_file_path:
            self._file_handle = open(config.telemetry.log_file_path, "a", encoding="utf-8")

    def _should_output(self) -> bool:
        return self._enabled and self.config.log_level != LogLevel.OFF

    def _is_step_level(self) -> bool:
        return self.config.log_level == LogLevel.STEP

    def log_layer1(self, label: str, estimated_token: int, mode: str, ponytail: str):
        """Layer1 完成时输出分类观测"""
        if not self._should_output():
            return
        msg = (
            f"[SmartGo 观测] 任务标签：{label} | "
            f"预估token：~{estimated_token} | "
            f"已选模式：{mode} | ponytail={ponytail}"
        )
        self._output(msg, "Layer1", "task_classified")

    def log_layer2(self, event: str, reason: str = "", saved: int = 0):
        """Layer2 模式切换/降级时输出观测"""
        if not self._should_output():
            return
        msg = f"[SmartGo 观测] {event}"
        if reason:
            msg += f" | 原因：{reason}"
        if saved > 0:
            msg += f" | 预估避免消耗~{saved} token {DISCLAIMER}"
        self._output(msg, "Layer2", event)

    def log_layer3(self, global_round: int, max_round: int,
                   total_tokens: int, budget: int, progress: str = ""):
        """Layer3 安全触发时输出观测"""
        if not self._should_output():
            return
        pct = int(total_tokens / budget * 100) if budget > 0 else 0
        msg = (
            f"[SmartGo 观测] 安全状态：轮次{global_round}/{max_round} | "
            f"token消耗{total_tokens}/{budget}({pct}%)"
        )
        if progress:
            msg += f" | 进度：{progress}"
        self._output(msg, "Layer3", "safety_check")

    def log_round(self, subtask_name: str, input_tokens: int, output_tokens: int):
        """每轮/子任务完成时输出 token 消耗"""
        self.total_input += input_tokens
        self.total_output += output_tokens

        if not self._should_output() or not self._is_step_level():
            return

        saved_ponytail = self._estimate_ponytail_savings(output_tokens)
        msg = (
            f"[SmartGo 观测] 子任务'{subtask_name}'完成 | "
            f"本轮消耗：输入{input_tokens}/输出{output_tokens} | "
            f"累计：输入{self.total_input}/输出{self.total_output} | "
            f"预估节省累计：~{self.saved_ponytail + self.saved_mode + self.saved_safety} token {DISCLAIMER}"
        )
        self._output(msg, "round", subtask_name)

    def log_summary(self, event: str, info: str = ""):
        """summary 粒度：模式切换、子任务组完成、触发安全保护时输出"""
        if not self._should_output() or self._is_step_level():
            return
        msg = f"[SmartGo 观测] {event}"
        if info:
            msg += f" | {info}"
        self._output(msg, "summary", event)

    def record_safety_trigger(self, trigger: str, saved_tokens: int = 0):
        """记录安全保护触发"""
        self.safety_triggers.append(trigger)
        if saved_tokens > 0:
            self.saved_safety += saved_tokens
        self.log_summary(f"安全保护触发：{trigger}", f"预估避免消耗~{saved_tokens} token {DISCLAIMER}")

    def record_ponytail_savings(self, output_tokens: int, ponytail_level: str):
        """记录 Ponytail 精简节省"""
        if not self.config.telemetry.calc_token_saved:
            return
        saved = self._estimate_ponytail_savings(output_tokens, ponytail_level)
        self.saved_ponytail += saved

    def record_mode_savings(self, avoided_superpowers: bool, estimated_cost: int):
        """记录模式自适应节省"""
        if not self.config.telemetry.calc_token_saved or not avoided_superpowers:
            return
        coeff = SAVINGS_COEFFICIENTS["mode_avoid_superpowers"]
        saved = int(estimated_cost * (coeff[0] + coeff[1]) / 2)
        self.saved_mode += saved

    def _estimate_ponytail_savings(self, output_tokens: int, level: str = "") -> int:
        """根据 Ponytail 等级估算节省的输出 token"""
        if not self.config.telemetry.calc_token_saved:
            return 0
        key = f"ponytail_{level or 'lite'}"
        coeff = SAVINGS_COEFFICIENTS.get(key, SAVINGS_COEFFICIENTS["ponytail_off"])
        if coeff[1] == 0:
            return 0
        avg_coeff = (coeff[0] + coeff[1]) / 2
        return int(output_tokens * avg_coeff)

    def _output(self, msg: str, layer: str, event: str):
        """输出日志到控制台和文件"""
        print(msg)

        record = TelemetryRecord(
            timestamp=datetime.now().isoformat(),
            layer=layer,
            event=event,
            cumulative_input=self.total_input,
            cumulative_output=self.total_output,
            cumulative_saved=self.saved_ponytail + self.saved_mode + self.saved_safety,
        )
        self.records.append(record)

        if self._file_handle:
            self._file_handle.write(json.dumps({
                "timestamp": record.timestamp,
                "layer": layer,
                "event": event,
                "message": msg,
                "cumulative_input": self.total_input,
                "cumulative_output": self.total_output,
            }, ensure_ascii=False) + "\n")
            self._file_handle.flush()

    def generate_final_report(
        self,
        run_mode: str,
        superpowers_on: bool,
        ponytail_level: str,
        total_rounds: int,
        task_label: str,
    ) -> str:
        """生成完整执行报告"""
        total_saved = self.saved_ponytail + self.saved_mode + self.saved_safety
        safety_str = "无" if not self.safety_triggers else "; ".join(self.safety_triggers)

        report = f"""======== SmartGo 执行报告 ========
运行模式：{run_mode}
Superpowers：{'开启' if superpowers_on else '未开启'}
马尾辫强度：{ponytail_level}
总运行轮次：{total_rounds}
【真实消耗】
输入token：{self.total_input} 输出token：{self.total_output} 合计：{self.total_input + self.total_output}
【预估节省 {DISCLAIMER}】
👉 精简代码节省：{self.saved_ponytail}
👉 模式选轻量避免重型流程节省：{self.saved_mode}
👉 拦截无效循环避免消耗：{self.saved_safety}
✅ 预估一共省下token：{total_saved}
安全触发：{safety_str}
任务标签：{task_label}
==================================="""
        print(report)

        if self._file_handle:
            self._file_handle.write(report + "\n")
            self._file_handle.close()

        return report

    def close(self):
        if self._file_handle:
            self._file_handle.close()
