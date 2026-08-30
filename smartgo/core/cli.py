#!/usr/bin/env python3
"""SmartGo CLI 入口

支持 smartgo:* 指令解析和任务执行。
用法：
  python -m smartgo.cli classify "修复登录页面的CSS bug"
  python -m smartgo.cli run "重构用户认证模块" --files 35 --token 250000
  python -m smartgo.cli config
  python -m smartgo.cli command smartgo:fast
"""

import argparse
import sys

from smartgo.core.config import SmartGoConfig, RunMode, LogLevel, TaskLabel, ExecutionMode
from smartgo.core.orchestrator import SmartGoOrchestrator, SubtaskResult


def cmd_classify(args):
    """仅分类任务，不执行"""
    config = SmartGoConfig.from_yaml(args.config) if args.config else SmartGoConfig()
    classifier = __import__("smartgo.core.classifier", fromlist=["TaskClassifier"]).TaskClassifier(config)
    label, features = classifier.classify(
        args.task,
        estimated_files=args.files,
        estimated_token=args.token,
    )
    print(classifier.format_label_output(label, features))


def cmd_run(args):
    """完整执行任务"""
    config = SmartGoConfig.from_yaml(args.config) if args.config else SmartGoConfig()

    # 应用命令行覆盖
    if args.run_mode:
        config.run_mode = RunMode(args.run_mode)
    if args.log_level:
        config.log_level = LogLevel(args.log_level)

    orchestrator = SmartGoOrchestrator(config)

    # 应用强制指令
    if args.force:
        print(orchestrator.handle_command(args.force))

    # 模拟子任务执行器（实际使用时由 Agent 替换）
    def mock_executor(subtask_name, ponytail_prompt):
        print(f"\n--- 执行子任务：{subtask_name} ---")
        print(f"Ponytail约束：{ponytail_prompt}")
        return SubtaskResult(
            name=subtask_name,
            success=True,
            input_tokens=3200,
            output_tokens=1800,
            output_code="# 示例代码\npass",
            dependencies=[],
        )

    subtask_names = args.subtasks.split(",") if args.subtasks else [args.task]

    result = orchestrator.run(
        task_description=args.task,
        subtask_executor=mock_executor,
        estimated_files=args.files,
        estimated_token=args.token,
        needs_subagents=args.subagents,
        is_refactor=args.refactor,
        is_from_scratch=args.from_scratch,
        subtask_names=subtask_names,
    )

    print(f"\n执行完成。标签={result.label.value} 模式={result.execution_mode.value}")


def cmd_config(args):
    """显示当前配置"""
    config = SmartGoConfig.from_yaml(args.config) if args.config else SmartGoConfig()
    import json
    print(json.dumps(config.to_dict(), indent=2, ensure_ascii=False))


def cmd_command(args):
    """处理 smartgo:* 指令"""
    config = SmartGoConfig.from_yaml(args.config) if args.config else SmartGoConfig()
    orchestrator = SmartGoOrchestrator(config)
    print(orchestrator.handle_command(args.cmd))


def cmd_status(args):
    """显示 SmartGo 状态信息"""
    config = SmartGoConfig.from_yaml(args.config) if args.config else SmartGoConfig()
    print(f"SmartGo 智跑 状态")
    print(f"  运行模式：{config.run_mode.value}")
    print(f"  日志粒度：{config.log_level.value}")
    print(f"  安全上限：总轮次{config.safety.max_all_round} 子任务{config.safety.max_one_subtask_round} token{config.safety.token_max_budget}")
    print(f"  Superpowers：auto_open@{config.superpowers.auto_open_token} danger@{config.superpowers.danger_task_token}")
    print(f"  Token节省计算：{'开启' if config.telemetry.calc_token_saved else '关闭'}")


def cmd_crawl(args):
    """爬取网站：内置爬虫 + 全程安全防护 + token 观测"""
    from smartgo.scenarios.crawler.executor import CrawlTaskBuilder

    config = SmartGoConfig.from_yaml(args.config) if args.config else SmartGoConfig()

    if args.run_mode:
        config.run_mode = RunMode(args.run_mode)
    if args.log_level:
        config.log_level = LogLevel(args.log_level)

    orchestrator = SmartGoOrchestrator(config)

    builder = CrawlTaskBuilder()
    task = builder.build(
        start_url=args.url,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        rate_limit=args.rate,
        max_retries=args.retries,
        output_format=args.format,
        output_path=args.output,
        follow_links=not args.no_links,
        verify_ssl=not args.no_ssl,
    )

    # 注入安全检查到爬虫
    if args.force:
        print(orchestrator.handle_command(args.force))

    result = orchestrator.run(**task)
    print(f"\n爬取完成。标签={result.label.value} 模式={result.execution_mode.value}")
    print(f"子任务数={len(result.subtasks)} 安全终止={result.terminated_by_safety}")


