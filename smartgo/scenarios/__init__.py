"""SmartGo 场景执行器集合"""
from smartgo.scenarios.crawler.crawler import Crawler, CrawlConfig, CrawlResult, DataCleaner
from smartgo.scenarios.crawler.executor import CrawlTaskBuilder, CrawlExecutor
from smartgo.scenarios.code_fix.fixer import CodeFixer, BugFixReport, BUG_PATTERNS
from smartgo.scenarios.test.runner import TestRunner, TestResult
from smartgo.scenarios.scaffold.scaffolder import ProjectScaffolder, ScaffoldReport, PROJECT_TEMPLATES
from smartgo.scenarios.audit.auditor import ProjectAuditor, AuditReport, Issue

__all__ = [
    # 爬虫
    "Crawler", "CrawlConfig", "CrawlResult", "DataCleaner",
    "CrawlTaskBuilder", "CrawlExecutor",
    # 修bug
    "CodeFixer", "BugFixReport", "BUG_PATTERNS",
    # 测试
    "TestRunner", "TestResult",
    # 脚手架
    "ProjectScaffolder", "ScaffoldReport", "PROJECT_TEMPLATES",
    # 审计
    "ProjectAuditor", "AuditReport", "Issue",
]
