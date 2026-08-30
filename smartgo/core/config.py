"""SmartGo 配置管理模块

支持 YAML 文件加载 + 运行时指令覆盖。
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RunMode(Enum):
    SEMI = "semi"
    STRICT_AUTO = "strict_auto"
    SAFE_AUTO = "safe_auto"


class LogLevel(Enum):
    STEP = "step"
    SUMMARY = "summary"
    OFF = "off"


class PonytailLevel(Enum):
    FULL = "full"
    LITE = "lite"
    OFF = "off"


class TaskLabel(Enum):
    TINY_FIX = "tiny_fix"
    NORMAL_FEATURE = "normal_feature"
    BIG_PROJECT = "big_project"
    DANGER_TASK = "danger_task"
    EXPLORE_DEBUG = "explore_debug"


class ExecutionMode(Enum):
    REACT = "ReAct"
    PLAN_EXECUTE = "Plan&Execute"
    PLAN_EXECUTE_REFLECTION = "Plan&Execute+Reflection"


@dataclass
class SafetyConfig:
    max_all_round: int = 30
    max_one_subtask_round: int = 10
    token_max_budget: int = 150000
    loop_detection_window: int = 5
    loop_similarity_threshold: float = 0.85


@dataclass
class SuperpowersConfig:
    auto_open_token: int = 120000
    danger_task_token: int = 200000


@dataclass
class TelemetryConfig:
    calc_token_saved: bool = True
    save_log_to_file: bool = False
    log_file_path: str = ""


@dataclass
class SmartGoConfig:
    run_mode: RunMode = RunMode.SAFE_AUTO
    log_level: LogLevel = LogLevel.SUMMARY
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    superpowers: SuperpowersConfig = field(default_factory=SuperpowersConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "SmartGoConfig":
        try:
            import yaml
        except ImportError:
            print("[SmartGo] pyyaml not installed, using defaults")
            return cls()

        if not os.path.exists(path):
            return cls()

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        sg = data.get("smartgo", data)
        config = cls()

        if "run_mode" in sg:
            config.run_mode = RunMode(sg["run_mode"])
        if "log_level" in sg:
            config.log_level = LogLevel(sg["log_level"])

        tel = sg.get("telemetry", {})
        config.telemetry = TelemetryConfig(
            calc_token_saved=tel.get("calc_token_saved", True),
            save_log_to_file=tel.get("save_log_to_file", False),
            log_file_path=tel.get("log_file_path", ""),
        )

        safe = sg.get("safety", {})
        config.safety = SafetyConfig(
            max_all_round=safe.get("max_all_round", 30),
            max_one_subtask_round=safe.get("max_one_subtask_round", 10),
            token_max_budget=safe.get("token_max_budget", 150000),
            loop_detection_window=safe.get("loop_detection_window", 5),
            loop_similarity_threshold=safe.get("loop_similarity_threshold", 0.85),
        )

        sp = sg.get("superpowers", {})
        config.superpowers = SuperpowersConfig(
            auto_open_token=sp.get("auto_open_token", 120000),
            danger_task_token=sp.get("danger_task_token", 200000),
        )

        return config

    def to_dict(self) -> dict:
        return {
            "run_mode": self.run_mode.value,
            "log_level": self.log_level.value,
            "telemetry": {
                "calc_token_saved": self.telemetry.calc_token_saved,
                "save_log_to_file": self.telemetry.save_log_to_file,
            },
            "safety": {
                "max_all_round": self.safety.max_all_round,
                "max_one_subtask_round": self.safety.max_one_subtask_round,
                "token_max_budget": self.safety.token_max_budget,
            },
            "superpowers": {
                "auto_open_token": self.superpowers.auto_open_token,
                "danger_task_token": self.superpowers.danger_task_token,
            },
        }
