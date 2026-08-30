"""SmartGo 主调度器

协调五层架构，贯穿式执行任务。
这是 Agent 调用的入口，负责将任务从分类到执行到报告全流程串联。
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Dict, Any

from .config import (
    SmartGoConfig, TaskLabel, ExecutionMode, RunMode, LogLevel,
)
from .classifier import TaskClassifier, TaskFeatures
from .router import ModeRouter, RoutingResult, SuperpowersDecision
from .safety import SafetyGuard
from .ponytail import PonytailConstraint
from .telemetry import TelemetryLogger


@dataclass
class SubtaskResult:
    name: str
    success: bool
    input_tokens: int = 0
    output_tokens: int = 0
    output_code: str = ""
    reflection_notes: str = ""
    dependencies: List[str] = field(default_factory=list)
    error: str = ""


@dataclass
class TaskResult:
    label: TaskLabel
    execution_mode: ExecutionMode
    superpowers_on: bool
    ponytail_level: str
    total_rounds: int
    subtasks: List[SubtaskResult] = field(default_factory=list)
    terminated_by_safety: bool = False
    terminate_reason: str = ""
    report: str = ""


class SmartGoOrchestrator:
    """主调度器：协调 Layer1-5 全流程"""

    def __init__(self, config: SmartGoConfig):
        self.config = config
        self.classifier = TaskClassifier(config)
        self.router = ModeRouter(config)
        self.safety = SafetyGuard(config)
        self.ponytail = PonytailConstraint()
        self.telemetry = TelemetryLogger(config)
        self._force_mode: Optional[str] = None
        self._force_superpowers: bool = False
        self._user_confirmed_danger: bool = False

    def handle_command(self, command: str) -> str:
        """处理 smartgo:* 快捷指令，返回反馈信息"""
        # 用户强制指令优先级高于一切自动判断
        if command == "smartgo:fast":
            self._force_mode = "fast"
            self._force_superpowers = False
            return "[SmartGo] 已切换快速模式，强制ReAct，不走复杂流程"

        if command == "smartgo:full_project":
            self._force_mode = None
            self._force_superpowers = True
            return "[SmartGo] 已强制开启Superpowers完整项目流程"

        if command.startswith("smartgo:run_mode="):
            mode_str = command.split("=")[1]
            try:
                self.config.run_mode = RunMode(mode_str)
                return f"[SmartGo] 运行模式已切换为：{mode_str}"
            except ValueError:
                return f"[SmartGo] 未知运行模式：{mode_str}"

        if command.startswith("smartgo:log_level="):
            level_str = command.split("=")[1]
            try:
                self.config.log_level = LogLevel(level_str)
                self.telemetry._enabled = self.config.log_level != LogLevel.OFF
                return f"[SmartGo] 日志粒度已切换为：{level_str}"
            except ValueError:
                return f"[SmartGo] 未知日志粒度：{level_str}"

        if command.startswith("smartgo:ponytail="):
            level = command.split("=")[1]
            self.ponytail.set_level(level)
            return f"[SmartGo] Ponytail已手动设置为：{level}"

        return f"[SmartGo] 未知指令：{command}"

    def run(
        self,
        task_description: str,
        subtask_executor: Callable,
        estimated_files: int = 1,
        estimated_token: int = 5000,
        needs_subagents: int = 0,
        needs_git_branches: int = 0,
        is_research: bool = False,
        is_refactor: bool = False,
        is_from_scratch: bool = False,
        subtask_names: Optional[List[str]] = None,
    ) -> TaskResult:
        """主执行入口

        Args:
            task_description: 任务描述
            subtask_executor: 子任务执行回调，签名: (subtask_name, ponytail_rule_str) -> SubtaskResult
            其余为任务特征估算参数
        """
        self.safety.reset()

        # ===== Layer1: 任务分类 =====
        label, features = self.classifier.classify(
            task_description,
            estimated_files=estimated_files,
            estimated_token=estimated_token,
            needs_subagents=needs_subagents,
            needs_git_branches=needs_git_branches,
            is_research=is_research,
            is_refactor=is_refactor,
            is_from_scratch=is_from_scratch,
        )
        label_output = self.classifier.format_label_output(label, features)
        print(label_output)

        # Layer5 观测：Layer1 完成
        self.telemetry.log_layer1(
            label.value, features.estimated_token,
            self.router.LABEL_TO_MODE.get(label, ExecutionMode.REACT).value,
            self.router.LABEL_TO_PONYTAIL.get(label, "lite"),
        )

        # ===== Layer2: 执行模式路由 =====
        routing = self.router.route(
            label, features,
            force_mode=self._force_mode,
            force_superpowers=self._force_superpowers,
        )
        print(self.router.format_routing_output(routing))

        # Layer5 观测：Layer2 路由完成
        superpowers_on = routing.superpowers in (
            SuperpowersDecision.ELIGIBLE,
            SuperpowersDecision.FORCED_ON,
        )
        self.telemetry.log_layer2(
            f"模式选择：{routing.execution_mode.value} | Superpowers：{routing.superpowers.value}",
        )

        # 模式自适应节省记录
        if not superpowers_on and label in (TaskLabel.TINY_FIX, TaskLabel.NORMAL_FEATURE, TaskLabel.EXPLORE_DEBUG):
            self.telemetry.record_mode_savings(True, estimated_token)

        # 高危任务用户确认
        if routing.needs_user_confirm:
            if self.config.run_mode == RunMode.SAFE_AUTO:
                print(f"\n⚠️ [SmartGo] {routing.confirm_reason}")
                print("请在终端输入确认指令后继续执行。")
                if not self._user_confirmed_danger:
                    return TaskResult(
                        label=label,
                        execution_mode=routing.execution_mode,
                        superpowers_on=False,
                        ponytail_level=routing.ponytail_level,
                        total_rounds=0,
                        terminated_by_safety=False,
                        terminate_reason="等待用户确认高危任务",
                    )
            elif self.config.run_mode == RunMode.SEMI:
                print(f"\n⚠️ [SmartGo] {routing.confirm_reason}")
                print("请在终端输入确认指令后继续执行。")
                return TaskResult(
                    label=label,
                    execution_mode=routing.execution_mode,
                    superpowers_on=False,
                    ponytail_level=routing.ponytail_level,
                    total_rounds=0,
                    terminated_by_safety=False,
                    terminate_reason="等待用户确认高危任务",
                )

        # ===== Layer4: Ponytail 约束生效 =====
        self.ponytail.apply(label)
        if self._force_mode == "fast":
            self.ponytail.set_level("full")
        print(self.ponytail.get_constraint_prompt())

        # ===== 执行阶段 =====
        subtask_list = subtask_names or [task_description]
        subtask_results: List[SubtaskResult] = []
        completed = 0

        for idx, st_name in enumerate(subtask_list):
            self.safety.begin_subtask()

            # Layer3: 每轮安全检查
            can_continue, reason = self.safety.record_round(
                action_signature=f"subtask:{st_name}:round0"
            )
            if not can_continue:
                print(f"\n[SmartGo] 任务终止：{reason}")
                self.telemetry.record_safety_trigger(reason, estimated_token // 4)
                break

            # 执行子任务（通过回调）
            ponytail_prompt = self.ponytail.get_constraint_prompt()
            # 追加 Layer2 Superpowers 状态，供执行器联动
            sp_flag = "on" if superpowers_on else "off"
            ponytail_prompt += f" [SmartGo Superpowers={sp_flag}]"
            st_result = subtask_executor(st_name, ponytail_prompt)

            if st_result is None:
                st_result = SubtaskResult(name=st_name, success=False)

            # Layer3: 记录消耗
            can_continue, reason = self.safety.record_round(
                input_tokens=st_result.input_tokens,
                output_tokens=st_result.output_tokens,
                action_signature=f"subtask:{st_name}:execute",
            )

            # Layer5: 记录轮次消耗
            self.telemetry.log_round(st_name, st_result.input_tokens, st_result.output_tokens)

            # Layer4: Ponytail 代码检查
            if st_result.output_code:
                check = self.ponytail.check_code(st_result.output_code, st_result.dependencies)
                if not check["passed"]:
                    print(f"[SmartGo Ponytail] 代码约束违规：{check['violations']}")
                if check["suggestions"]:
                    print(f"[SmartGo Ponytail] 建议：{check['suggestions']}")

                # Layer5: 记录 Ponytail 节省
                self.telemetry.record_ponytail_savings(
                    st_result.output_tokens, self.ponytail.current_level
                )

            # Reflection 模式：自省校验
            if routing.execution_mode == ExecutionMode.PLAN_EXECUTE_REFLECTION:
                reflection = self._reflect(st_result, label)
                st_result.reflection_notes = reflection
                if reflection:
                    print(f"[SmartGo Reflection] {reflection}")

            subtask_results.append(st_result)
            if st_result.success:
                completed += 1

            # Layer3: 安全快照
            self.telemetry.log_layer3(
                self.safety.state.global_round,
                self.config.safety.max_all_round,
                self.safety.state.total_tokens,
                self.config.safety.token_max_budget,
                progress=f"{completed}/{len(subtask_list)}子任务完成",
            )

            if not can_continue:
                print(f"\n[SmartGo] 任务终止：{reason}")
                self.telemetry.record_safety_trigger(reason, estimated_token // 4)
                break

            # Layer5: summary 粒度输出
            self.telemetry.log_summary(
                f"子任务'{st_name}'完成",
                f"成功：{st_result.success} | 累计消耗：{self.safety.state.total_tokens} token",
            )

        # ===== Layer5: 最终报告 =====
        terminated = self.safety.state.terminated
        report = self.telemetry.generate_final_report(
            run_mode=self.config.run_mode.value,
            superpowers_on=superpowers_on,
            ponytail_level=self.ponytail.current_level,
            total_rounds=self.safety.state.global_round,
            task_label=label.value,
        )

        return TaskResult(
            label=label,
            execution_mode=routing.execution_mode,
            superpowers_on=superpowers_on,
            ponytail_level=self.ponytail.current_level,
            total_rounds=self.safety.state.global_round,
            subtasks=subtask_results,
            terminated_by_safety=terminated,
            terminate_reason=self.safety.state.terminate_reason,
            report=report,
        )

    def _reflect(self, result: SubtaskResult, label: TaskLabel) -> str:
        """自省校验逻辑（简化版）"""
        notes = []
        if not result.success:
            notes.append("子任务执行失败，需检查并修正")
        if result.output_tokens > 10000:
            notes.append("输出token偏高，考虑精简")
        if label == TaskLabel.DANGER_TASK and not result.reflection_notes:
            notes.append("高危任务需额外审查代码安全性")
        return "；".join(notes) if notes else "自省通过，无偏差"

    def confirm_danger_task(self):
        """用户确认高危任务后调用"""
        self._user_confirmed_danger = True
