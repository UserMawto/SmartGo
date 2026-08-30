"""SmartGo 核心引擎 — 主链路 Layer1-5 + 调度器"""
from smartgo.core.config import SmartGoConfig, RunMode, LogLevel, TaskLabel, ExecutionMode
from smartgo.core.classifier import TaskClassifier, TaskFeatures
from smartgo.core.router import ModeRouter, RoutingResult, SuperpowersDecision
from smartgo.core.safety import SafetyGuard, SafetyState
from smartgo.core.ponytail import PonytailConstraint, PonytailRule
from smartgo.core.telemetry import TelemetryLogger, TelemetryRecord, SAVINGS_COEFFICIENTS
from smartgo.core.orchestrator import SmartGoOrchestrator, TaskResult, SubtaskResult

__all__ = [
    "SmartGoConfig", "RunMode", "LogLevel", "TaskLabel", "ExecutionMode",
    "TaskClassifier", "TaskFeatures",
    "ModeRouter", "RoutingResult", "SuperpowersDecision",
    "SafetyGuard", "SafetyState",
    "PonytailConstraint", "PonytailRule",
    "TelemetryLogger", "TelemetryRecord", "SAVINGS_COEFFICIENTS",
    "SmartGoOrchestrator", "TaskResult", "SubtaskResult",
]