def cmd_fix(args):
    """修bug：扫描文件 → 修复已知模式 → 可选跑测试"""
    from smartgo.scenarios.code_fix.fixer import CodeFixer

    config = SmartGoConfig.from_yaml(args.config) if args.config else SmartGoConfig()
    if args.run_mode:
        config.run_mode = RunMode(args.run_mode)
    orchestrator = SmartGoOrchestrator(config)

    task = CodeFixer.build_task(
        file_path=args.file,
        bug_description=args.description or "",
        run_test=bool(args.test_cmd),
        test_cmd=args.test_cmd or "",
    )

    if args.force:
        print(orchestrator.handle_command(args.force))

    result = orchestrator.run(**task)
    print(f"\n修复完成。标签={result.label.value} 成功={all(s.success for s in result.subtasks)}")


def cmd_test(args):
    """跑测试：发现 → 执行 → 分析覆盖率"""
    from smartgo.scenarios.test.runner import TestRunner

    config = SmartGoConfig.from_yaml(args.config) if args.config else SmartGoConfig()
    if args.run_mode:
        config.run_mode = RunMode(args.run_mode)
    orchestrator = SmartGoOrchestrator(config)

    task = TestRunner.build_task(
        test_path=args.path,
        run_coverage=args.coverage,
    )

    if args.force:
        print(orchestrator.handle_command(args.force))

    result = orchestrator.run(**task)
    print(f"\n测试完成。标签={result.label.value} 全部通过={all(s.success for s in result.subtasks)}")


def cmd_scaffold(args):
    """项目脚手架：规划 → 生成 → 初始化 → 验证"""
    from smartgo.scenarios.scaffold.scaffolder import ProjectScaffolder

    config = SmartGoConfig.from_yaml(args.config) if args.config else SmartGoConfig()
    if args.run_mode:
        config.run_mode = RunMode(args.run_mode)
    orchestrator = SmartGoOrchestrator(config)

    if args.list_templates:
        scaffolder = ProjectScaffolder()
        for name, desc in scaffolder.list_templates().items():
            print(f"  {name}: {desc}")
        return

    task = ProjectScaffolder.build_task(
        project_name=args.name,
        template=args.template,
        base_dir=args.dir,
        git_init=args.git,
    )

    if args.force:
        print(orchestrator.handle_command(args.force))

    result = orchestrator.run(**task)
    print(f"\n脚手架完成。标签={result.label.value} 模式={result.execution_mode.value}")


def cmd_audit(args):
    """项目审计：安全扫描 → 代码异味 → 项目健康 → 依赖检查 → 生成报告"""
    from smartgo.scenarios.audit.auditor import ProjectAuditor

    config = SmartGoConfig.from_yaml(args.config) if args.config else SmartGoConfig()
    if args.run_mode:
        config.run_mode = RunMode(args.run_mode)
    orchestrator = SmartGoOrchestrator(config)

    task = ProjectAuditor.build_task(project_path=args.path)

    if args.force:
        print(orchestrator.handle_command(args.force))

    result = orchestrator.run(**task)
    print(f"\n审计完成。标签={result.label.value} 评级见上方报告")


