"""
SmartGo 智跑 — 通用任务调度管控 Skill
=====================
核心架构：Layer1-5 主链路 + 场景执行器

smartgo.core         — 主链路（分类→路由→安全→约束→观测→调度）
smartgo.scenarios    — 场景执行器（爬虫/修bug/测试/脚手架/审计）

用法：
    from smartgo import SmartGoOrchestrator, SmartGoConfig
    orch = SmartGoOrchestrator(SmartGoConfig())
    result = orch.run("修复登录bug", subtask_executor=my_executor)
"""

from smartgo.core import (
    SmartGoConfig, RunMode, LogLevel, TaskLabel, ExecutionMode,
    TaskClassifier, TaskFeatures,
    ModeRouter, RoutingResult, SuperpowersDecision,
    SafetyGuard, SafetyState,
    PonytailConstraint, PonytailRule,
    TelemetryLogger, TelemetryRecord, SAVINGS_COEFFICIENTS,
    SmartGoOrchestrator, TaskResult, SubtaskResult,
)

from smartgo.scenarios import (
    Crawler, CrawlConfig, CrawlResult, DataCleaner,
    CrawlTaskBuilder, CrawlExecutor,
    CodeFixer, BugFixReport, BUG_PATTERNS,
    TestRunner, TestResult,
    ProjectScaffolder, ScaffoldReport, PROJECT_TEMPLATES,
    ProjectAuditor, AuditReport, Issue,
)

__version__ = "2.0.0"
__all__ = [
    # 核心引擎
    "SmartGoConfig", "RunMode", "LogLevel", "TaskLabel", "ExecutionMode",
    "TaskClassifier", "TaskFeatures",
    "ModeRouter", "RoutingResult", "SuperpowersDecision",
    "SafetyGuard", "SafetyState",
    "PonytailConstraint", "PonytailRule",
    "TelemetryLogger", "TelemetryRecord", "SAVINGS_COEFFICIENTS",
    "SmartGoOrchestrator", "TaskResult", "SubtaskResult",
    # 场景执行器
    "Crawler", "CrawlConfig", "CrawlResult", "DataCleaner",
    "CrawlTaskBuilder", "CrawlExecutor",
    "CodeFixer", "BugFixReport", "BUG_PATTERNS",
    "TestRunner", "TestResult",
    "ProjectScaffolder", "ScaffoldReport", "PROJECT_TEMPLATES",
    "ProjectAuditor", "AuditReport", "Issue",
]