def main():
    parser = argparse.ArgumentParser(
        prog="smartgo",
        description="SmartGo 智跑 - 任务调度管控系统",
    )
    parser.add_argument("--config", type=str, default=None, help="配置文件路径(YAML)")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # classify
    p_cls = subparsers.add_parser("classify", help="仅分类任务")
    p_cls.add_argument("task", type=str, help="任务描述")
    p_cls.add_argument("--files", type=int, default=1, help="预估文件数")
    p_cls.add_argument("--token", type=int, default=5000, help="预估token")
    p_cls.set_defaults(func=cmd_classify)

    # run
    p_run = subparsers.add_parser("run", help="执行任务")
    p_run.add_argument("task", type=str, help="任务描述")
    p_run.add_argument("--files", type=int, default=1, help="预估文件数")
    p_run.add_argument("--token", type=int, default=5000, help="预估token")
    p_run.add_argument("--subagents", type=int, default=0, help="子代理数")
    p_run.add_argument("--refactor", action="store_true", help="是否重构")
    p_run.add_argument("--from-scratch", action="store_true", help="是否从零搭建")
    p_run.add_argument("--subtasks", type=str, default=None, help="子任务列表(逗号分隔)")
    p_run.add_argument("--force", type=str, default=None, help="强制指令 smartgo:fast/full_project")
    p_run.add_argument("--run-mode", type=str, default=None, help="覆盖运行模式")
    p_run.add_argument("--log-level", type=str, default=None, help="覆盖日志粒度")
    p_run.set_defaults(func=cmd_run)

    # config
    p_cfg = subparsers.add_parser("config", help="显示配置")
    p_cfg.set_defaults(func=cmd_config)

    # command
    p_cmd = subparsers.add_parser("command", help="处理smartgo:*指令")
    p_cmd.add_argument("cmd", type=str, help="指令如 smartgo:fast")
    p_cmd.set_defaults(func=cmd_command)

    # status
    p_st = subparsers.add_parser("status", help="显示状态")
    p_st.set_defaults(func=cmd_status)

    # crawl
    p_crawl = subparsers.add_parser("crawl", help="爬取网站")
    p_crawl.add_argument("url", type=str, help="起始URL")
    p_crawl.add_argument("--max-pages", type=int, default=20, help="最大爬取页数")
    p_crawl.add_argument("--max-depth", type=int, default=3, help="最大爬取深度")
    p_crawl.add_argument("--rate", type=float, default=1.0, help="请求间隔(秒)")
    p_crawl.add_argument("--retries", type=int, default=3, help="最大重试次数")
    p_crawl.add_argument("--format", type=str, default="json", choices=["json", "csv"], help="导出格式")
    p_crawl.add_argument("--output", type=str, default="", help="输出文件路径")
    p_crawl.add_argument("--no-links", action="store_true", help="不跟踪链接")
    p_crawl.add_argument("--no-ssl", action="store_true", help="跳过SSL证书验证(macOS)")
    p_crawl.add_argument("--force", type=str, default=None, help="强制指令")
    p_crawl.add_argument("--run-mode", type=str, default=None, help="覆盖运行模式")
    p_crawl.add_argument("--log-level", type=str, default=None, help="覆盖日志粒度")
    p_crawl.set_defaults(func=cmd_crawl)

    # fix
    p_fix = subparsers.add_parser("fix", help="修bug")
    p_fix.add_argument("file", type=str, help="目标文件路径")
    p_fix.add_argument("--description", type=str, default="", help="bug描述")
    p_fix.add_argument("--test-cmd", type=str, default="", help="修复后执行的测试命令")
    p_fix.add_argument("--force", type=str, default=None, help="强制指令")
    p_fix.add_argument("--run-mode", type=str, default=None, help="覆盖运行模式")
    p_fix.set_defaults(func=cmd_fix)

    # test
    p_test = subparsers.add_parser("test", help="跑测试")
    p_test.add_argument("path", type=str, nargs="?", default="tests/", help="测试路径")
    p_test.add_argument("--coverage", action="store_true", help="分析覆盖率")
    p_test.add_argument("--force", type=str, default=None, help="强制指令")
    p_test.add_argument("--run-mode", type=str, default=None, help="覆盖运行模式")
    p_test.set_defaults(func=cmd_test)

    # scaffold
    p_scaffold = subparsers.add_parser("scaffold", help="项目脚手架")
    p_scaffold.add_argument("name", type=str, nargs="?", default="", help="项目名")
    p_scaffold.add_argument("--template", type=str, default="python_web",
                           choices=["python_web", "python_cli", "python_package"], help="项目模板")
    p_scaffold.add_argument("--dir", type=str, default=".", help="创建目录")
    p_scaffold.add_argument("--git", action="store_true", help="初始化git")
    p_scaffold.add_argument("--list-templates", action="store_true", help="列出可用模板")
    p_scaffold.add_argument("--force", type=str, default=None, help="强制指令")
    p_scaffold.add_argument("--run-mode", type=str, default=None, help="覆盖运行模式")
    p_scaffold.set_defaults(func=cmd_scaffold)

    # audit
    p_audit = subparsers.add_parser("audit", help="项目审计")
    p_audit.add_argument("path", type=str, help="目标项目路径")
    p_audit.add_argument("--force", type=str, default=None, help="强制指令")
    p_audit.add_argument("--run-mode", type=str, default=None, help="覆盖运行模式")
    p_audit.set_defaults(func=cmd_audit)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
